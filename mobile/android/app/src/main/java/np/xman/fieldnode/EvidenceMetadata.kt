package np.xman.fieldnode

import org.json.JSONObject
import java.time.Instant
import java.time.temporal.ChronoUnit

/**
 * The `metadata` part of POST /api/iot/evidence (M-LIVE-02 contract).
 *
 * Only keys the server allows. Everything authoritative (district, severity, status, hazard type,
 * source, incident, recipients...) is derived by X-MAN and is never sent: the server answers 400 if it is.
 * No device_score / model / model_version: this milestone has no detector, frames are captured by hand.
 */
object EvidenceMetadata {
    val ALLOWED = setOf("client_event_id", "captured_at", "latitude", "longitude", "gps_accuracy_m", "gps_fix_at",
                        "device_score", "model", "model_version", "app_version", "battery_pct", "network_type")

    fun build(pkg: EvidencePackage, gps: GpsFix?, appVersion: String?, batteryPct: Int?, networkType: String?): JSONObject {
        val capturedAt = requireNotNull(pkg.capturedAtMs) { "no frame captured" }
        val json = JSONObject()
            .put("client_event_id", pkg.clientEventId)
            .put("captured_at", iso(capturedAt))
        if (gps != null) {  // no fix -> no coordinates at all (never invented)
            json.put("latitude", gps.latitude).put("longitude", gps.longitude).put("gps_fix_at", iso(gps.fixTimeMs))
            gps.accuracyM?.let { json.put("gps_accuracy_m", it) }
        }
        appVersion?.takeIf { it.isNotBlank() }?.let { json.put("app_version", it.take(32)) }
        batteryPct?.takeIf { it in 0..100 }?.let { json.put("battery_pct", it) }
        networkType?.let { json.put("network_type", it) }
        check(json.keys().asSequence().all { it in ALLOWED })
        return json
    }

    /** ISO 8601 UTC, whole seconds: "2026-10-04T12:00:00Z". */
    fun iso(epochMs: Long): String = Instant.ofEpochMilli(epochMs).truncatedTo(ChronoUnit.SECONDS).toString()
}
