package np.xman.fieldnode

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import kotlin.math.abs
import kotlin.random.Random

private val C = MonitorConfig()

/**
 * Synthetic camera Y plane (sensor orientation = upright, rotation 0): a smooth-but-textured scene defined
 * on normalized coordinates, so the same scene can be rendered at any resolution. [patches] replace
 * rectangles (normalized) with different texture = a local visual change there.
 */
/** A test patch (any size, unlike a monitoring ROI). */
private data class P(val left: Float, val top: Float, val right: Float, val bottom: Float)

private class Scene(val seed: Int = 11) {
    private val r = Random(seed)
    private val coarse = Array(96) { FloatArray(128) { 30f + r.nextFloat() * 190f } }  // texture defined on a 128x96 lattice

    fun value(nx: Float, ny: Float, patches: List<Pair<P, Int>> = emptyList(), shift: Float = 0f, gain: Float = 1f,
              offset: Float = 0f): Int {
        for ((rect, s) in patches) if (nx >= rect.left && nx < rect.right && ny >= rect.top && ny < rect.bottom) {
            val pr = Random(s * 100_003 + (nx * 128).toInt() * 97 + (ny * 96).toInt())
            return (30f + pr.nextFloat() * 190f).toInt()
        }
        val x = ((nx + shift) * 128).toInt().coerceIn(0, 127)
        val y = (ny * 96).toInt().coerceIn(0, 95)
        return (coarse[y][x] * gain + offset).toInt().coerceIn(0, 255)
    }

    fun render(w: Int, h: Int, patches: List<Pair<P, Int>> = emptyList(), shift: Float = 0f, gain: Float = 1f,
               offset: Float = 0f): ByteBuffer {
        val b = ByteBuffer.allocate(w * h)
        for (y in 0 until h) for (x in 0 until w)
            b.put(y * w + x, value((x + 0.5f) / w, (y + 0.5f) / h, patches, shift, gain, offset).toByte())
        return b
    }
}

private fun roi(l: Float, t: Float, r: Float, b: Float) = NormRect.of(l, t, r, b)!!
private const val W = 320
private const val H = 240
private fun grids(buf: ByteBuffer, area: NormRect, w: Int = W, h: Int = H): Pair<LumaGrid, LumaGrid?> =
    FrameSampler.downsample(buf, w, 1, w, h, C.gridWidth, C.gridHeight, area) to
        (if (area.isFull) null else FrameSampler.downsample(buf, w, 1, w, h, C.gridWidth, C.gridHeight))

class NormRectTest {
    @Test fun validRoiAcceptedInAnyCornerOrder() {
        val a = NormRect.of(0.2f, 0.3f, 0.6f, 0.8f)!!
        assertEquals(a, NormRect.of(0.6f, 0.8f, 0.2f, 0.3f))
        assertEquals(0.4f, a.width, 1e-6f)
        assertEquals(0.5f, a.height, 1e-6f)
        assertFalse(a.isFull)
    }

    @Test fun clampedToTheFrame() {
        val a = NormRect.of(-0.5f, -1f, 0.5f, 2f)!!
        assertEquals(0f, a.left); assertEquals(0f, a.top); assertEquals(0.5f, a.right); assertEquals(1f, a.bottom)
    }

    @Test fun zeroAreaAndTinyRegionsRejected() {
        assertNull(NormRect.of(0.4f, 0.4f, 0.4f, 0.4f))          // a tap, not a drag
        assertNull(NormRect.of(0.1f, 0.1f, 0.9f, 0.1f))          // zero height
        assertNull(NormRect.of(0.1f, 0.1f, 0.15f, 0.9f))         // 5 % wide
        assertNull(NormRect.of(1.2f, 0.1f, 1.5f, 0.9f))          // entirely outside -> clamps to nothing
        assertNull(NormRect.of(Float.NaN, 0f, 1f, 1f))
        assertNotNull(NormRect.of(0.1f, 0.1f, 0.2f, 0.2f))       // exactly the minimum side
    }

