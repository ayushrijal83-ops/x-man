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
import androidx.camera.core.resolutionselector.AspectRatioStrategy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Visual monitoring (M-LIVE-04 + M-LIVE-05 area selection). The camera is used only while this screen is
 * visible: a preview to select the monitored area (nothing analysed), then preview + analysis between
 * "Start monitoring" and "Stop monitoring". Stop releases the camera; leaving the screen releases it too.
 * There is no background camera and no foreground service. Detects persistent local visual change only.
 */
class MonitorActivity : ComponentActivity(), MonitorEffects {
    private val config = MonitorConfig()
    private lateinit var controller: MonitorController
    private lateinit var analysisExecutor: ExecutorService
    private lateinit var overlay: RoiOverlayView
    private var provider: ProcessCameraProvider? = null
    private var gpsCancel: CancellationSignal? = null
    private val ui = Handler(Looper.getMainLooper())
    private var pendingUploads = 0
    private var refreshes = 0
    private var startAfterPermission = false
    private var previewing = false
    /** Upright monitoring area, read by the analysis thread. FULL = no area selected (M-LIVE-04 behaviour). */
    @Volatile private var roi: NormRect = NormRect.FULL

    private val permissions = registerForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { result ->
        when {
            result[Manifest.permission.CAMERA] != true -> status("Camera permission denied. ${getString(R.string.camera_rationale)}")
            startAfterPermission -> startMonitoring()
            else -> bindCamera(analysis = false)
        }
        startAfterPermission = false
    }

    private val refresh = object : Runnable {
        override fun run() { render(); ui.postDelayed(this, 500) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_monitor)
        controller = MonitorController(config, this)  // wall clock: same clock as the analysis timestamps
        findViewById<PreviewView>(R.id.preview).scaleType = PreviewView.ScaleType.FIT_CENTER  // whole frame visible
        roi = NormRect.decode(prefs().getString(PREF_ROI, null)) ?: NormRect.FULL
        overlay = findViewById<RoiOverlayView>(R.id.roi_overlay).apply {
            roi = this@MonitorActivity.roi
            onRoiSelected = { selected -> setRoi(selected) }
            onRoiRejected = { status("That area is too small: drag a larger rectangle (at least 10 % of the width and height).") }
        }
        findViewById<CheckBox>(R.id.auto_upload).setOnCheckedChangeListener { _, on -> controller.autoUpload = on }
        findViewById<Button>(R.id.toggle).setOnClickListener {
            if (controller.running) stopMonitoring() else requestCamera(start = true)
        }
        findViewById<Button>(R.id.preview_button).setOnClickListener { requestCamera(start = false) }
        findViewById<Button>(R.id.full_frame).setOnClickListener { setRoi(NormRect.FULL) }
        findViewById<Button>(R.id.last).setOnClickListener {
            Node.store(this).all().firstOrNull { it.state != EvidenceState.DRAFT }?.let {
                startActivity(Intent(this, ResultActivity::class.java).putExtra(ResultActivity.EXTRA_ID, it.clientEventId))
            }
        }
    }

    /** Visible screen: show the preview so the area can be selected (nothing is analysed until Start). */
    override fun onStart() { super.onStart(); requestCamera(start = false) }

    override fun onResume() { super.onResume(); ui.post(refresh) }

    override fun onPause() { ui.removeCallbacks(refresh); super.onPause() }

    /** Not visible = no monitoring and no camera at all. */
    override fun onStop() { stopMonitoring(); releaseCamera(); super.onStop() }

    private fun prefs() = getSharedPreferences("monitor", MODE_PRIVATE)

    private fun setRoi(value: NormRect) {
        if (controller.running) return  // the area is fixed while monitoring
        roi = value
        overlay.roi = value
        prefs().edit().putString(PREF_ROI, value.encode()).apply()
        render()
    }

    private fun requestCamera(start: Boolean) {
        val camera = ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
        // monitoring also asks for location: the fix is taken at confirmation, possibly unattended
        if (camera && (!start || Gps.hasPermission(this))) {
            if (start) startMonitoring() else bindCamera(analysis = false)
            return
        }
        startAfterPermission = start
        permissions.launch(arrayOf(Manifest.permission.CAMERA, Manifest.permission.ACCESS_FINE_LOCATION,
                                   Manifest.permission.ACCESS_COARSE_LOCATION))
    }

    private fun startMonitoring() {
        if (controller.running) return
        analysisExecutor = Executors.newSingleThreadExecutor()
        controller.start()
        overlay.locked = true
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        bindCamera(analysis = true)
    }

