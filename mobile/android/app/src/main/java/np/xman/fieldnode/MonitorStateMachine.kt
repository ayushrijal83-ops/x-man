package np.xman.fieldnode

enum class MonitorState {
    /** Monitoring is off: no camera, no analysis. */
    STOPPED,
    MONITORING,
    /** "Possible visual event": local motion seen, waiting for persistence. */
    POSSIBLE_EVENT,
    /** Persistent motion: observing a fixed window before deciding. */
    CONFIRMING,
    /** "Visual evidence candidate": keyframes + GPS are being collected into a package. */
    CONFIRMED_EVIDENCE,
    /** Package stored on the phone; upload in progress or left for manual upload. */
    UPLOAD_PENDING,
    UPLOADED,
    /** No new candidate until the cooldown has passed. */
    COOLDOWN,
    /** Camera failed; nothing is analysed until it recovers. */
    DEGRADED,
}

data class Transition(val from: MonitorState, val to: MonitorState)

/**
 * Deterministic temporal confirmation. Pure logic: every input carries its own timestamp, nothing here
 * touches the camera, the clock, the network or the UI. A single transient motion sample can never produce
 * evidence (POSSIBLE_EVENT needs [MonitorConfig.possibleHitsToConfirm] hits, then CONFIRMING needs a full
 * window). Every waiting state has a timeout, so no input sequence can keep the machine stuck.
 */
class MonitorStateMachine(private val config: MonitorConfig = MonitorConfig()) {
    var state = MonitorState.STOPPED
        private set
    var possibleEvents = 0
        private set
    var confirmedEvents = 0
        private set

    private var enteredAt = 0L
    private var hits = 0
    private var misses = 0
    private var windowSamples = 0
    private var windowMotion = 0

    private fun go(to: MonitorState, now: Long): Transition? {
        if (to == state) return null
        val t = Transition(state, to)
        state = to
        enteredAt = now
        hits = 0; misses = 0; windowSamples = 0; windowMotion = 0
        when (to) {
            MonitorState.POSSIBLE_EVENT -> { possibleEvents++; hits = 1 }
            MonitorState.CONFIRMED_EVIDENCE -> confirmedEvents++
            else -> Unit
        }
        return t
    }

    /** Starts a monitoring session; event counters are per session. */
    fun start(now: Long): Transition? {
        if (state != MonitorState.STOPPED) return null
        possibleEvents = 0; confirmedEvents = 0
        return go(MonitorState.MONITORING, now)
    }

    /** Always safe: from any state, back to STOPPED with all per-event counters reset. */
    fun stop(now: Long): Transition? = go(MonitorState.STOPPED, now)

    /** One analysed sample. Returns the transition it caused, if any. */
    fun onSample(kind: MotionKind, now: Long): Transition? {
        timeouts(now)?.let { return it }
        val motion = kind == MotionKind.LOCAL_MOTION
        return when (state) {
            MonitorState.MONITORING -> if (motion) go(MonitorState.POSSIBLE_EVENT, now) else null
            MonitorState.POSSIBLE_EVENT -> if (motion) {
                misses = 0
                if (++hits >= config.possibleHitsToConfirm) go(MonitorState.CONFIRMING, now) else null
            } else {
                if (++misses >= config.possibleMaxMisses) go(MonitorState.MONITORING, now) else null
            }
            MonitorState.CONFIRMING -> {
                windowSamples++
                if (motion) { windowMotion++; misses = 0 } else misses++
                when {
                    misses >= config.confirmMaxConsecutiveMisses -> go(MonitorState.MONITORING, now)
                    now - enteredAt >= config.confirmWindowMs ->
                        if (windowMotion >= config.confirmMinMotionRatio * windowSamples) go(MonitorState.CONFIRMED_EVIDENCE, now)
                        else go(MonitorState.MONITORING, now)
                    else -> null
                }
            }
            // waiting for the package / upload / cooldown: motion is ignored
            else -> null
        }
    }

    /** Time-based exits; also call on every sample (done by [onSample]). */
    fun timeouts(now: Long): Transition? = when (state) {
        MonitorState.COOLDOWN -> if (now - enteredAt >= config.cooldownMs) go(MonitorState.MONITORING, now) else null
        MonitorState.CONFIRMED_EVIDENCE -> if (now - enteredAt >= config.evidenceTimeoutMs) go(MonitorState.COOLDOWN, now) else null
        MonitorState.UPLOAD_PENDING -> if (now - enteredAt >= config.uploadTimeoutMs) go(MonitorState.COOLDOWN, now) else null
        MonitorState.UPLOADED -> go(MonitorState.COOLDOWN, now)
        else -> null
    }

    /** The evidence package is stored on the phone. */
    fun onEvidenceStored(now: Long): Transition? =
        if (state == MonitorState.CONFIRMED_EVIDENCE) go(MonitorState.UPLOAD_PENDING, now) else null

    /** Accepted by X-MAN -> UPLOADED (then COOLDOWN); not sent / failed -> COOLDOWN, package stays pending on the phone. */
    fun onUploadFinished(uploaded: Boolean, now: Long): Transition? {
        if (state != MonitorState.UPLOAD_PENDING) return null
        return if (uploaded) go(MonitorState.UPLOADED, now) else go(MonitorState.COOLDOWN, now)
    }

    fun onCameraError(now: Long): Transition? =
        if (state != MonitorState.STOPPED) go(MonitorState.DEGRADED, now) else null

    fun onCameraRecovered(now: Long): Transition? =
        if (state == MonitorState.DEGRADED) go(MonitorState.MONITORING, now) else null
}
