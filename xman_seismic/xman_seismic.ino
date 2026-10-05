// ============================================================
// X-MAN SEISMIC NODE — H03.8 (H03.7 detector + X-MAN telemetry)
// Device: ESP32-SEISMIC-001   Board: ESP32 Dev Module (ESP32-D0WD-V3)
// Sensor: MPU6050 / GY-521 at 0x68, SDA GPIO 21, SCL GPIO 22
//
// Prototype ground-motion EVIDENCE only. Not an earthquake detector, not a
// magnitude, not a probability, not a certified seismic measurement.
// X-MAN decides what (if anything) the readings mean.
//
// Credentials come only from secrets.h (gitignored). They are never printed:
// not the API key, not the Wi-Fi password, not the Authorization header,
// not the server URL (only the API path is shown).
// ============================================================

#include <WiFi.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <math.h>

#include "secrets.h"

#define FIRMWARE_VERSION "H03.8"

// ---------------- MPU6050 ----------------
#define MPU6050_ADDR 0x68
#define SDA_PIN      21
#define SCL_PIN      22
#define REG_PWR_MGMT_1   0x6B
#define REG_ACCEL_XOUT_H 0x3B
#define REG_WHO_AM_I     0x75
#define ACCEL_SCALE      16384.0f   // LSB per g at +-2 g

// ---------------- H03.7 detector (unchanged values) ----------------
#define SAMPLE_INTERVAL_MS         50
#define CALIBRATION_SAMPLES        200
#define ELEVATED_THRESHOLD_MG      15.0f   // prototype thresholds, NOT earthquake thresholds
#define ABNORMAL_THRESHOLD_MG      30.0f
#define RECOVERY_THRESHOLD_MG      12.0f
#define ELEVATED_REQUIRED_SAMPLES  5
#define ABNORMAL_REQUIRED_SAMPLES  8
#define RECOVERY_REQUIRED_SAMPLES  10
#define MAX_EVENT_DURATION_MS      30000

// ---------------- H03.8 telemetry ----------------
#define TELEMETRY_INTERVAL_MS      2000
#define WIFI_RETRY_INTERVAL_MS     30000   // > one full scan+auth+DHCP cycle; never interrupts an attempt
#define WIFI_SETUP_WAIT_MS         10000
#define HTTP_TIMEOUT_MS            3000
#define SENSOR_RECOVERY_INTERVAL_MS 2000
// X-MAN validates vibration in 0..1000 mg; larger values are clamped (and reported on serial).
#define XMAN_VIBRATION_MAX_MG      1000.0f
static const char *TELEMETRY_PATH = "/api/iot/telemetry";

// ---------------- state ----------------
enum MotionState { NORMAL, ELEVATED, ABNORMAL };
MotionState state = NORMAL;

float baselineX = 0, baselineY = 0, baselineZ = 0;
bool calibrated = false;

int abnormalSamples = 0, elevatedSamples = 0, recoverySamples = 0;
unsigned long eventStartTime = 0;
float eventPeak = 0;

bool sensorOk = false;
unsigned long lastSensorRecovery = 0;
unsigned long lastSample = 0;
unsigned long lastWifiAttempt = 0;
bool wifiWasConnected = false;

// Telemetry window: peak of the prototype metric over ~2 s of valid samples.
unsigned long windowStart = 0;
float windowPeakVibration = 0;
int windowValidSamples = 0;
float lastAx = 0, lastAy = 0, lastAz = 0, lastMag = 0, lastDeviation = 0;

// ============================================================
// MPU6050
// ============================================================

bool writeMPURegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg);
  Wire.write(value);
  return Wire.endTransmission() == 0;   // 0 = ACK: the sensor answered
}

bool readMPURegister(uint8_t reg, uint8_t &value) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU6050_ADDR, 1) != 1) return false;
  value = Wire.read();
  return true;
}

// Wake the sensor and check it answers. Prints WHO_AM_I (0x68 on a genuine MPU6050; some clones differ).
bool initMPU() {
  if (!writeMPURegister(REG_PWR_MGMT_1, 0x00)) return false;
  delay(100);
  uint8_t who = 0;
  if (!readMPURegister(REG_WHO_AM_I, who)) return false;
  Serial.print("MPU6050 WHO_AM_I: 0x");
  Serial.println(who, HEX);
  return true;
}

