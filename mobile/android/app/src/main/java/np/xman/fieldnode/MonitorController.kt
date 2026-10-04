package np.xman.fieldnode

/** What the controller needs from the platform; the app implements it with GPS, EvidenceStore and the uploader. */
interface MonitorEffects {
    /** One GPS fix at confirmation time. Calls back with a fix, or null and a reason. */
    fun requestGps(onResult: (GpsFix?, String) -> Unit)
    fun cancelGps()
    /** Persist the keyframes as a READY package (M-LIVE-03 store); null if storing failed. */
    fun store(keyframes: KeyframeCollector, gps: GpsFix?, gpsNote: String): EvidencePackage?
    /** Upload through the M-LIVE-03 uploader; calls back true only when X-MAN accepted it. */
    fun upload(pkg: EvidencePackage, onDone: (Boolean) -> Unit)
}

/** Diagnostic counters + current status for the UI. Never contains images or credentials. */
data class MonitorSnapshot(
    val running: Boolean, val state: MonitorState, val analysisFps: Float, val framesAnalyzed: Long,
    val framesSkipped: Long, val rejected: Map<MotionKind, Long>, val localMotion: Long,
    val possibleEvents: Int, val confirmedEvents: Int, val lastEventAtMs: Long?, val gpsStatus: String,
    val uploadStatus: String, val lastPackageId: String?,
)

/**
 * FrameSampler output -> MotionGate -> MonitorStateMachine -> keyframes, GPS, EvidenceStore, upload.
 * Called from the camera analysis thread (samples), the main thread (GPS) and the I/O thread (upload),
 * so every entry point is synchronized. Holds at most: one previous grid, three keyframes.
 */
