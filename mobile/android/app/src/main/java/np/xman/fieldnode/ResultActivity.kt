package np.xman.fieldnode

import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.TextView
import androidx.activity.ComponentActivity

/** Upload status of one package; manual "Retry upload" with the same client_event_id. */
class ResultActivity : ComponentActivity() {
    private lateinit var store: EvidenceStore
    private lateinit var pkg: EvidencePackage

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_result)
        store = Node.store(this)
        pkg = intent.getStringExtra(EXTRA_ID)?.let { runCatching { store.load(it) }.getOrNull() } ?: run { finish(); return }

        findViewById<Button>(R.id.retry).setOnClickListener { upload() }
        findViewById<Button>(R.id.discard).setOnClickListener { store.delete(pkg); finish() }
        findViewById<Button>(R.id.done).setOnClickListener { finish() }
        render()
        if (pkg.state == EvidenceState.READY) upload()  // the user just pressed Send Test Evidence
    }

    private fun upload() {
        val credentials = Node.credentials(this)
        val config = credentials.config()
        val apiKey = credentials.apiKey()
        if (config == null || apiKey == null) {
            pkg.lastMessage = "This phone is not provisioned (or its key is unavailable). Re-provision, then retry."
            render()
            return
        }
        pkg.state = EvidenceState.UPLOADING
        render()
        Node.io.execute {
            val uploader = EvidenceUploader(store, UrlConnectionTransport())
            runCatching { uploader.upload(store.load(pkg.clientEventId)!!, config.evidenceEndpoint, config.deviceId, apiKey) }
            runOnUiThread { pkg = store.load(pkg.clientEventId) ?: pkg; render() }
        }
    }

    private fun render() {
        findViewById<TextView>(R.id.result).text = buildString {
            appendLine("Client event ID: ${pkg.clientEventId}")
            appendLine("Upload status: ${pkg.state}")
            appendLine("Frames: ${pkg.frameCount}${if (pkg.state == EvidenceState.UPLOADED) " (removed from phone after acceptance)" else " (kept on this phone)"}")
            pkg.capturedAtMs?.let { appendLine("Captured at (UTC): ${EvidenceMetadata.iso(it)}") }
            appendLine("Attempts: ${pkg.attempts}")
            pkg.lastHttpCode?.let { appendLine("HTTP status: $it") }
            pkg.evidenceId?.let { appendLine("Evidence ID: $it") }
            pkg.incidentId?.let { appendLine("Incident ID: $it") }
            pkg.serverStatus?.let { appendLine("Server evidence status: $it${if (pkg.duplicate) " (duplicate)" else ""}") }
            pkg.lastMessage?.let { appendLine(); appendLine(it) }
        }
        findViewById<View>(R.id.retry).visibility = if (pkg.canRetry) View.VISIBLE else View.GONE
        findViewById<View>(R.id.discard).visibility =
            if (pkg.state == EvidenceState.FAILED_PERMANENT) View.VISIBLE else View.GONE
    }

    companion object {
        const val EXTRA_ID = "client_event_id"
    }
}
