package np.xman.fieldnode

/**
 * Monitoring region of interest as fractions of the frame (0..1), so it survives any camera resolution.
 * Drawn by the user on the upright preview; [toSensor] maps it into the camera buffer's orientation.
 * Always valid: use [of] / [decode], which clamp to the frame and refuse zero-area or tiny regions.
 */
@ConsistentCopyVisibility  // copy() is private too: every NormRect goes through of()/decode() validation
data class NormRect private constructor(val left: Float, val top: Float, val right: Float, val bottom: Float) {
    val width get() = right - left
    val height get() = bottom - top
    val isFull get() = this == FULL

    /**
     * Upright (display) coordinates -> camera buffer coordinates. [rotationDegrees] is CameraX's
     * "rotate the buffer this much clockwise to make it upright"; a clockwise 90 degree rotation maps
     * buffer (x, y) to upright (1 - y, x), so the inverse is applied here.
     */
    fun toSensor(rotationDegrees: Int): NormRect = when (((rotationDegrees % 360) + 360) % 360) {
        0 -> this
        90 -> NormRect(top, 1 - right, bottom, 1 - left)
        180 -> NormRect(1 - right, 1 - bottom, 1 - left, 1 - top)
        270 -> NormRect(1 - bottom, left, 1 - top, right)
        else -> throw IllegalArgumentException("rotation must be a multiple of 90")
    }

    fun encode() = "$left,$top,$right,$bottom"

    companion object {
        /** Smallest allowed side (10 % of the frame): smaller regions have too few pixels to analyse. */
        const val MIN_SIDE = 0.1f
        private const val EPS = 1e-4f
        val FULL = NormRect(0f, 0f, 1f, 1f)

        /** Corners in any order; clamped to the frame. Null if not finite, zero-area or too small. */
        fun of(x1: Float, y1: Float, x2: Float, y2: Float): NormRect? {
            if (!listOf(x1, y1, x2, y2).all { it.isFinite() }) return null
            val l = minOf(x1, x2).coerceIn(0f, 1f)
            val r = maxOf(x1, x2).coerceIn(0f, 1f)
            val t = minOf(y1, y2).coerceIn(0f, 1f)
            val b = maxOf(y1, y2).coerceIn(0f, 1f)
            if (r - l < MIN_SIDE - EPS || b - t < MIN_SIDE - EPS) return null  // EPS: 0.5f - 0.4f is 0.0999...
            return NormRect(l, t, r, b)
        }

        /** Stored form from [encode]; anything malformed or invalid -> null (caller falls back to FULL). */
        fun decode(s: String?): NormRect? {
            val v = s?.split(',')?.map { it.toFloatOrNull() ?: return null } ?: return null
            return if (v.size == 4) of(v[0], v[1], v[2], v[3]) else null
        }
    }
}