// Accelerometer in g. High byte then low byte, read explicitly in that order.
bool readAccelerometer(float &ax, float &ay, float &az) {
  Wire.beginTransmission(MPU6050_ADDR);
  Wire.write(REG_ACCEL_XOUT_H);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(MPU6050_ADDR, 6) != 6) return false;
  int16_t raw[3];
  for (int i = 0; i < 3; i++) {
    uint8_t hi = Wire.read();
    uint8_t lo = Wire.read();
    raw[i] = (int16_t)((hi << 8) | lo);
  }
  ax = raw[0] / ACCEL_SCALE;
  ay = raw[1] / ACCEL_SCALE;
  az = raw[2] / ACCEL_SCALE;
  return true;
}

// H03.7 baseline calibration. Returns false (no baseline) if no valid sample was read.
bool calibrate() {
  Serial.println("KEEP SENSOR COMPLETELY STILL");
  Serial.println("Calibrating...");
  delay(2000);
  float sumX = 0, sumY = 0, sumZ = 0;
  int valid = 0;
  for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
    float ax, ay, az;
    if (readAccelerometer(ax, ay, az)) {
      sumX += ax; sumY += ay; sumZ += az;
      valid++;
    }
    delay(10);
  }
  if (valid == 0) {
    Serial.println("ERROR: MPU6050 calibration failed (no valid samples). Will retry.");
    return false;
  }
  baselineX = sumX / valid;
  baselineY = sumY / valid;
  baselineZ = sumZ / valid;
  Serial.println("BASELINE READY");
  Serial.print("X: "); Serial.print(baselineX, 4);
  Serial.print(" g  Y: "); Serial.print(baselineY, 4);
  Serial.print(" g  Z: "); Serial.print(baselineZ, 4);
  Serial.print(" g  Magnitude: ");
  Serial.print(sqrt(baselineX * baselineX + baselineY * baselineY + baselineZ * baselineZ), 4);
  Serial.println(" g");
  Serial.println("Prototype thresholds: elevated >= 15 mg, abnormal >= 30 mg, recovery < 12 mg");
  return true;
}

// ============================================================
// H03.7 DETECTOR (logic unchanged; local serial output only)
// ============================================================

float calculateDeviation(float ax, float ay, float az) {
  float dx = ax - baselineX, dy = ay - baselineY, dz = az - baselineZ;
  return sqrt(dx * dx + dy * dy + dz * dz) * 1000.0f;
}

void startAbnormalEvent(float deviation) {
  state = ABNORMAL;
  eventStartTime = millis();
  eventPeak = deviation;
  recoverySamples = 0;
  Serial.println();
  Serial.println("======================================");
  Serial.println("!!! ABNORMAL GROUND MOTION STARTED !!! (prototype local state)");
  Serial.println("======================================");
  Serial.print("Trigger deviation: "); Serial.print(deviation, 2); Serial.println(" mg");
}

void endAbnormalEvent() {
  Serial.println();
  Serial.println("======================================");
  Serial.println(">>> GROUND MOTION EVENT ENDED");
  Serial.println("======================================");
  Serial.print("Peak deviation: "); Serial.print(eventPeak, 2); Serial.println(" mg");
  Serial.print("Duration: "); Serial.print(millis() - eventStartTime); Serial.println(" ms");
  state = NORMAL;
  abnormalSamples = elevatedSamples = recoverySamples = 0;
  eventPeak = 0;
  eventStartTime = 0;
}

