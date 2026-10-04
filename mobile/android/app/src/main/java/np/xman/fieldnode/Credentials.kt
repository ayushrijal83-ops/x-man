package np.xman.fieldnode

import java.net.URI
import java.util.Base64

/** Encrypts the API key. Production: [KeystoreCipher] (Android Keystore AES-GCM, key never leaves the keystore). */
interface SecretCipher {
    /** Returns (iv, ciphertext). */
    fun encrypt(plain: ByteArray): Pair<ByteArray, ByteArray>
    fun decrypt(iv: ByteArray, ciphertext: ByteArray): ByteArray
    fun destroyKey()
}

/** Minimal persistent string map (SharedPreferences in the app, a HashMap in tests). */
interface KeyValueStore {
    fun get(key: String): String?
    fun put(values: Map<String, String>)
    fun remove(keys: Collection<String>)
}

/** Non-secret node configuration. toString is safe to log: there is no key in it. */
data class NodeConfig(val serverUrl: String, val deviceId: String) {
    val evidenceEndpoint get() = "$serverUrl/api/iot/evidence"
    val healthEndpoint get() = "$serverUrl/api/health"
}

/**
 * One camera-node identity (device_id + API key) per installation. The key is stored only as Keystore
 * ciphertext; it is never returned by [config], never shown again after provisioning and never logged.
 */
class CredentialStore(private val kv: KeyValueStore, private val cipher: SecretCipher) {

    fun save(serverUrl: String, deviceId: String, apiKey: String) {
        require(DEVICE_ID_RE.matches(deviceId)) { "Device ID: 1-64 letters, digits, '.', '_' or '-'" }
        require(apiKey.length in 16..200 && apiKey.none { it.isWhitespace() || it == ':' }) {
            "API key looks wrong: paste the one-time key exactly as shown by X-MAN"
        }
        val (iv, ct) = cipher.encrypt(apiKey.toByteArray(Charsets.UTF_8))
        kv.put(mapOf(URL to serverUrl, DEVICE to deviceId, KEY_IV to b64(iv), KEY_CT to b64(ct)))
    }

    fun config(): NodeConfig? {
        val url = kv.get(URL) ?: return null
        val device = kv.get(DEVICE) ?: return null
        return NodeConfig(url, device)
    }

    val isProvisioned get() = config() != null && kv.get(KEY_CT) != null

    /** For the Authorization header only. Null if not provisioned or the Keystore key is gone. */
    fun apiKey(): String? {
        val iv = kv.get(KEY_IV) ?: return null
        val ct = kv.get(KEY_CT) ?: return null
        return runCatching { String(cipher.decrypt(unb64(iv), unb64(ct)), Charsets.UTF_8) }.getOrNull()
    }

    fun clear() {
        kv.remove(listOf(URL, DEVICE, KEY_IV, KEY_CT))
        cipher.destroyKey()
    }

    companion object {
        val DEVICE_ID_RE = Regex("^[A-Za-z0-9._-]{1,64}$")  // same rule as X-MAN provisioning
        private const val URL = "server_url"
        private const val DEVICE = "device_id"
        private const val KEY_IV = "api_key_iv"
        private const val KEY_CT = "api_key_ciphertext"
        private fun b64(b: ByteArray) = Base64.getEncoder().encodeToString(b)
        private fun unb64(s: String) = Base64.getDecoder().decode(s)
    }
}

/**
 * Which X-MAN base URLs the node may talk to. HTTPS always; plain HTTP only in debug builds and only to
 * localhost / private LAN addresses (development against a local server). No credentials, query or
 * fragment in the URL: the key travels only in the Authorization header.
 */
object ServerUrlPolicy {
    fun normalize(raw: String, allowLanHttp: Boolean): String {
        val uri = try { URI(raw.trim()) } catch (e: Exception) { throw IllegalArgumentException("Server URL is not valid") }
        val scheme = uri.scheme?.lowercase()
        val host = uri.host?.lowercase() ?: throw IllegalArgumentException("Server URL needs a host, e.g. https://xman.example.org")
        require(uri.rawUserInfo == null && uri.rawQuery == null && uri.rawFragment == null) {
            "Server URL must not contain credentials, a query or a fragment"
        }
        when (scheme) {
            "https" -> Unit
            "http" -> require(allowLanHttp && isLocalOrPrivate(host)) {
                if (allowLanHttp) "HTTP is only allowed for localhost or a private LAN address (development)"
                else "HTTPS is required"
            }
            else -> throw IllegalArgumentException("Server URL must start with https://")
        }
        val port = if (uri.port == -1) "" else ":${uri.port}"
        val path = (uri.rawPath ?: "").trimEnd('/')
        return "$scheme://$host$port$path"
    }

    fun isLocalOrPrivate(host: String): Boolean {
        if (host == "localhost") return true
        val parts = host.split('.').map { it.toIntOrNull() ?: return false }
        if (parts.size != 4 || parts.any { it !in 0..255 }) return false
        val (a, b) = parts
        return a == 10 || a == 127 || (a == 172 && b in 16..31) || (a == 192 && b == 168)
    }
}
