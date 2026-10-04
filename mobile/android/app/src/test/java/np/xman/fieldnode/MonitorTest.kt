package np.xman.fieldnode

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import kotlin.random.Random

private val CFG = MonitorConfig()

/** Deterministic textured scene (like terrain), 64x48, values ~30..220. */
private fun scene(seed: Int = 7): FloatArray {
    val r = Random(seed)
    return FloatArray(CFG.gridWidth * CFG.gridHeight) { 30f + r.nextFloat() * 190f }
}

private fun grid(v: FloatArray) = LumaGrid(CFG.gridWidth, CFG.gridHeight, v)

/** Replace a w x h patch at (x0, y0) with different texture: a local visual change. */
private fun withPatch(base: FloatArray, x0: Int, y0: Int, w: Int, h: Int, seed: Int = 99): FloatArray {
    val r = Random(seed)
    return base.copyOf().also { v -> for (y in y0 until y0 + h) for (x in x0 until x0 + w) v[y * CFG.gridWidth + x] = 30f + r.nextFloat() * 190f }
}

/** Whole frame translated by (dx, dy), edges clamped: camera shake. */
private fun shifted(base: FloatArray, dx: Int, dy: Int) = FloatArray(base.size) {
    val x = (it % CFG.gridWidth - dx).coerceIn(0, CFG.gridWidth - 1)
    val y = (it / CFG.gridWidth - dy).coerceIn(0, CFG.gridHeight - 1)
    base[y * CFG.gridWidth + x]
}

class MotionGateTest {
    private val gate = MotionGate(CFG)
    private val base = scene()

    @Test fun identicalFramesAreStatic() {
        assertEquals(MotionKind.STATIC, gate.compare(grid(base), grid(base.copyOf())).kind)
    }

    @Test fun tinySensorAndCompressionNoiseIsRejected() {
        val r = Random(3)
        val noisy = FloatArray(base.size) { base[it] + (r.nextFloat() - 0.5f) * 8f }  // +-4 grey levels everywhere
        val kind = gate.compare(grid(base), grid(noisy)).kind
        assertTrue(kind.name, kind == MotionKind.STATIC || kind == MotionKind.NOISE)
    }

    @Test fun localChangeIsAMotionCandidate() {
        val r = gate.compare(grid(base), grid(withPatch(base, 20, 16, 12, 12)))
        assertEquals(MotionKind.LOCAL_MOTION, r.kind)
        assertTrue(r.largestRegion >= CFG.minRegionCells)
        assertTrue(r.changedFraction < CFG.maxLocalFraction)
    }

    @Test fun globalBrightnessAndExposureChangesAreRejected() {
        val brighter = FloatArray(base.size) { base[it] + 40f }
        val gain = FloatArray(base.size) { base[it] * 1.3f }
        assertEquals(MotionKind.STATIC, gate.compare(grid(base), grid(brighter)).kind)
        assertEquals(MotionKind.STATIC, gate.compare(grid(base), grid(gain)).kind)
    }

    @Test fun lightingChangePlusLocalChangeStillFindsTheLocalChange() {
        val v = withPatch(base, 8, 8, 12, 12).map { it * 0.7f + 15f }.toFloatArray()
        assertEquals(MotionKind.LOCAL_MOTION, gate.compare(grid(base), grid(v)).kind)
    }

    @Test fun cameraShakeIsRejected() {
        for ((dx, dy) in listOf(1 to 0, 0 to 2, 2 to -1, -2 to 2)) {
            assertEquals("shift $dx,$dy", MotionKind.SHAKE, gate.compare(grid(base), grid(shifted(base, dx, dy))).kind)
        }
    }

    @Test fun completelyDifferentFrameIsGlobalNotLocal() {
        assertEquals(MotionKind.GLOBAL_CHANGE, gate.compare(grid(base), grid(scene(seed = 1234))).kind)
    }

    @Test fun scatteredSmallChangesAreNoise() {
        var v = base
        for ((x, y) in listOf(0 to 0, 24 to 20, 48 to 40, 56 to 4)) v = withPatch(v, x, y, 4, 4, seed = x + y)
        val r = gate.compare(grid(base), grid(v))
        assertEquals(MotionKind.NOISE, r.kind)
        assertTrue(r.changedCells >= CFG.minChangedCells && r.largestRegion < CFG.minRegionCells)
    }

