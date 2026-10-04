package np.xman.fieldnode

import android.os.Bundle
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.ComponentActivity

/** Enter server URL + device ID + one-time API key. The key is never pre-filled or shown again. */
class ProvisionActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // keep the key out of screenshots, screen recording and the recent-apps thumbnail
        window.setFlags(WindowManager.LayoutParams.FLAG_SECURE, WindowManager.LayoutParams.FLAG_SECURE)
        setContentView(R.layout.activity_provision)
        val credentials = Node.credentials(this)
        val url = findViewById<EditText>(R.id.server_url)
        val device = findViewById<EditText>(R.id.device_id)
        val key = findViewById<EditText>(R.id.api_key)
        val message = findViewById<TextView>(R.id.message)

        findViewById<TextView>(R.id.url_hint).text = if (Node.allowLanHttp)
            "Debug build: http:// is accepted only for localhost or a private LAN address (development only). Production must use HTTPS."
        else "HTTPS is required."
        credentials.config()?.let { url.setText(it.serverUrl); device.setText(it.deviceId) }
        showKeyState(credentials.isProvisioned)

        findViewById<Button>(R.id.save).setOnClickListener {
            message.text = try {
                val normalized = ServerUrlPolicy.normalize(url.text.toString(), Node.allowLanHttp)
                val newKey = key.text.toString().trim().ifEmpty { credentials.apiKey() ?: "" }  // blank = keep stored key
                credentials.save(normalized, device.text.toString().trim(), newKey)
                url.setText(normalized)
                "Saved. This phone is now camera node ${device.text.toString().trim()}."
            } catch (e: IllegalArgumentException) {
                e.message ?: "Invalid input"  // validation messages never contain the key
            }
            key.text.clear()
            showKeyState(credentials.isProvisioned)
        }
        findViewById<Button>(R.id.clear).setOnClickListener {
            credentials.clear()
            url.text.clear(); device.text.clear(); key.text.clear()
            showKeyState(false)
            message.text = "Credentials cleared. Captured evidence on this phone is kept."
        }
    }

    private fun showKeyState(stored: Boolean) {
        findViewById<TextView>(R.id.key_label).text = if (stored)
            "API key: stored encrypted (hidden). Enter a new one only to replace it."
        else "API key (shown once by X-MAN; stored encrypted, never shown again)"
    }
}