    @Test fun defaultIsTheFullFrame() {
        assertTrue(NormRect.FULL.isFull)
        assertEquals(NormRect.FULL, NormRect.of(0f, 0f, 1f, 1f))
        assertNull(NormRect.decode(null))
        assertNull(NormRect.decode("garbage"))
        assertNull(NormRect.decode("0.1,0.1,0.12,0.9"))          // stored but invalid -> caller uses FULL
        val a = roi(0.25f, 0.1f, 0.75f, 0.6f)
        assertEquals(a, NormRect.decode(a.encode()))
    }

    @Test fun rotationMapsTheSameScenePoints() {
        // upright point (x, y) for a buffer rotated r degrees clockwise to be upright, mapped back to the buffer
        fun bufferPoint(x: Float, y: Float, r: Int) = when (r) {
            0 -> x to y; 90 -> y to 1 - x; 180 -> 1 - x to 1 - y; 270 -> 1 - y to x; else -> error("") }
        val a = roi(0.1f, 0.2f, 0.4f, 0.9f)
        for (r in listOf(0, 90, 180, 270)) {
            val s = a.toSensor(r)
            for ((x, y) in listOf(0.1f to 0.2f, 0.4f to 0.9f, 0.25f to 0.5f)) {
                val (bx, by) = bufferPoint(x, y, r)
                assertTrue("r=$r ($x,$y)->($bx,$by) in $s", bx >= s.left - 1e-5f && bx <= s.right + 1e-5f && by >= s.top - 1e-5f && by <= s.bottom + 1e-5f)
            }
            assertEquals(a.width * a.height, s.width * s.height, 1e-5f)  // area preserved
        }
        for ((there, back) in listOf(90 to 270, 270 to 90, 180 to 180, 0 to 0)) {  // a rotation and its inverse
            val r = a.toSensor(there).toSensor(back)
            for ((x, y) in listOf(r.left to a.left, r.top to a.top, r.right to a.right, r.bottom to a.bottom)) assertEquals(y, x, 1e-5f)
        }
        assertEquals(NormRect.FULL, NormRect.FULL.toSensor(90))
    }

    @Test fun normalizedRoiSurvivesResolutionChange() {
        val scene = Scene()
        val a = roi(0.25f, 0.25f, 0.75f, 0.75f)
        val small = FrameSampler.downsample(scene.render(320, 240), 320, 1, 320, 240, 64, 48, a)
        val large = FrameSampler.downsample(scene.render(1280, 960), 1280, 1, 1280, 960, 64, 48, a)
        val meanDiff = small.values.indices.sumOf { abs(small.values[it] - large.values[it]).toDouble() } / small.values.size
        assertTrue("same scene region at both resolutions (mean diff $meanDiff)", meanDiff < 12)
        // and it really is the region: a different region gives very different grids
        val other = FrameSampler.downsample(scene.render(1280, 960), 1280, 1, 1280, 960, 64, 48, roi(0f, 0f, 0.5f, 0.5f))
        val otherDiff = small.values.indices.sumOf { abs(small.values[it] - other.values[it]).toDouble() } / small.values.size
        assertTrue("$otherDiff", otherDiff > 3 * meanDiff)
    }

    @Test fun smallRoiStillFillsEveryCell() {
        val g = FrameSampler.downsample(Scene().render(W, H), W, 1, W, H, 64, 48, roi(0.4f, 0.4f, 0.5f, 0.5f))  // 32x24 px
        assertTrue(g.values.all { it > 0f })
    }
}

class RoiMotionGateTest {
    private val gate = MotionGate(C)
    private val scene = Scene()
    private val area = roi(0.5f, 0.25f, 0.95f, 0.85f)
    private val base = scene.render(W, H)

    private fun classify(after: ByteBuffer): MotionKind {
        val (r0, f0) = grids(base, area)
        val (r1, f1) = grids(after, area)
        return gate.classify(r0, r1, f0, f1).kind
    }

