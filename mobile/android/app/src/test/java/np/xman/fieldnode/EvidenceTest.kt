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
import java.io.File

/** Server rule (M-LIVE-02 node_evidence_service.CLIENT_EVENT_ID_RE). */
private val SERVER_EVENT_ID = Regex("^[A-Za-z0-9_-]{8,64}$")

/** Every key X-MAN owns and refuses with 400 (M-LIVE-02 FORBIDDEN_FIELDS). */
private val FORBIDDEN = setOf("severity", "district", "district_id", "status", "confirmed", "authority", "authority_id",
    "recipients", "incident_id", "event_type", "hazard_type", "source", "received_at", "affected_districts",
    "device_id", "review_status")

class ClientEventIdTest {
    @Test fun generatedIdsAreUniqueAndAcceptedByServer() {
        val ids = (1..500).map { EvidencePackage.newClientEventId() }.toSet()
        assertEquals(500, ids.size)
        assertTrue(ids.all { SERVER_EVENT_ID.matches(it) })
    }

    @Test fun idSurvivesPersistence() {
        val pkg = EvidencePackage(frameCount = 2, capturedAtMs = 1_000L, state = EvidenceState.FAILED_RETRYABLE)
        val back = EvidencePackage.fromJson(JSONObject(pkg.toJson().toString()))
        assertEquals(pkg, back)
    }
}

class EvidenceMetadataTest {
    private val pkg = EvidencePackage(clientEventId = "1b4e28ba-2fa1-11d2-883f-0016d3cca427", capturedAtMs = 1_791_100_000_123L)
    private val fix = GpsFix(27.700123, 85.300456, 8.5, 1_791_099_990_000L)

    @Test fun requiredFieldsPresent() {
        val json = EvidenceMetadata.build(pkg, null, null, null, null)
        assertEquals(setOf("client_event_id", "captured_at"), json.keyNames())
        assertEquals(pkg.clientEventId, json.getString("client_event_id"))
        assertEquals("2026-10-04T07:46:40Z", json.getString("captured_at"))  // UTC, whole seconds
    }

    @Test fun fullMetadataUsesOnlyAllowedKeys() {
        val json = EvidenceMetadata.build(pkg, fix, "0.1.0-mlive03", 81, "wifi")
        assertTrue(EvidenceMetadata.ALLOWED.containsAll(json.keyNames()))
        assertTrue(json.keyNames().intersect(FORBIDDEN).isEmpty())
        assertEquals(27.700123, json.getDouble("latitude"), 0.0)
        assertEquals(85.300456, json.getDouble("longitude"), 0.0)
        assertEquals(8.5, json.getDouble("gps_accuracy_m"), 0.0)
        assertEquals("2026-10-04T07:46:30Z", json.getString("gps_fix_at"))
        assertEquals(81, json.getInt("battery_pct"))
        assertEquals("wifi", json.getString("network_type"))
    }

    @Test fun noDetectorClaims() {
        val json = EvidenceMetadata.build(pkg, fix, "0.1.0", 50, "wifi")
        for (key in listOf("device_score", "model", "model_version")) assertFalse(key, json.has(key))
    }

    @Test fun gpsOmittedWhenUnavailable() {
        val json = EvidenceMetadata.build(pkg, null, "0.1.0", 50, "cellular")
        for (key in listOf("latitude", "longitude", "gps_accuracy_m", "gps_fix_at")) assertFalse(key, json.has(key))
    }

    @Test fun unknownAccuracyOmittedNotInvented() {
        val json = EvidenceMetadata.build(pkg, fix.copy(accuracyM = null), null, null, null)
        assertTrue(json.has("latitude"))
        assertFalse(json.has("gps_accuracy_m"))
    }

    @Test fun invalidBatteryOmitted() {
        assertFalse(EvidenceMetadata.build(pkg, null, null, -1, null).has("battery_pct"))
        assertFalse(EvidenceMetadata.build(pkg, null, null, 101, null).has("battery_pct"))
    }

    @Test(expected = IllegalArgumentException::class)
    fun needsACapturedFrame() {
        EvidenceMetadata.build(EvidencePackage(), null, null, null, null)
    }
}

class UploadOutcomeTest {
    @Test fun created() {
        val o = UploadOutcome.fromResponse(201,
            """{"success": true, "duplicate": false, "evidence_id": 12, "incident_id": 7, "status": "attached"}""")
        assertEquals(EvidenceState.UPLOADED, o.state)
        assertEquals(12L, o.evidenceId); assertEquals(7L, o.incidentId); assertEquals("attached", o.serverStatus)
        assertFalse(o.duplicate)
    }

    @Test fun duplicate() {
        val o = UploadOutcome.fromResponse(200,
            """{"success": true, "duplicate": true, "evidence_id": 12, "incident_id": 7, "status": "attached"}""")
        assertEquals(EvidenceState.UPLOADED, o.state)
        assertTrue(o.duplicate)
        assertEquals(12L, o.evidenceId)
    }

    @Test fun heldEvidenceHasNoIncident() {
        val o = UploadOutcome.fromResponse(201,
            """{"success": true, "duplicate": false, "evidence_id": 3, "incident_id": null, "status": "held"}""")
        assertNull(o.incidentId)
        assertEquals("held", o.serverStatus)
    }

    @Test fun ok200WithoutDuplicateIsNotSuccess() {
        assertEquals(EvidenceState.FAILED_RETRYABLE, UploadOutcome.fromResponse(200, "{}").state)
    }