    @Test fun thresholdBoundaries() {
        // two adjacent cells (< minChangedCells = 3): not motion; three in a row: motion
        assertEquals(MotionKind.NOISE, gate.compare(grid(base), grid(withPatch(base, 20, 16, 8, 4))).kind)
        assertEquals(MotionKind.LOCAL_MOTION, gate.compare(grid(base), grid(withPatch(base, 20, 16, 12, 4))).kind)
        // a stricter cell threshold turns the same change into "static"
        val strict = MotionGate(CFG.copy(cellThreshold = 10f))
        assertEquals(MotionKind.STATIC, strict.compare(grid(base), grid(withPatch(base, 20, 16, 12, 12))).kind)
        // a larger region requirement rejects a 3-cell change
        val bigRegion = MotionGate(CFG.copy(minRegionCells = 5, minChangedCells = 3))
        assertEquals(MotionKind.NOISE, bigRegion.compare(grid(base), grid(withPatch(base, 20, 16, 12, 4))).kind)
    }

    @Test fun flatSceneDoesNotAmplifyNoise() {
        val flat = FloatArray(base.size) { 120f }
        val r = Random(5)
        val flatNoisy = FloatArray(base.size) { 120f + (r.nextFloat() - 0.5f) * 6f }
        val kind = gate.compare(grid(flat), grid(flatNoisy)).kind
        assertTrue(kind.name, kind == MotionKind.STATIC || kind == MotionKind.NOISE)
    }
}

class FrameSamplerTest {
    @Test fun blockAveragesTheYPlaneWithStride() {
        val w = 128; val h = 96; val rowStride = 160  // padded rows, as on real devices
        val buf = ByteBuffer.allocate(rowStride * h)
        for (y in 0 until h) for (x in 0 until w) buf.put(y * rowStride + x, (if (x < w / 2) 50 else 200).toByte())
        val g = FrameSampler.downsample(buf, rowStride, 1, w, h, 64, 48)
        assertEquals(64 * 48, g.values.size)
        assertEquals(50f, g[0, 0], 0.001f)
        assertEquals(200f, g[63, 47], 0.001f)
        assertEquals(50f, g[31, 20], 0.001f)
        assertEquals(200f, g[32, 20], 0.001f)
    }

    @Test fun readsUnsignedBytes() {
        val buf = ByteBuffer.allocate(64 * 48).apply { for (i in 0 until capacity()) put(i, 250.toByte()) }
        assertEquals(250f, FrameSampler.downsample(buf, 64, 1, 64, 48, 64, 48)[10, 10], 0.001f)
    }
}

class MonitorStateMachineTest {
    private val m = MonitorStateMachine(CFG).also { it.start(0) }
    private var t = 0L
    private fun sample(kind: MotionKind) = m.onSample(kind, t.also { t += CFG.analysisIntervalMs })

    private fun reachConfirming() {
        repeat(CFG.possibleHitsToConfirm) { sample(MotionKind.LOCAL_MOTION) }
        assertEquals(MonitorState.CONFIRMING, m.state)
    }

    private fun reachConfirmed() {
        reachConfirming()
        while (m.state == MonitorState.CONFIRMING) sample(MotionKind.LOCAL_MOTION)
        assertEquals(MonitorState.CONFIRMED_EVIDENCE, m.state)
    }

    @Test fun staticSceneStaysMonitoring() {
        repeat(500) { sample(MotionKind.STATIC); sample(MotionKind.NOISE); sample(MotionKind.SHAKE); sample(MotionKind.GLOBAL_CHANGE) }
        assertEquals(MonitorState.MONITORING, m.state)
        assertEquals(0, m.possibleEvents)
    }

    @Test fun motionOpensPossibleEvent() {
        assertEquals(Transition(MonitorState.MONITORING, MonitorState.POSSIBLE_EVENT), sample(MotionKind.LOCAL_MOTION))
        assertEquals(1, m.possibleEvents)
    }

