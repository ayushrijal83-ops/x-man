package np.xman.fieldnode

import org.json.JSONObject
import java.io.File

/**
 * App-private evidence packages: <root>/<client_event_id>/{package.json, metadata.json, frame_N.jpg}.
 * Never the shared gallery. Frames stay until X-MAN confirms the upload (201, or 200 duplicate), so a
 * network failure cannot destroy captured evidence.
 */
class EvidenceStore(private val root: File) {

    private fun dir(id: String): File {
        require(ID_RE.matches(id)) { "invalid package id" }  // ids are used as directory names
        return File(root, id)
    }

    fun create(): EvidencePackage {
        val pkg = EvidencePackage()
        dir(pkg.clientEventId).mkdirs()
        save(pkg)
        return pkg
    }

    fun save(pkg: EvidencePackage) {
        val d = dir(pkg.clientEventId).apply { mkdirs() }
        atomicWrite(File(d, "package.json"), pkg.toJson().toString().toByteArray())
    }

    fun load(id: String): EvidencePackage? {
        val f = File(dir(id), "package.json")
        if (!f.isFile) return null
        val pkg = EvidencePackage.fromJson(JSONObject(f.readText()))
        if (pkg.state == EvidenceState.UPLOADING) {
            // the app died mid-upload: X-MAN may or may not have it; the same id makes a retry safe
            pkg.state = EvidenceState.FAILED_RETRYABLE
            pkg.lastMessage = "Upload was interrupted. Retry to resend the same evidence."
        }
        return pkg
    }

    /** Newest first. */
    fun all(): List<EvidencePackage> =
        (root.listFiles { f -> f.isDirectory && ID_RE.matches(f.name) } ?: emptyArray())
            .sortedByDescending { File(it, "package.json").lastModified() }
            .mapNotNull { load(it.name) }

    fun frameFile(pkg: EvidencePackage, index: Int): File {
        require(index in 0 until EvidencePackage.MAX_FRAMES)
        return File(dir(pkg.clientEventId), "frame_$index.jpg")
    }

    fun addFrame(pkg: EvidencePackage, jpeg: ByteArray, nowMs: Long) {
        check(pkg.state == EvidenceState.DRAFT) { "frames can only be added to a draft" }
        check(pkg.frameCount < EvidencePackage.MAX_FRAMES) { "at most ${EvidencePackage.MAX_FRAMES} frames" }
        atomicWrite(frameFile(pkg, pkg.frameCount), jpeg)
        if (pkg.frameCount == 0) pkg.capturedAtMs = nowMs
        pkg.frameCount++
        save(pkg)
    }

    fun clearFrames(pkg: EvidencePackage) {
        check(pkg.state == EvidenceState.DRAFT)
        for (i in 0 until EvidencePackage.MAX_FRAMES) frameFile(pkg, i).delete()
        pkg.frameCount = 0
        pkg.capturedAtMs = null
        save(pkg)
    }

    fun frames(pkg: EvidencePackage): List<ByteArray> = (0 until pkg.frameCount).map { frameFile(pkg, it).readBytes() }

    /** Freezes the metadata sent on every attempt: retries resend exactly the same package. */
    fun markReady(pkg: EvidencePackage, metadata: JSONObject) {
        check(pkg.state == EvidenceState.DRAFT && pkg.frameCount > 0) { "a draft with at least one frame is required" }
        atomicWrite(File(dir(pkg.clientEventId), "metadata.json"), metadata.toString().toByteArray())
        pkg.state = EvidenceState.READY
        save(pkg)
    }

    fun metadata(pkg: EvidencePackage): String = File(dir(pkg.clientEventId), "metadata.json").readText()

    /** After X-MAN confirmed the package: keep the small result record, drop the frames. */
    fun dropFrames(pkg: EvidencePackage) {
        for (i in 0 until EvidencePackage.MAX_FRAMES) frameFile(pkg, i).delete()
    }

    fun delete(pkg: EvidencePackage) {
        dir(pkg.clientEventId).deleteRecursively()
    }

    private fun atomicWrite(target: File, bytes: ByteArray) {
        val tmp = File(target.parentFile, target.name + ".tmp")
        tmp.writeBytes(bytes)
        if (!tmp.renameTo(target)) {
            target.delete()
            check(tmp.renameTo(target)) { "could not write ${target.name}" }
        }
    }

    companion object {
        private val ID_RE = Regex("^[A-Za-z0-9_-]{8,64}$")
    }
}
