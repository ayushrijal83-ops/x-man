package np.xman.fieldnode

/**
 * Every tunable of the M-LIVE-04 visual-monitoring pipeline, in one place. Engineering defaults for a
 * mounted phone (Redmi 12), NOT validated against real landslides: they decide when a *persistent local
 * visual change* becomes a visual evidence candidate, nothing more.
 */
data class MonitorConfig(
    // --- sampling -----------------------------------------------------------------------------
    /** Analyse at most one camera frame per interval (500 ms = 2 frames/s). Other frames are dropped. */
    val analysisIntervalMs: Long = 500,
    /** Luminance grid the camera frame is block-averaged into (averaging suppresses pixel/JPEG noise). */
    val gridWidth: Int = 64,
    val gridHeight: Int = 48,

    // --- MotionGate (values are in per-frame z-score units, see MotionGate) ----------------------
    /** Grid pixels per cell side: 64x48 grid / 4 = 16x12 = 192 cells. */
    val cellSize: Int = 4,
    /** A cell "changed" when its mean |z difference| exceeds this. */
    val cellThreshold: Float = 0.5f,
    /** Below this many changed cells: static or noise. */
    val minChangedCells: Int = 3,
    /** The largest 4-connected group of changed cells must have at least this many cells (locality). */
    val minRegionCells: Int = 3,
    /** More than this fraction of cells changed = global change (lighting, pan), not local motion. */
    val maxLocalFraction: Float = 0.5f,
    /** Shake test: try whole-frame shifts up to this many grid pixels... */
    val maxShakeShift: Int = 2,
    /** ...and call it shake if the best shift leaves at most this fraction of the unshifted residual. */
    val shakeResidualRatio: Float = 0.6f,
    /** Floor for the per-frame standard deviation, so a flat/covered scene doesn't amplify sensor noise. */
    val minStd: Float = 4f,

    // --- temporal confirmation ------------------------------------------------------------------
    /** POSSIBLE_EVENT -> CONFIRMING after this many local-motion samples (the first one included). */
    val possibleHitsToConfirm: Int = 3,
    /** POSSIBLE_EVENT -> MONITORING after this many consecutive samples without local motion. */
    val possibleMaxMisses: Int = 2,
    /** CONFIRMING observes this long, then decides. */
    val confirmWindowMs: Long = 4_000,
    /** Fraction of samples in the window that must show local motion. */
    val confirmMinMotionRatio: Float = 0.6f,
    /** CONFIRMING -> MONITORING early after this many consecutive samples without local motion. */
    val confirmMaxConsecutiveMisses: Int = 3,
    /** After a candidate: ignore motion for this long (no immediate re-trigger). */
    val cooldownMs: Long = 60_000,
    /** Safety nets so the machine can never wait forever. */
    val evidenceTimeoutMs: Long = 45_000,
    val uploadTimeoutMs: Long = 120_000,
    /** Max wait for the "after confirmation" keyframe before the package is finalized without it. */
    val afterFrameTimeoutMs: Long = 3_000,
    /** Give up on the confirmation-time GPS fix after this long (shorter than evidenceTimeoutMs). */
    val gpsTimeoutMs: Long = 35_000,
)

/** A small grayscale image (luminance 0..255) of [width] x [height], row-major. */
class LumaGrid(val width: Int, val height: Int, val values: FloatArray) {
    init { require(values.size == width * height) }
    operator fun get(x: Int, y: Int) = values[y * width + x]
}

/** Camera Y plane -> block-averaged [LumaGrid]. Reads the plane directly: no Bitmap, no copy of the frame. */
object FrameSampler {
    /**
     * Averages the Y (luminance) plane inside [roi] (camera-buffer orientation, see NormRect.toSensor)
     * into a gridW x gridH grid: a small ROI gets the same grid size, i.e. more detail at the same cost.
     * Every cell reads at most ~5x5 evenly spaced pixels and always at least one, so no cell is empty.
     * Works on any row/pixel stride (CameraX YUV_420_888). No Bitmap, no copy of the frame.
     */
    fun downsample(y: java.nio.ByteBuffer, rowStride: Int, pixelStride: Int, width: Int, height: Int,
                   gridW: Int, gridH: Int, roi: NormRect = NormRect.FULL): LumaGrid {
        val x0 = (roi.left * width).toInt().coerceIn(0, width - 1)
        val y0 = (roi.top * height).toInt().coerceIn(0, height - 1)
        val rw = maxOf(1, (roi.right * width).toInt().coerceAtMost(width) - x0)
        val rh = maxOf(1, (roi.bottom * height).toInt().coerceAtMost(height) - y0)
        val out = FloatArray(gridW * gridH)
        for (gy in 0 until gridH) {
            val ys = y0 + gy * rh / gridH
            val ye = maxOf(ys + 1, y0 + (gy + 1) * rh / gridH)
            val stepY = maxOf(1, (ye - ys) / 5)
            for (gx in 0 until gridW) {
                val xs = x0 + gx * rw / gridW
                val xe = maxOf(xs + 1, x0 + (gx + 1) * rw / gridW)
                val stepX = maxOf(1, (xe - xs) / 5)
                var sum = 0
                var n = 0
                var row = ys
                while (row < ye) {
                    val base = row * rowStride
                    var col = xs
                    while (col < xe) {
                        sum += y.get(base + col * pixelStride).toInt() and 0xFF
                        n++
                        col += stepX
                    }
                    row += stepY
                }
                out[gy * gridW + gx] = sum.toFloat() / n
            }
        }
        return LumaGrid(gridW, gridH, out)
    }
}