void updateDetector(float deviation) {
  if (deviation > eventPeak) eventPeak = deviation;

  if (state == NORMAL) {
    recoverySamples = 0;
    if (deviation >= ABNORMAL_THRESHOLD_MG) { abnormalSamples++; elevatedSamples++; }
    else if (deviation >= ELEVATED_THRESHOLD_MG) { elevatedSamples++; abnormalSamples = 0; }
    else { abnormalSamples = 0; elevatedSamples = 0; }

    if (abnormalSamples >= ABNORMAL_REQUIRED_SAMPLES) {
      startAbnormalEvent(deviation);
      abnormalSamples = elevatedSamples = 0;
      return;
    }
    if (elevatedSamples >= ELEVATED_REQUIRED_SAMPLES) {
      state = ELEVATED;
      Serial.println(">> ELEVATED GROUND MOTION (prototype local state)");
      elevatedSamples = 0;
    }
    return;
  }

  if (state == ELEVATED) {
    if (deviation >= ABNORMAL_THRESHOLD_MG) { abnormalSamples++; recoverySamples = 0; }
    else if (deviation >= ELEVATED_THRESHOLD_MG) { abnormalSamples = 0; recoverySamples = 0; }
    else { abnormalSamples = 0; recoverySamples++; }

    if (abnormalSamples >= ABNORMAL_REQUIRED_SAMPLES) {
      startAbnormalEvent(deviation);
      abnormalSamples = 0;
      return;
    }
    if (recoverySamples >= RECOVERY_REQUIRED_SAMPLES) {
      Serial.println(">> MOTION RETURNED TO NORMAL");
      state = NORMAL;
      recoverySamples = 0;
    }
    return;
  }

  // ABNORMAL
  if (millis() - eventStartTime >= MAX_EVENT_DURATION_MS) {
    Serial.println(">> EVENT TIMEOUT: ending prototype event safely.");
    endAbnormalEvent();
    return;
  }
  if (deviation >= RECOVERY_THRESHOLD_MG) recoverySamples = 0;
  else recoverySamples++;
  if (recoverySamples >= RECOVERY_REQUIRED_SAMPLES) endAbnormalEvent();
}

const char *stateName() {
  return state == NORMAL ? "NORMAL" : (state == ELEVATED ? "ELEVATED" : "ABNORMAL");
}

// ============================================================
// WI-FI (non-blocking after setup: the sensor keeps being read)
// ============================================================

const char *wifiStatusName(wl_status_t s) {
  switch (s) {
    case WL_IDLE_STATUS:     return "IDLE";
    case WL_NO_SSID_AVAIL:   return "NO_SSID_AVAIL";
    case WL_SCAN_COMPLETED:  return "SCAN_COMPLETED";
    case WL_CONNECTED:       return "CONNECTED";
    case WL_CONNECT_FAILED:  return "CONNECT_FAILED";
    case WL_CONNECTION_LOST: return "CONNECTION_LOST";
    case WL_DISCONNECTED:    return "DISCONNECTED";
    case WL_STOPPED:         return "STOPPED";
    default:                 return "UNKNOWN";
  }
}

void printWifiStatus() {
  wl_status_t s = WiFi.status();
  Serial.print("Wi-Fi status: ");
  Serial.print((int)s);
  Serial.print(" ");
  Serial.print(wifiStatusName(s));
  // Core 3.x: IDLE after begin() means associated with the AP but no DHCP lease yet.
  Serial.println(s == WL_IDLE_STATUS ? " (associated, waiting for DHCP IP)" : "");
}

// Runs on the Wi-Fi event task. Prints the driver's reason for a failed/dropped association
// (AUTH_FAIL, NO_AP_FOUND, 4WAY_HANDSHAKE_TIMEOUT, ...). A repeat of the same reason is not
// printed again while the core keeps retrying, so the log does not flood.
volatile uint8_t lastDisconnectReason = 0;
void onWifiDisconnected(WiFiEvent_t event, WiFiEventInfo_t info) {
  uint8_t reason = info.wifi_sta_disconnected.reason;
  if (reason == lastDisconnectReason) return;
  lastDisconnectReason = reason;
  Serial.print("Wi-Fi disconnect reason: ");
  Serial.print(reason);
  Serial.print(" ");
  Serial.println(WiFi.disconnectReasonName((wifi_err_reason_t)reason));
}

// Starts (or nudges) an association. Deliberately NO WiFi.disconnect() first: on core 3.x it
// aborts any association in progress and its ASSOC_LEAVE (reason 8) tells the core's
// auto-reconnect to stop (STA.cpp _onStaArduinoEvent). If the driver is already mid-attempt,
// begin() is simply rejected and the active attempt continues untouched.
void startWifi() {
  lastWifiAttempt = millis();
  Serial.print("Wi-Fi SSID: ");
  Serial.println(XMAN_WIFI_SSID);   // SSID only; password never printed
  wl_status_t r = WiFi.begin(XMAN_WIFI_SSID, XMAN_WIFI_PASSWORD);
  Serial.println(r == WL_CONNECT_FAILED ? "Wi-Fi begin: not started (driver busy with an attempt or rejected config)"
                                        : "Wi-Fi begin: attempt started");
}