    @Test fun identicalRoiIsStatic() = assertEquals(MotionKind.STATIC, classify(scene.render(W, H)))

    @Test fun smallNoiseInRoiRejected() {
        val r = Random(1)
        val noisy = scene.render(W, H).also { b -> for (i in 0 until b.capacity()) b.put(i, ((b.get(i).toInt() and 0xFF) + r.nextInt(-3, 4)).coerceIn(0, 255).toByte()) }
        val kind = classify(noisy)
        assertTrue(kind.name, kind == MotionKind.STATIC || kind == MotionKind.NOISE)
    }

    @Test fun localChangeInsideRoiIsACandidate() =
        assertEquals(MotionKind.LOCAL_MOTION, classify(scene.render(W, H, listOf(P(0.6f, 0.4f, 0.8f, 0.6f) to 5))))

    @Test fun motionOutsideRoiDoesNotCount() {
        // a change outside the area that WOULD be local motion for the full frame
        val outside = scene.render(W, H, listOf(P(0.05f, 0.3f, 0.3f, 0.6f) to 6))
        assertEquals(MotionKind.STATIC, classify(outside))
        val (f0, _) = grids(base, NormRect.FULL)
        val (f1, _) = grids(outside, NormRect.FULL)
        assertEquals(MotionKind.LOCAL_MOTION, gate.classify(f0, f1, null, null).kind)  // M-LIVE-04 full frame would fire
    }

    @Test fun smallChangeInsideRoiGetsMoreDetailThanFullFrame() {
        // ~6 % x 8 % of the frame: too small for the full-frame grid, clear inside the selected area
        val small = scene.render(W, H, listOf(P(0.70f, 0.50f, 0.76f, 0.58f) to 9))
        assertEquals(MotionKind.LOCAL_MOTION, classify(small))
    }

    @Test fun globalBrightnessChangeRejected() {
        assertEquals(MotionKind.STATIC, classify(scene.render(W, H, offset = 35f)))
        assertEquals(MotionKind.STATIC, classify(scene.render(W, H, gain = 1.25f)))
    }

    @Test fun cameraShakeIsVetoedByTheWholeFrame() {
        val kind = classify(scene.render(W, H, shift = 0.015f))  // whole view slid ~5 px: the area moved over the scene
        assertTrue(kind.name, kind == MotionKind.SHAKE || kind == MotionKind.STATIC || kind == MotionKind.NOISE)
        assertFalse(kind == MotionKind.LOCAL_MOTION)
    }

    @Test fun largeChangeAcrossTheWholeViewIsVetoed() {
        // something covering most of the view (e.g. a person right in front of the lens) also covers the area
        val covered = scene.render(W, H, listOf(P(0f, 0f, 0.9f, 1f) to 13))
        val (r0, f0) = grids(base, area); val (r1, f1) = grids(covered, area)
        assertEquals(MotionKind.GLOBAL_CHANGE, gate.compare(f0!!, f1!!).kind)
        assertFalse(gate.classify(r0, r1, f0, f1).kind == MotionKind.LOCAL_MOTION)
    }

    @Test fun fullFrameRoiBehavesExactlyLikeMLive04() {
        val changed = scene.render(W, H, listOf(P(0.6f, 0.4f, 0.8f, 0.6f) to 5))
        val (a, fa) = grids(base, NormRect.FULL)
        val (b, fb) = grids(changed, NormRect.FULL)
        assertNull(fa); assertNull(fb)
        assertEquals(gate.compare(a, b), gate.classify(a, b, null, null))
    }
}

/** Controller with ROI: the same state machine, keyframes, store and metadata as M-LIVE-04. */
class RoiControllerTest {
    @get:Rule val tmp = TemporaryFolder()
    private val scene = Scene()
    private val area = roi(0.5f, 0.25f, 0.95f, 0.85f)
    private val base = scene.render(W, H)
    private val inside = scene.render(W, H, listOf(P(0.6f, 0.4f, 0.8f, 0.6f) to 5))
    private val outside = scene.render(W, H, listOf(P(0.05f, 0.3f, 0.3f, 0.6f) to 6))
    private var now = 1_791_100_000_000L

