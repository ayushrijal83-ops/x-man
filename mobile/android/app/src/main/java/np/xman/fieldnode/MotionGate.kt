package np.xman.fieldnode

import kotlin.math.abs
import kotlin.math.sqrt

enum class MotionKind {
    /** No changed cell. */
    STATIC,
    /** A few changed cells, or changed cells too scattered to be one moving region (pixel/compression noise). */
    NOISE,
    /** One local region changed: a candidate for persistent visual change. Not a landslide claim. */
    LOCAL_MOTION,
    /** Most of the frame changed (lighting change, pan, reflections): not local. */
    GLOBAL_CHANGE,
    /** The change is explained by shifting the whole frame a little: ordinary camera shake. */
    SHAKE,
}

data class MotionResult(val kind: MotionKind, val changedCells: Int, val largestRegion: Int, val changedFraction: Float)

/**
 * Deterministic, CPU-only local-change detector between two consecutive sampled frames.
 *
 * 1. Each frame is normalized to z-scores ((v - mean) / max(std, minStd)): a uniform brightness offset or
 *    exposure gain change disappears.
 * 2. The |z difference| is averaged per cell (cellSize x cellSize grid pixels); a cell changed if the mean
 *    exceeds cellThreshold. Averaging rejects isolated pixel and compression noise.
 * 3. Fewer than minChangedCells changed cells -> STATIC / NOISE.
 * 4. Shake: if some whole-frame shift of up to maxShakeShift grid pixels reduces the residual to at most
 *    shakeResidualRatio of the unshifted residual, the frames are a translation of each other -> SHAKE.
 *    (A real local change is not explained by moving the whole frame; static texture gets worse when shifted.)
 * 5. More than maxLocalFraction of cells changed -> GLOBAL_CHANGE.
 * 6. The largest 4-connected group of changed cells must reach minRegionCells, else NOISE (scattered).
 * 7. Otherwise LOCAL_MOTION.
 *
 * Assumptions: the phone is mounted (not hand-held), frames are ~500 ms apart, the scene has some texture.
 * It cannot tell a landslide from a person, vehicle, animal, moving branch or rain streak: that is what the
 * temporal confirmation and, later, a classifier and X-MAN review are for.
 */
class MotionGate(private val config: MonitorConfig = MonitorConfig()) {
    private val cellsX = config.gridWidth / config.cellSize
    private val cellsY = config.gridHeight / config.cellSize

    fun compare(previous: LumaGrid, current: LumaGrid): MotionResult {
        require(previous.width == config.gridWidth && previous.height == config.gridHeight)
        require(current.width == config.gridWidth && current.height == config.gridHeight)
        val a = normalize(previous.values)
        val b = normalize(current.values)

        val changed = BooleanArray(cellsX * cellsY)
        var changedCount = 0
        for (cy in 0 until cellsY) for (cx in 0 until cellsX) {
            var sum = 0f
            for (y in cy * config.cellSize until (cy + 1) * config.cellSize)
                for (x in cx * config.cellSize until (cx + 1) * config.cellSize) {
                    val i = y * config.gridWidth + x
                    sum += abs(b[i] - a[i])
                }
            if (sum / (config.cellSize * config.cellSize) > config.cellThreshold) {
                changed[cy * cellsX + cx] = true
                changedCount++
            }
        }
        val fraction = changedCount.toFloat() / changed.size
        fun result(kind: MotionKind, region: Int = 0) = MotionResult(kind, changedCount, region, fraction)

        if (changedCount == 0) return result(MotionKind.STATIC)
        if (changedCount < config.minChangedCells) return result(MotionKind.NOISE)
        if (isShake(a, b)) return result(MotionKind.SHAKE)
        if (fraction > config.maxLocalFraction) return result(MotionKind.GLOBAL_CHANGE)
        val region = largestRegion(changed)
        if (region < config.minRegionCells) return result(MotionKind.NOISE, region)
        return result(MotionKind.LOCAL_MOTION, region)
    }

    /**
     * M-LIVE-05 ROI decision. The selected region (resampled to the same grid) is the primary signal;
     * the whole frame is context only:
     *   - ROI not LOCAL_MOTION                 -> the ROI result (motion outside the ROI can't create a hit)
     *   - ROI LOCAL_MOTION, frame SHAKE        -> SHAKE: the camera moved, so the scene slid under the ROI
     *   - ROI LOCAL_MOTION, frame GLOBAL_CHANGE-> GLOBAL_CHANGE: most of the view changed (lighting, a person
     *                                              right in front of the lens), not a change of the area itself
     *   - otherwise                            -> LOCAL_MOTION
     * Without frame grids (ROI = full frame) this is exactly [compare], i.e. the M-LIVE-04 behaviour.
     */
    fun classify(roiPrevious: LumaGrid, roiCurrent: LumaGrid, framePrevious: LumaGrid?, frameCurrent: LumaGrid?): MotionResult {
        val roi = compare(roiPrevious, roiCurrent)
        if (roi.kind != MotionKind.LOCAL_MOTION || framePrevious == null || frameCurrent == null) return roi
        return when (compare(framePrevious, frameCurrent).kind) {
            MotionKind.SHAKE -> roi.copy(kind = MotionKind.SHAKE)
            MotionKind.GLOBAL_CHANGE -> roi.copy(kind = MotionKind.GLOBAL_CHANGE)
            else -> roi
        }
    }

    private fun normalize(v: FloatArray): FloatArray {
        val mean = v.average().toFloat()
        var variance = 0f
        for (x in v) variance += (x - mean) * (x - mean)
        val std = maxOf(sqrt(variance / v.size), config.minStd)
        return FloatArray(v.size) { (v[it] - mean) / std }
    }

    /** Mean |b(x+dx, y+dy) - a(x, y)| over the overlap, ignoring a border of maxShakeShift. */
    private fun residual(a: FloatArray, b: FloatArray, dx: Int, dy: Int): Float {
        val s = config.maxShakeShift
        val w = config.gridWidth
        var sum = 0f
        var n = 0
        for (y in s until config.gridHeight - s) for (x in s until w - s) {
            sum += abs(b[(y + dy) * w + x + dx] - a[y * w + x])
            n++
        }
        return sum / n
    }

    private fun isShake(a: FloatArray, b: FloatArray): Boolean {
        val unshifted = residual(a, b, 0, 0)
        if (unshifted == 0f) return false
        var best = Float.MAX_VALUE
        val s = config.maxShakeShift
        for (dy in -s..s) for (dx in -s..s) if (dx != 0 || dy != 0) best = minOf(best, residual(a, b, dx, dy))
        return best <= config.shakeResidualRatio * unshifted
    }

    /** Size of the largest 4-connected group of changed cells (iterative flood fill, no recursion). */
    private fun largestRegion(changed: BooleanArray): Int {
        val seen = BooleanArray(changed.size)
        val stack = IntArray(changed.size)
        var largest = 0
        for (start in changed.indices) {
            if (!changed[start] || seen[start]) continue
            var top = 0
            var size = 0
            stack[top++] = start
            seen[start] = true
            while (top > 0) {
                val c = stack[--top]
                size++
                val cx = c % cellsX
                val cy = c / cellsX
                for ((nx, ny) in arrayOf(cx - 1 to cy, cx + 1 to cy, cx to cy - 1, cx to cy + 1)) {
                    if (nx !in 0 until cellsX || ny !in 0 until cellsY) continue
                    val n = ny * cellsX + nx
                    if (changed[n] && !seen[n]) { seen[n] = true; stack[top++] = n }
                }
            }
            largest = maxOf(largest, size)
        }
        return largest
    }
}