class MonitorController(
    private val config: MonitorConfig,
    private val effects: MonitorEffects,
    private val clock: () -> Long = System::currentTimeMillis,
) {
    private val gate = MotionGate(config)
    private val machine = MonitorStateMachine(config)
    private val keyframes = KeyframeCollector()
    private var previous: LumaGrid? = null
    private var previousFrame: LumaGrid? = null  // whole-frame context grid (null when the ROI is the full frame)
    private var lastSampleAt = 0L

    /** Upload candidates automatically; off = the package waits on the phone for a manual upload. */
    @Volatile var autoUpload = false

    private var framesAnalyzed = 0L
    private var framesSkipped = 0L
    private val counts = MotionKind.values().associateWith { 0L }.toMutableMap()
    private val recent = LongArray(10)  // analysis timestamps for the FPS estimate (bounded)
    private var recentCount = 0
    private var lastEventAt: Long? = null
    private var confirmedAt = 0L
    private var gpsPending = false
    private var gpsDone = false
    private var gpsFix: GpsFix? = null
    private var gpsNote = "not requested yet"
    private var uploadStatus = "none"
    private var lastPackageId: String? = null

    val state: MonitorState @Synchronized get() = machine.state
    val running: Boolean @Synchronized get() = machine.state != MonitorState.STOPPED

    /** Diagnostics are per monitoring session: the FPS estimate never spans a stop/start gap. */
    @Synchronized fun start() {
        previous = null
        previousFrame = null
        keyframes.clear()
        framesAnalyzed = 0; framesSkipped = 0; recentCount = 0; lastSampleAt = 0
        for (k in counts.keys) counts[k] = 0L
        // status lines are per session too (a previous session's package may already be uploaded or deleted)
        lastEventAt = null; gpsPending = false; gpsDone = false; gpsFix = null; gpsNote = "not requested yet"
        uploadStatus = "none"; lastPackageId = null
        machine.start(clock())
    }

    /** Stops analysis at once. A candidate already confirmed is still saved (no GPS wait), never dropped. */
    @Synchronized fun stop() {
        val now = clock()
        if (machine.state == MonitorState.CONFIRMED_EVIDENCE && keyframes.count > 0) {
            if (!gpsDone) { gpsFix = null; gpsNote = "unavailable: monitoring stopped before a fix" }
            effects.cancelGps()
            persist(now, uploadAfter = false)
        }
        effects.cancelGps()
        gpsPending = false
        keyframes.clear()
        previous = null
        previousFrame = null
        machine.stop(now)
    }

    /** Rate limit: true if this camera frame should be analysed; otherwise it is counted and skipped. */
    @Synchronized fun shouldSample(now: Long): Boolean {
        if (machine.state == MonitorState.STOPPED || machine.state == MonitorState.DEGRADED) return false
        if (now - lastSampleAt < config.analysisIntervalMs) { framesSkipped++; return false }
        lastSampleAt = now
        return true
    }

    /**
     * One sampled frame: [grid] is the monitored region (ROI) and [frameGrid] the whole frame as context
     * (null when the ROI is the full frame). [encodeKeyframe] is only invoked when a keyframe slot needs it.
     */
    @Synchronized fun onSample(grid: LumaGrid, now: Long, frameGrid: LumaGrid? = null, encodeKeyframe: () -> ByteArray) {
        if (machine.state == MonitorState.STOPPED || machine.state == MonitorState.DEGRADED) return
        framesAnalyzed++
        recent[(recentCount++ % recent.size)] = now
        val prev = previous
        val prevFrame = previousFrame
        previous = grid
        previousFrame = frameGrid
        if (prev == null) { machine.timeouts(now); return }

        val result = gate.classify(prev, grid, prevFrame, frameGrid)
        counts[result.kind] = counts.getValue(result.kind) + 1
        val t = machine.onSample(result.kind, now)

        when {
            t?.to == MonitorState.POSSIBLE_EVENT -> {
                keyframes.clear()
                keyframes.put(KeyframeCollector.Slot.DETECTION, now, encodeKeyframe)
                lastEventAt = now
            }
            t?.to == MonitorState.MONITORING -> keyframes.clear()  // transient or not confirmed: nothing kept
            t?.to == MonitorState.CONFIRMED_EVIDENCE -> {
                keyframes.put(KeyframeCollector.Slot.CONFIRMED, now, encodeKeyframe)
                confirmedAt = now
                lastEventAt = now
                requestGps()
            }
            t == null && machine.state == MonitorState.CONFIRMED_EVIDENCE ->
                keyframes.put(KeyframeCollector.Slot.AFTER, now, encodeKeyframe)
        }
        if (machine.state == MonitorState.CONFIRMED_EVIDENCE && !gpsDone && now - confirmedAt >= config.gpsTimeoutMs) {
            gpsDone = true; gpsPending = false; gpsFix = null; gpsNote = "unavailable: no fix in time"
            effects.cancelGps()
        }
        maybeFinalize(now)
    }

    @Synchronized fun onCameraError() {
        val now = clock()
        if (machine.state == MonitorState.CONFIRMED_EVIDENCE && keyframes.count > 0) {
            if (!gpsDone) { gpsFix = null; gpsNote = "unavailable: camera error before a fix" }
            effects.cancelGps()
            persist(now, uploadAfter = false)
        }
        keyframes.clear()
        previous = null
        previousFrame = null
        machine.onCameraError(now)
    }

    @Synchronized fun onCameraRecovered() {
        previous = null
        previousFrame = null
        machine.onCameraRecovered(clock())
    }

    private fun requestGps() {
        gpsPending = true; gpsDone = false; gpsFix = null; gpsNote = "requested at confirmation"
        effects.requestGps { fix, note -> onGps(fix, note) }
    }

    @Synchronized private fun onGps(fix: GpsFix?, note: String) {
        if (!gpsPending || machine.state != MonitorState.CONFIRMED_EVIDENCE) return
        gpsPending = false; gpsDone = true; gpsFix = fix; gpsNote = note
        maybeFinalize(clock())
    }

    private fun maybeFinalize(now: Long) {
        if (machine.state != MonitorState.CONFIRMED_EVIDENCE || !gpsDone) return
        val afterReady = keyframes.has(KeyframeCollector.Slot.AFTER) || now - confirmedAt >= config.afterFrameTimeoutMs
        if (afterReady) persist(now, uploadAfter = true)
    }

    private fun persist(now: Long, uploadAfter: Boolean) {
        val pkg = effects.store(keyframes, gpsFix, gpsNote)
        keyframes.clear()
        if (pkg == null) { uploadStatus = "storing the package failed"; return }  // evidence timeout ends the wait
        lastPackageId = pkg.clientEventId
        machine.onEvidenceStored(now)
        if (uploadAfter && autoUpload) {
            uploadStatus = "uploading ${pkg.clientEventId.take(8)}..."
            effects.upload(pkg) { ok -> onUploaded(pkg.clientEventId, ok) }
        } else {
            uploadStatus = "pending manual upload (${pkg.clientEventId.take(8)}...)"
            machine.onUploadFinished(uploaded = false, now = now)
        }
    }

    @Synchronized private fun onUploaded(id: String, ok: Boolean) {
        uploadStatus = if (ok) "uploaded (${id.take(8)}...)" else "upload failed: kept on phone for retry (${id.take(8)}...)"
        machine.onUploadFinished(ok, clock())
    }

    @Synchronized fun snapshot(): MonitorSnapshot {
        val n = minOf(recentCount, recent.size)
        val fps = if (n < 2 || machine.state == MonitorState.STOPPED) 0f else {
            val newest = recent[(recentCount - 1) % recent.size]
            val oldest = recent[(recentCount - n) % recent.size]
            if (newest > oldest) (n - 1) * 1000f / (newest - oldest) else 0f
        }
        val gps = when {
            gpsPending -> "waiting for fix"
            gpsFix != null -> "fix (±${gpsFix!!.accuracyM?.let { "%.0f m".format(it) } ?: "?"})"
            else -> gpsNote
        }
        return MonitorSnapshot(machine.state != MonitorState.STOPPED, machine.state, fps, framesAnalyzed, framesSkipped,
            counts.filterKeys { it != MotionKind.LOCAL_MOTION }, counts.getValue(MotionKind.LOCAL_MOTION),
            machine.possibleEvents, machine.confirmedEvents, lastEventAt, gps, uploadStatus, lastPackageId)
    }
}