    @Test fun permanentFailures() {
        val bad = UploadOutcome.fromResponse(400, """{"error": "Server-owned field(s) not allowed: severity"}""")
        assertEquals(EvidenceState.FAILED_PERMANENT, bad.state)
        assertTrue(bad.message.contains("severity"))
        assertEquals(EvidenceState.FAILED_PERMANENT, UploadOutcome.fromResponse(403, """{"error": "x"}""").state)
        assertEquals(EvidenceState.FAILED_PERMANENT, UploadOutcome.fromResponse(413, null).state)
        assertEquals(EvidenceState.FAILED_PERMANENT, UploadOutcome.fromResponse(404, "<html>").state)
    }

    @Test fun credentialsInvalid() {
        val o = UploadOutcome.fromResponse(401, """{"error": "Invalid or missing device credentials"}""")
        assertEquals(EvidenceState.FAILED_RETRYABLE, o.state)  // retry only after re-provisioning
        assertEquals("Camera node credentials invalid or revoked. Re-provision this device.", o.message)
    }

    @Test fun retryableFailures() {
        assertEquals(EvidenceState.FAILED_RETRYABLE, UploadOutcome.fromResponse(429, """{"error": "retry later"}""").state)
        for (code in listOf(500, 502, 503)) assertEquals(EvidenceState.FAILED_RETRYABLE, UploadOutcome.fromResponse(code, null).state)
        assertEquals(EvidenceState.FAILED_RETRYABLE, UploadOutcome.networkFailure().state)
    }

    @Test fun longServerErrorIsTruncated() {
        val o = UploadOutcome.fromResponse(400, JSONObject().put("error", "x".repeat(5000)).toString())
        assertTrue(o.message.length < 400)
    }
}

class MultipartTest {
    @Test fun partsMatchTheContract() {
        val m = Multipart("""{"client_event_id":"abcdefgh"}""", listOf(byteArrayOf(1, 2), byteArrayOf(3), byteArrayOf(4)))
        val text = m.body.toString(Charsets.ISO_8859_1)
        assertEquals("multipart/form-data; boundary=${m.boundary}", m.contentType)
        assertTrue(text.contains("Content-Disposition: form-data; name=\"metadata\"\r\nContent-Type: application/json"))
        for (i in 0..2) {
            assertTrue(text.contains("Content-Disposition: form-data; name=\"frame_$i\"; filename=\"frame_$i.jpg\"\r\nContent-Type: image/jpeg"))
        }
        assertFalse(text.contains("frame_3"))
        assertTrue(text.endsWith("--${m.boundary}--\r\n"))
        assertFalse(text.contains("/data/") || text.contains("\\"))  // no local paths
    }

    @Test(expected = IllegalArgumentException::class)
    fun atMostThreeFrames() {
        Multipart("{}", List(4) { byteArrayOf(1) })
    }

    @Test(expected = IllegalArgumentException::class)
    fun atLeastOneFrame() {
        Multipart("{}", emptyList())
    }
}

class EvidenceStoreTest {
    @get:Rule val tmp = TemporaryFolder()

    @Test fun framesAndStateSurviveRestart() {
        val root = tmp.newFolder("evidence")
        val store = EvidenceStore(root)
        val pkg = store.create()
        store.addFrame(pkg, byteArrayOf(1), 1_000)
        store.addFrame(pkg, byteArrayOf(2), 2_000)
        assertEquals(1_000L, pkg.capturedAtMs)  // the first frame's time
        val again = EvidenceStore(root).load(pkg.clientEventId)!!
        assertEquals(2, again.frameCount)
        assertEquals(listOf(1, 2), EvidenceStore(root).frames(again).map { it[0].toInt() })
    }

    @Test(expected = IllegalStateException::class)
    fun atMostThreeFrames() {
        val store = EvidenceStore(tmp.newFolder())
        val pkg = store.create()
        repeat(4) { store.addFrame(pkg, byteArrayOf(1), 1) }
    }

    @Test(expected = IllegalStateException::class)
    fun readyNeedsAFrame() {
        val store = EvidenceStore(tmp.newFolder())
        store.markReady(store.create(), JSONObject())
    }

    @Test fun interruptedUploadBecomesRetryable() {
        val root = tmp.newFolder()
        val store = EvidenceStore(root)
        val pkg = store.create().apply { state = EvidenceState.UPLOADING }
        store.save(pkg)
        val loaded = EvidenceStore(root).load(pkg.clientEventId)!!
        assertEquals(EvidenceState.FAILED_RETRYABLE, loaded.state)
        assertEquals(pkg.clientEventId, loaded.clientEventId)
    }

    @Test(expected = IllegalArgumentException::class)
    fun idsCannotEscapeTheEvidenceFolder() {
        EvidenceStore(tmp.newFolder()).load("../../shared_prefs")
    }

    @Test fun framesAreAppPrivateFiles() {
        val root = tmp.newFolder("evidence")
        val store = EvidenceStore(root)
        val pkg = store.create()
        store.addFrame(pkg, byteArrayOf(9), 1)
        assertTrue(store.frameFile(pkg, 0).canonicalPath.startsWith(root.canonicalPath + File.separator))
    }
}

/** Android's org.json has no keySet(). */
internal fun JSONObject.keyNames(): Set<String> = keys().asSequence().toSet()