    @Test fun singleTransientMotionReturnsToMonitoringWithoutEvidence() {
        sample(MotionKind.LOCAL_MOTION)
        repeat(CFG.possibleMaxMisses) { sample(MotionKind.STATIC) }
        assertEquals(MonitorState.MONITORING, m.state)
        assertEquals(0, m.confirmedEvents)
    }

    @Test fun persistenceLeadsToConfirmingThenEvidence() {
        reachConfirmed()
        assertEquals(1, m.confirmedEvents)
        // the window took at least confirmWindowMs: no instant confirmation
        assertTrue(t >= CFG.confirmWindowMs)
    }

    @Test fun intermittentMotionInWindowIsNotConfirmed() {
        reachConfirming()
        while (m.state == MonitorState.CONFIRMING) { sample(MotionKind.LOCAL_MOTION); sample(MotionKind.STATIC); sample(MotionKind.STATIC) }
        assertEquals(MonitorState.MONITORING, m.state)
        assertEquals(0, m.confirmedEvents)
    }

    @Test fun motionStoppingDuringConfirmationResets() {
        reachConfirming()
        repeat(CFG.confirmMaxConsecutiveMisses) { sample(MotionKind.STATIC) }
        assertEquals(MonitorState.MONITORING, m.state)
    }

    @Test fun fullFlowWithUploadAndCooldown() {
        reachConfirmed()
        assertEquals(MonitorState.UPLOAD_PENDING, m.onEvidenceStored(t)!!.to)
        assertEquals(MonitorState.UPLOADED, m.onUploadFinished(true, t)!!.to)
        assertEquals(MonitorState.COOLDOWN, m.timeouts(t)!!.to)
        // cooldown: persistent motion does not re-trigger
        val until = t + CFG.cooldownMs - CFG.analysisIntervalMs
        while (t < until) { sample(MotionKind.LOCAL_MOTION); assertEquals(MonitorState.COOLDOWN, m.state) }
        assertEquals(1, m.confirmedEvents)
        t += CFG.analysisIntervalMs
        sample(MotionKind.STATIC)
        assertEquals(MonitorState.MONITORING, m.state)
    }

    @Test fun failedOrManualUploadGoesToCooldown() {
        reachConfirmed()
        m.onEvidenceStored(t)
        assertEquals(MonitorState.COOLDOWN, m.onUploadFinished(false, t)!!.to)
    }

    @Test fun stuckStatesTimeOut() {
        reachConfirmed()
        assertEquals(MonitorState.COOLDOWN, m.timeouts(t + CFG.evidenceTimeoutMs)!!.to)
        val m2 = MonitorStateMachine(CFG).apply { start(0) }
        var t2 = 0L
        repeat(CFG.possibleHitsToConfirm) { m2.onSample(MotionKind.LOCAL_MOTION, t2); t2 += 500 }
        while (m2.state == MonitorState.CONFIRMING) { m2.onSample(MotionKind.LOCAL_MOTION, t2); t2 += 500 }
        m2.onEvidenceStored(t2)
        assertEquals(MonitorState.COOLDOWN, m2.timeouts(t2 + CFG.uploadTimeoutMs)!!.to)
    }

    @Test fun cameraErrorDegradesAndRecoveryResumes() {
        reachConfirming()
        assertEquals(MonitorState.DEGRADED, m.onCameraError(t)!!.to)
        repeat(20) { sample(MotionKind.LOCAL_MOTION) }
        assertEquals(MonitorState.DEGRADED, m.state)  // nothing analysed while degraded
        assertEquals(MonitorState.MONITORING, m.onCameraRecovered(t)!!.to)
        assertNull(m.onCameraRecovered(t))
    }

    @Test fun stopResetsFromAnyState() {
        reachConfirming()
        assertEquals(MonitorState.STOPPED, m.stop(t)!!.to)
        repeat(10) { sample(MotionKind.LOCAL_MOTION) }
        assertEquals(MonitorState.STOPPED, m.state)
        assertNull(m.onCameraError(t))
        m.start(t)
        assertEquals(MonitorState.MONITORING, m.state)
        sample(MotionKind.LOCAL_MOTION)
        assertEquals(MonitorState.POSSIBLE_EVENT, m.state)  // counters were reset: needs persistence again
    }

