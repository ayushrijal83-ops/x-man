package np.xman.fieldnode

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.CameraState
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Visual monitoring (M-LIVE-04): the camera runs ONLY between "Start monitoring" and "Stop monitoring",
 * with the preview visible and the screen kept on. Leaving the screen stops monitoring: there is no
 * background camera and no foreground service. Detects persistent local visual change, nothing more.
 */
class MonitorActivity : ComponentActivity(), MonitorEffects {
    private val config = MonitorConfig()
    private lateinit var controller: MonitorController
    private lateinit var analysisExecutor: ExecutorService
    private var provider: ProcessCameraProvider? = null
    private var gpsCancel: CancellationSignal? = null
    private val ui = Handler(Looper.getMainLooper())
    private var pendingUploads = 0
    private var refreshes = 0

    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        if (result[Manifest.permission.CAMERA] == true) startMonitoring()
        else status("Camera permission denied. ${getString(R.string.camera_rationale)}")
    }

    private val refresh = object : Runnable {
        override fun run() { render(); ui.postDelayed(this, 500) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_monitor)
        controller = MonitorController(config, this)  // wall clock: same clock as the analysis timestamps
        findViewById<CheckBox>(R.id.auto_upload).setOnCheckedChangeListener { _, on -> controller.autoUpload = on }
        findViewById<Button>(R.id.toggle).setOnClickListener {
            if (controller.running) stopMonitoring() else requestAndStart()
        }
        findViewById<Button>(R.id.last).setOnClickListener {
            Node.store(this).all().firstOrNull { it.state != EvidenceState.DRAFT }?.let {
                startActivity(Intent(this, ResultActivity::class.java).putExtra(ResultActivity.EXTRA_ID, it.clientEventId))
            }
        }
    }

    override fun onResume() { super.onResume(); ui.post(refresh) }

    override fun onPause() { ui.removeCallbacks(refresh); super.onPause() }

    /** Not visible = not monitoring. */
    override fun onStop() { stopMonitoring(); super.onStop() }

    private fun requestAndStart() {
        val camera = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        // location is asked up front because the fix is taken at confirmation, possibly unattended
        if (camera && Gps.hasPermission(this)) startMonitoring()
        else permissions.launch(arrayOf(Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
                                        Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    private fun startMonitoring() {
        if (controller.running) return
        analysisExecutor = Executors.newSingleThreadExecutor()
        controller.start()
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (!controller.running) return@addListener  // stopped before the camera came up
            try {
                val p = future.get().also { provider = it }
                val preview = Preview.Builder().build().also {
                    it.surfaceProvider = findViewById<PreviewView>(R.id.preview).surfaceProvider
                }
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)  // never queue frames
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                    .build()
                analysis.setAnalyzer(analysisExecutor, ::analyze)
                p.unbindAll()
                val camera = p.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
                // camera errors -> DEGRADED (nothing analysed); CameraX reopens the camera -> back to MONITORING
                camera.cameraInfo.cameraState.observe(this) { state ->
                    if (state.error != null) controller.onCameraError()
                    else if (state.type == CameraState.Type.OPEN && controller.state == MonitorState.DEGRADED) controller.onCameraRecovered()
                }
            } catch (e: Exception) {
                controller.onCameraError()
                status("Camera could not start (${e.javaClass.simpleName}). Monitoring is degraded.")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun stopMonitoring() {
        if (!controller.running) return
        controller.stop()                    // no further sample is accepted from here on
        provider?.unbindAll()                // camera closed: preview and analysis end
        provider = null
        if (::analysisExecutor.isInitialized) analysisExecutor.shutdown()
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        render()
    }

    /** Camera analysis thread. Always closes the frame; a bitmap is made only for a keyframe. */
    private fun analyze(image: ImageProxy) {
        image.use {
            val now = System.currentTimeMillis()
            if (!controller.shouldSample(now)) return
            val y = it.planes[0]
            val grid = FrameSampler.downsample(y.buffer, y.rowStride, y.pixelStride, it.width, it.height,
                                               config.gridWidth, config.gridHeight)
            controller.onSample(grid, now) {
                val bitmap = it.toBitmap()
                try { FrameEncoder.encode(bitmap, it.imageInfo.rotationDegrees) } finally { bitmap.recycle() }
            }
        }
    }

    // --- MonitorEffects ----------------------------------------------------------------------------

    override fun requestGps(onResult: (GpsFix?, String) -> Unit) {
        when {
            !Gps.hasPermission(this) -> onResult(null, "unavailable: no location permission")
            !Gps.providerEnabled(this) -> onResult(null, "unavailable: GPS switched off")
            else -> ui.post {
                gpsCancel?.cancel()
                val cancel = CancellationSignal().also { gpsCancel = it }
                Gps.requestFix(this, cancel) { fix -> onResult(fix, if (fix != null) "fix" else "unavailable: no fix obtained") }
            }
        }
    }

    override fun cancelGps() { ui.post { gpsCancel?.cancel(); gpsCancel = null } }

    override fun store(keyframes: KeyframeCollector, gps: GpsFix?, gpsNote: String): EvidencePackage? = runCatching {
        EvidenceAssembler(Node.store(this)).assemble(keyframes, gps, gpsNote, BuildConfig.VERSION_NAME,
                                                     DeviceStatus.batteryPct(this), DeviceStatus.networkType(this))
    }.getOrNull()

    override fun upload(pkg: EvidencePackage, onDone: (Boolean) -> Unit) {
        val credentials = Node.credentials(this)
        val config = credentials.config()
        val key = credentials.apiKey()
        if (config == null || key == null) { onDone(false); return }
        Node.io.execute {
            val outcome = runCatching {
                EvidenceUploader(Node.store(this), UrlConnectionTransport())
                    .upload(pkg, config.evidenceEndpoint, config.deviceId, key)
            }.getOrNull()
            onDone(outcome?.state == EvidenceState.UPLOADED)
        }
    }

    // --- UI -------------------------------------------------------------------------------------------

    private fun status(text: String) { findViewById<TextView>(R.id.status).text = text }

    private fun render() {
        if (refreshes++ % 4 == 0) {  // disk scan every 2 s, not every refresh
            pendingUploads = Node.store(this).all().count {
                it.state == EvidenceState.READY || it.state == EvidenceState.FAILED_RETRYABLE
            }
        }
        val s = controller.snapshot()
        findViewById<Button>(R.id.toggle).text = if (s.running) "Stop monitoring" else "Start monitoring"
        status(buildString {
            appendLine("Monitoring: ${if (s.running) "ON" else "OFF"}")
            appendLine("State: ${label(s.state)}")
            appendLine("Analysis rate: %.1f frames/s (target %.1f)".format(s.analysisFps, 1000f / config.analysisIntervalMs))
            appendLine("Frames analysed: ${s.framesAnalyzed}  skipped by rate limit: ${s.framesSkipped}")
            appendLine("Rejected by MotionGate: " + s.rejected.entries.joinToString { "${it.key.name.lowercase()} ${it.value}" })
            appendLine("Local motion samples: ${s.localMotion}")
            appendLine("Possible visual events: ${s.possibleEvents}")
            appendLine("Visual evidence candidates: ${s.confirmedEvents}")
            appendLine("Last event: ${s.lastEventAtMs?.let { EvidenceMetadata.iso(it) } ?: "-"}")
            appendLine("GPS: ${s.gpsStatus}")
            appendLine("Upload: ${s.uploadStatus}")
            append("Packages waiting for upload on this phone: $pendingUploads")
        })
    }

    private fun label(state: MonitorState) = when (state) {
        MonitorState.STOPPED -> "stopped"
        MonitorState.MONITORING -> "monitoring"
        MonitorState.POSSIBLE_EVENT -> "possible visual event"
        MonitorState.CONFIRMING -> "confirming persistent change"
        MonitorState.CONFIRMED_EVIDENCE -> "visual evidence candidate: collecting keyframes + GPS"
        MonitorState.UPLOAD_PENDING -> "upload pending"
        MonitorState.UPLOADED -> "uploaded"
        MonitorState.COOLDOWN -> "cooldown (no new candidate yet)"
        MonitorState.DEGRADED -> "DEGRADED: camera problem"
    }
}
