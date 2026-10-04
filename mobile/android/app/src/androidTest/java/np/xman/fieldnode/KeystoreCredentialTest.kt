package np.xman.fieldnode

import android.content.Context
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.io.File

/** Runs on a real device: Android Keystore + SharedPreferences (the production credential path). */
@RunWith(AndroidJUnit4::class)
class KeystoreCredentialTest {
    private val context: Context = InstrumentationRegistry.getInstrumentation().targetContext
    private val alias = "xman_test_alias"
    private val key = "TestOnlyKey_9Qw3Rt7Yu1Io5Pa2Sd8Fg4Hj6Kl0Zx"

    private fun store() = CredentialStore(PrefsStore(context), KeystoreCipher(alias))

    @After fun cleanUp() = store().clear()

    @Test fun keystoreRoundTripAndNoPlaintextAtRest() {
        store().save("https://xman.example.org", "PHONE-LANDSLIDE-TEST-001", key)
        assertEquals(key, store().apiKey())  // a new instance reads it back through the Keystore
        val prefsFile = File(context.applicationInfo.dataDir, "shared_prefs/camera_node.xml")
        assertTrue(prefsFile.isFile)
        assertFalse(prefsFile.readText().contains(key))
    }

    @Test fun clearDeletesTheKeystoreKey() {
        store().save("https://xman.example.org", "PHONE-LANDSLIDE-TEST-001", key)
        store().clear()
        assertNull(store().apiKey())
        val ks = java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        assertFalse(ks.containsAlias(alias))
    }
}
