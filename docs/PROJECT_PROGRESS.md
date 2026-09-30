# NepalSathi - Project Progress

## Current Status: M02 Hazard Event Engine Complete (M01 Hardware Readiness Foundation — VERIFIED)

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

### 📋 Next Steps
- M03 — Notification System (see the M02 section at the end).
- Still open from M01: ESP32 firmware, periodic risk worker, real-time dashboard transport, device provisioning UI.

### 🐛 Known Issues
- AI offline (Ollama not installed)
- Need more demo data
- No rate limiting on IoT or hazard endpoints
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

---

## M02 — Hazard Event Engine

### Objective
One reusable hazard-event layer that every source (IoT, citizen, authority, system) feeds into.
Sources produce **evidence**; evidence creates or updates a **hazard event**; notifications are a
separate, downstream concern (M03).

```
IoT reading / citizen report / authority / system
                  ↓
   hazard_event_service (validate, dedup, lifecycle)
                  ↓
            Incident (hazard event)
                  ↓
        [M03] notification delivery
```

### Architecture decision — Incident vs HazardEvent (Option B)
The existing `Incident` model already represented "something is happening at a place, with a
severity, a status and a report count". A separate `HazardEvent` table would have created two
competing records for the same thing. **`Incident` is extended and is the single hazard-event
concept.** There is no `HazardEvent` table.

- Constants live only in `app/models/incident.py` (`HAZARD_TYPES`, `HAZARD_SOURCES`,
  `HAZARD_SEVERITY`, `HAZARD_STATUS`, `ACTIVE_STATUSES`, `VALID_STATUS_TRANSITIONS`).
- Business logic lives only in `app/services/hazard_event_service.py`.
- Legacy readers of incidents (dashboard, district page, AI summary, travel planner) moved from
  `status='active'` / `category` to `ACTIVE_STATUSES` / `event_type`.
- `app/routes/incidents.py` was removed: it was never registered and its templates never existed
  (dead code since the first commit). Citizen reporting goes through `POST /api/hazards`.

### Model / schema (`incidents`)
| Column | Notes |
|---|---|
| `event_type` | `flood` / `landslide` / `road_damage` (NOT NULL) |
| `severity` | `low` / `medium` / `high` / `critical` |
| `source` | `iot` / `citizen_report` / `authority` / `system` |
| `status` | lifecycle below, default `detected` |
| `confidence` | nullable; only set when a real model produces one (never faked) |
| `district_id`, `latitude`, `longitude`, `location` | geography; lat/lon validated and required together |
| `river_id`, `road_segment_id` | nullable FKs to existing `rivers` / `road_segments` (no duplicate location records) |
| `title`, `description` | human text |
| `source_reference` | internal (`device_<id>`, `user_<id>`); only exposed to authority/admin |
| `report_count` | pieces of evidence merged into this event |
| `detected_at`, `updated_at`, `resolved_at`, `created_at` | `updated_at` = time of latest evidence/change |
| `category` | legacy column kept in DB (nullable, no longer written) so no data is lost |

### Lifecycle
```
detected ──► investigating ──► confirmed ──► resolved
    │               │
    └──► rejected ◄─┘
```
`resolved` and `rejected` are terminal. Any other transition raises `ValueError` → HTTP 400.
Only authority/admin can transition. Sensor evidence **never** changes status by itself.
Active = `detected`, `investigating`, `confirmed`.

### Deduplication strategy
`find_active_related_event()` decides "new hazard vs existing active hazard":
1. Same type + same `river_id` (or `road_segment_id`) + active → same event, no time window
   (one active flood event per river).
2. Otherwise: same type + active + latest evidence within **24 h**, filtered by same district and/or
   a **5 km** lat/lon bounding box (longitude span scaled by cos(latitude)). Plain SQL, no PostGIS.

`report_hazard()` merges into the match via `add_evidence()`: `report_count += 1`, `updated_at`
refreshed, severity **escalated only** (never lowered automatically; lowering is an authority
decision). Otherwise it creates a new event. The API returns 201 (new) or 200 (merged).

### IoT integration
```
POST /api/iot/telemetry → SensorReading → risk_engine.assess_water_level_risk()
   → River.status (unchanged M01 logic)
   → if alert_required and risk_level >= 2 (rising/flooding):
        auto_create_flood_event_from_river(river, risk, device)
```
- `normal` / `unknown` / suspect- or bad-quality readings → **no event** (telemetry stays telemetry).
- `rising` → flood event, severity `medium`; `flooding` → severity `high`.
- Repeated rising/flooding readings update the same active event for that river.
- `risk_engine` stays the only authority on thresholds; no LLM involved.
- Event gets `source='iot'`, `confidence=None`, device coordinates, `source_reference='device_<id>'`.
- The M01 `create_river_alert()` notification call is unchanged (reworking it is M03).

