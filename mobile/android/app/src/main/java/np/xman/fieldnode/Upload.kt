package np.xman.fieldnode

import android.util.Log
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** What one upload attempt means for the package. */
data class UploadOutcome(
    val state: EvidenceState,
    val message: String,
    val httpCode: Int? = null,
    val evidenceId: Long? = null,
    val incidentId: Long? = null,
    val serverStatus: String? = null,
    val duplicate: Boolean = false,
) {
    companion object {
        const val CREDENTIALS_MESSAGE = "Camera node credentials invalid or revoked. Re-provision this device."

        /** Maps an HTTP response of POST /api/iot/evidence (M-LIVE-02) to a local state. */
        fun fromResponse(code: Int, body: String?): UploadOutcome {
            val json = runCatching { JSONObject(body ?: "") }.getOrNull()
            val error = json?.optString("error")?.takeIf { it.isNotBlank() }?.take(300)
            fun id(key: String) = json?.takeIf { it.has(key) && !it.isNull(key) }?.optLong(key)
            return when {
                code == 201 || (code == 200 && json?.optBoolean("duplicate") == true) -> UploadOutcome(
                    EvidenceState.UPLOADED,
                    if (code == 201) "Accepted by X-MAN." else "Already accepted earlier (duplicate): nothing new was created.",
                    code, id("evidence_id"), id("incident_id"), json?.optString("status"), duplicate = code == 200)
                code == 401 -> UploadOutcome(EvidenceState.FAILED_RETRYABLE, CREDENTIALS_MESSAGE, code)
                code == 403 -> UploadOutcome(EvidenceState.FAILED_PERMANENT,
                    "This device is not allowed to upload evidence (not a camera node).", code)
                code == 413 -> UploadOutcome(EvidenceState.FAILED_PERMANENT, "Evidence package is too large.", code)
                code == 429 -> UploadOutcome(EvidenceState.FAILED_RETRYABLE,
                    "Rate limited by X-MAN. Retry later with the same evidence.", code)
                code >= 500 -> UploadOutcome(EvidenceState.FAILED_RETRYABLE, "X-MAN server error ($code). Retry later.", code)
                code == 400 -> UploadOutcome(EvidenceState.FAILED_PERMANENT, "Rejected by X-MAN: ${error ?: "invalid evidence"}", code)
                code in 400..499 -> UploadOutcome(EvidenceState.FAILED_PERMANENT, "Rejected by X-MAN ($code).", code)
                else -> UploadOutcome(EvidenceState.FAILED_RETRYABLE, "Unexpected response ($code). Retry later.", code)
            }
        }

        fun networkFailure() = UploadOutcome(EvidenceState.FAILED_RETRYABLE,
            "Network unavailable or timed out. The evidence is kept on this phone; retry when online.")
    }
}

/** multipart/form-data body: `metadata` (JSON) + frame_0..frame_2 (JPEG). No client paths are sent. */
class Multipart(metadata: String, frames: List<ByteArray>, val boundary: String = "xman-" + UUID.randomUUID()) {
    val contentType = "multipart/form-data; boundary=$boundary"
    val body: ByteArray

    init {
        require(frames.size in 1..EvidencePackage.MAX_FRAMES)
        val out = ByteArrayOutputStream()
        fun line(s: String = "") = out.write("$s\r\n".toByteArray(Charsets.UTF_8))
        line("--$boundary")
        line("Content-Disposition: form-data; name=\"metadata\"")
        line("Content-Type: application/json; charset=utf-8")
        line()
        line(metadata)
        frames.forEachIndexed { i, jpeg ->
            line("--$boundary")
            line("Content-Disposition: form-data; name=\"frame_$i\"; filename=\"frame_$i.jpg\"")
            line("Content-Type: image/jpeg")
            line()
            out.write(jpeg)
            line()
        }
        line("--$boundary--")
        body = out.toByteArray()
    }
}

data class HttpResponse(val code: Int, val body: String?)

/** Seam for tests; the app uses [UrlConnectionTransport]. */
fun interface HttpTransport {
    @Throws(IOException::class)
    fun post(url: String, headers: Map<String, String>, contentType: String, body: ByteArray): HttpResponse
}

/** Platform HttpURLConnection with normal certificate/hostname validation (no pinning, nothing bypassed). */
class UrlConnectionTransport : HttpTransport {
    override fun post(url: String, headers: Map<String, String>, contentType: String, body: ByteArray): HttpResponse {
        val conn = URL(url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = "POST"
            conn.instanceFollowRedirects = false  // never replay the Authorization header to another location
            conn.connectTimeout = 15_000
            conn.readTimeout = 60_000
            conn.doOutput = true
            conn.setFixedLengthStreamingMode(body.size)
            conn.setRequestProperty("Content-Type", contentType)
            conn.setRequestProperty("Accept", "application/json")
            headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            val stream = if (code >= 400) conn.errorStream else conn.inputStream
            val text = stream?.use { it.readBytes().take(64 * 1024).toByteArray().toString(Charsets.UTF_8) }
            return HttpResponse(code, text)
        } finally {
            conn.disconnect()
        }
    }
}

/**
 * Sends one READY or FAILED_RETRYABLE package. FAILED_PERMANENT is never retried; UPLOADED is never
 * resent. Every attempt sends the same client_event_id and the same frozen metadata.
 */
class EvidenceUploader(
    private val store: EvidenceStore,
    private val transport: HttpTransport,
    private val log: (String) -> Unit = { Log.i("XmanNode", it) },
) {
    fun upload(pkg: EvidencePackage, endpoint: String, deviceId: String, apiKey: String): UploadOutcome {
        check(pkg.state == EvidenceState.READY || pkg.state == EvidenceState.FAILED_RETRYABLE) {
            "package is ${pkg.state}: only READY or FAILED_RETRYABLE packages are uploaded"
        }
        pkg.state = EvidenceState.UPLOADING
        pkg.attempts++
        store.save(pkg)
        val outcome = try {
            val multipart = Multipart(store.metadata(pkg), store.frames(pkg))
            log("authenticated upload attempted")  // never the header, key or device id
            val response = transport.post(endpoint, mapOf("Authorization" to "Bearer $deviceId:$apiKey"),
                                          multipart.contentType, multipart.body)
            UploadOutcome.fromResponse(response.code, response.body)
        } catch (e: IOException) {
            UploadOutcome.networkFailure()
        }
        pkg.state = outcome.state
        pkg.lastHttpCode = outcome.httpCode
        pkg.lastMessage = outcome.message
        if (outcome.state == EvidenceState.UPLOADED) {
            pkg.evidenceId = outcome.evidenceId
            pkg.incidentId = outcome.incidentId
            pkg.serverStatus = outcome.serverStatus
            pkg.duplicate = outcome.duplicate
            store.dropFrames(pkg)
        }
        store.save(pkg)
        return outcome
    }
}