void printNetworkInfo() {
  Serial.println("Wi-Fi connected.");
  Serial.print("IP address: "); Serial.println(WiFi.localIP());
  Serial.print("Gateway: ");    Serial.println(WiFi.gatewayIP());
  Serial.print("Subnet: ");     Serial.println(WiFi.subnetMask());
  Serial.print("DNS: ");        Serial.println(WiFi.dnsIP());
  Serial.print("RSSI: ");       Serial.print(WiFi.RSSI()); Serial.println(" dBm");
}

// Reconnect policy: the core's auto-reconnect handles most drops/failures on its own. The firmware
// only nudges with begin() if still offline after WIFI_RETRY_INTERVAL_MS (covers reasons the core
// does not retry, e.g. AUTH_FAIL after the first attempt). Never blocks: the sensor keeps running.
void maintainWifi() {
  bool connected = WiFi.status() == WL_CONNECTED;
  if (connected && !wifiWasConnected) {
    printNetworkInfo();
    lastDisconnectReason = 0;   // next drop's reason is printed even if it repeats an old one
  } else if (!connected && wifiWasConnected) {
    Serial.println("Wi-Fi disconnected. Reconnecting in the background; sensor reading continues.");
    lastWifiAttempt = millis();   // give the core's auto-reconnect a full interval first
  }
  wifiWasConnected = connected;
  if (!connected && millis() - lastWifiAttempt >= WIFI_RETRY_INTERVAL_MS) {
    printWifiStatus();
    Serial.println("Wi-Fi unavailable: retrying...");
    startWifi();
  }
}

// ============================================================
// X-MAN TELEMETRY: only readings[] (identity/district come from the server registration)
// ============================================================

bool sendTelemetry(float vibrationMg) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("X-MAN telemetry: NOT SENT (Wi-Fi unavailable)");
    return false;
  }

  HTTPClient http;
  http.setConnectTimeout(HTTP_TIMEOUT_MS);
  http.setTimeout(HTTP_TIMEOUT_MS);
  if (!http.begin(String(XMAN_SERVER_URL) + TELEMETRY_PATH)) {
    Serial.println("X-MAN telemetry: FAILED (HTTP client could not start)");
    return false;
  }

  // Built in RAM only; never printed or logged.
  String authorization = String("Bearer ") + XMAN_DEVICE_ID + ":" + XMAN_API_KEY;
  http.addHeader("Authorization", authorization);
  http.addHeader("Content-Type", "application/json");

  String payload = String("{\"readings\":[{\"sensor_type\":\"vibration\",\"value\":") +
                   String(vibrationMg, 2) + ",\"unit\":\"mg\"}]}";

  Serial.print("Sending telemetry... POST ");
  Serial.println(TELEMETRY_PATH);
  unsigned long postStart = millis();
  int code = http.POST(payload);
  unsigned long postMs = millis() - postStart;
  http.end();
  authorization = "";

  if (code <= 0) {
    // HTTPClient reports every failed TCP connect as -1 "connection refused"; the elapsed time
    // separates "nothing answered" (LAN: wrong IP, host down, filtered) from "port answered with RST".
    Serial.print("X-MAN telemetry: FAILED (");
    if (code == HTTPC_ERROR_CONNECTION_REFUSED && postMs >= HTTP_TIMEOUT_MS - 100) {
      Serial.print("TCP connect timeout: no answer from server host; check XMAN_SERVER_URL IP / PC on LAN / firewall");
    } else if (code == HTTPC_ERROR_CONNECTION_REFUSED) {
      Serial.print("TCP connection refused: host reached but nothing accepting on that port; is Flask running on 0.0.0.0?");
    } else if (code == HTTPC_ERROR_READ_TIMEOUT) {
      Serial.print("connected, but server sent no HTTP response in time");
    } else {
      Serial.print("connection error: ");
      Serial.print(HTTPClient::errorToString(code));
    }
    Serial.print(", ");
    Serial.print(postMs);
    Serial.println(" ms)");
    return false;
  }
  Serial.print("HTTP status: ");
  Serial.println(code);
  if (code >= 200 && code < 300) {
    Serial.println("X-MAN telemetry: SUCCESS");
    return true;
  }
  Serial.print("X-MAN telemetry: FAILED (HTTP ");
  Serial.print(code);
  if (code == 401 || code == 403) Serial.print(": authentication rejected; check XMAN_DEVICE_ID / XMAN_API_KEY registration");
  else if (code == 404)           Serial.print(": endpoint not found; check XMAN_SERVER_URL has no extra path");
  else if (code == 400)           Serial.print(": payload rejected by validation");
  else if (code >= 500)           Serial.print(": server error; see Flask log");
  Serial.println(")");
  return false;
}

