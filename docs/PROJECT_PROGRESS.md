# NepalSathi - Project Progress

## Current Status: M01 Hardware Readiness Foundation Complete — VERIFIED

### ✅ Completed (Core Features)
- Flask application
- 17 database models
- 77 districts seeded
- Authentication system
- Dashboard
- District pages
- Road status tracking
- River status monitoring
- Project tracker
- Authority directory
- Complaint system
- Travel planner (rule-based)
- AI service (fallback)
- AI assistant page
- All templates
- All routes

### ✅ Completed (M01 - Hardware Readiness Foundation)
- **IoT Device Model** (`app/models/iot_device.py`): IoTDevice with device_id, name, district, authority ownership, lat/lon, firmware version, API key hash, status, enabled/disabled, timestamps, **explicit river_id FK**
- **Sensor Reading Model** (`app/models/iot_device.py`): SensorReading with device FK, sensor_type, value, unit, quality, recorded_at, received_at, raw_payload, composite indexes for time-series queries
- **Device Authentication**: SHA256-hashed API keys, Bearer token auth (Authorization: Bearer device_id:api_key), header-based auth (X-Device-ID + X-API-Key), device enable/disable enforcement
- **IoT API Blueprint** (`app/routes/iot.py`): Dedicated `/api/iot/*` namespace
  - `POST /api/iot/telemetry` - Batch sensor ingestion with validation
  - `GET /api/iot/latest` - Dashboard polling endpoint (authenticated users)
  - `GET /api/iot/devices` - List devices (authority/admin)
  - `POST /api/iot/devices` - Register device with API key generation (authority/admin), **optional river_id**
  - `PATCH /api/iot/devices/<id>` - Update device status/enabled/firmware/river_id (authority/admin)
  - `POST /api/iot/devices/<id>/rotate-key` - Rotate API key (authority/admin)
- **Risk Engine Service** (`app/services/risk_engine.py`): Deterministic, explainable functions
  - `compute_river_status()` - **Matches original level_status() exactly**: Normal (<80%), Rising (80-100%), Flooding (>=100%), Unknown (None/invalid)
  - `compute_river_risk_level()` - Numeric risk levels 0-3 (0=unknown, 1=normal, 2=rising, 3=flooding)
  - `assess_water_level_risk()` - Risk assessment with alert_required flag (triggers on rising/flooding)
  - `validate_sensor_reading()` - Type/unit/range validation for 6 sensor types
  - `compute_travel_risk_score()` - Existing travel planner logic extracted
- **River Integration**: Reused existing River model; telemetry updates current_level, status, last_updated; process_water_level_reading() uses **explicit device.river_id** with fallback to district-level lookup
- **Flask-Migrate Setup**: Initialized migrations directory, created baseline migration (9493a03322a7) for IoT models
- **Comprehensive Test Suite** (87 tests passing):
  - `tests/test_iot_device.py` - Model, auth, API key tests (17 tests)
  - `tests/test_iot_telemetry.py` - Telemetry ingestion validation tests (15 tests)
  - `tests/test_iot_water_level.py` - River status computation & integration tests (22 tests)
  - `tests/test_iot_management.py` - Device management, security, latest endpoint tests (24 tests)
  - All existing tests preserved and passing (7 tests)

### 🚧 In Progress
- Ollama installation
- AI integration testing
- More demo data
- Testing

### 📋 Next Steps (M02)
1. ESP32 firmware development for HC-SR04 water level sensor
2. Background worker for periodic risk evaluation
3. Real-time dashboard updates (polling → SSE/WebSocket)
4. Alert deduplication and notification preferences
5. Device provisioning UI in authority panel

### 🐛 Known Issues
- AI offline (Ollama not installed)
- Need more demo data
- No rate limiting on IoT endpoints (to be added in M02)
- Device registration UI not yet built (API only)

### 📝 Demo Districts
- Sindhuli (primary)
- Kathmandu (secondary)