    /** Preview only (area selection, nothing analysed) or preview + analysis (monitoring). Both 4:3. */
    private fun bindCamera(analysis: Boolean) {
        val future = ProcessCameraProvider.getInstance(this)
        future.addListener({
            if (analysis != controller.running) return@addListener  // state changed before the camera came up
            if (!lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) return@addListener
            try {
                val p = future.get().also { provider = it }
                val ratio = ResolutionSelector.Builder()
                    .setAspectRatioStrategy(AspectRatioStrategy.RATIO_4_3_FALLBACK_AUTO_STRATEGY).build()
                val preview = Preview.Builder().setResolutionSelector(ratio).build().also {
                    it.surfaceProvider = findViewById<PreviewView>(R.id.preview).surfaceProvider
                }
                p.unbindAll()
                if (!analysis) {
                    p.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview)
                    previewing = true
                    return@addListener
                }
                val imageAnalysis = ImageAnalysis.Builder()
                    .setResolutionSelector(ratio)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)  // never queue frames
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_YUV_420_888)
                    .build()
                imageAnalysis.setAnalyzer(analysisExecutor, ::analyze)
                val camera = p.bindToLifecycle(this, CameraSelector.DEFAULT_BACK_CAMERA, preview, imageAnalysis)
                previewing = true
                // camera errors -> DEGRADED (nothing analysed); CameraX reopens the camera -> back to MONITORING
                camera.cameraInfo.cameraState.observe(this) { state ->
                    if (state.error != null) controller.onCameraError()
                    else if (state.type == CameraState.Type.OPEN && controller.state == MonitorState.DEGRADED) controller.onCameraRecovered()
                }
            } catch (e: Exception) {
                if (analysis) controller.onCameraError()
                status("Camera could not start (${e.javaClass.simpleName}).")
            }
        }, ContextCompat.getMainExecutor(this))
    }

    private fun releaseCamera() {
        provider?.unbindAll()
        provider = null
        previewing = false
    }

    /** Stop = analysis ends AND the camera is released; "Show preview" brings the preview back to adjust the area. */
    private fun stopMonitoring() {
        if (!controller.running) return
        controller.stop()                    // no further sample is accepted from here on
        releaseCamera()                      // camera closed: preview and analysis end
        if (::analysisExecutor.isInitialized) analysisExecutor.shutdown()
        overlay.locked = false
        window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        render()
    }

    /** Camera analysis thread. Always closes the frame; a bitmap is made only for a keyframe. */
    private fun analyze(image: ImageProxy) {
        image.use {
            val now = System.currentTimeMillis()
            if (!controller.shouldSample(now)) return
            val area = roi
            val rotation = it.imageInfo.rotationDegrees
            val y = it.planes[0]
            val grid = FrameSampler.downsample(y.buffer, y.rowStride, y.pixelStride, it.width, it.height,
                                               config.gridWidth, config.gridHeight, area.toSensor(rotation))
            // whole-frame context for shake / global-change rejection; not needed when the area is the full frame
            val frame = if (area.isFull) null else FrameSampler.downsample(y.buffer, y.rowStride, y.pixelStride,
                                                                          it.width, it.height, config.gridWidth, config.gridHeight)
            controller.onSample(grid, now, frame) {
                val bitmap = it.toBitmap()
                try { FrameEncoder.encode(bitmap, rotation, area) } finally { bitmap.recycle() }
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
        val area = roi
        findViewById<Button>(R.id.toggle).text = if (s.running) "Stop monitoring" else "Start monitoring"
        findViewById<Button>(R.id.preview_button).isEnabled = !s.running && !previewing
        findViewById<Button>(R.id.full_frame).isEnabled = !s.running && !area.isFull
        status(buildString {
            appendLine("Monitoring: " + when {
                !s.running -> "OFF"
                area.isFull -> "ON (full frame)"
                else -> "ON - monitoring selected area"
            })
            appendLine("Area: " + if (area.isFull) "not selected (full frame)" else
                "selected, %d%% x %d%% of the frame".format((area.width * 100).toInt(), (area.height * 100).toInt()))
            appendLine("Camera: " + when {
                s.running -> "preview + analysis"
                previewing -> "preview only (nothing analysed)"
                else -> "released"
            })
            appendLine("State: ${label(s.state)}")
            appendLine("Analysis rate: %.1f frames/s (target %.1f)".format(s.analysisFps, 1000f / config.analysisIntervalMs))
            appendLine("Frames analysed: ${s.framesAnalyzed}  skipped by rate limit: ${s.framesSkipped}")
            appendLine("Rejected by MotionGate: " + s.rejected.entries.joinToString { "${it.key.name.lowercase()} ${it.value}" })
            appendLine("Motion samples in area: ${s.localMotion}")
            appendLine("Possible visual events: ${s.possibleEvents}")
            appendLine("Visual evidence candidates: ${s.confirmedEvents}")
            appendLine("Last candidate/event: ${s.lastEventAtMs?.let { EvidenceMetadata.iso(it) } ?: "-"}")
            appendLine("GPS: ${s.gpsStatus}")
            appendLine("Upload: ${s.uploadStatus}  (auto-upload ${if (controller.autoUpload) "ON" else "OFF"})")
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

    companion object {
        private const val PREF_ROI = "roi"
    }
}
