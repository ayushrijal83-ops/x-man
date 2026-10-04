package np.xman.fieldnode

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.location.Location
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.CancellationSignal
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import androidx.core.content.ContextCompat
import androidx.core.location.LocationManagerCompat
import java.io.ByteArrayOutputStream
import java.io.File
import java.security.KeyStore
import java.util.concurrent.Executors
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** AES-256-GCM key generated inside the Android Keystore; the raw key material is never exportable. */
class KeystoreCipher(private val alias: String = "xman_camera_node_api_key") : SecretCipher {
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    private fun key(): SecretKey {
        (keyStore.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build())
        return generator.generateKey()
    }

    override fun encrypt(plain: ByteArray): Pair<ByteArray, ByteArray> {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key()) }
        return cipher.iv to cipher.doFinal(plain)
    }

    override fun decrypt(iv: ByteArray, ciphertext: ByteArray): ByteArray {
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
        return cipher.doFinal(ciphertext)
    }

    override fun destroyKey() {
        if (keyStore.containsAlias(alias)) keyStore.deleteEntry(alias)
    }
}

class PrefsStore(context: Context) : KeyValueStore {
    private val prefs = context.getSharedPreferences("camera_node", Context.MODE_PRIVATE)
    override fun get(key: String) = prefs.getString(key, null)
    override fun put(values: Map<String, String>) = prefs.edit().apply { values.forEach { (k, v) -> putString(k, v) } }.commit().let { }
    override fun remove(keys: Collection<String>) = prefs.edit().apply { keys.forEach { remove(it) } }.commit().let { }
}

/** App-wide wiring; no DI framework for four screens. */
object Node {
    val io = Executors.newSingleThreadExecutor()
    fun credentials(context: Context) = CredentialStore(PrefsStore(context.applicationContext), KeystoreCipher())
    fun store(context: Context) = EvidenceStore(File(context.applicationContext.filesDir, "evidence"))
    val allowLanHttp get() = BuildConfig.DEBUG
}

object DeviceStatus {
    fun batteryPct(context: Context): Int? =
        (context.getSystemService(Context.BATTERY_SERVICE) as BatteryManager)
            .getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY).takeIf { it in 0..100 }

    /** Only the transport kind: no SSID, MAC or IP is read or sent. */
    fun networkType(context: Context): String {
        val cm = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.getNetworkCapabilities(cm.activeNetwork) ?: return "none"
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "unknown"
        }
    }
}

/** One fresh fix from the platform GPS provider (no Google Play Services). Never a cached/invented position. */
object Gps {
    fun hasPermission(context: Context) =
        ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED

    fun providerEnabled(context: Context) =
        (context.getSystemService(Context.LOCATION_SERVICE) as LocationManager).isProviderEnabled(LocationManager.GPS_PROVIDER)

    /** Calls back on the main thread with a fix, or null (no permission, GPS off, or no fix in time). */
    fun requestFix(context: Context, cancel: CancellationSignal, onResult: (GpsFix?) -> Unit) {
        val lm = context.getSystemService(Context.LOCATION_SERVICE) as LocationManager
        if (!hasPermission(context) || !lm.isProviderEnabled(LocationManager.GPS_PROVIDER)) return onResult(null)
        try {
            LocationManagerCompat.getCurrentLocation(lm, LocationManager.GPS_PROVIDER, cancel,
                ContextCompat.getMainExecutor(context)) { location: Location? ->
                onResult(location?.let {
                    GpsFix(it.latitude, it.longitude, if (it.hasAccuracy()) it.accuracy.toDouble() else null, it.time)
                })
            }
        } catch (e: SecurityException) {
            onResult(null)
        }
    }
}

/** Camera frame -> upright JPEG without EXIF, longest side <= 1600 px (bandwidth only; X-MAN re-sanitizes). */
object FrameEncoder {
    private const val MAX_SIDE = 1600

    /** [roi] (upright coordinates), if given and not the full frame, is outlined so reviewers see the monitored area. */
    fun encode(bitmap: Bitmap, rotationDegrees: Int, roi: NormRect? = null): ByteArray {
        val scale = minOf(1f, MAX_SIDE.toFloat() / maxOf(bitmap.width, bitmap.height))
        val matrix = Matrix().apply { postRotate(rotationDegrees.toFloat()); postScale(scale, scale) }
        var upright = Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
        if (roi != null && !roi.isFull) {
            if (!upright.isMutable) upright = upright.copy(Bitmap.Config.ARGB_8888, true).also { upright.recycle() }
            val w = upright.width.toFloat()
            val h = upright.height.toFloat()
            android.graphics.Canvas(upright).drawRect(roi.left * w, roi.top * h, roi.right * w, roi.bottom * h,
                android.graphics.Paint().apply { style = android.graphics.Paint.Style.STROKE; strokeWidth = maxOf(3f, w / 200); color = 0xFFFFC107.toInt() })
        }
        return ByteArrayOutputStream().use { out ->
            upright.compress(Bitmap.CompressFormat.JPEG, 85, out)  // a fresh JPEG: no EXIF is written
            if (upright !== bitmap) upright.recycle()
            out.toByteArray()
        }
    }
}
