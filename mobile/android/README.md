# X-MAN Field Node (Android)

Manual test-evidence uploader for one registered X-MAN **camera node** (M-LIVE-03).
It does **not** detect landslides: a person captures 1–3 frames and presses **Send Test Evidence**.
Details, security model and test results: `docs/PROJECT_PROGRESS.md` → M-LIVE-03.

## Build
Requires JDK 17 and the Android SDK (platform 37). Create `local.properties` (git-ignored):
```
sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk
```
Then:
```
./gradlew assembleDebug testDebugUnitTest lintDebug
```
On-device Keystore tests (phone connected): `./gradlew assembleDebugAndroidTest`, then
`adb install` both APKs and run `adb shell am instrument -w np.xman.fieldnode.test/androidx.test.runner.AndroidJUnitRunner`.

## Use
1. X-MAN Super Admin → IoT devices → Register device → device kind **Camera node**. Copy the one-time key.
2. App → Provisioning: server URL, device ID, API key → Save. Production URLs must be HTTPS; debug
   builds also accept `http://` to localhost or a private LAN address (e.g. `adb reverse tcp:5000 tcp:5000`
   + `http://localhost:5000`).
3. Capture test evidence → Get GPS fix (optional) → Send Test Evidence.

Never commit API keys, captured photos or GPS coordinates.