// ============================================================
// SETUP / LOOP
// ============================================================

void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println();
  Serial.println("================================");
  Serial.println("X-MAN SEISMIC NODE");
  Serial.println("================================");
  Serial.print("Device ID: ");
  Serial.println(XMAN_DEVICE_ID);   // not a secret: the registered device name
  Serial.print("Firmware: ");
  Serial.println(FIRMWARE_VERSION);
  Serial.println("Prototype ground-motion evidence only (not an earthquake detector).");

  Wire.begin(SDA_PIN, SCL_PIN);
  delay(100);
  sensorOk = initMPU();
  if (sensorOk) {
    Serial.println("MPU6050 initialized.");
    calibrated = calibrate();
  } else {
    Serial.println("ERROR: MPU6050 not responding at 0x68. Will keep retrying; no values will be sent.");
  }

  Serial.println("Connecting to Wi-Fi...");
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.onEvent(onWifiDisconnected, ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
  startWifi();
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_SETUP_WAIT_MS) delay(250);
  maintainWifi();
  if (WiFi.status() != WL_CONNECTED) {
    printWifiStatus();
    Serial.println("Wi-Fi not connected yet: continuing; will retry.");
  }

  windowStart = millis();
}

void loop() {
  maintainWifi();

  // Sensor recovery: never send values that weren't measured.
  if (!sensorOk || !calibrated) {
    if (millis() - lastSensorRecovery >= SENSOR_RECOVERY_INTERVAL_MS) {
      lastSensorRecovery = millis();
      Serial.println("Sensor recovery attempt...");
      sensorOk = initMPU();
      if (sensorOk && !calibrated) calibrated = calibrate();
      if (!sensorOk) Serial.println("ERROR: MPU6050 still not responding.");
    }
  }

  if (sensorOk && calibrated && millis() - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = millis();
    float ax, ay, az;
    if (readAccelerometer(ax, ay, az)) {
      float magnitude = sqrt(ax * ax + ay * ay + az * az);
      // H03.8 prototype metric (spec): deviation of |a| from 1 g, in mg. Evidence only.
      float vibrationMg = fabs(magnitude - 1.0f) * 1000.0f;
      float deviation = calculateDeviation(ax, ay, az);   // H03.7 baseline metric for the local detector
      updateDetector(deviation);

      if (vibrationMg > windowPeakVibration) windowPeakVibration = vibrationMg;
      windowValidSamples++;
      lastAx = ax; lastAy = ay; lastAz = az; lastMag = magnitude; lastDeviation = deviation;
    } else {
      Serial.println("ERROR: MPU6050 read failed.");
      sensorOk = false;   // next loop: recovery attempt (re-wake)
    }
  }

  if (millis() - windowStart >= TELEMETRY_INTERVAL_MS) {
    windowStart = millis();
    if (windowValidSamples == 0) {
      Serial.println("X-MAN telemetry: NOT SENT (no valid sensor samples in this window)");
    } else {
      Serial.print("ACCEL X: "); Serial.print(lastAx, 3);
      Serial.print(" Y: "); Serial.print(lastAy, 3);
      Serial.print(" Z: "); Serial.print(lastAz, 3);
      Serial.print(" | MAG: "); Serial.print(lastMag, 3);
      Serial.print(" g | VIBRATION (2 s peak): "); Serial.print(windowPeakVibration, 2);
      Serial.print(" mg | DEVIATION: "); Serial.print(lastDeviation, 2);
      Serial.print(" mg | STATE: "); Serial.println(stateName());

      float value = windowPeakVibration;
      if (value > XMAN_VIBRATION_MAX_MG) {
        Serial.println("Note: vibration above 1000 mg clamped to the X-MAN validation limit.");
        value = XMAN_VIBRATION_MAX_MG;
      }
      sendTelemetry(value);
    }
    windowPeakVibration = 0;
    windowValidSamples = 0;
  }
}
