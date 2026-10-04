package np.xman.fieldnode

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.IOException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

private const val KEY = "TestOnly_NotARealKey_0123456789abcdefghijkl"  // fake, same shape as an X-MAN key
private const val DEVICE = "PHONE-LANDSLIDE-TEST-001"
private const val ENDPOINT = "https://xman.example.org/api/iot/evidence"

/** Records every request; answers with the scripted responses (an IOException = network failure). */
private class FakeTransport(vararg responses: Any) : HttpTransport {
    val queue = ArrayDeque(responses.toList())
    val requests = mutableListOf<Triple<Map<String, String>, String, String>>()  // headers, contentType, body

    override fun post(url: String, headers: Map<String, String>, contentType: String, body: ByteArray): HttpResponse {
        requests += Triple(headers, contentType, body.toString(Charsets.ISO_8859_1))
        return when (val next = queue.removeFirst()) {
            is IOException -> throw next
            is HttpResponse -> next
            else -> error("bad script")
        }
    }

    fun metadataOf(i: Int): JSONObject {
        val body = requests[i].third
        val start = body.indexOf("application/json; charset=utf-8\r\n\r\n") + "application/json; charset=utf-8\r\n\r\n".length
        return JSONObject(body.substring(start, body.indexOf("\r\n", start)))
    }
}

class EvidenceUploaderTest {
    @get:Rule val tmp = TemporaryFolder()
    private val logs = mutableListOf<String>()

    private fun ready(store: EvidenceStore, frames: Int = 2): EvidencePackage {
        val pkg = store.create()
        repeat(frames) { store.addFrame(pkg, byteArrayOf(it.toByte()), 1_791_100_000_000L) }
        store.markReady(pkg, EvidenceMetadata.build(pkg, null, "0.1.0", 70, "wifi"))
        return pkg
    }

    private fun created(id: Int = 41) = HttpResponse(201,
        """{"success": true, "duplicate": false, "evidence_id": $id, "incident_id": 9, "status": "attached"}""")

