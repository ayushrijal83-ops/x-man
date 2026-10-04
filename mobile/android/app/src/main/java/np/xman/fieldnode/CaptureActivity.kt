package np.xman.fieldnode

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.BitmapFactory
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.provider.Settings
import android.view.View
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat

/**
 * Manual capture of up to 3 frames + one GPS fix, then "Send Test Evidence". The camera runs only while
 * this screen is visible (bound to its lifecycle): no background camera, no continuous analysis.
 */
class CaptureActivity : ComponentActivity() {
    private lateinit var store: EvidenceStore
    private lateinit var pkg: EvidencePackage
    private var imageCapture: ImageCapture? = null
    private var gpsFix: GpsFix? = null
    private var gpsCancel: CancellationSignal? = null
    private var busy = false
    private var cameraAsked = false

    private val cameraPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
        if (granted) startCamera() else showCameraDenied()
    }
    private val locationPermission = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result[Manifest.permission.ACCESS_FINE_LOCATION] == true) requestGps()
        else gpsText("GPS unavailable: location permission denied. Evidence can still be sent, without GPS metadata; " +
                     "X-MAN then uses the node's registered location.")
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_capture)
        if (!Node.credentials(this).isProvisioned) { finish(); return }
        store = Node.store(this)
        pkg = store.all().firstOrNull { it.state == EvidenceState.DRAFT } ?: store.create()

        findViewById<Button>(R.id.capture).setOnClickListener { capture() }
        findViewById<Button>(R.id.clear_frames).setOnClickListener { store.clearFrames(pkg); render() }
        findViewById<Button>(R.id.gps_fix).setOnClickListener { onGpsPressed() }
        findViewById<Button>(R.id.send).setOnClickListener { send() }
        findViewById<Button>(R.id.camera_permission).setOnClickListener { onCameraPermissionPressed() }
        gpsText(getString(R.string.location_rationale) + "\nNo GPS fix yet. Press Get GPS fix (works best outdoors).")

        if (hasCamera()) startCamera() else { cameraAsked = true; cameraPermission.launch(Manifest.permission.CAMERA) }
        render()
    }

    override fun onDestroy() {
        gpsCancel?.cancel()
        super.onDestroy()
    }

    private fun hasCamera() =
        ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED

    private fun startCamera() {
        findViewById<View>(R.id.camera_permission).visibility = View.GONE
        findViewById<TextView>(R.id.camera_message).text = getString(R.string.camera_rationale)
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            val provider = future.get()
            val preview = Preview.Builder().build().also {
                it.surfaceProvider = findViewById<PreviewView>(R.id.preview).surfaceProvider
            }
            val capture = ImageCapture.Builder().setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY).build()
            provider.unbindAll()
            provider.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, capture)
            imageCapture = capture
            render()
        }, ContextCompat.getMainExecutor(this))
    }

    /** One request per screen visit; after a permanent denial the button leads to app settings. */
    private fun showCameraDenied() {
        findViewById<TextView>(R.id.camera_message).text =
            "Camera permission denied. ${getString(R.string.camera_rationale)}"
        findViewById<View>(R.id.camera_permission).visibility = View.VISIBLE
        render()
    }

    private fun onCameraPermissionPressed() {
        if (shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) {
            cameraPermission.launch(Manifest.permission.CAMERA)
        } else {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", packageName, null)))
        }
    }

    private fun capture() {
        val capture = imageCapture ?: return
        if (busy || pkg.frameCount >= EvidencePackage.MAX_FRAMES) return
        busy = true
        render()
        val pressedAt = System.currentTimeMillis()
        capture.takePicture(Node.io, object : ImageCapture.OnImageCapturedCallback() {
            override fun onCaptureSuccess(image: ImageProxy) {
                val jpeg = image.use { FrameEncoder.encode(it.toBitmap(), it.imageInfo.rotationDegrees) }
                store.addFrame(pkg, jpeg, pressedAt)
                runOnUiThread { busy = false; render() }
            }

            override fun onError(exception: ImageCaptureException) {
                runOnUiThread {
                    busy = false
                    findViewById<TextView>(R.id.camera_message).text = "Capture failed. Try again."
                    render()
                }
            }
        })
    }

    private fun onGpsPressed() {
        if (Gps.hasPermission(this)) requestGps()
        else locationPermission.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    private fun requestGps() {
        if (!Gps.providerEnabled(this)) {
            gpsText("GPS is switched off. Turn on location in the phone settings, then press Get GPS fix again.")
            return
        }
        gpsCancel?.cancel()
        val cancel = CancellationSignal().also { gpsCancel = it }
        gpsText("Waiting for a GPS fix (this can take a minute; outdoors works best)...")
        Gps.requestFix(this, cancel) { fix ->
            if (fix != null) gpsFix = fix
            gpsText(fix?.let {
                "Location: %.6f, %.6f\nAccuracy: %s\nFix time (UTC): %s".format(
                    it.latitude, it.longitude, it.accuracyM?.let { a -> "%.0f m".format(a) } ?: "unknown",
                    EvidenceMetadata.iso(it.fixTimeMs))
            } ?: "No GPS fix obtained. Press Get GPS fix to retry. Nothing is invented: without a fix, no coordinates are sent.")
        }
    }

    private fun gpsText(text: String) {
        findViewById<TextView>(R.id.gps).text = text
    }

    private fun send() {
        if (pkg.frameCount == 0) return
        val metadata = EvidenceMetadata.build(pkg, gpsFix, BuildConfig.VERSION_NAME,
                                              DeviceStatus.batteryPct(this), DeviceStatus.networkType(this))
        store.markReady(pkg, metadata)
        startActivity(Intent(this, ResultActivity::class.java).putExtra(ResultActivity.EXTRA_ID, pkg.clientEventId))
        finish()
    }

    private fun render() {
        val thumbs = listOf(R.id.thumb0, R.id.thumb1, R.id.thumb2).map { findViewById<ImageView>(it) }
        thumbs.forEachIndexed { i, view ->
            if (i < pkg.frameCount) {
                val opts = BitmapFactory.Options().apply { inSampleSize = 8 }
                view.setImageBitmap(BitmapFactory.decodeFile(store.frameFile(pkg, i).path, opts))
            } else view.setImageDrawable(null)
        }
        val full = pkg.frameCount >= EvidencePackage.MAX_FRAMES
        findViewById<Button>(R.id.capture).apply {
            text = if (full) "3/3 captured" else "Capture frame ${pkg.frameCount + 1}/3"
            isEnabled = imageCapture != null && !busy && !full
        }
        findViewById<Button>(R.id.clear_frames).isEnabled = pkg.frameCount > 0 && !busy
        findViewById<Button>(R.id.send).isEnabled = pkg.frameCount > 0 && !busy
    }
}
