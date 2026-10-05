# X-MAN Seismic Node — ESP32-SEISMIC-001 (firmware H03.8, frozen)

Prototype **abnormal-ground-motion** node: an MPU6050 on an ESP32 sends a vibration metric to X-MAN.
It is **not** a certified earthquake early-warning instrument, does not estimate magnitude, does not
predict earthquakes and produces no probability. X-MAN decides what, if anything, the readings mean.

## Hardware

| Item | Value |
|---|---|
| Board | ESP32 (chip ESP32-D0WD-V3) — Arduino board setting **ESP32 Dev Module** (`esp32:esp32:esp32`), **not** ESP32-C3 |
| Sensor | GY-521 / MPU6050, I2C address `0x68` |
| Serial | 115200 baud (development PC: COM9 via USB-serial) |

| GY-521 pin | ESP32 pin |
|---|---|
| VCC | 3V3 |
| GND | GND |
| SDA | GPIO 21 |
| SCL | GPIO 22 |

Mount the sensor rigidly and keep it still during the ~4 s calibration after every reset.

## Firmware (`xman_seismic.ino`, H03.8)

- MPU6050 wake (`0x6B`) and presence check, accelerometer at ±2 g (16384 LSB/g), sampled every 50 ms.
- **H03.7 local detector (unchanged):** 200-sample baseline calibration; deviation from baseline in mg;
  NORMAL → ELEVATED (5 samples ≥ 15 mg) → ABNORMAL (8 samples ≥ 30 mg); recovery after 10 samples
  < 12 mg; 30 s event timeout. Serial output only — it does not create X-MAN hazards.
- **Telemetry:** every ~2 s, the peak of `|‖a‖ − 1 g| × 1000` (mg) over the window, clamped to X-MAN's
  0–1000 mg validation range. Not sent if the window had no valid sensor sample (no fake values).
- Wi-Fi reconnects in the background; sensor reading continues while offline. MPU6050 failures trigger
  re-wake/recalibration attempts.

## X-MAN integration

- Device ID `ESP32-SEISMIC-001`, registered in X-MAN as kind *Sensor*, district **Sindhuli**, no river.
  District, river and identity are server-owned: the payload never contains them.
- `POST /api/iot/telemetry`, `Authorization: Bearer <device_id>:<api_key>`, body:
  `{"readings":[{"sensor_type":"vibration","value":<mg>,"unit":"mg"}]}` → `201` when stored.
- X-MAN creates no earthquake incident from these readings unless `MOTION_VIBRATION_THRESHOLD_MG` /
  `MOTION_TILT_CHANGE_THRESHOLD_DEG` are configured on the server (they are not).

## Local configuration (`secrets.h`, gitignored — never commit it)

Create `secrets.h` next to the sketch with these macros (values are local only):

```
XMAN_DEVICE_ID      "ESP32-SEISMIC-001"
XMAN_API_KEY        one-time key from X-MAN Super Admin (rotate there if exposed)
XMAN_WIFI_SSID      2.4 GHz network name
XMAN_WIFI_PASSWORD  network password
XMAN_SERVER_URL     "http://<X-MAN PC LAN IP>:5000"  (no trailing slash; not 127.0.0.1)
```

The firmware never prints the key, the Wi-Fi password, the Authorization header or the server URL.

## Build / upload

```
arduino-cli compile --fqbn esp32:esp32:esp32 xman_seismic
arduino-cli upload  --fqbn esp32:esp32:esp32 -p COM9 xman_seismic
```
Close the Arduino IDE Serial Monitor first (it locks the port). Monitoring with arduino-cli:
`arduino-cli monitor -p COM9 -c baudrate=115200 -c dtr=off -c rts=off` (with DTR/RTS on, the
USB-serial adapter can hold the ESP32 in reset).

## Known limitations

- Plain HTTP on the LAN (prototype): the key crosses the network unencrypted; flash is not encrypted.
- `XMAN_SERVER_URL` must be updated if the X-MAN PC's DHCP address changes (a router reservation helps).
- The telemetry metric includes the sensor's static offset (~60–70 mg at rest on this unit); the H03.7
  baseline deviation (~1–10 mg at rest) is the cleaner signal for a future milestone.
- Thresholds are prototype values, not seismological ones.
