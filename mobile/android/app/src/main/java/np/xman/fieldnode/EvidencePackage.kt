package np.xman.fieldnode

import org.json.JSONObject
import java.util.UUID

/**
 * Local lifecycle of one manually captured test-evidence package (M-LIVE-03).
 *
 * DRAFT -> READY (metadata frozen by "Send Test Evidence") -> UPLOADING
 *   -> UPLOADED | FAILED_RETRYABLE (network, 5xx, 429, 401 after re-provisioning) | FAILED_PERMANENT (400/403/413)
 * FAILED_RETRYABLE -> UPLOADING again only when the user presses "Retry upload", with the same client_event_id.
 */
enum class EvidenceState { DRAFT, READY, UPLOADING, UPLOADED, FAILED_RETRYABLE, FAILED_PERMANENT }

/** One GPS fix from the platform location provider. Never invented: absent means "no fix". */
data class GpsFix(val latitude: Double, val longitude: Double, val accuracyM: Double?, val fixTimeMs: Long)

data class EvidencePackage(
    /** Idempotency key sent to X-MAN: created once per package, reused on every retry. */
    val clientEventId: String = newClientEventId(),
    var state: EvidenceState = EvidenceState.DRAFT,
    var frameCount: Int = 0,
    /** Device clock (ms) when the first frame was captured. */
    var capturedAtMs: Long? = null,
    var attempts: Int = 0,
    var lastHttpCode: Int? = null,
    var lastMessage: String? = null,
    var evidenceId: Long? = null,
    var incidentId: Long? = null,
    var serverStatus: String? = null,
    var duplicate: Boolean = false,
    /** What created the package: a person ("manual", M-LIVE-03) or the visual monitor ("motion_gate", M-LIVE-04). */
    var trigger: String = TRIGGER_MANUAL,
    /** GPS outcome in words (e.g. "fix", "unavailable: no permission"); coordinates are never invented. */
    var gpsNote: String? = null,
) {
    val canRetry get() = state == EvidenceState.FAILED_RETRYABLE

    fun toJson(): JSONObject = JSONObject()
        .put("client_event_id", clientEventId).put("state", state.name).put("frame_count", frameCount)
        .put("captured_at_ms", capturedAtMs ?: JSONObject.NULL).put("attempts", attempts)
        .put("last_http_code", lastHttpCode ?: JSONObject.NULL).put("last_message", lastMessage ?: JSONObject.NULL)
        .put("evidence_id", evidenceId ?: JSONObject.NULL).put("incident_id", incidentId ?: JSONObject.NULL)
        .put("server_status", serverStatus ?: JSONObject.NULL).put("duplicate", duplicate)
        .put("trigger", trigger).put("gps_note", gpsNote ?: JSONObject.NULL)

    companion object {
        const val MAX_FRAMES = 3
        const val TRIGGER_MANUAL = "manual"
        const val TRIGGER_MOTION_GATE = "motion_gate"

        /** UUID v4: matches the server's ^[A-Za-z0-9_-]{8,64}$. */
        fun newClientEventId(): String = UUID.randomUUID().toString()

        fun fromJson(json: JSONObject): EvidencePackage {
            fun long(key: String) = if (json.isNull(key)) null else json.getLong(key)
            fun str(key: String) = if (json.isNull(key)) null else json.getString(key)
            return EvidencePackage(
                clientEventId = json.getString("client_event_id"),
                state = EvidenceState.valueOf(json.getString("state")),
                frameCount = json.getInt("frame_count"),
                capturedAtMs = long("captured_at_ms"),
                attempts = json.getInt("attempts"),
                lastHttpCode = long("last_http_code")?.toInt(),
                lastMessage = str("last_message"),
                evidenceId = long("evidence_id"),
                incidentId = long("incident_id"),
                serverStatus = str("server_status"),
                duplicate = json.optBoolean("duplicate", false),
                trigger = json.optString("trigger", TRIGGER_MANUAL),  // M-LIVE-03 packages have no trigger
                gpsNote = if (json.has("gps_note")) str("gps_note") else null,
            )
        }
    }
}