    @Test fun cannotReachEvidenceFasterThanConfigured() {
        // even unbroken motion needs possibleHitsToConfirm samples + a full confirmation window
        var steps = 0
        while (m.state != MonitorState.CONFIRMED_EVIDENCE) { sample(MotionKind.LOCAL_MOTION); steps++; assertTrue(steps < 100) }
        val minSteps = CFG.possibleHitsToConfirm + (CFG.confirmWindowMs / CFG.analysisIntervalMs).toInt()
        assertTrue("$steps >= $minSteps", steps >= minSteps)
    }
}

/** Records effects; GPS and upload answer immediately with scripted results. */
private class FakeEffects(private val store: EvidenceStore) : MonitorEffects {
    var gpsRequests = 0
    var gpsAnswer: Pair<GpsFix?, String>? = Pair(GpsFix(27.7, 85.3, 9.0, 1_000L), "fix")
    var uploads = mutableListOf<EvidencePackage>()
    var uploadOk = true
    var heldGps: ((GpsFix?, String) -> Unit)? = null

    override fun requestGps(onResult: (GpsFix?, String) -> Unit) {
        gpsRequests++
        gpsAnswer?.let { onResult(it.first, it.second) } ?: run { heldGps = onResult }
    }
    override fun cancelGps() {}
    override fun store(keyframes: KeyframeCollector, gps: GpsFix?, gpsNote: String) =
        EvidenceAssembler(store).assemble(keyframes, gps, gpsNote, "0.2.0-mlive04", 80, "wifi")
    override fun upload(pkg: EvidencePackage, onDone: (Boolean) -> Unit) { uploads += pkg; onDone(uploadOk) }
}

class MonitorControllerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val base = scene()
    private val moved = withPatch(base, 20, 16, 12, 12)
    private var now = 1_791_100_000_000L
    private var encodes = 0

    private fun setup(auto: Boolean = true): Triple<MonitorController, FakeEffects, EvidenceStore> {
        val store = EvidenceStore(tmp.newFolder())
        val fx = FakeEffects(store)
        val c = MonitorController(CFG, fx) { now }.apply { autoUpload = auto; start() }
        return Triple(c, fx, store)
    }

    /** Alternating frames = continuous local motion between consecutive samples. */
    private fun feed(c: MonitorController, samples: Int, motion: Boolean = true) {
        repeat(samples) {
            now += CFG.analysisIntervalMs
            val frame = if (motion && it % 2 == 0) moved else base
            if (c.shouldSample(now)) c.onSample(grid(frame), now) { encodes++; byteArrayOf(encodes.toByte()) }
        }
    }

    @Test fun staticSceneCreatesNothing() {
        val (c, fx, store) = setup()
        feed(c, 400, motion = false)
        assertEquals(MonitorState.MONITORING, c.state)
        assertEquals(0, encodes)
        assertEquals(0, fx.gpsRequests)
        assertTrue(store.all().isEmpty())
    }

    @Test fun persistentMotionProducesOneBoundedPackageAndUploadsIt() {
        val (c, fx, store) = setup()
        feed(c, 1)  // first frame: reference only
        feed(c, 40)
        val packages = store.all()
        assertEquals(1, packages.size)
        val pkg = packages[0]
        assertEquals(3, pkg.frameCount)  // detection, confirmed, after: never more
        assertEquals(3, encodes)         // a frame is only encoded for a keyframe slot
        assertEquals(EvidencePackage.TRIGGER_MOTION_GATE, pkg.trigger)
        assertEquals("fix", pkg.gpsNote)
        assertEquals(1, fx.gpsRequests)  // GPS only at confirmation, not per frame
        assertEquals(listOf(pkg.clientEventId), fx.uploads.map { it.clientEventId })
        assertTrue(c.state == MonitorState.COOLDOWN)
        val meta = JSONObject(store.metadata(pkg))
        assertEquals(pkg.clientEventId, meta.getString("client_event_id"))
        assertEquals("motion-gate", meta.getString("model"))
        assertFalse(meta.has("device_score"))
        assertTrue(meta.has("latitude"))
    }

    @Test fun cooldownPreventsASecondPackage() {
        val (c, _, store) = setup()
        feed(c, 1); feed(c, 40)
        feed(c, (CFG.cooldownMs / CFG.analysisIntervalMs).toInt() - 30)  // motion continues during cooldown
        assertEquals(1, store.all().size)
    }

    @Test fun transientMotionKeepsNothing() {
        val (c, fx, store) = setup()
        feed(c, 1)
        now += CFG.analysisIntervalMs
        c.shouldSample(now); c.onSample(grid(moved), now) { encodes++; byteArrayOf(1) }  // one changed sample
        feed(c, 20, motion = false)
        assertEquals(MonitorState.MONITORING, c.state)
        assertEquals(0, fx.gpsRequests)
        assertTrue(store.all().isEmpty())
        assertEquals(1, c.snapshot().possibleEvents)
        assertEquals(0, c.snapshot().confirmedEvents)
    }

    @Test fun noGpsMeansNoCoordinatesAndAnExplicitNote() {
        val (c, fx, store) = setup()
        fx.gpsAnswer = Pair(null, "unavailable: no location permission")
        feed(c, 1); feed(c, 40)
        val pkg = store.all().single()
        assertEquals("unavailable: no location permission", pkg.gpsNote)
        val meta = JSONObject(store.metadata(pkg))
        assertFalse(meta.has("latitude") || meta.has("longitude") || meta.has("gps_fix_at"))
    }

    @Test fun slowGpsTimesOutWithoutInventingCoordinates() {
        val (c, fx, store) = setup()
        fx.gpsAnswer = null  // never answers
        feed(c, 1); feed(c, 20)
        assertEquals(MonitorState.CONFIRMED_EVIDENCE, c.state)
        feed(c, (CFG.gpsTimeoutMs / CFG.analysisIntervalMs).toInt() + 2)
        val pkg = store.all().single()
        assertEquals("unavailable: no fix in time", pkg.gpsNote)
        assertFalse(JSONObject(store.metadata(pkg)).has("latitude"))
        fx.heldGps!!.invoke(GpsFix(1.0, 2.0, 3.0, 4L), "fix")  // a late answer changes nothing
        assertEquals(1, store.all().size)
    }

    @Test fun offlineCandidateIsKeptWithTheSameIdForRetry() {
        val (c, fx, store) = setup()
        fx.uploadOk = false
        feed(c, 1); feed(c, 40)
        val pkg = store.all().single()
        assertEquals(MonitorState.COOLDOWN, c.state)
        assertTrue(c.snapshot().uploadStatus.startsWith("upload failed"))
        assertEquals(3, store.frames(store.load(pkg.clientEventId)!!).size)  // frames still on the phone
        assertEquals(pkg.clientEventId, fx.uploads.single().clientEventId)
    }

    @Test fun manualModeLeavesThePackageReady() {
        val (c, fx, store) = setup(auto = false)
        feed(c, 1); feed(c, 40)
        assertTrue(fx.uploads.isEmpty())
        assertEquals(EvidenceState.READY, store.all().single().state)
        assertTrue(c.snapshot().uploadStatus.startsWith("pending manual upload"))
    }

    @Test fun stopDuringCollectionStillSavesTheCandidate() {
        val (c, fx, store) = setup()
        fx.gpsAnswer = null
        feed(c, 1); feed(c, 20)
        assertEquals(MonitorState.CONFIRMED_EVIDENCE, c.state)
        c.stop()
        assertEquals(MonitorState.STOPPED, c.state)
        val pkg = store.all().single()
        assertEquals("unavailable: monitoring stopped before a fix", pkg.gpsNote)
        assertTrue(pkg.frameCount in 1..3)
        feed(c, 40)  // after stop: nothing is analysed
        assertEquals(1, store.all().size)
        assertFalse(c.shouldSample(now + 10_000))
    }

    @Test fun rateLimitSkipsFramesBetweenSamples() {
        val (c, _, _) = setup()
        var accepted = 0
        repeat(30) { now += 33; if (c.shouldSample(now)) accepted++ }  // ~30 fps camera for ~1 s
        assertTrue("accepted $accepted", accepted in 1..3)
        assertEquals(30L - accepted, c.snapshot().framesSkipped)
    }

    @Test fun cameraErrorDegradesThenRecovers() {
        val (c, _, store) = setup()
        feed(c, 1); feed(c, 4)
        c.onCameraError()
        assertEquals(MonitorState.DEGRADED, c.state)
        assertFalse(c.shouldSample(now + 1_000))
        c.onCameraRecovered()
        assertEquals(MonitorState.MONITORING, c.state)
        assertTrue(store.all().isEmpty())
    }

    @Test fun diagnosticsArePerSessionSoFpsNeverSpansAStop() {
        val (c, _, _) = setup()
        feed(c, 1); feed(c, 40)
        c.stop()
        assertEquals(0f, c.snapshot().analysisFps)  // nothing is analysed while stopped
        now += 600_000  // ten minutes stopped
        c.start()
        feed(c, 12, motion = false)
        val s = c.snapshot()
        assertEquals(12L, s.framesAnalyzed)
        assertTrue("fps ${s.analysisFps}", s.analysisFps in 1.9f..2.1f)
        assertEquals(0, s.confirmedEvents)
    }

    @Test fun diagnosticsCountWhatHappened() {
        val (c, _, _) = setup()
        feed(c, 1); feed(c, 10, motion = false); feed(c, 40)
        val s = c.snapshot()
        assertEquals(51L, s.framesAnalyzed)
        assertTrue(s.localMotion > 0)
        assertEquals(1, s.confirmedEvents)
        assertTrue(s.analysisFps in 1.9f..2.1f)
        assertNotEquals(null, s.lastEventAtMs)
    }
}

class EvidenceAssemblerTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun boundedFramesAndStableId() {
        val store = EvidenceStore(tmp.newFolder())
        val k = KeyframeCollector()
        k.put(KeyframeCollector.Slot.DETECTION, 1_000) { byteArrayOf(1) }
        k.put(KeyframeCollector.Slot.DETECTION, 2_000) { error("a filled slot is never re-encoded") }
        k.put(KeyframeCollector.Slot.CONFIRMED, 3_000) { byteArrayOf(2) }
        k.put(KeyframeCollector.Slot.AFTER, 4_000) { byteArrayOf(3) }
        assertEquals(3, k.count)
        val pkg = EvidenceAssembler(store).assemble(k, null, "unavailable: test", "v", null, null)
        assertEquals(3, pkg.frameCount)
        assertEquals(1_000L, pkg.capturedAtMs)  // detection time = captured_at
        assertEquals(EvidenceState.READY, pkg.state)
        val reloaded = store.load(pkg.clientEventId)!!
        assertEquals(pkg.clientEventId, reloaded.clientEventId)
        assertEquals(EvidencePackage.TRIGGER_MOTION_GATE, reloaded.trigger)
        assertEquals(listOf(1, 2, 3), store.frames(reloaded).map { it[0].toInt() })
    }

    @Test fun clearDropsAllFrames() {
        val k = KeyframeCollector()
        k.put(KeyframeCollector.Slot.DETECTION, 1) { byteArrayOf(1) }
        k.clear()
        assertEquals(0, k.count)
        assertNull(k.detectionAtMs)
    }

    @Test fun manualPackagesStillSendNoModel() {
        val pkg = EvidencePackage(capturedAtMs = 1_000L)
        val meta = EvidenceMetadata.build(pkg, null, null, null, null)
        assertFalse(meta.has("model") || meta.has("model_version"))
    }

    @Test fun olderPackagesLoadAsManual() {
        val old = JSONObject(EvidencePackage(capturedAtMs = 5L).toJson().toString()).apply { remove("trigger"); remove("gps_note") }
        val pkg = EvidencePackage.fromJson(old)
        assertEquals(EvidencePackage.TRIGGER_MANUAL, pkg.trigger)
        assertNull(pkg.gpsNote)
    }
}
