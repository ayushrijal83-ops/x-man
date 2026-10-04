package np.xman.fieldnode

/**
 * At most three JPEG keyframes for one visual evidence candidate: no video, no rolling buffer.
 *   DETECTION  the sample that opened POSSIBLE_EVENT (around the start of the change)
 *   CONFIRMED  the sample that confirmed the persistent change
 *   AFTER      the next sample after confirmation, if one arrives in time
 * A slot is written once; later frames for a filled slot are ignored. [clear] drops everything.
 */
class KeyframeCollector {
    enum class Slot { DETECTION, CONFIRMED, AFTER }

    private val frames = arrayOfNulls<ByteArray>(Slot.values().size)
    var detectionAtMs: Long? = null
        private set

    fun has(slot: Slot) = frames[slot.ordinal] != null

    /** Stores the frame from [encode] only if the slot is empty, so a frame is only encoded when needed. */
    fun put(slot: Slot, atMs: Long, encode: () -> ByteArray) {
        if (has(slot)) return
        frames[slot.ordinal] = encode()
        if (slot == Slot.DETECTION) detectionAtMs = atMs
    }

    /** Filled frames in time order (1..3). */
    fun frames(): List<ByteArray> = frames.filterNotNull()

    val count get() = frames.count { it != null }

    fun clear() {
        frames.fill(null)
        detectionAtMs = null
    }
}

/** Builds a READY package from collected keyframes through the M-LIVE-03 store (same files, same upload). */
class EvidenceAssembler(private val store: EvidenceStore) {
    fun assemble(keyframes: KeyframeCollector, gps: GpsFix?, gpsNote: String, appVersion: String?,
                 batteryPct: Int?, networkType: String?): EvidencePackage {
        val frames = keyframes.frames()
        require(frames.isNotEmpty()) { "no keyframe" }
        val pkg = store.create()
        pkg.trigger = EvidencePackage.TRIGGER_MOTION_GATE
        pkg.gpsNote = gpsNote
        val at = keyframes.detectionAtMs ?: System.currentTimeMillis()
        frames.take(EvidencePackage.MAX_FRAMES).forEach { store.addFrame(pkg, it, at) }
        store.markReady(pkg, EvidenceMetadata.build(pkg, gps, appVersion, batteryPct, networkType))
        return pkg
    }
}
