package np.xman.fieldnode

import android.content.Intent
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity
import java.net.HttpURLConnection
import java.net.URL

/** Node status: identity (never the key), GPS, battery, network, last upload. */
class MainActivity : ComponentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        findViewById<Button>(R.id.provision).setOnClickListener { startActivity(Intent(this, ProvisionActivity::class.java)) }
        findViewById<Button>(R.id.capture).setOnClickListener { startActivity(Intent(this, CaptureActivity::class.java)) }
        findViewById<Button>(R.id.monitor).setOnClickListener { startActivity(Intent(this, MonitorActivity::class.java)) }
        findViewById<Button>(R.id.last).setOnClickListener {
            Node.store(this).all().firstOrNull { it.state != EvidenceState.DRAFT }?.let {
                startActivity(Intent(this, ResultActivity::class.java).putExtra(ResultActivity.EXTRA_ID, it.clientEventId))
            }
        }
        findViewById<Button>(R.id.test_connection).setOnClickListener { testConnection() }
    }

    override fun onResume() {
        super.onResume()
        val config = Node.credentials(this).config()
        val provisioned = Node.credentials(this).isProvisioned
        val last = Node.store(this).all().firstOrNull { it.state != EvidenceState.DRAFT }
        val gps = when {
            !Gps.hasPermission(this) -> "location permission not granted"
            !Gps.providerEnabled(this) -> "GPS is switched off"
            else -> "available (fix taken on the capture screen)"
        }
        findViewById<TextView>(R.id.status).text = buildString {
            appendLine("Provisioning: ${if (provisioned) "provisioned" else "NOT provisioned"}")
            appendLine("Device ID: ${config?.deviceId ?: "-"}")
            appendLine("Server: ${config?.serverUrl ?: "-"}")
            appendLine("API key: ${if (provisioned) "stored encrypted (hidden)" else "-"}")
            appendLine("GPS: $gps")
            appendLine("Battery: ${DeviceStatus.batteryPct(this@MainActivity)?.let { "$it%" } ?: "unknown"}")
            appendLine("Network: ${DeviceStatus.networkType(this@MainActivity)}")
            append("Last upload: ")
            append(last?.let { "${it.state} - ${it.lastMessage ?: ""}" } ?: "none")
        }
        findViewById<Button>(R.id.capture).isEnabled = provisioned
        findViewById<Button>(R.id.monitor).isEnabled = provisioned
        findViewById<Button>(R.id.last).isEnabled = last != null
        findViewById<Button>(R.id.test_connection).isEnabled = config != null
    }

    /** Reachability only, via the public /api/health. No credentials are sent: X-MAN has no authenticated
     *  device health check, so credentials are proven by the first test-evidence upload. */
    private fun testConnection() {
        val config = Node.credentials(this).config() ?: return
        val out = findViewById<TextView>(R.id.connection)
        out.text = "Checking ${config.serverUrl} ..."
        Node.io.execute {
            val text = try {
                val conn = URL(config.healthEndpoint).openConnection() as HttpURLConnection
                conn.instanceFollowRedirects = false
                conn.connectTimeout = 10_000
                conn.readTimeout = 10_000
                val code = conn.responseCode
                conn.disconnect()
                if (code == 200) "Server reachable (HTTP 200). Credentials are checked when test evidence is sent."
                else "Server answered HTTP $code."
            } catch (e: Exception) {
                "Server not reachable (${e.javaClass.simpleName})."
            }
            runOnUiThread { out.text = text }
        }
    }
}