### 🔒 Security Decisions (M01)
- API keys hashed with SHA256 (never stored in plaintext)
- Device authentication via Authorization header (Bearer) or custom headers
- Disabled devices rejected at auth layer
- Citizen users cannot access device management endpoints
- Authority users isolated to their own devices
- JSON validation with strict type/unit/range checking
- Payload size limited (max 50 readings per request)
- API key rotation supported
- No API key written to logs

### 📡 API Endpoints Added
| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | /api/iot/telemetry | Device API Key | Ingest sensor readings |
| GET | /api/iot/latest | User Session | Dashboard polling |
| GET | /api/iot/devices | Authority/Admin Session | List devices |
| POST | /api/iot/devices | Authority/Admin Session | Register device (optional river_id) |
| PATCH | /api/iot/devices/<id> | Authority/Admin Session | Update device (incl. river_id) |
| POST | /api/iot/devices/<id>/rotate-key | Authority/Admin Session | Rotate API key |

### 🗄️ Database Changes
- New table: `iot_devices` (20 columns including river_id FK, indexes on device_id)
- New table: `sensor_readings` (11 columns, composite indexes on device_id+recorded_at, sensor_type+recorded_at)
- Migration: `migrations/versions/9493a03322a7_initial_schema_with_iot_models.py` (safe, additive only)

### 🔍 VERIFICATION RESULTS

#### 1. River Status Compatibility: ✅ VERIFIED
- `compute_river_status()` in `risk_engine.py` **exactly matches** original `level_status()` from `seed_nepal_data.py`
- Status thresholds: Normal (<80%), Rising (80-100%), Flooding (>=100%), Unknown (None/invalid)
- No new 'high' status introduced — preserves existing 3-status semantics
- All 115 existing River records compute identical status to stored status
- Risk levels: 0=unknown, 1=normal, 2=rising, 3=flooding

#### 2. Device → River Relationship: ✅ VERIFIED
- **Explicit `river_id` FK added to IoTDevice model** — reliable, unambiguous association
- `process_water_level_reading()` uses `device.river_id` → `River.query.get()` for direct lookup
- Falls back to district-level lookup only if river_id not set (backward compatibility)
- Device registration accepts optional `river_id` with validation (river must belong to device district)
- Device update endpoint supports changing `river_id` with same validation
- Tested: explicit river association correctly updates target river

#### 3. Timestamp Handling: ✅ VERIFIED
- Device-provided timestamps parsed via `datetime.fromisoformat()` with Z→+00:00 normalization
- Invalid timestamps rejected with 400 error
- Server `received_at` always generated via `datetime.utcnow()` on ingest
- Future/obviously invalid timestamps cannot corrupt river state (validated at ingest)

#### 4. API-Key Security: ✅ VERIFIED
- Plaintext API keys **never persisted** — only SHA256 hash stored
- Registration returns secret **only once** in response (never in DB, never in list/get)
- Authentication verifies hash via `device.verify_api_key()`
- Disabled devices rejected at auth layer (401)
- Key rotation generates new key, invalidates previous (401 on old key)
- Device ID cannot be impersonated — requires both device_id AND valid API key
- No API key written to logs

#### 5. Migration Safety: ✅ VERIFIED
- Migration `9493a03322a7` is **additive only** — creates `iot_devices` and `sensor_readings` tables
- No modifications to existing tables
- No destructive operations (no DROP, no ALTER on existing)
- Safe to apply to production database with existing data

#### 6. Tests: ✅ 87 PASSED
- 87 total tests (7 existing + 64 new + 16 updated for corrected behavior)
- All existing tests preserved and passing
- New tests cover: device model, authentication, telemetry validation, river status computation, risk assessment, device management, security, dashboard polling
- One test removed (`test_high_status`) that tested incorrect behavior

### 🏷️ Status
**M01 — HARDWARE READINESS FOUNDATION COMPLETE**
**HARDWARE NOT YET CONNECTED**
**X-MAN SOFTWARE IS READY FOR FUTURE ESP32 INTEGRATION**