### API endpoints (`/api/hazards`, all require login, JSON errors)
| Method | Endpoint | Who | Purpose |
|---|---|---|---|
| GET | `/api/hazards` | any user | list (filters: event_type, severity, source, status, district_id, limit; default active) |
| GET | `/api/hazards/<id>` | any user | one event |
| POST | `/api/hazards` | any user | report a hazard (dedup-merged); 201 new / 200 merged |
| PATCH | `/api/hazards/<id>` | authority (own district) / admin | edit severity, status, title, description, location, lat+lon |
| POST, PATCH | `/api/hazards/<id>/status` | authority (own district) / admin | lifecycle transition |
| POST | `/api/hazards/<id>/resolve` | authority (own district) / admin | confirmed → resolved (+ notes) |
| POST | `/api/hazards/<id>/reject` | authority (own district) / admin | detected/investigating → rejected (+ reason) |
| GET | `/api/hazards/statistics` | authority / admin | counts by status/type/source/severity |
| GET | `/api/hazards/district/<id>/active` | any user | active events in a district |
| GET | `/api/hazards/types/<type>` | any user | events by type |
| GET | `/api/hazards/sources/<source>` | any user | events by source |

### Authorization & security
- Unauthenticated → 401 JSON. Citizen on a management endpoint → 403.
- **Source comes from the caller's role, never from the payload**: citizen → `citizen_report`,
  authority/admin → `authority`; `iot` only via device-authenticated telemetry; `system` only from
  server code. `status` and `confidence` in a create payload are ignored.
- Authority isolation uses the M01 rule `user.authority.district_id`: no creating or managing events
  outside it (403); an authority user with no linked authority gets 403.
- Citizens report into their own district by default, always start at `detected`, and cannot
  confirm, resolve, reject or edit.
- No mass assignment: PATCH applies a fixed allow-list with per-field validation.
- Strict input types: ints for ids, finite numbers for coordinates, length-limited strings, JSON
  object bodies only; malformed JSON → 400.
- `source_reference` (identifies the reporting user/device) is hidden from citizens.
- Reads are open to all logged-in users: hazard information is public-safety data, consistent with
  the existing river/road pages.
- CSRF: the app-wide `CSRFProtect` still covers these session-authenticated POST/PATCH endpoints
  (JS sends `X-CSRFToken`); nothing was exempted. All queries go through the SQLAlchemy ORM.

### Migration
`migrations/versions/199353c81cdc_add_hazard_event_fields_to_incident_.py` (revises `9493a03322a7`)
- Adds `event_type`, `source`, `river_id`, `road_segment_id`, `title`, `source_reference`,
  `detected_at`, `resolved_at` and two FKs; makes legacy `category` nullable. **No column or table
  dropped, no rows deleted.**
- Backfills legacy rows: `event_type` from `category` (flood/landslide by name, else `road_damage`),
  `title` ← `category`, `detected_at` ← `created_at`, `source` ← `citizen_report`,
  status `active` → `detected`; out-of-vocabulary severity → `medium`, status → `resolved`.
- Verified on a scratch pre-M02 database with legacy rows: upgrade → downgrade → upgrade, then an
  ORM insert. Downgrade restores `category` / `active`.
- Note: the local dev DB (`instance/hackforge.db`) was upgraded earlier with a first draft of this
  migration that dropped `category`. It held 0 incident rows, so nothing was lost, and the model no
  longer uses `category`.

### Tests — 157 passed, 44 warnings (full suite)
Warnings are pre-existing SQLAlchemy `Query.get()` legacy warnings.
- `tests/test_hazard_event_model.py`: fields, relationships, transitions, constants
- `tests/test_hazard_event_service.py`: create/validate, dedup (river, district, geo, window),
  transitions, resolve/reject/confirm, IoT update, statistics
- `tests/test_hazard_events_api.py`: auth, filters, create/update/status/resolve/reject, statistics
- `tests/test_hazard_m02_integration.py`: telemetry normal → no event; rising → event; repeated →
  same event (`report_count`); severity escalation only; resolved event not reused; citizen
  restrictions; citizen report merge; authority isolation; admin access; source spoofing;
  malformed/invalid payloads; latitude-scaled dedup radius; travel planner and district page on the
  new lifecycle

### Known limitations
- IoT events are never auto-resolved when a river returns to normal; an authority resolves them.
- The M01 river notification is still created on every rising/flooding reading (no notification
  dedup yet); that is M03.
- Dedup uses a bounding box and fixed 24 h / 5 km constants, not true geodesic distance.
- No web UI yet for citizen hazard reporting or authority event management (API only).
- No rate limiting on `POST /api/hazards` or the IoT endpoints.
- `landslide` / `road_damage` have no automatic sensor source yet (tilt/vibration are stored as
  telemetry only).

### Next milestone
**M03 — Notification System** (not started).

### 🏷️ Status
**M02 — HAZARD EVENT ENGINE COMPLETE**
**HARDWARE NOT YET CONNECTED · NO AI VISION IMPLEMENTED**