    @Test fun successStoresServerIdsAndDropsFrames() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val transport = FakeTransport(created())
        val outcome = EvidenceUploader(store, transport) { logs += it }.upload(pkg, ENDPOINT, DEVICE, KEY)
        assertEquals(EvidenceState.UPLOADED, outcome.state)
        val saved = store.load(pkg.clientEventId)!!
        assertEquals(41L, saved.evidenceId); assertEquals(9L, saved.incidentId); assertEquals(1, saved.attempts)
        assertFalse(store.frameFile(saved, 0).exists())
        assertEquals("Bearer $DEVICE:$KEY", transport.requests[0].first["Authorization"])
    }

    @Test fun networkFailureKeepsEvidenceAndRetryReusesTheSameId() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val transport = FakeTransport(IOException("timeout"), HttpResponse(503, null), created())
        val uploader = EvidenceUploader(store, transport) { logs += it }

        assertEquals(EvidenceState.FAILED_RETRYABLE, uploader.upload(pkg, ENDPOINT, DEVICE, KEY).state)
        assertTrue(store.frameFile(pkg, 0).exists() && store.frameFile(pkg, 1).exists())
        val reloaded = store.load(pkg.clientEventId)!!  // e.g. after an app restart
        assertTrue(reloaded.canRetry)
        assertEquals(EvidenceState.FAILED_RETRYABLE, uploader.upload(reloaded, ENDPOINT, DEVICE, KEY).state)
        assertEquals(EvidenceState.UPLOADED, uploader.upload(store.load(pkg.clientEventId)!!, ENDPOINT, DEVICE, KEY).state)

        val sent = (0..2).map { transport.metadataOf(it) }
        assertTrue(sent.all { it.getString("client_event_id") == pkg.clientEventId })
        assertTrue(sent.all { it.toString() == sent[0].toString() })  // frozen metadata: identical retries
        assertEquals(3, store.load(pkg.clientEventId)!!.attempts)
    }

    @Test fun permanentFailureIsNeverRetried() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val transport = FakeTransport(HttpResponse(400, """{"error": "frame_0: Photo is not a valid image"}"""))
        val uploader = EvidenceUploader(store, transport) { logs += it }
        assertEquals(EvidenceState.FAILED_PERMANENT, uploader.upload(pkg, ENDPOINT, DEVICE, KEY).state)
        val saved = store.load(pkg.clientEventId)!!
        assertFalse(saved.canRetry)
        assertThrows(IllegalStateException::class.java) { uploader.upload(saved, ENDPOINT, DEVICE, KEY) }
        assertEquals(1, transport.requests.size)
    }

    @Test fun uploadedPackageIsNeverResent() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val uploader = EvidenceUploader(store, FakeTransport(created())) { logs += it }
        uploader.upload(pkg, ENDPOINT, DEVICE, KEY)
        assertThrows(IllegalStateException::class.java) { uploader.upload(store.load(pkg.clientEventId)!!, ENDPOINT, DEVICE, KEY) }
    }

    @Test fun draftIsNotUploaded() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = store.create()
        assertThrows(IllegalStateException::class.java) {
            EvidenceUploader(store, FakeTransport()) { logs += it }.upload(pkg, ENDPOINT, DEVICE, KEY)
        }
    }

    @Test fun duplicateResponseCountsAsAccepted() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val dup = HttpResponse(200, """{"success": true, "duplicate": true, "evidence_id": 41, "incident_id": 9, "status": "attached"}""")
        EvidenceUploader(store, FakeTransport(dup)) { logs += it }.upload(pkg, ENDPOINT, DEVICE, KEY)
        val saved = store.load(pkg.clientEventId)!!
        assertEquals(EvidenceState.UPLOADED, saved.state)
        assertTrue(saved.duplicate)
    }

    @Test fun credentialsRejectedAskForReprovisioning() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val outcome = EvidenceUploader(store, FakeTransport(HttpResponse(401, "{}"))) { logs += it }.upload(pkg, ENDPOINT, DEVICE, KEY)
        assertEquals(UploadOutcome.CREDENTIALS_MESSAGE, outcome.message)
        assertTrue(store.frameFile(pkg, 0).exists())
    }

    @Test fun rateLimitedIsRetryableLater() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = ready(store)
        val outcome = EvidenceUploader(store, FakeTransport(HttpResponse(429, """{"error":"x"}"""))) { logs += it }
            .upload(pkg, ENDPOINT, DEVICE, KEY)
        assertEquals(EvidenceState.FAILED_RETRYABLE, outcome.state)
        assertTrue(outcome.message.contains("Rate limited"))
    }

    @Test fun nothingSecretIsLoggedOrStored() {
        val root = tmp.newFolder()
        val store = EvidenceStore(root)
        val pkg = ready(store)
        EvidenceUploader(store, FakeTransport(IOException("x"), created())) { logs += it }.apply {
            upload(pkg, ENDPOINT, DEVICE, KEY)
            upload(store.load(pkg.clientEventId)!!, ENDPOINT, DEVICE, KEY)
        }
        assertEquals(listOf("authenticated upload attempted", "authenticated upload attempted"), logs)
        val onDisk = root.walkTopDown().filter { it.isFile }.joinToString("\n") { it.readText(Charsets.ISO_8859_1) }
        assertFalse(onDisk.contains(KEY) || onDisk.contains("Bearer"))
    }

    @Test fun requestBodyHasNoKeyAndNoForbiddenFields() {
        val store = EvidenceStore(tmp.newFolder())
        val transport = FakeTransport(created())
        EvidenceUploader(store, transport) { logs += it }.upload(ready(store), ENDPOINT, DEVICE, KEY)
        assertFalse(transport.requests[0].third.contains(KEY))
        val meta = transport.metadataOf(0)
        assertTrue(EvidenceMetadata.ALLOWED.containsAll(meta.keyNames()))
        assertFalse(meta.has("district_id") || meta.has("severity") || meta.has("device_score"))
    }
}

/** JVM stand-in for the Android Keystore cipher: same algorithm (AES-256-GCM), key in memory. */
private class JvmCipher : SecretCipher {
    var key: SecretKey? = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
    override fun encrypt(plain: ByteArray): Pair<ByteArray, ByteArray> {
        val c = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
        return c.iv to c.doFinal(plain)
    }
    override fun decrypt(iv: ByteArray, ciphertext: ByteArray): ByteArray =
        Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE, key!!, GCMParameterSpec(128, iv)) }.doFinal(ciphertext)
    override fun destroyKey() { key = null }
}