    private class Fx(val store: EvidenceStore) : MonitorEffects {
        val uploads = mutableListOf<EvidencePackage>()
        var gpsRequests = 0
        override fun requestGps(onResult: (GpsFix?, String) -> Unit) { gpsRequests++; onResult(null, "unavailable: test") }
        override fun cancelGps() {}
        override fun store(keyframes: KeyframeCollector, gps: GpsFix?, gpsNote: String) =
            EvidenceAssembler(store).assemble(keyframes, gps, gpsNote, "0.3.0-mlive05", 70, "wifi")
        override fun upload(pkg: EvidencePackage, onDone: (Boolean) -> Unit) { uploads += pkg; onDone(true) }
    }

    private fun run(frames: (Int) -> ByteBuffer, samples: Int): Triple<MonitorController, Fx, EvidenceStore> {
        val store = EvidenceStore(tmp.newFolder())
        val fx = Fx(store)
        val c = MonitorController(C, fx) { now }.apply { autoUpload = false; start() }
        for (i in 0 until samples) {
            now += C.analysisIntervalMs
            val (g, f) = grids(frames(i), area)
            if (c.shouldSample(now)) c.onSample(g, now, f) { byteArrayOf(i.toByte()) }
        }
        return Triple(c, fx, store)
    }

    @Test fun staticAreaCreatesNothing() {
        val (c, fx, store) = run({ base }, 240)  // two minutes
        assertEquals(0, c.snapshot().possibleEvents)
        assertEquals(0, fx.gpsRequests)
        assertTrue(store.all().isEmpty())
    }

    @Test fun persistentMotionOutsideTheAreaCreatesNothing() {
        val (c, _, store) = run({ if (it % 2 == 0) outside else base }, 120)
        assertEquals(0, c.snapshot().localMotion)
        assertTrue(store.all().isEmpty())
    }

    @Test fun transientMotionInsideTheAreaDoesNotConfirm() {
        val (c, _, store) = run({ if (it == 10) inside else base }, 60)
        assertTrue(c.snapshot().possibleEvents >= 1)
        assertEquals(0, c.snapshot().confirmedEvents)
        assertTrue(store.all().isEmpty())
    }

    @Test fun persistentMotionInsideTheAreaConfirmsOnceWithBoundedKeyframes() {
        val (c, fx, store) = run({ if (it % 2 == 0) inside else base }, 120)  // a minute: cooldown blocks a second one
        val pkg = store.all().single()
        assertEquals(1, c.snapshot().confirmedEvents)
        assertEquals(3, pkg.frameCount)
        assertEquals(1, fx.gpsRequests)
        assertEquals(EvidenceState.READY, pkg.state)  // auto-upload OFF by default: waits on the phone
        assertTrue(fx.uploads.isEmpty())
        val meta = org.json.JSONObject(store.metadata(pkg))
        assertEquals(pkg.clientEventId, meta.getString("client_event_id"))
        assertEquals("mlive05-1", meta.getString("model_version"))
        assertFalse(meta.has("device_score") || meta.has("district_id") || meta.has("severity"))
    }

    @Test fun stopAndRecoveryStillSafe() {
        val (c, _, store) = run({ if (it % 2 == 0) inside else base }, 6)
        c.onCameraError()
        assertEquals(MonitorState.DEGRADED, c.state)
        c.onCameraRecovered()
        assertEquals(MonitorState.MONITORING, c.state)
        c.stop()
        assertEquals(MonitorState.STOPPED, c.state)
        assertFalse(c.shouldSample(now + 5_000))
        assertTrue(store.all().isEmpty())
    }

    @Test fun autoUploadDefaultsOff() {
        val c = MonitorController(C, Fx(EvidenceStore(tmp.newFolder())))
        assertFalse(c.autoUpload)
    }
}