private class MapStore : KeyValueStore {
    val map = mutableMapOf<String, String>()
    override fun get(key: String) = map[key]
    override fun put(values: Map<String, String>) { map.putAll(values) }
    override fun remove(keys: Collection<String>) { keys.forEach { map.remove(it) } }
}

class CredentialStoreTest {
    @Test fun keyIsStoredEncryptedAndRetrievable() {
        val kv = MapStore()
        val store = CredentialStore(kv, JvmCipher())
        store.save("https://xman.example.org", DEVICE, KEY)
        assertTrue(store.isProvisioned)
        assertEquals(KEY, store.apiKey())
        assertFalse(kv.map.values.any { it.contains(KEY) })  // only ciphertext at rest
        assertEquals(NodeConfig("https://xman.example.org", DEVICE), store.config())
        assertFalse(store.config().toString().contains(KEY))
    }

    @Test fun clearRemovesEverythingAndTheKey() {
        val kv = MapStore()
        val cipher = JvmCipher()
        val store = CredentialStore(kv, cipher)
        store.save("https://xman.example.org", DEVICE, KEY)
        store.clear()
        assertTrue(kv.map.isEmpty())
        assertNull(cipher.key)
        assertNull(store.apiKey())
        assertFalse(store.isProvisioned)
    }

    @Test fun lostKeystoreKeyMeansNoKeyNotACrash() {
        val cipher = JvmCipher()
        val store = CredentialStore(MapStore(), cipher)
        store.save("https://xman.example.org", DEVICE, KEY)
        cipher.key = KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()  // e.g. key invalidated
        assertNull(store.apiKey())
    }

    @Test fun validationMessagesNeverEchoTheKey() {
        val store = CredentialStore(MapStore(), JvmCipher())
        val badKey = "short key with spaces"
        val e = assertThrows(IllegalArgumentException::class.java) { store.save("https://x.org", DEVICE, badKey) }
        assertFalse(e.message!!.contains(badKey))
        assertThrows(IllegalArgumentException::class.java) { store.save("https://x.org", "PHONE:01", KEY) }
        assertThrows(IllegalArgumentException::class.java) { store.save("https://x.org", DEVICE, "$KEY:extra") }
    }
}

class ServerUrlPolicyTest {
    @Test fun httpsAlwaysAllowed() {
        assertEquals("https://xman.example.org", ServerUrlPolicy.normalize(" https://XMAN.example.org/ ", false))
        assertEquals("https://xman.example.org:8443/x", ServerUrlPolicy.normalize("https://xman.example.org:8443/x/", false))
    }

    @Test fun lanHttpOnlyInDebug() {
        assertEquals("http://192.168.1.20:5000", ServerUrlPolicy.normalize("http://192.168.1.20:5000", true))
        for (url in listOf("http://10.0.0.5:5000", "http://172.20.1.1", "http://localhost:5000", "http://127.0.0.1:5000")) {
            ServerUrlPolicy.normalize(url, true)
        }
        assertThrows(IllegalArgumentException::class.java) { ServerUrlPolicy.normalize("http://192.168.1.20:5000", false) }
    }

    @Test fun publicHttpRefusedEvenInDebug() {
        for (url in listOf("http://xman.example.org", "http://8.8.8.8", "http://172.32.0.1", "http://192.169.1.1")) {
            assertThrows(url, IllegalArgumentException::class.java) { ServerUrlPolicy.normalize(url, true) }
        }
    }

    @Test fun noCredentialsQueryOrOtherSchemes() {
        for (url in listOf("https://user:pw@xman.example.org", "https://xman.example.org/?key=abc",
                           "https://xman.example.org/#x", "ftp://xman.example.org", "xman.example.org", "", "https://")) {
            assertThrows(url, IllegalArgumentException::class.java) { ServerUrlPolicy.normalize(url, true) }
        }
    }

    @Test fun endpointsDerivedFromBase() {
        val c = NodeConfig("https://xman.example.org", DEVICE)
        assertEquals("https://xman.example.org/api/iot/evidence", c.evidenceEndpoint)
        assertEquals("https://xman.example.org/api/health", c.healthEndpoint)
    }
}
