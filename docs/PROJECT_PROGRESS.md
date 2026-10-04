# NepalSathi - Project Progress

## Current Status: M11 Full Software Integration Testing Complete (M10 Security/Reliability Hardening, M09 Authority Response, M08 Risk Engine, M07 Monitoring Dashboard, M06 Vision AI, M05.1 Security Hardening, M05 Mobile Camera Citizen Reporting, M04 Affected Areas, M03 Notifications, M02 Hazard Events, M01 Hardware Readiness)

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
- M06 — Road Damage + Landslide Vision AI (see the M05 section at the end).
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

---

## M03 — Notification System

### 1. Status
**Complete.** In-app notifications only. No SMS, email, push, or external providers.

### 2. Architecture
```
Route (/api/hazards) or IoT (/api/iot/telemetry)
            ↓
  hazard_event_service   ← the only code that changes hazard state
            ↓  state change: detected / severity up / confirmed / resolved
  notification_service   ← the only code that creates notifications
            ↓
  Notification rows (one per recipient)
            ↓
  /api/notifications  +  /notifications page  +  sidebar unread badge
```
No route, template, model method or IoT handler builds notifications. Every hazard status change
goes through `hazard_event_service._apply_transition()`, so a notification can't be bypassed by
calling a different endpoint. Authority PATCH edits now go through `update_event()`.

### 3. Notification model decision
The existing `Notification` model is **reused and extended** (no new table):
- added `incident_id` (nullable FK → `incidents`, indexed): the hazard event it is about
- added `severity` (nullable, M02 `HAZARD_SEVERITY`): severity when sent
- added index `(user_id, is_read)` for unread counts
- read state stays the existing `is_read` boolean
- `to_dict()` returns id, type, title, message, link, severity, is_read, created_at and
  `hazard: {id, event_type, status}`. No reporter/device identifiers.

### 4. Notification service (`app/services/notification_service.py`)
`create_notification`, `hazard_recipients`, `notify_hazard` (+ `notify_hazard_detected`,
`notify_hazard_escalated`, `notify_hazard_confirmed`, `notify_hazard_resolved`),
`get_user_notifications`, `unread_count`, `mark_as_read`, `mark_all_as_read`.
It adds to the session without committing; the hazard service owns the transaction, so an event
change and its notifications commit together.

### 5. Notification types
`hazard_detected`, `hazard_escalated`, `hazard_confirmed`, `hazard_resolved`, `system`.
The legacy values `road_alert`, `river_alert`, `project_update` and `complaint_response` stay valid
so existing rows keep displaying. Severity reuses M02 `low / medium / high / critical`.

| Hazard change | Notification |
|---|---|
| event created | `hazard_detected` |
| severity goes up (evidence or authority edit) | `hazard_escalated` |
| severity unchanged or lowered | none |
| → `confirmed` | `hazard_confirmed` |
| → `resolved` | `hazard_resolved` |
| → `investigating` / `rejected` | none |

### 6. Targeting (`hazard_recipients`)
- Hazard with a district → users whose home `district_id` is that district (citizens and
  authorities), **plus** authority users whose `Authority.district_id` is that district (the
  responsible authority, even with no home district set), **plus** all admins.
- Hazard with no district → admins only.
- Never broadcast to everyone. Affected-area / radius targeting is M04.

### 7. RBAC
- Citizen / authority / admin: can only list, count, and mark-read **their own** notifications.
- Nobody can create a notification over HTTP (`POST /api/notifications` → 405). Only the hazard
  service creates them.
- Authorities see notifications for their district because targeting sends them there.
  Hazard-event authorization (M02) is unchanged.
- Admins receive every hazard notification (system-wide recipient). They cannot read other users'
  notifications.
- No new roles.

### 8. Flood / IoT integration
The M01 `create_river_alert()` (one notification per user per rising/flooding **reading**) was
removed. Threshold semantics are unchanged (<80% normal, 80–100% rising, ≥100% flooding).

| Reading | Hazard | Notification |
|---|---|---|
| normal | none | none |
| first rising | flood event created (`medium`) | `hazard_detected` once |
| repeated rising | same event, `report_count+1` | none |
| flooding | same event, severity → `high` | `hazard_escalated` once |
| repeated flooding | same event | none |
| back to rising | severity not lowered | none |

Legacy `river_alert` rows already in the DB are kept and still shown.

### 9. Earthquake support
`earthquake` is now a first-class `HAZARD_TYPES` value (`flood, earthquake, landslide, road_damage`):
it passes validation in the service and API, and gets dedup, lifecycle, statistics and
notifications like any other type. It is labelled
**"Earthquake / abnormal ground motion"**, because a future MPU6050 prototype detects abnormal
ground motion and is not a certified early-warning instrument.
**Not implemented:** MPU6050/ESP32 firmware, wiring, calibration, thresholds, magnitude, prediction,
external APIs. Tilt/vibration telemetry is still stored only. The ready path for later is
`MPU6050 → ESP32 → /api/iot/telemetry → (future risk rule) → create/report_hazard('earthquake') →
notifications`. Tests create earthquake events directly; no sensor data is faked.

### 10. Deduplication
- A notification only follows a real state change (see table above).
- Safety net in `notify_hazard`: a (hazard, type) pair is sent once; escalations once per severity
  level. Repeated calls, or an authority lowering then re-raising severity, send nothing new.
- Cross-event dedup / affected areas: M04.

### 11. API endpoints
| Method | Endpoint | Auth | Result |
|---|---|---|---|
| GET | `/api/notifications?unread=1&limit=N` | login | own notifications + `unread_count` |
| GET | `/api/notifications/unread-count` | login | `{unread_count}` |
| POST | `/api/notifications/<id>/read` | login | 200 own; 404 missing **or another user's**; 400 non-integer id |
| POST | `/api/notifications/read-all` | login | `{updated, unread_count: 0}`, own only |

Unauthenticated → 401 JSON. Errors are JSON `{error}`.

### 12. Frontend notification center
- `GET /notifications` (`pages/notifications.html`): Jinja + a small inline vanilla-JS block, no
  build step. It shows severity badge, hazard type, UTC timestamp, title, message, a "View" link to
  the relevant river/district page, per-item "Mark as read", and "Mark all as read". Fetch calls
  send `X-CSRFToken` from the existing meta tag.
- A "Notifications" link with an unread count badge in the citizen sidebar and in the six authority
  page navs (count injected by a context processor).
- Nepali strings added to `page_strings.py` (UI labels, `earthquake`, `road_damage`).

### 13. Migration
`migrations/versions/a3f1c9d2e8b4_m03_link_notifications_to_hazard_events.py` (revises
`199353c81cdc`). **Additive only:** two nullable columns, one FK, two indexes. Nothing is dropped
and no rows are changed.
Verified on a scratch DB with legacy `river_alert` / `complaint_response` rows:
upgrade → downgrade → upgrade, then an ORM earthquake event that produced a linked notification.
Legacy rows survived every step. The local dev DB (`instance/hackforge.db`) was backed up and then
upgraded to `a3f1c9d2e8b4`.

### 14. Security review
- Authentication: every notification endpoint → 401 JSON without login; page → login redirect.
- Ownership / no IDOR: every query is filtered by `current_user.id` in the service. Another user's
  id returns the same 404 as a missing id.
- RBAC: no HTTP create path; authority district boundaries for hazard management unchanged (M02).
- Privacy: messages are built only from public fields (type, district, title, river/road name,
  severity). They never include `description` (free text, may identify the reporter),
  `source_reference`, user ids, device ids, or API keys.
- CSRF: `CSRFProtect` covers the POST endpoints (tested: 400 without a token when enabled). Nothing
  exempted.
- Input validation: integer id check (ASCII digits only), `limit` clamped 1–200, type/severity
  validated.
- ORM-only DB access. No logging of notification contents or credentials.

### 15. Tests
`tests/test_notifications_m03.py` (28 tests): model/relationship/defaults, validation, targeting
(district, responsible authority, admin, no-district), lifecycle, reject/investigating silent,
escalation only on increase, authority lowering silent + no repeat, dedup, invalid transition
sends nothing, privacy, earthquake detected + escalated (service and API), IoT flood sequence,
API auth/ownership/IDOR/malformed/nonexistent/read/read-all/unread-count, no create endpoint,
CSRF, page render + badge + Nepali + empty state.
Updated: `test_hazard_event_model.py` (hazard types list),
`test_hazard_m02_integration.py` (used `earthquake` as its invalid-type example → `volcano`).

**Full suite: `python -m pytest tests/ -q` → 185 passed, 51 warnings.**
All warnings are pre-existing SQLAlchemy `Query.get()` legacy warnings. The count rose from 44
because new telemetry tests exercise the existing `iot.py` `River.query.get` line more often.

### 16. Known limitations
- Notification title/message text is stored in English. Badges and UI labels are translated, the
  body text is not.
- `rejected` sends no notification, so citizens told "detected" are not told it was a false alarm
  unless an authority resolves it instead.
- IoT events are still not auto-resolved when a river returns to normal (M02 limitation).
- Targeting is district-level only. A hazard near a district border doesn't reach the neighbouring
  district (M04).
- The unread badge updates on page load and on actions in the notification page. There is no live
  polling or push.
- No retention/cleanup of old notifications; no per-user notification preferences.
- One notification row per recipient: fine for district scale, but a very large district would
  benefit from batching.

### 17. Next milestone
**M04 — Alert Deduplication + Affected Areas** (not started).

### 18. Files
- Created: `app/services/notification_service.py`, `app/routes/notifications.py`,
  `app/templates/pages/notifications.html`,
  `migrations/versions/a3f1c9d2e8b4_m03_link_notifications_to_hazard_events.py`,
  `tests/test_notifications_m03.py`
- Modified: `app/models/notification.py`, `app/models/incident.py`,
  `app/services/hazard_event_service.py`, `app/routes/hazard_events.py`, `app/routes/iot.py`,
  `app/__init__.py`, `app/templates/base.html`, `app/templates/components/navbar.html`,
  `app/templates/authority/{dashboard,complaints,complaint_detail,projects,roads,rivers}.html`,
  `app/services/page_strings.py`, `tests/test_hazard_event_model.py`,
  `tests/test_hazard_m02_integration.py`, `docs/PROJECT_PROGRESS.md`
- Deleted: none (the `create_river_alert()` function was removed from `app/routes/iot.py`)

### 19. Git commit
```
feat(m03): add centralized hazard notification system
```

### 🏷️ Status
**M03 — NOTIFICATION SYSTEM COMPLETE**
**HARDWARE NOT YET CONNECTED · NO MPU6050/ESP32 FIRMWARE · NO AI VISION**

---

## M04 — Alert Deduplication + Affected Areas

### 1. Status
**Complete.** Scope: district-level affected areas and reliable per-user alert deduplication.
This is not GPS-radius or polygon targeting.

### 2. Architecture
```
Evidence (IoT / citizen / authority)
      ↓  M02: same hazard or new hazard?  (find_active_related_event — unchanged)
Incident  ── primary district (incidents.district_id)
      │   └─ additional districts (incident_affected_districts)
      ↓  state change (detected / severity up / confirmed / resolved / area added)
notification_service
      ↓  recipients = users of every affected district + responsible authorities + admins
      ↓  M04: has THIS user already had THIS alert?  (dedup_key, DB-unique per user)
Notification rows
```
There is still one hazard record (`Incident`) and one notification record (`Notification`). The
only new table is `incident_affected_districts`.

### 3. Affected-area model
`IncidentAffectedDistrict` (`incident_affected_districts`): `id`, `incident_id` (FK), `district_id`
(FK, indexed), `created_at`, with **unique `(incident_id, district_id)`**. District names are never
copied; they come from the `District` FK.
`Incident.affected_districts` / `affected_district_ids` = primary first, then additional.
`Incident.to_dict()` now includes `affected_districts: [{id, name}]`.

### 4. Primary vs additional districts — decision: Option B (implicit primary)
`Incident.district_id` **is** the primary affected district and is never stored as a row. Only
additional districts are stored. This gives one source of truth, no backfill of existing
incidents, and no way for the primary to exist twice. Adding the primary returns 409; removing the
primary returns 400. An incident with no primary district can still have additional districts
(admin).

### 5. Targeting
For each affected district (primary + additional):
- users whose home `district_id` is that district (citizens and authority users)
- authority users whose `Authority.district_id` is that district (the responsible authority)
- plus all admins (unchanged from M03)

Users outside every affected district get nothing. No affected district → admins only.
District-scoped reads also follow the affected area (`/api/hazards/district/<id>/active`,
`/api/hazards?district_id=`, district page, AI district summary) through one SQL helper,
`affects_district()`.

### 6. Notification deduplication
- **Key:** `notifications.dedup_key` = `"<incident_id>:<type>"`, or
  `"<incident_id>:hazard_escalated:<severity>"` for escalations. Same user + same key = same alert.
- **Python:** `notify_hazard` skips users who already hold the key.
- **Database (final defence):** unique index `uq_notifications_user_dedup (user_id, dedup_key)`.
  Inserts run in a SAVEPOINT; a row that hits the index (e.g. a concurrent writer) is skipped and
  the hazard change that triggered it is **not** rolled back.
- Legacy / non-hazard notifications keep `dedup_key = NULL` and are never constrained.
- No time-based cooldown: none is needed, because alerts only follow real state changes and each
  is unique per user.
- M02 evidence dedup is unchanged; it is a separate layer (which event?) from M04 (which user
  already knows?).

### 7. Escalation
| Change | Alert |
|---|---|
| medium → high | `hazard_escalated` (high), once per user |
| high → high | none |
| high → critical | `hazard_escalated` (critical), once per user |
| critical → high (authority edit) | none, never a downgrade alert |
| back up to critical | none (already alerted at critical) |
| evidence with a lower severity | ignored (severity never lowered automatically) |

### 8. Expansion, removal, resolved, rejected
- **Add district** (`add_affected_district`): newly covered users get `hazard_detected` at the
  current severity (plus `hazard_confirmed` if the event is confirmed) **once**. Users already
  notified get nothing.
- **Remove district:** deletes only that affected-area row. The incident, lifecycle, users and
  historical notifications are untouched; future alerts just stop going there.
- **Resolved:** `hazard_resolved` goes to all currently affected users. After that, no
  detected/escalated/confirmed alerts; area changes are kept for history but are silent.
- **Rejected:** no active alerts; incident and affected areas kept.

### 9. Flood behaviour
```
rising (A)            → event in A → A users: 1 × detected
authority adds B      → B users: 1 × detected (A users: nothing)
rising, rising, ...   → same event, report_count++ → nothing
flooding              → medium→high → A + B users: 1 × escalated
flooding again        → nothing
```
M01 thresholds unchanged (<80% normal, 80–100% rising, ≥100% flooding).

### 10. Earthquake / landslide / road damage
All four types (`flood, earthquake, landslide, road_damage`) go through the same code for affected
districts, targeting, dedup, escalation and statistics. There is no per-type branch, and a
parametrized test runs the same scenario for each type.
Earthquake is still "Earthquake / abnormal ground motion": no MPU6050/ESP32 code, no thresholds,
no magnitude, no prediction. Camera AI for landslide/road damage is not implemented.

### 11. API
| Method | Endpoint | Who | Result |
|---|---|---|---|
| GET | `/api/hazards/<id>/affected-districts` | any logged-in user | `{hazard_id, primary_district_id, affected_districts:[{id,name}]}`; 404 unknown hazard |
| POST | `/api/hazards/<id>/affected-districts` body `{"district_id": <int>}` | authority (own hazards, M02 rule) / admin | 201 + `notifications_sent`; 400 bad body/type; 404 unknown hazard or district; 409 already affected (incl. primary); 403 not authorized |
| DELETE | `/api/hazards/<id>/affected-districts/<district_id>` | authority (own hazards) / admin | 200; 400 primary; 404 not attached / unknown hazard; 403 not authorized |

Existing hazard responses gain `affected_districts`. Notification responses gain
`hazard.district_name` and `hazard.affected_districts` (names only). `dedup_key` is not exposed.

### 12. Frontend
The notification center shows, per alert: severity badge, hazard type, affected district names
(map-pin), and a relative time ("5 minutes ago", Nepali or English via `Intl.RelativeTimeFormat`)
with the absolute UTC time as a tooltip. The app has no hazard detail page, so affected districts
are shown on the notification card and in the API rather than on a new page.

### 13. Security
- Authentication: all endpoints → 401 JSON without login.
- RBAC: citizens view only. Authorities modify affected areas only for hazards they may manage
  under the M02 rule (`user.authority.district_id` == hazard's primary district), and may extend
  their hazard into neighbouring districts. Admins act globally. No new roles.
- Input: `district_id` must be a JSON integer (strings/bools rejected); names are not accepted;
  body must be a JSON object; district and hazard existence checked.
- CSRF: POST/DELETE covered by `CSRFProtect` (tested: 400 without token when enabled).
- IDOR: notifications remain scoped to `current_user.id`. Affected-area endpoints go through
  the same authorization as other hazard writes.
- Privacy: no `source_reference`, reporter identity, device IDs, API keys or `dedup_key` in
  notification or hazard responses for citizens. ORM-only queries; nothing sensitive logged.

### 14. Migration
`migrations/versions/c7e2b5a91d3f_m04_affected_districts_and_alert_dedup.py` (revises
`a3f1c9d2e8b4`). **Additive:** creates `incident_affected_districts`, adds nullable
`notifications.dedup_key` and the unique index. Backfill gives existing M03 hazard notifications a
key, but only the **earliest** row per (user, key). Historical duplicates keep NULL, so the index
is created without deleting or rewriting rows.
Verified on a scratch pre-M04 DB with legacy `river_alert` rows, a deliberate duplicate
`hazard_detected`, users, districts, a river and an incident: upgrade → downgrade → upgrade with
identical row counts at every step, then expansion + escalation on the migrated DB and a forced
duplicate rejected by the DB. The local dev DB was backed up and upgraded to `c7e2b5a91d3f`.

### 15. Tests
`tests/test_affected_areas_m04.py` (28 tests): model (implicit primary, DB duplicate pair,
unknown/duplicate/primary district), targeting, expansion (B then C, no repeats), escalation across
districts, confirmed-state expansion, removal keeps history, resolved/rejected silent, dedup (same
key once, escalation ladder, DB defence, savepoint batch skip, legacy unconstrained), all four
hazard types, IoT rising/flooding across two districts, API (auth, citizen view-only, authority
own vs other, admin, validation incl. string/bool/name/unknown/duplicate/primary, CSRF, payloads
and district views), notification center.
Updated: `tests/test_notifications_m03.py` (hazard payload now includes district fields).

**Full suite: `python -m pytest tests/ -q` → 213 passed, 57 warnings.**
All warnings are the pre-existing SQLAlchemy `Query.get()` legacy warnings (more of them because
new IoT tests run the existing `iot.py` line).

### 16. Known limitations
- District-level only: no GPS radius, polygons, or river-downstream inference. Affected districts
  are assigned explicitly by an authority/admin (IoT events start with the gauge's district only).
- An authority can only manage hazards whose **primary** district is theirs. Authority B can't
  manage a hazard that merely extends into B.
- Notification titles name the primary district. Users in an additional district see it in the
  "Affected:" line and the district badge.
- No real-time push; alerts appear on page load or when polled.
- No notification retention/cleanup or per-user preferences.
- Not a certified seismic system; no earthquake prediction; no evacuation routing; no external
  disaster-authority integration.

### 17. Next milestone
**M05 — Mobile Camera Citizen Reporting** (not started).

### 18. Files
- Created: `migrations/versions/c7e2b5a91d3f_m04_affected_districts_and_alert_dedup.py`,
  `tests/test_affected_areas_m04.py`
- Modified: `app/models/incident.py` (+ `IncidentAffectedDistrict`), `app/models/__init__.py`,
  `app/models/notification.py`, `app/services/notification_service.py`,
  `app/services/hazard_event_service.py`, `app/routes/hazard_events.py`, `app/routes/main.py`,
  `app/routes/district.py`, `app/routes/ai_routes.py`, `app/templates/pages/notifications.html`,
  `tests/test_notifications_m03.py`, `docs/PROJECT_PROGRESS.md`
- Deleted: none

### 19. Git commit
```
feat(m04): add affected areas and alert deduplication
```

### 🏷️ Status
**M04 — ALERT DEDUPLICATION + AFFECTED AREAS COMPLETE**
**HARDWARE NOT YET CONNECTED · NO MPU6050/ESP32 FIRMWARE · NO AI VISION**

---

## M05 — Mobile Camera Citizen Reporting

### 1. Status
**Complete.** Secure mobile photo evidence collection, integrated with the existing hazard-event
system. **No vision AI**: a photo is human-reviewable evidence and proves nothing on its own.

### 2. Architecture
```
Phone browser (camera via <input capture>, GPS via Geolocation API, description)
      ↓ multipart POST /api/reports (login + CSRF)
citizen_report_service
      ├─ validate fields (type, district, coords, text)
      ├─ decode + re-encode image (Pillow) → instance/uploads/reports/<uuid>.jpg
      ├─ CitizenReport row (evidence, status 'submitted')
      └─ hazard_event_service.report_hazard(source='citizen_report', escalate=False)
              ↓ M02 dedup: new Incident or join the related active one
         Incident ('detected') → M03/M04 alerts to affected districts (reporter gets a receipt instead)
```
A **report** is evidence and an **Incident** is the hazard. Two reports can point at one Incident.
There is no second hazard table.

### 3. Report model — `CitizenReport` (`citizen_reports`)
`reporter_id` (FK users), `incident_id` (FK incidents, nullable), `district_id` (FK districts),
`hazard_type`, `description` (private), `location` (landmark, becomes public `Incident.location`),
`latitude`/`longitude` (optional), `image_filename` (server-generated, unique), `status`,
`reviewed_by_id`, `reviewed_at`, `created_at`, `updated_at`.
`Incident.citizen_reports` lists the evidence for an event.

### 4. Report lifecycle (separate from the Incident lifecycle)
`submitted → accepted | rejected`, set by an authority responsible for the report's district, or an
admin, via `POST /api/reports/<id>/review`. Nobody reviews their own report. Reviewing a report
**never** changes the Incident: that stays `detected → investigating → confirmed → resolved/rejected`
through `/api/hazards`. A report can never auto-confirm anything.

### 5. Supported visual hazards
`VISUAL_HAZARD_TYPES = ['landslide', 'road_damage']` (subset of the global `HAZARD_TYPES`).
`earthquake`, `flood`, `iot`, `authority` etc. are rejected with 400 on this endpoint. Globally all
four hazard types still work (flood/earthquake via their own paths). New visual hazards can be
added to the list later.

### 6. Image upload & storage
- **Allowed:** JPG/JPEG, PNG, WEBP. The extension must match the **decoded** format, and the
  client MIME type must be `image/*`. SVG, GIF, PDF, executables, scripts and polyglots are
  rejected.
- **Size:** 10 MB per photo (413), under the existing app-wide 16 MB `MAX_CONTENT_LENGTH` (also a
  JSON 413).
- **Decompression bombs:** more than 40 MP is rejected, and Pillow's bomb warning is treated as an
  error.
- **Re-encoding:** the upload is decoded, orientation-fixed from EXIF, downscaled to at most 2560 px
  and **re-encoded to a new JPEG**. The original bytes are never stored, and EXIF (camera
  make/model, **embedded GPS**) and any appended payload are dropped.
- **Storage:** `instance/uploads/reports/<uuid4 hex>.jpg` (configurable via `REPORT_UPLOAD_DIR`).
  It's outside `/static`, and `instance/` is gitignored. The client filename is ignored entirely,
  so path traversal isn't possible. The file is opened with `'xb'` (never overwrites), and the
  stored name is re-checked against `^[0-9a-f]{32}\.jpg$` before serving. On any failure after
  the file is written, the DB is rolled back and the file removed.
- **Serving:** only through `GET /api/reports/<id>/image` after an authorization check,
  `Cache-Control: private, no-store`, `nosniff`.
- The DB stores only the generated filename, never a path or image bytes.
- Pillow (already installed) was added to `requirements.txt`. No external storage.

### 7. Location & district
- "📍 Use My Location" fills latitude/longitude from the browser Geolocation API.
- If permission is denied or unavailable, the user can type coordinates **or leave them empty**.
  District plus an optional landmark is enough to report.
- Server-side validation: both or neither, real finite numbers, lat −90..90, lon −180..180.
- **District decision: Option A (explicit selection).** The project has no district boundary data,
  so point-in-district lookup would be invented. The form defaults to the user's home district.
  Coordinates are stored and used by M02 dedup (5 km box).

### 8. Report → Incident integration
`submit_report` calls `report_hazard()` (the M02 path):
- `source = 'citizen_report'`, always set by the server. `source`, `status`, `severity`,
  `incident_id` and `reporter_id` form fields are ignored.
- Severity is fixed at `medium`, and `escalate=False`: joining an existing event bumps
  `report_count` but **never raises its severity**, so a photo can't trigger escalation alerts.
- M02 dedup decides whether to create or join: 2 reports → 1 Incident (both reports kept).
- The citizen's description stays on the report (private); the Incident gets a neutral title and
  the landmark. `Incident.source_reference = report_<id>` (internal, hidden from citizens).

### 9. Notifications
- A new Incident → `hazard_detected` to its affected districts (M03/M04 targeting + per-user dedup).
- **The reporter is excluded from that emergency alert** and instead gets a `report_update`
  receipt ("Your road damage report was received … This is a receipt, not a hazard alert").
  Review outcomes send `accepted`/`rejected` receipts. Receipts use dedup keys
  `report:<id>:<status>` and have no incident link.
- More reports on the same event don't create duplicate alerts (M04).

### 10. API
| Method | Endpoint | Who | Notes |
|---|---|---|---|
| POST | `/api/reports` | any logged-in user | multipart: `hazard_type`, `district_id`, `image`, optional `latitude`, `longitude`, `location`, `description`. 201 `{report, incident_created}`; 400 validation; 404 unknown district; 413 too large |
| GET | `/api/reports?status=&limit=` | logged-in | citizen: own; authority: own district's + own; admin: all |
| GET | `/api/reports/<id>` | reporter / responsible authority / admin | others 404; non-integer 400 |
| GET | `/api/reports/<id>/image` | same as above | private JPEG |
| POST | `/api/reports/<id>/review` `{"status": "accepted"\|"rejected"}` | responsible authority / admin, not own report | 409 if already reviewed |

Responses never include file paths, `image_filename`, `source_reference` or email. Reviewers see
only the reporter's username.

### 11. Frontend
- `/report` (`pages/report_hazard.html`): large 🏔️ Landslide / 🚧 Road Damage choice, a
  `<input type="file" accept="image/jpeg,image/png,image/webp" capture="environment">` with live
  preview (the phone's own camera/file picker; no native camera control is claimed), district
  select, 📍 Use My Location plus manual coordinates, landmark, private description, and a 48 px
  submit button. Vanilla JS `fetch` + `FormData` + `X-CSRFToken`, with error messages shown inline.
- `/reports/mine` (`pages/my_reports.html`): the user's own reports with a thumbnail (via the
  authorized image route), status, district, time, and linked hazard number and status.
- Sidebar links "Report a Hazard" and "My Reports". All new UI strings are in Nepali too.

### 12. Security review
- Authentication: API → 401 JSON; pages → login redirect.
- RBAC/ownership: visibility = reporter, admin, or authority responsible for the report's district;
  everyone else 404 (no id leak). Review = responsible authority/admin, never self.
- Citizens cannot change severity, confirm, resolve, or edit affected districts through reports.
- CSRF: `CSRFProtect` on POST `/api/reports` and review (tested).
- Uploads: see §6. Private image route; no public copy.
- No source spoofing; no arbitrary Incident modification; ORM-only; no image data, paths or
  descriptions logged; safe JSON errors.

### 13. Migration
`migrations/versions/e4d8a1f6b209_m05_citizen_reports.py` (revises `c7e2b5a91d3f`). **Additive:**
creates `citizen_reports` plus 3 indexes; no existing table touched.
Verified on a scratch pre-M05 DB holding M01–M04 data (users, districts, river, IoT device, incident,
affected district, hazard + legacy notifications): upgrade → downgrade → upgrade with identical row
counts in every existing table, then an ORM report linked to the incident. The local dev DB was
backed up and upgraded to `e4d8a1f6b209`.

### 14. Tests
`tests/test_citizen_reports_m05.py` (54 tests):
- **submission:** both visual types; 6 rejected types; global types unchanged; source, status,
  severity, incident and reporter override ignored; GPS optional; 8 bad-coordinate cases; district
  and text limits
- **upload security:** missing file; exe, php-polyglot, text, pdf, empty, svg and gif; content
  mismatch both ways; non-image MIME; no extension; PNG, WEBP and uppercase accepted; 10 MB and
  16 MB limits; decompression bomb; path traversal (`/` and `\`); EXIF/GPS stripped and
  downscaled; malformed multipart/JSON; login; CSRF
- **integration:** 2 reports → 1 incident; report never escalates or confirms; reporter gets a
  receipt, not an alert; repeated reports send no duplicate alerts
- **access:** cross-user/authority 404, reviewer sees username only, private image headers, no
  static copy, review rules/409/self-review/CSRF
- **pages:** mobile form markup, Nepali, "My Reports" shows only your own

**Full suite: `python -m pytest tests/ -q` → 267 passed, 57 warnings.**
All warnings are the pre-existing SQLAlchemy `Query.get()` legacy warnings.

### 15. Known limitations
- No vision AI; nothing verifies what the photo shows (M06).
- District is chosen by the user and not checked against the coordinates (no boundary data).
- Without coordinates, M02 dedup matches any active same-type event in the district within 24 h, so
  two separate road-damage spots reported without GPS in one district can merge into one event.
- Browser geolocation needs HTTPS (or localhost) on phones. Over plain HTTP on a LAN, users must
  type coordinates or skip them.
- `capture="environment"` is a hint; some browsers show a file picker instead of opening the camera.
- HEIC photos (iPhone default in some settings) are not accepted; most browsers convert to JPEG on
  upload, but not all.
- Photos are on local disk: no replication or backup, and no retention/cleanup policy.
- No per-user rate limit on report submission.
- Pre-existing, outside M05: the older JSON `POST /api/hazards` lets a citizen pass any
  `severity`, which can escalate an existing event (and send district-wide escalation alerts). The
  M05 photo path does not allow this. Restricting it on `/api/hazards` too is recommended.
- Pre-existing, outside M05: community post photos (`/posts/create`) are still saved under public
  `static/uploads` with the original (sanitised) filename.

### 16. Next milestone
**M06 — ROAD DAMAGE + LANDSLIDE VISION AI** (not started).

### 17. Files
- Created: `app/models/citizen_report.py`, `app/services/citizen_report_service.py`,
  `app/routes/reports.py`, `app/templates/pages/report_hazard.html`,
  `app/templates/pages/my_reports.html`, `migrations/versions/e4d8a1f6b209_m05_citizen_reports.py`,
  `tests/test_citizen_reports_m05.py`
- Modified: `app/__init__.py`, `app/models/__init__.py`, `app/models/notification.py`
  (`report_update` type), `app/services/hazard_event_service.py` (`escalate` flag, detection alert
  exclusion), `app/services/notification_service.py` (exclusion, report receipts),
  `app/services/page_strings.py`, `app/templates/components/navbar.html`, `requirements.txt`
  (Pillow), `docs/PROJECT_PROGRESS.md`
- Deleted: none

### 18. Git commit
```
feat(m05): add mobile citizen hazard reporting
```

### 🏷️ Status
**M05 — MOBILE CAMERA CITIZEN REPORTING COMPLETE**
**NO VISION AI · HARDWARE NOT YET CONNECTED**

M05 remains **COMPLETE / LOCKED**. M05.1 is a hardening patch on top of it, not a replacement.

---

## M05.1 — Citizen Hazard API Security Hardening

### 1. Status
Complete. Application/service/test change only — no migration.

### 2. Vulnerability
`POST /api/hazards` (M02 JSON endpoint) read `severity` from the request body for every role,
including citizens. A citizen could open an event at `critical`/`high`, or merge into an existing
active event with a higher severity, which escalated it and sent a district-wide
`hazard_escalated` notification (M03/M04).

### 3. Root cause
`create_hazard()` in `app/routes/hazard_events.py`: `severity = data.get('severity', 'medium')`
→ `report_hazard(event_type, severity, 'citizen_report', ...)` (default `escalate=True`)
→ `add_evidence()` raised severity and called `notify_hazard_escalated()`.
`source`, `status` and `incident_id` were already safe (source derived from role, new events
always `detected`, `incident_id` never read). The M05 `/api/reports` path was already safe
(fixed `medium`, `escalate=False`) — the rule just lived only in that one caller.

### 4. Fix
- `hazard_event_service.report_hazard()` — the single entry point for citizen-sourced evidence —
  now forces `severity = CITIZEN_REPORT_SEVERITY ('medium')` and `escalate=False` whenever
  `source == 'citizen_report'`, regardless of what the caller passes.
- `CITIZEN_REPORT_SEVERITY` moved from M05's `citizen_report_service` (which now aliases it as
  `REPORT_SEVERITY`, behaviour unchanged) so there is one definition.
- `POST /api/hazards` ignores a citizen's `severity` (no validation error for a value that is
  discarded), matching `/api/reports` (Option A: ignore, server decides).

### 5. Citizen behaviour
Citizens control: `event_type`, `title`, `description`, `location`, `latitude`/`longitude`,
`district_id` (defaults to their own), `river_id`, `road_segment_id`.
Ignored: `severity`, `status`, `source`, `incident_id`, `reporter_id`, `role`, any other key.
Result: always `source=citizen_report`, `severity=medium` on create, `status=detected`; merging
into an existing event only bumps `report_count` — never severity, never status, no escalation alert.

### 6. Authority/admin behaviour
Unchanged. Role comes from the authenticated session. Authority/admin may set severity on
create (`source=authority`), their evidence may still escalate a merged event, authorities stay
limited to their own district, and PATCH/status/resolve/reject remain manager-only.

### 7. Tests
`tests/test_hazard_api_security_m051.py` (21 tests): severity injection (critical/high/low/invalid),
no escalation of an existing event + no `hazard_escalated` notification, status injection
(confirmed/investigating/resolved/rejected), source spoofing (iot/authority/system), role/reporter
spoofing, `incident_id` abuse, service-level guard for any `citizen_report` caller, normal citizen
submission, authority/admin severity control kept, invalid manager severity still 400, and M05
`/api/reports` unchanged.
`tests/test_hazard_m02_integration.py::test_citizen_reports_merge_into_active_event` asserted the
vulnerable behaviour (citizen escalating to `critical`); it now expects `medium`.
Baseline before M05.1: 267 passed, 57 warnings. After: **288 passed, 57 warnings** (267 + 21 new).

### 8. Known limitations
- A citizen whose report merges into an existing event overwrites that event's
  `source_reference` with `user_<id>` (pre-existing M02/M05 behaviour on both citizen paths; it is
  manager-only internal data, but the original reference is lost).
- No rate limiting: a citizen can inflate `report_count` with repeated reports (out of scope).

### 9. Next milestone
**M06 — ROAD DAMAGE + LANDSLIDE VISION AI** (not started).

### 10. Files
- Modified: `app/routes/hazard_events.py`, `app/services/hazard_event_service.py`,
  `app/services/citizen_report_service.py`, `tests/test_hazard_m02_integration.py`,
  `docs/PROJECT_PROGRESS.md`
- Added: `tests/test_hazard_api_security_m051.py`

### 11. Git commit
```
fix(m05.1): harden citizen hazard severity handling
```

### 🏷️ Status
**M05.1 — SECURITY HARDENING COMPLETE**

---

## M06 — Road Damage + Landslide Vision AI

### 1. Status
Complete. M01–M05.1 behaviour is unchanged, and all earlier tests pass without modification.

### 2. Vision architecture
```
Citizen photo (multipart)
  ↓ M05: validate, re-encode to JPEG, strip EXIF/GPS, store as <uuid>.jpg (unchanged)
CitizenReport + Incident (M02 report_hazard, source=citizen_report, severity=medium) — committed
  ↓ citizen_report_service.analyze_report(report)
reads the stored file via image_path(report) (regex-checked server name, never a client path)
  ↓ vision_service.classify(image_bytes)        (bytes in, VisionResult out)
SigLIP zero-shot → {road_damage, landslide, other} → label + confidence
  ↓
CitizenReport.ai_* fields (evidence only)
  ↓
Human review: /reports/review page or POST /api/reports/<id>/review (M05, unchanged)
  ↓
Incident lifecycle stays with authorities via /api/hazards (M02, unchanged)
```
Analysis is **synchronous** and runs **after** the report is committed, so the report exists
whatever the model does. There is no worker, no queue and no new infrastructure.

### 3. Model
| | |
|---|---|
| Model | `google/siglip-base-patch16-224` (SigLIP ViT-B/16, 224 px input, 203,155,970 parameters) |
| Source | Hugging Face, pinned revision `7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed` |
| License | Apache-2.0 |
| Size on disk | 813 MB (`model.safetensors`) + ~1 MB tokenizer/config |
| Runtime | PyTorch CPU via `transformers`; no GPU. Measured ~1.1 GB extra process memory once loaded |
| Training | **This model was not trained by X-MAN.** There is no fine-tuning and no X-MAN dataset; it runs zero-shot only. |

**Why this model:** it is a genuine image model, runs on CPU, needs no training data, and its
license allows deployment. `openai/clip-vit-base-patch32` was evaluated first and rejected because
its model card says that *any deployed use case is out of scope*. Ollama's text model is not used:
it cannot see images, and M06 does not send it filenames or descriptions.

**Setup** (one-time; internet is needed only here, and the app loads with `local_files_only=True`):
```
pip install -r requirements-vision.txt      # torch 2.10.0, transformers 4.57.1, sentencepiece 0.2.1
python scripts/download_vision_model.py     # -> instance/models/siglip-base-patch16-224 (gitignored)
```
If torch/transformers or the model files are missing, every analysis is stored as `failed` and the
report flows exactly as in M05. `transformers` is told not to import TensorFlow (`USE_TF=0`),
because a broken TensorFlow install on the dev machine otherwise crashes the import.

**Config** (`app/config.py`, no secrets): `VISION_ENABLED` (default true; false in tests),
`VISION_MODEL_PATH` and `VISION_CONFIDENCE_THRESHOLD` (0.6). The model name and revision are
constants.

### 4. Classes
The classes are `road_damage`, `landslide` and `unknown` (abstain). The image is compared with 21
fixed English prompts ("This is a photo of …"):
- 4 road-damage prompts
- 4 landslide prompts
- 13 "other" prompts: intact road, normal street, building, collapsed building, person, animal,
  sky, food, indoor room, forest, mountain landscape, river, painting

The "other" prompts give the model somewhere to put normal or unrelated photos, so nothing is
forced into a hazard class.

### 5. Confidence
- `confidence` is the share of the softmax over all 21 prompts that falls on the best hazard
  class's prompts. It is a **relative model score against this prompt set**, not a calibrated
  probability that a hazard exists. The UI calls it "Model confidence".
- The label is that hazard class if `confidence >= 0.6`, otherwise `unknown`. The threshold must
  stay above 0.5, so that a hazard label always means the hazard class holds most of the prompt
  mass.
- **The threshold is not scientifically validated.** It was chosen by looking at the scores of 36
  public Wikimedia Commons photos (see §12). It is a configurable starting point, to be revisited
  with real Nepali reports.

### 6. Report integration
- **New columns on `citizen_reports`:** `ai_status` (`not_analyzed` | `completed` | `failed`),
  `ai_label`, `ai_confidence`, `ai_model`, `ai_model_version` (first 12 characters of the
  revision) and `ai_analyzed_at`.
- **Not stored:** raw model output and image bytes.
- **Citizen's choice:** `hazard_type` is never changed. Reviewers see disagreements flagged as
  "differs from citizen" and make the call.

### 7. Safety: why AI cannot confirm or escalate
- `vision_service` imports none of `db`, `Incident`, `CitizenReport`, `hazard_event_service` or
  `notification_service` (a test asserts this). It only turns bytes into a label.
- `analyze_report` writes only the report's `ai_*` columns. It never touches `status`,
  `hazard_type`, the Incident, severity, affected districts or notifications.
- The Incident is created or merged **before** analysis, by the unchanged M02/M05.1 path. So
  citizen reports stay fixed at severity `medium` and can never escalate an event.
- Report review (accept/reject) is still a human action and still does not change the Incident.

### 8. API
| Method | Endpoint | Who | Notes |
|---|---|---|---|
| GET | `/api/reports`, `/api/reports/<id>` | as M05 | Reviewers (authority/admin) get an extra `ai_analysis` object `{status, label, confidence, model, model_version, analyzed_at}`; reporters do not. |
| POST | `/api/reports/<id>/analyze` | Responsible authority or admin, not on their own report (same rule as review) | Re-runs analysis on the stored image, e.g. after a failure or once the model is installed. The body is ignored. Returns 503 if analysis is disabled, and 401/403/404 as in M05. |
| GET | `/reports/review` (page) | Authority or admin (others get 403) | Lists the reports visible to the reviewer (same query as `/api/reports`). |

### 9. Frontend
- **New `/reports/review` page** (`pages/review_reports.html`): the photo plus three separate
  panels.
  - **Citizen report:** type, reporter, district, location, coordinates, description and report
    status.
  - **AI analysis:** label, a "differs from citizen" flag, model confidence, model@version and
    time. Otherwise it shows "Analysis failed. Review the photo manually." or "Not analyzed".
  - **Hazard event:** incident id, status and severity.
- **Actions:** Accept, Reject and "Run analysis again" buttons call the API with CSRF. The page
  switches to one column on phones.
- **Links:** "Review Photo Reports" in the sidebar (authority/admin only) and in the authority
  dashboard nav.
- **Citizens:** see no model output anywhere. `/report`, `/reports/mine` and the API responses
  they get are unchanged.
- **Translations:** all new strings have Nepali translations.

### 10. Database
`migrations/versions/b5c9e3f7a142_m06_citizen_report_vision.py` (revises `e4d8a1f6b209`).
- **Additive:** 6 columns on `citizen_reports`. `ai_status` is NOT NULL with server default
  `not_analyzed`; the rest are nullable. No other table is touched.
- **Round trip:** tested on a copy of the dev DB seeded with an incident and a citizen report:
  upgrade → downgrade → upgrade. Row counts in users/districts/incidents/citizen_reports/
  notifications stayed identical and the report row stayed intact each time.
- **Drift check:** `flask db check` found no drift between models and schema.
- **Dev DB:** the local dev DB was backed up to `instance/hackforge.pre-m06.db` and upgraded to
  `b5c9e3f7a142`.

### 11. Tests
`tests/test_vision_m06.py` has 36 tests. Most replace the classifier with a deterministic stub
whose scores come from the decoded pixels' mean colour, so the stored image really flows through
the service. In production, the real model class is used.
- **classify:**
  - each outcome: road_damage, landslide, "other" → unknown, below-threshold → unknown
  - configurable threshold
  - 4 invalid or truncated images
  - path strings rejected as images
  - missing model, with no path in the error message
  - unloadable model or missing dependency (not cached as broken)
  - inference exception
  - no Incident or notification access in the module
- **Integration:**
  - AI evidence is stored, and the analysed image equals the stored re-encoded file
  - disagreement in either direction keeps the citizen's type and the Incident type
  - `unknown` keeps the report valid
  - at confidence 0.99 and at low confidence: report stays `submitted`, incident stays
    `detected`/`medium`, affected districts are unchanged, and zero escalated/confirmed/resolved
    notifications are sent
  - inference failure or missing model: the report is kept as `failed` and its image is still
    served
  - disabled: `not_analyzed`
  - a tampered `../../secret.txt` filename is not read
  - a deleted image gives `failed` without leaking the path
- **API:**
  - reviewers see `ai_analysis`; reporters do not
  - re-analysis after a failure
  - authorization: reporter and other citizens 403, other-district authority 404, admin 200,
    logged out 401
  - disabled 503
  - review still does not change the Incident
- **Page:** three panels and the disagreement flag; Nepali; no access for citizens or other
  districts; no model output on "My Reports".
- **Real model** (skipped if not installed): a blank grey image gives `unknown`. It runs on this
  machine.

**Full suite: `python -m pytest tests/ -q` → 324 passed, 59 warnings** (baseline 288 passed, 57
warnings at `662f223`). The two new warnings are SWIG `DeprecationWarning`s raised by the
real-model test when it imports the third-party sentencepiece/torch stack.

### 12. Performance and observed behaviour (this laptop, CPU only)
- **Warm inference** through `vision_service.classify` on 36 photos (≤640 px): **mean 0.549 s,
  median 0.544 s, max 0.74 s**.
- **Cold model load** in a fresh process, including the torch/transformers import: **16.7 s** in a
  standalone run and **9.4 s** for the first end-to-end submission.
- **Warm full submission** (upload, re-encode, incident and analysis): **~0.31 s**.
- **Informal sanity check, not an accuracy figure.** The 36 photos are Wikimedia Commons search
  results for landslide, pothole, road crack, highway, building, dog, sky, person, food and
  mudslide.
  - Every clearly visible road crack, pothole or landslide got the matching label (0.76–0.998).
  - Every building, person, animal, food, sky and intact-highway photo got `unknown`.
  - Ambiguous cases: a 1980 mudflow scene with mailboxes → `unknown` (0.42); a worn, cracked road
    marking → `road_damage` (0.94).
  - No precision, recall or F1 has been measured, because there is no labelled X-MAN dataset.

### 13. Security
- Only the M05-validated, re-encoded, EXIF-free stored JPEG is analysed. It is located by
  `image_path(report)`, which only accepts names matching `^[0-9a-f]{32}\.jpg$`.
- `vision_service` accepts bytes only, so no path or URL can reach it. The analyze endpoint ignores
  its body.
- Visibility and review rules are reused unchanged (`can_view`, `can_review`); other districts
  still get 404.
- Error messages, API responses and logs contain no filesystem paths or image data. Logs record
  only the report id and a short reason.
- AI cannot change severity or Incident status, resolve an Incident, modify affected districts or
  send notifications (see §7; tested).
- Failures keep the report, image and Incident, and no fake result is stored.
- There are no secrets in config. Model weights live in the gitignored `instance/` directory and
  are not committed.
- No image metadata is reintroduced: analysis only reads the stored file and never writes to it.

### 14. Known limitations
- **Not validated locally:** the model runs zero-shot on general-purpose features learned from web
  images. It has not been validated on Nepali roads or terrain, monsoon lighting, night photos or
  low-end phone cameras. Expect errors on ambiguous scenes (rubble vs landslide debris, gravel
  roads vs damaged roads, worn paint vs cracks).
- **Uncalibrated confidence:** `confidence` depends on the prompt set, so changing the prompts
  changes the scores.
- **Synchronous inference:** the first report after a server start waits for the model load
  (~10–17 s here), and a global lock runs one inference at a time (~0.5 s each). That is fine for
  district-level volumes; bursts would need a queue.
- **Separate download:** the model must be downloaded separately (813 MB). Without it, every report
  is `failed` until a reviewer re-runs analysis.
- **Older reports:** reports submitted before M06 stay `not_analyzed` until a reviewer clicks "Run
  analysis again".
- **Two classes only:** floods and earthquakes stay sensor-driven.

### 15. Next milestone
**M07 — DISASTER MONITORING DASHBOARD** (not started).

### 16. Files
- **Created:** `app/services/vision_service.py`, `app/templates/pages/review_reports.html`,
  `migrations/versions/b5c9e3f7a142_m06_citizen_report_vision.py`, `requirements-vision.txt`,
  `scripts/download_vision_model.py`, `tests/test_vision_m06.py`
- **Modified:** `app/config.py`, `app/models/citizen_report.py`,
  `app/services/citizen_report_service.py`, `app/routes/reports.py`,
  `app/services/page_strings.py`, `app/templates/components/navbar.html`,
  `app/templates/authority/dashboard.html`, `.env.example`, `docs/PROJECT_PROGRESS.md`
- **Deleted:** none

### 17. Git commit
```
feat(m06): add road damage and landslide vision analysis
```

### 🏷️ Status
**M06 — ROAD DAMAGE + LANDSLIDE VISION AI COMPLETE**
**PRETRAINED ZERO-SHOT MODEL · NOT TRAINED BY X-MAN · AI IS EVIDENCE, HUMANS DECIDE**

---

## Pre-M07 — Hardware Architecture Synchronization

Documentation/architecture sync only. No physical hardware has been built or tested, there is no
firmware, no GPIO/driver code and no change to the telemetry API. M06 stays **COMPLETE / LOCKED**.

### Final hardware selection
*(Updated after M11: the DHT22 that was originally listed on the flood node has been removed. See
"Hardware architecture update — DHT22 removed" at the end of this file.)*
```
ESP32 #1 — flood node
└── JSN-SR04T waterproof ultrasonic sensor → water_level (metres)

ESP32 #2 — seismic node
└── GY-521 (MPU6050) → vibration, tilt (abnormal ground-motion prototype)

Existing smartphone
└── Camera + GPS → citizen landslide / road-damage reports (M05/M06)
```
Components: ESP32 DevKit ×2, JSN-SR04T ×1, GY-521 (MPU6050) ×1, breadboard ×2, jumper wire set ×2,
USB cable ×2, USB power supply/power bank ×2, JSN-SR04T mounting/protection ×1, MPU6050 stable
mounting platform ×1, running-water channel/container ×1, stilling/measurement chamber ×1, existing
smartphone ×1.
**Not required:** DHT22 (removed after M11), HC-SR04, hydrostatic pressure sensor, HFS-DC06 microwave motion sensor, rain sensor,
water pump, relay, MOSFET, Raspberry Pi, Arduino, separate GPS module, dedicated camera, GSM module,
third ESP32.

### Responsibilities
- **ESP32 #1 (flood):**
  - The JSN-SR04T replaces the HC-SR04 because it is waterproof.
  - It measures the distance from the sensor down to the water surface.
  - The firmware derives `water_level_m = (reference_height_cm − distance_cm) / 100` and sends
    `water_level` in **m**.
  - No other sensor on this node (the DHT22 temperature/humidity context sensor was removed after M11).
- **Running-water demo:** the sensor reads the level inside a stilling/measurement chamber
  connected to the channel, so turbulent surface motion is not the measurement target.
- **ESP32 #2 (seismic):**
  - The MPU6050 sends `vibration` (mg) and `tilt` (°).
  - It is an abnormal-ground-motion prototype: not a certified earthquake early-warning instrument,
    and not an earthquake predictor.
- **Smartphone:** its camera and GPS feed the existing `/report` flow. No dedicated camera or GPS
  module is needed.
- **Evidence boundary:**
  `sensor → ESP32 → telemetry → ingestion → risk engine → hazard event → notifications`.
  - Sensors, the MPU6050 and the vision AI provide evidence only.
  - X-MAN interprets it and owns the event lifecycle and notifications.

### Backend stays sensor-model agnostic
Telemetry still uses logical types (`water_level`, `temperature`, `humidity`, `vibration`, `tilt`,
plus the unused `rainfall`). No sensor model appears in the code paths, and no new sensor types
were added.

**Brief vs code:** the brief's example sends `water_level` in `cm`, but the M01 contract
(`risk_engine.SENSOR_TYPES`, river `current_level`/`danger_level`) is in **metres**, and readings in
`cm` are rejected. I kept the API unchanged and documented that the firmware converts to metres.

### Changes
- `app/routes/iot.py`: the device-registration docstring example no longer names the HC-SR04 as the
  water-level sensor. It is the only code reference to a sensor model, and it changes no behaviour.
- `README.md`: new "Hardware" section covering architecture, the flood/seismic node details, the
  stilling chamber, the telemetry contract table, the component list and the not-required list.
- `docs/PROJECT_PROGRESS.md`: this entry.

Repository search for `HC-SR04` (excluding `venv/` and `instance/`): it remains only where it is
named as *replaced* / *not required*.

### Tests
`python -m pytest tests/ -q` → **324 passed, 59 warnings** (unchanged from M06). No tests were
added, changed or removed. Security behaviour is unchanged: device auth, API-key hashing, RBAC,
CSRF, telemetry validation and hazard lifecycle code were not touched.

### Known limitations (for M07/M08)
- Nothing physical has been validated yet: JSN-SR04T accuracy and its minimum range (blind zone,
  to be measured on the real module), chamber behaviour, the MPU6050 noise floor, and
  power.
- `vibration` is capped at 1000 mg (1 g) by validation. Strong shaking above that would be
  rejected, so the range needs revisiting with the real MPU6050 settings before seismic rules are
  written (M08).
- No risk rules exist yet for `vibration`/`tilt`. Only `water_level` drives hazard events (M01/M02).

### Next milestone
**M07 — DISASTER MONITORING DASHBOARD** (not started).

### Git commit
```
docs: synchronize finalized x-man hardware architecture
```

### 🏷️ Status
**PRE-M07 HARDWARE SYNCHRONIZATION COMPLETE · NO HARDWARE BUILT · NO FIRMWARE**

---

## M07 — Disaster Monitoring Dashboard

### 1. Status
Complete. It is a presentation and aggregation layer only: no new detection or risk rules, no
schema change, no change to telemetry, the hazard lifecycle, notifications, M05 report security or
M06 classification.

### 2. Objective and architecture
One operational view of what M01–M06 already produce:
```
/monitoring (Jinja shell + vanilla JS + Leaflet)
   │  polls every 30 s (paused while the tab is hidden)
   ▼
GET /api/dashboard  (routes/monitoring.py: auth, input validation)
   ▼
dashboard_service.build(user)   read-only, role-scoped
   ├─ hazards ......... Incident (+ M04 affects_district), Incident.to_dict(include_internal=False)
   ├─ summary ......... one GROUP BY over the same active-hazard filter
   ├─ devices ......... IoTDevice + latest SensorReading per (device, sensor_type)   [managers]
   ├─ reports + AI .... citizen_report_service.visible_reports_query (M05/M06)       [managers]
   ├─ notifications ... notification_service.get_user_notifications (own only, M03)
   └─ statistics ...... hazard_event_service.get_event_statistics + report/notification counts [admin]
```
The frontend only displays what the server sent: severity colours are a fixed severity→badge map,
and no value is computed or reclassified in JS.

### 3. Dashboard behaviour by role
| Section | Citizen | Authority | Admin |
|---|---|---|---|
| Hazard summary/list/map | active hazards affecting their home district (incl. M04 extra districts); nationwide if no home district | active hazards affecting their authority's district | all active hazards, optional `?district_id` filter |
| IoT devices + latest readings + freshness | — | devices owned by their authority (same rule as `/api/iot/devices`) | all devices (district filter applies) |
| Citizen reports + AI evidence | — | `visible_reports_query` (own district + own reports) | all (district filter applies) |
| Notifications | own | own | own |
| System statistics | — | — | events by status/type/source/severity, reports by status and AI status, notifications in the last 24 h, device count (always system-wide) |

- An authority user not linked to an authority gets an empty operational view, consistent with
  M02.
- Citizens and authorities may only pass their own `district_id`; any other value returns 403.

### 4. Components
- **Active hazard summary:** counts by type (flood, earthquake, landslide, road_damage) and by
  severity (low, medium, high, critical). Earthquake is labelled "Earthquake / abnormal ground
  motion".
- **Hazard list:** title, severity, status, type, source, affected districts (primary first),
  detected/updated time and location.
- **Map:** Leaflet 1.9.4 from unpkg (the same CDN as Lucide), pinned with SRI hashes, using
  OpenStreetMap tiles.
  - Hazards with coordinates show as severity-coloured circles; the popup is the same hazard card.
  - Managers also see devices with coordinates as dashed grey circles.
  - Hazards without coordinates are listed under the map ("Not on the map (no coordinates)") with
    their affected districts. `District` has no geometry/centroid data, so nothing is invented.
- **IoT devices:** name, freshness, enabled/disabled, operator status, district, "last seen … ago",
  and the latest value + unit + time for each sensor type (e.g. Water level 1.25 m, Temperature
  27.4 °C, Humidity 81 %, Vibration 42 mg, Tilt 0.8 °). The page states that "A vibration or tilt
  value is not an earthquake detection".
- **Device freshness (presentation rule):** computed at read time from `last_seen`:
  - `online` ≤ 5 min
  - `stale` ≤ 60 min
  - `offline` older
  - `never` no telemetry

  It never writes `IoTDevice.status` or anything else; a test checks that opening the dashboard
  changes no row.
- **Citizen reports:** type, district, landmark, time, review status, linked hazard and its
  status, and AI status/label/model confidence/model.
  - Not sent: description, image filename/path, reporter.
  - A link points to `/reports/review`.
- **My alerts:** the user's latest 10 notifications (`Notification.to_dict`: severity, type,
  title, message, affected district names, time, read state) plus the unread count.
- **Statistics:** admin only.
- **Navigation:** "Disaster Monitoring" in the sidebar for everyone, and in the authority panel nav.
  All new strings have Nepali translations.

### 5. API
| Method | Endpoint | Who | Notes |
|---|---|---|---|
| GET | `/monitoring` | logged-in (pages redirect to login) | page shell; sections depend on role |
| GET | `/api/dashboard` | logged-in (401 JSON otherwise) | role-scoped JSON. `district_id` must be a positive ASCII integer (400), must exist (404), and is admin-only unless it equals your own district (403). Other params are ignored. `Cache-Control: private, no-store` |

No existing endpoint was changed.

### 6. Refresh / polling
- The page fetches `/api/dashboard` on load and then every **30 s** (`POLL_SECONDS`), one request
  per cycle.
- Polling stops while `document.hidden` is true and reloads immediately when the tab becomes
  visible again. There is also a manual Refresh button.
- The UI says "Updated hh:mm:ss · refreshes every 30 s". It is described as periodically
  refreshed, not real-time.
- No WebSockets, workers or caches were added.

### 7. Performance
- All lists are eager-loaded (`joinedload`/`selectinload`).
- Latest readings come from one `MAX(id) GROUP BY device, sensor_type` subquery plus one fetch.
- The summary is one `GROUP BY`.
- Hazards are capped at 200, reports at 20 and notifications at 10.
- A test adds 10 hazards (each with an extra affected district), 10 devices and readings, and
  asserts the admin request issues **no more SQL statements than before** (19 → 17 observed;
  identity-map hits).

### 8. Security review
- **Authentication:** API 401, page redirects to login.
- **RBAC:** visibility rules are reused from M02/M04, M01 (`/api/iot/devices`), M05/M06 and M03.
  No new visibility rule was invented.
- **Not in any payload (tested for every role):** `source_reference`, API keys or hashes,
  `raw_payload`, image filenames, report descriptions, reporter ids, emails.
- **Citizens:** get no `devices`, `reports`, `ai_analysis` or `statistics` keys.
- **Read-only:** GET only, so no CSRF surface is added, and the ORM is used throughout.
- **Frontend:** JS builds every node with `textContent` (no `innerHTML` with data), contains no
  secrets, and loads Leaflet with SRI.
- **Fix:** `[hidden] { display: none !important; }` was added to `base.html`, because `.alert`'s
  `display: flex` overrode the `hidden` attribute. This had also shown an empty error bar on the
  M06 review page.

### 9. Tests
`tests/test_dashboard_m07.py` (39 tests):
- **Auth and input:** login required (API and page); 8 malformed `district_id` values → 400;
  unknown → 404; other district for citizen/authority → 403; unknown params ignored; no-store
  header.
- **Citizen:**
  - scope and exact summary counts, including the M04 extra district
  - affected districts in order
  - no operational or private data
  - another district's coordinates are not sent (map authorization)
  - a citizen with no home district sees the nationwide public view
  - notifications are their own only
- **Authority:**
  - operational scope
  - latest reading per sensor type with correct units (m, °C, %, mg, °)
  - freshness labels and the rule
  - reports with AI evidence but no private fields
  - cross-district isolation; never-reported disabled device
  - an unlinked authority sees nothing
- **Admin:** system-wide data and statistics, district filter, no secrets.
- **Read-only and performance:** device/incident/notification/reading/report rows unchanged after
  dashboard and page loads; freshness boundaries (0/300/301/3600/3601 s, never); constant query
  count.
- **Page:**
  - citizens get no IoT, report or district-picker sections; managers and admins do
  - Leaflet pinned with SRI; polling documented; no "real-time" wording
  - Nepali; sidebar link

**Full suite: `python -m pytest tests/ -q` → 363 passed, 59 warnings** (M06 baseline 324 passed,
59 warnings, + 39 new; no existing test changed).

Manually checked in Chrome against a seeded scratch copy of the dev DB as admin:
- summary, map markers and the unmapped list
- hazard cards, IoT cards (online/offline), alerts and statistics
- no console errors
- polling paused while the tab was hidden

### 10. Migration
None. No schema change.

### 11. Known limitations
- **Map:** no district polygons or centroids. Hazards and devices without coordinates are listed,
  not drawn, and affected districts are shown by name. Map tiles and Leaflet need internet
  (OSM/unpkg).
- **Freshness thresholds** (5/60 min) are a UI convention until real device reporting intervals
  are known.
- **Polling:** up to 30 s of delay; no push.
- **Scope:** authority device visibility follows the existing ownership rule (`authority_id`). A
  device in an authority's district but owned by no authority is visible only to admins.
- **Pre-existing, not changed in M07:** `GET /api/iot/devices` lets an authority user who is *not
  linked* to an authority list any district's devices via `?district_id=` (device metadata, no
  keys). The dashboard does not have this gap. Restricting it is recommended for M10 hardening.
- **Telemetry only:** there are no seismic risk rules. Vibration/tilt values are shown as
  telemetry until M08.
- **Not committed yet:** the pre-M07 hardware documentation changes (README, `iot.py` docstring,
  progress entry) are still uncommitted alongside M07.

### 12. Files
- **Created:** `app/services/dashboard_service.py`, `app/routes/monitoring.py`,
  `app/templates/pages/monitoring.html`, `tests/test_dashboard_m07.py`
- **Modified:** `app/__init__.py` (register blueprint), `app/templates/base.html` (`[hidden]`
  rule), `app/templates/components/navbar.html`, `app/templates/authority/dashboard.html`,
  `app/services/page_strings.py`, `README.md`, `docs/PROJECT_PROGRESS.md`
- **Deleted:** none

### 13. Next milestone
**M08 — MULTI-SIGNAL RISK ENGINE** (not started).

### 14. Git commit
```
feat(m07): add disaster monitoring dashboard
```

### 🏷️ Status
**M07 — DISASTER MONITORING DASHBOARD COMPLETE · PRESENTATION ONLY · NO NEW DETECTION RULES**

---

## M08 — Multi-Signal Risk Engine

### 1. Status
Complete. Deterministic, rule-based and explainable. There is no ML, no LLM and no prediction. No
schema change. No hardware or firmware work.

### 2. Architecture
```
telemetry (POST /api/iot/telemetry) ── validation (unchanged) ──┐
citizen photo report (POST /api/reports, M05) + AI (M06) ───────┤  evidence
authority-created events (/api/hazards, M02) ───────────────────┘
        ↓
risk_service      gathers evidence from the DB, scoped to river / device / district / linked reports
        ↓
risk_engine       pure rules → RiskAssessment (level, action, suggested severity, reasons, evidence, sources)
        ↓  only if action == 'report_event'
hazard_event_service   create / merge (M02 dedup) / escalation rules — unchanged
        ↓
notification_service   detected / escalated / … with M04 dedup and affected areas — unchanged
```
- `risk_engine.py` holds the M01 functions (untouched) plus the M08 rules. They are pure: no `db`,
  no `Incident`, no notifications.
- `risk_service.py` reads evidence and calls `hazard_event_service` only. It never imports
  `Notification` or `notification_service`; a test asserts this.
- The flood path in `iot.py` now goes `process_water_level_reading → risk_service.evaluate_water_level`.
  Vibration/tilt readings call `risk_service.evaluate_motion`.
- Citizen reports still go through the M05 → `report_hazard` path. Their fixed-severity /
  no-escalation rule stays in the single M05.1 guard in `hazard_event_service`; M08 adds an evidence
  assessment on top.

### 3. RiskAssessment (service-layer result, not persisted)
`hazard_type, level, action ('none' | 'report_event'), severity (suggested, only with
report_event), reasons[], evidence{}, sources[], district_id, assessed_at`.
- It is never a probability. Numbers inside `evidence` are measurements or counts.
- No new table: assessments are recomputed from stored evidence on demand.

### 4. Flood rules
- **Decision = M01, unchanged.** `assess_water_level_risk(current, danger)`: <80% normal, 80–100%
  rising, ≥100% flooding.
  - rising → event at `medium`, flooding → `high`, same as M02's `RISK_LEVEL_SEVERITY`.
  - No usable danger level → `unknown`, no event.
  - Water level stays in **metres**.
- **Window evidence** (last 30 min of `water_level` readings in `m` from devices on that river,
  plus the reporting device for the M01 district fallback):
  - Only `quality == 'good'` readings count; the others are counted as ignored.
  - **Corroboration:** the number of valid readings in the window with the same rising/flooding
    status as the current one.
  - **Trend:** `change = latest − earliest valid value` ordered by `recorded_at`. It needs ≥ 3
    readings spanning ≥ 5 min; `increasing` if change ≥ +0.05 m, `decreasing` if ≤ −0.05 m,
    otherwise `steady`. `rate_m_per_hour = change / span`.
  - The trend describes recent change only. It is **not a forecast** and never creates or
    escalates an event; a test checks a rising trend below 80% gives no action.
- Telemetry timestamps with an offset (e.g. `…Z`) are now stored as naive UTC like every other
  timestamp. Before, aware and naive datetimes were mixed in the session and could not be
  compared. The payload format is unchanged.

### 5. Seismic / abnormal ground motion (MPU6050-class prototype)
- Uses the existing `vibration` (mg) and `tilt` (°) types; no new sensor types.
- **Rule** (per device, 60 s window, good-quality readings only): `elevated_motion` if
  - ≥ 3 vibration readings ≥ `MOTION_VIBRATION_THRESHOLD_MG`, or
  - ≥ 3 tilt readings whose `max − min` ≥ `MOTION_TILT_CHANGE_THRESHOLD_DEG`.

  A single spike is ignored.
- **Thresholds are unset by default**, which reports `uncharacterized` and creates no event. There
  are no validated values, so hardware characterization (H-milestones) must set them via
  environment variables.
  - A vibration threshold above the 1000 mg validation cap (or ≤ 0) disables the vibration rule
    and says why.
  - The 1000 mg cap itself was **not** changed.
- **When it fires:** `report_hazard('earthquake', 'medium', 'iot', escalate=False, …)` in the
  device's district.
  - The title is "Abnormal ground motion signal: <device>". The description states that it is
    prototype evidence, not a certified detection, not a prediction and has no magnitude.
  - Repeated evidence merges into the active event (M02 dedup) and **never escalates** it.

### 6. Landslide and road-damage evidence
`assess_visual(event_type, reports linked to the event)`:
- **What counts:**
  - Counted per **distinct reporter**: one person's repeated reports count once.
  - `rejected` reports are excluded.
  - AI agrees only when `ai_label == event_type`. M06 already returns `unknown` below its
    threshold, so a low score never counts.
- **Grades:**
  - `insufficient`: no usable report
  - `single_report`: one reporter, no AI agreement
  - `supported`: one reporter + AI agreement, or ≥ 2 distinct reporters
  - `corroborated`: ≥ 2 distinct reporters + ≥ 1 AI agreement
- **Reasons** also cover: AI conflicts (AI suggests the other hazard type, which needs human
  review and raises nothing), rejected or accepted reports, and authority source.
- **Always `action: none`:** AI and report counts never change severity or status. "Nearby" means
  the reports M02 dedup already linked to this event (same type, district/location, 24 h), so no
  new geography is invented.
- Tests cover AI at 0.99 + two reporters → `corroborated`, while the event stays `detected` /
  `medium` with no escalation or confirmation notification.

### 7. Multi-signal and cross-district behaviour
- **Combined only within one event's own evidence:** the river's devices (flood), devices in its
  primary district (motion), reports linked to it (visual), and its authority source.
- **Duplicate evidence:** the same reporter, or repeated telemetry, does not raise the grade or
  severity.
- **Bad evidence:** bad- or suspect-quality readings and rejected reports are ignored, never
  strengthening.
- **No cross-district leakage:** another district's river, devices or reports never enter an
  assessment (tested for flood, motion, reports and notifications).

### 8. API
- **New:** `GET /api/hazards/<id>/assessment`. It is read-only and manager-only; authorities see
  only their own district (same rule as event management): 401 / 403 / 404, and POST → 405.
  - It returns `{hazard_id, assessments: [RiskAssessment…]}`, one per motion device for
    earthquake events.
  - Query parameters are ignored, so no client can inject a level, severity or confidence.
  - It contains no report text, filenames, reporter ids, raw payloads, keys or source references.
- **Unchanged:** the telemetry, report and hazard contracts. Extra fields such as `severity`,
  `risk_level`, `confidence` or `source` in telemetry are ignored (tested).

### 9. Security
- Risk is computed server-side only from stored, validated evidence.
- Source is still derived server-side: `iot` for devices, `citizen_report` for reports (M05.1).
- There is no direct notification path from sensors, AI or the engine.
- CSRF, RBAC and device auth are unchanged.
- **Still open, recorded for M10:** the M07 finding that `GET /api/iot/devices` lets an authority
  user *not linked* to an authority list any district's devices via `?district_id=`.

### 10. Tests
`tests/test_risk_engine_m08.py` (68 tests):
- **Flood:**
  - M01 boundaries (79.75 / 80 / 99.75 / 100%) and unknown danger levels
  - trend calculation (increasing, decreasing, steady, timestamp order not row order, insufficient
    cases)
  - bad and suspect readings ignored; repeated readings corroborate
  - a rising trend below threshold gives no event
  - pipeline: normal → none; rising ×3 → one event with one detected alert per user; flooding →
    one escalation
  - invalid readings (cm, out of range, non-number) rejected with no event
  - client-injected severity/source ignored; stored timestamps used for the trend; another river's
    readings excluded
- **Motion:**
  - disabled by default
  - repeated vibration → one `earthquake` event at `medium`, never escalated, with a disclaimer
  - single spike ignored; tilt-change rule
  - 6 invalid or unsupported readings rejected
  - threshold above the cap disabled; bad quality ignored
  - another district's device stays in its district
- **Visual:**
  - 9 evidence cases × 2 hazard types, covering none, single, AI unknown/low/failed, AI agree,
    2 reporters, a duplicate reporter, corroborated, and a rejected report
  - conflicting AI; sources
  - pipeline: corroborated but not confirmed or escalated; AI unknown and disagreement; other
    district's reports not combined
- **API / security:** authorization, read-only, query-param injection, no private data, flood and
  motion assessments.
- **Architecture:** no notification access in the engine or service; notifications are created
  only through `notification_service` via event state changes (spy); serialization.

Changed existing tests: none. **Full suite: see §13.**

### 11. Known limitations
- Motion thresholds, the trend window and step (30 min, 3 readings, 5 min, ±0.05 m) and the
  motion window (60 s, 3 readings) are engineering defaults, not validated against real rivers or
  the real MPU6050.
- Telemetry ingestion still marks every accepted reading `quality='good'` (as in M01). The quality
  filter matters once firmware or ingestion flags suspect data.
- The trend is not used for decisions on purpose. Using it for early warnings needs field data and
  a documented rule.
- Each elevated motion or rising-water reading adds to `report_count` of the active event (same as
  M02 flood evidence).
- Assessments are not persisted, so there is no risk history.
- Earthquake assessments use only devices in the event's primary district, with a 60 s window,
  so an old event shows the current motion state.
- The M07 `/api/iot/devices` unlinked-authority gap remains for M10.

### 12. Hardware dependency
The JSN-SR04T (water level in metres, converted on the ESP32) and the GY-521 (MPU6050) have
**not** been built or validated. The motion rule cannot be enabled
meaningfully before hardware characterization (H-milestones).

### 13. Files
- **Created:** `app/services/risk_service.py`, `tests/test_risk_engine_m08.py`
- **Modified:**
  - `app/services/risk_engine.py` (M08 rules appended, M01 functions untouched)
  - `app/routes/iot.py` (flood/motion via `risk_service`, UTC timestamp normalization)
  - `app/routes/hazard_events.py` (assessment endpoint)
  - `app/config.py` (motion thresholds, unset by default)
  - `docs/PROJECT_PROGRESS.md`
- **Deleted:** none
- **Migration:** none

**Full suite: `python -m pytest tests/ -q` → 431 passed, 79 warnings** (M07 baseline 363 passed, 59 warnings; +68 new tests). The 20 extra warnings are all the pre-existing `River.query.get()` LegacyAPIWarning in `iot.py`, hit more often by the new telemetry tests. There is no new warning type.

### 14. Next milestone
**M09 — AUTHORITY RESPONSE SYSTEM** (not started).

### 15. Git commit
```
feat(m08): add multi-signal risk engine
```

### 🏷️ Status
**M08 — MULTI-SIGNAL RISK ENGINE COMPLETE · DETERMINISTIC · NO PREDICTION · AI AND SENSORS ARE EVIDENCE**

---

## M09 — Authority Response System

### 1. Objective
Answers the question "an alert was generated, what does the responsible authority do with it?"
M09 adds human investigation, confirmation or rejection, recorded response actions and an
evidence-backed resolution, all with an audit trail. It is not a detection engine: no risk
scoring, classification, sensor evidence, automatic confirmation or resolution, and no
notification rows.

### 2. Architecture
```
Hazard Event (M02, created from M08 RiskAssessment)
     ↓
Authority Investigation (notes)          ┐
     ↓                                   │ authority_response_service
Confirmation / Rejection                 │  (authorization, validation, notes, actions, timeline)
     ↓                                   │
Response (actions)                       │
     ↓                                   ┘
Resolution (required note)
     ↓
hazard_event_service._apply_transition   (single status path: CAS update + audit row, one transaction)
     ↓
notification_service                     (unchanged M03/M04 rules and dedup)
```
- **Routes stay thin.** `/api/hazards/*` and `/hazards/<id>/response` only parse input and map
  errors.
- **Shared scope rule.** `authority_response_service.can_manage` is the M02 rule (admin: all;
  authority: events whose primary district is its authority's district). `_load_managed_incident`
  now uses it, so the behaviour is unchanged.

### 3. Status lifecycle
```
detected → investigating → confirmed → response → resolved
detected → rejected        investigating → rejected        confirmed → resolved (M02, kept)
```
- **`response` is new.** It means the authority response is under way. It is an *active* status
  (in `ACTIVE_STATUSES`), so dashboards, lists, M02 dedup and M04 area expansion treat it like
  `confirmed`.
- **Terminal states stay terminal:** `resolved` and `rejected`. No reopening was implemented.
- **Every M02 transition is still valid.**
- **Notes:**
  - `resolved` and `rejected` require a note (string, trimmed, ≤ 2000 chars).
  - Other transitions take an optional note.
  - This rule is enforced at the M09 service/API layer. Internal service callers (e.g. M04
    tests) can still resolve without a note.

### 4. Models / migration
Migration `c3d7f1a9b6e2_m09_authority_response.py` (revises `b5c9e3f7a142`) is additive: three
tables with foreign keys and `incident_id` indexes. `incidents.status` is already a `String(20)`,
so `response` needs no schema change.

| Table | Columns | Notes |
|---|---|---|
| `incident_status_history` | incident_id, previous_status, new_status, changed_by_id (NULL = system), note, created_at | one row per transition, same transaction as the status change |
| `incident_investigations` | incident_id, author_id, note, created_at | append-only (no edit/delete) |
| `incident_response_actions` | incident_id, author_id, action_type, description, status, created_at, updated_at, completed_at | type ∈ inspect_site, close_road, evacuate_area, deploy_team, contact_local_authority, place_warning, monitor_area, other. Status planned → in_progress → completed; planned/in_progress → cancelled; completed/cancelled are final. `completed_at` is server-set |

**Migration verification:** run on a copy of the dev DB seeded with legacy incidents (one
`confirmed`, one `resolved`) and a citizen report.
- upgrade → downgrade → upgrade, with identical row counts and incident rows each time
- `flask db check`: no drift
- The legacy `confirmed` incident then went → `response` → `resolved`.
- The legacy `resolved` incident stayed terminal.
- Its timeline uses `detected_at` for the detection entry, so no backfill is needed.

The local dev DB was backed up to `instance/hackforge.pre-m09.db` and upgraded to `c3d7f1a9b6e2`.

### 5. API
All endpoints are manager-only: authority in its own district, or admin. They return JSON errors:
401 not logged in, 403 citizen / other district / unlinked authority, 404 unknown, 400
validation, 409 closed incident or concurrent change.
| Method | Endpoint | Notes |
|---|---|---|
| POST/PATCH | `/api/hazards/<id>/status` `{status, note?}` | existing M02 endpoint, now audited; note required for resolved/rejected |
| POST | `/api/hazards/<id>/resolve` `{resolution_notes}` | existing; note now **required** |
| POST | `/api/hazards/<id>/reject` `{reason}` | existing; reason now **required** |
| PATCH | `/api/hazards/<id>` `{status?, note?, …}` | existing manager edit; a status change follows the same rules |
| GET | `/api/hazards/<id>/status-history` | history + `allowed_transitions`; read-only (POST/PATCH/DELETE → 405) |
| GET/POST | `/api/hazards/<id>/investigations` `{note}` | |
| GET/POST | `/api/hazards/<id>/response-actions` `{action_type, description, status?}` | |
| PATCH | `/api/hazards/<id>/response-actions/<action_id>` `{status?, description?}` | the action must belong to that hazard (404 otherwise) |
| GET | `/hazards/<id>/response` (page) | authority/admin incident-response page |

**Client-controlled fields rejected (400)** on the status, note and action endpoints: `severity,
source, risk_level, confidence, reporter_id, device_id, authority_id, author_id, changed_by(_id),
incident_id, completed_at, created_at, previous_status, ai_label, ai_confidence, ai_model`.
Severity is still editable only through the existing M02 `PATCH /api/hazards/<id>` manager
edit.

### 6. Authorization
- **Citizen:**
  - Sees public hazard data (status including `response`, severity, type, affected districts,
    times) and their own notifications.
  - Cannot investigate, confirm, reject, start a response, resolve, add notes or actions, or read
    history.
- **Authority:** all M09 actions on events whose primary district is its authority's district.
- **Admin:** all M09 actions system-wide.

### 7. Privacy (internal vs public)
- **Internal** (manager endpoints and the response page only): investigation notes, response
  actions, status history with notes, and author usernames (never user ids or emails).
- **Public serializers are unchanged** (`Incident.to_dict(include_internal=False)`), and the M07
  citizen dashboard gets no response data.
- **Description fix:** `/resolve` and `/reject` used to append the note to the **public**
  `Incident.description` ("Resolution: …"). M09 stores it only in the status history. Four
  existing assertions (in `test_hazard_event_service.py` and `test_hazard_events_api.py`) were
  updated for this privacy change.

### 8. Audit trail
- **One history row per successful transition**, recording old and new status, actor (NULL for
  system callers), timestamp and note, written in the same transaction as the status change.
- **Concurrency:** `_apply_transition` uses a compare-and-set `UPDATE … WHERE id=? AND status=<validated
  status>`.
  - A stale or concurrent request matches 0 rows and raises `TransitionConflict` (409); the whole
    transaction rolls back, writing no history.
  - A repeated identical request is rejected as an invalid transition.
  - The service also re-reads the row (`refresh`) before validating.
- **Atomicity:** if the history insert fails, the status change rolls back with it (tested by
  forcing a NOT NULL violation).
- **Timeline** (response page) = detection (`detected_at`) + status changes + notes + actions,
  in time order: what, when, who, why, what action, when resolved.

### 9. Notifications
- M03/M04 remain the only notification source.
- `investigating`, `response`, notes and actions send nothing.
- `confirmed` and `resolved` send the existing `hazard_confirmed` / `hazard_resolved` once per
  recipient (existing dedup keys).
- The detected and escalated alerts are never duplicated (tested).
- **M04 compatibility fix:** `notify_area_expanded` also sends `hazard_confirmed` to newly covered
  districts when the status is `response`, because response follows confirmation.

### 10. Frontend
- **`/hazards/<id>/response`** (Jinja, server-rendered, autoescaped):
  - summary (type, severity, status, source, detected time, location) and M04 affected districts
  - only the transition buttons valid for the current status (e.g. Start Investigation / Reject
    Hazard at `detected`)
  - note field (required for resolve/reject, also checked client-side)
  - timeline; add-note form; response actions with only valid next-status buttons; add-action form
  - read-only M08 assessment ("evidence only")
  - Closed incidents show "cannot be reopened" and no forms.
  - The JS only sends JSON with CSRF and reloads. Errors are shown with `textContent`; there is no
    `innerHTML`.
- **M07 dashboard:**
  - Status labels for everyone (Detected / Investigating / Confirmed / Response in progress).
  - For managers, each hazard card also shows notes / open-action counts (two `GROUP BY` queries,
    no N+1) and an "Open response" link.
  - Citizens get no response data.
- All new strings have Nepali translations.
- Manually checked in Chrome on the migrated scratch DB:
  - the legacy confirmed incident → response; note + action shown
  - resolving with an empty note was refused client-side; resolving with a note worked
  - `<script>`/`<b>` in notes rendered as text; no console errors

### 11. Tests
`tests/test_authority_response_m09.py` (127 tests, including parametrized cases):
- **Lifecycle:**
  - full path with exact audit rows; both rejected paths; confirmed → resolved kept
  - 12 invalid transitions (terminal → anything, skips, unknown, empty) with no history
  - resolution note validation (7 bad inputs); legacy resolve/reject require notes
  - PATCH follows the same rules; a duplicate request gives one history row
- **Integrity:**
  - a stale object gets a conflict and full rollback
  - a history insert failure rolls back the status
  - conflict maps to 409
- **Authorization:**
  - 9 endpoints × (anonymous 401, citizen 403, other authority 403, unlinked authority 403), with
    no state change
  - authority and admin allowed; admin system-wide
  - history is read-only (405)
  - response page access matrix
- **Input manipulation:** 8 forbidden fields × 3 endpoints, with no change.
- **Investigations:**
  - add/list with author and time, no user ids
  - 7 invalid notes; a closed incident → 409
- **Response actions:**
  - create → in_progress → completed (`completed_at` server-set), final states are final
  - created as completed; cancel
  - 10 invalid creates; 6 update cases; no going back; the action must belong to the incident
- **Privacy:**
  - citizens see no notes, actions, authors, `source_reference` or device refs in the hazard API,
    list, dashboard, notifications or pages
  - the resolution note is never public
  - managers see the response summary
- **Notifications:**
  - no duplicate detected/escalated alerts; investigation/response send nothing
  - confirmed/resolved once per recipient
  - area expansion during response; `response` is active everywhere
- **Page:**
  - only valid controls per status; closed view
  - XSS payloads escaped in notes and actions; Nepali

**Changed existing tests (6 assertions, all deliberate M09 contract changes):**
- `test_hazard_event_model.py`: `HAZARD_STATUS` and `VALID_STATUS_TRANSITIONS` gain `response`.
- `test_hazard_event_service.py` and `test_hazard_events_api.py`: the resolve/reject notes are no
  longer in the public description and are now asserted in the status history.

**Full suite: `python -m pytest tests/ -q` → 558 passed, 79 warnings** (M08 baseline 431 passed, 79
warnings; +127 new; the warning count is unchanged).

### 12. Security status
- **In place:** authentication, RBAC, authority scope (M02 rule), admin scope, CSRF on all
  writes (Flask-WTF, as before), input validation, XSS-safe rendering.
- **No leaks:** no private data in public serializers; no client-controlled
  severity/source/risk/confidence/actor fields.
- **No new notification path.**
- **Still open (M10):** the M07/M08 finding that `GET /api/iot/devices?district_id=` lets an
  authority user not linked to an authority list another district's devices.

### 13. Known limitations
- **Scope uses the primary district only:** authority scope follows the M02 rule, so an authority
  of an M04 *additional* affected district can see the hazard but cannot manage it.
- **No reopening:** a wrongly resolved or rejected incident needs a new event.
- **Append-only notes and actions:** there's no edit or delete. Corrections are new notes, or a
  cancelled action plus a new one.
- **Detection in the timeline** comes from `detected_at`. Pre-M09 transitions on legacy incidents
  have no history rows, and pre-M09 resolve/reject notes remain in those incidents' descriptions
  (no data was rewritten).
- **Concurrency on SQLite:** handled by compare-and-set within SQLite's single-writer model. There
  is no distributed locking.
- **No outbound channels:** no SMS, email or push; the in-app notifications are the existing
  M03 ones.
- Nothing here has been validated in a real emergency operation.

### 14. Hardware dependencies
None. M09 works on events from any source. The physical sensors are still not built or validated.

### 15. Files
- **Created:**
  - `app/models/incident_response.py`
  - `app/services/authority_response_service.py`
  - `app/templates/pages/hazard_response.html`
  - `migrations/versions/c3d7f1a9b6e2_m09_authority_response.py`
  - `tests/test_authority_response_m09.py`
- **Modified:**
  - `app/models/incident.py` (lifecycle), `app/models/__init__.py`
  - `app/services/hazard_event_service.py` (audited compare-and-set transitions; notes out of the
    public description)
  - `app/services/notification_service.py` (M04 area expansion during `response`)
  - `app/routes/hazard_events.py` (thin status routes via the service; new endpoints)
  - `app/routes/monitoring.py` (response page)
  - `app/services/dashboard_service.py`, `app/templates/pages/monitoring.html` (status labels,
    manager response summary)
  - `app/services/page_strings.py`
  - `tests/test_hazard_event_model.py`, `tests/test_hazard_event_service.py`,
    `tests/test_hazard_events_api.py`
  - `docs/PROJECT_PROGRESS.md`
- **Deleted:** none
- **Not committed:** M08 is still uncommitted in the working tree alongside M09.

### 16. Next milestone
**M10 — Security/Reliability/Production Hardening** (not started).

### 17. Git commit
```
feat(m09): add authority response system
```

### 🏷️ Status
**M09 — AUTHORITY RESPONSE SYSTEM COMPLETE · HUMAN DECISIONS AUDITED · NO NEW DETECTION OR ALERT PATHS**

---

# M10 — Security/Reliability/Production Hardening

### Objective
Find and fix security, authorization, validation, reliability, privacy and production-readiness
weaknesses left after M01–M09, without adding features or changing the M01–M09 rules (water level
in metres, M02 dedup, M03/M04 notifications, M05/M05.1 report rules, M06 evidence-only AI, M07,
M08, M09 lifecycle).

### Security audit performed
Every route module was reviewed: `iot`, `hazard_events`, `reports`, `notifications`,
`monitoring`, `auth`, `authority_panel`, `complaints`, `projects`, `rivers`, `profile`, `posts`,
`social`, `ai_routes`. For each sensitive endpoint the review answered: who can call it, which
object and district, which fields can be written, whether ids or query parameters can be swapped,
and whether a citizen or another authority can act. Repo-wide searches covered:
- `innerHTML` / `insertAdjacentHTML` / `document.write` / `|safe` / `Markup`
- logging and `print`
- `csrf.exempt`, error handlers, `Query.get`
- `current_user.authority*` assumptions
- generic serializers (`__dict__`, `vars`): none found

The migration chain was checked from an empty database and on a dev-DB copy. Every finding has a
regression test, and **65 of the new tests fail on the pre-M10 code** (verified in a temporary
worktree of HEAD with the staged M08/M09 changes applied).

### Vulnerabilities found and fixed
| # | Finding | Impact | Fix | Tests |
|---|---|---|---|---|
| 1 | **Public `/auth/authority/register`** created a pre-verified (`is_verified=True`) authority for any district | Critical: anyone became a district manager (private reports and photos, confirm/resolve/reject, severity escalation alerts, device keys) | Off unless `AUTHORITY_SELF_REGISTRATION=true` (default false). Link hidden. README documents admin provisioning | `TestAccounts` |
| 2 | `GET /api/iot/devices`: authority **not linked** to an authority fell through to `?district_id=` / home district (known M07/M08 gap) | High: device metadata of any district | Unlinked authority → 403. Linked authority → own devices only (`district_id` can't widen scope). Admin → all, optional validated filter | `test_unlinked_authority_cannot_list_devices`, `test_device_list_scope` |
| 3 | `PATCH /api/iot/devices/<id>` and `rotate-key`: ownership check `device.authority_id != current_user.authority_id` was `None != None` → **False** for an unlinked authority on unowned devices | High: disable/reconfigure devices and **take over their API keys** | `_can_manage_device`: admin, or a linked authority owning the device | `test_update_and_rotate_ownership` (9 cases) |
| 4 | Authority panel IDOR: `/authority/complaints/<id>` (read and respond), `/authority/{projects,roads,rivers}/<id>/update` loaded any object by id | High: read/answer other authorities' complaints, change other districts' roads/rivers/projects | Scoped to the authority (complaint/project `authority_id`, road/river district) → 404 | `TestObjectLevelAuthorization` |
| 5 | `POST /projects/<id>/update` and `POST /rivers/<id>/update` open to **any logged-in user**; the river route used its own 60%/80% "high" thresholds | High: citizens could change public project progress and river levels/status; inconsistent with M01 | Admin or scoped authority only (403). River status now uses M01 `compute_river_status`; values validated | `test_public_update_routes_need_scoped_manager` |
| 6 | `GET /complaints/<id>` readable by any logged-in user | Medium: other citizens' complaint text | Complainant, the authority it was filed to, or admin; others 404 | `test_complaint_detail_scoped` |
| 7 | Telemetry accepted `NaN` (NaN fails every comparison, so it passed the range check and then hit a NOT NULL **500**), booleans (`true` → 1.0), numeric strings. Non-object readings, non-string `sensor_type`/`timestamp` and non-object bodies caused 500s | Medium: crashes and invalid data accepted | JSON numbers only (no bool), finite; readings must be objects; types checked; `validate_sensor_reading` itself rejects non-finite | `TestTelemetryValidation` (22 payloads, 7 timestamps) |
| 8 | Global `CSRFProtect` without an exemption for `POST /api/iot/telemetry` | Functional: a real ESP32 (no session, no token) would always get 400 outside tests | `@csrf.exempt` on that view only: it is authenticated by the device API key header and uses no cookies. All session-based writes still require a token | `TestCsrf` |
| 9 | XSS: LLM answers, the user's question, and classifier output inserted with `innerHTML` (`ai_assistant`, `create_post` preview, `test_classify`) | Medium: a model answer containing `<img onerror>` executes | DOM building with `textContent`/`createTextNode` | `TestXss`; manual Chrome check (payload rendered as text) |
| 10 | Open redirect: login `?next=` used unvalidated | Medium: phishing redirect after a real login | `_safe_next`: same-site relative paths only | `test_login_next_is_same_site_only` |
| 11 | `/profile/<id>` showed every user's email and phone to all users | Medium: personal data disclosure | Shown to the profile owner and admins only | `test_profile_contact_details_private` |
| 12 | `POST /api/iot/devices` with `river_id` → **500 `NameError`** (`River` not imported), same in PATCH | Reliability: M01 river association unusable via API | Import fixed; registration and updates fully validated (device id pattern without `:`, ints, text limits, coordinates). PATCH rejects unknown/server fields (`api_key_hash`, `authority_id`, `district_id`, `device_id`), non-bool `enabled`, bad status | `TestDeviceInput` |
| 13 | `/api/iot/latest?limit=-1` → SQLite `LIMIT -1` = unlimited | Low: full readings-table scan per request | Clamped to 1..500 | `test_latest_limit_cannot_be_disabled` |
| 14 | `init_db.py` (`create_all`) left no Alembic version, so the next `flask db upgrade` replays every migration on existing tables and **fails**. The initial migration only adds IoT tables, so the chain can't build an empty DB either | Reliability: fresh installs could never take later migrations | `init_db.py` stamps the head after `create_all()`. Historical migrations untouched | `test_fresh_install_is_migration_tracked` |
| 15 | Production config fell back to the public `SECRET_KEY` default; remember-me cookie not `Secure`; `/api/*` errors were HTML; no CSP/Referrer/Permissions headers | Low/Medium: session and CSRF forgery if deployed with the default | `create_app('production')` refuses the default/empty key. `REMEMBER_COOKIE_SECURE/HTTPONLY/SAMESITE`. JSON errors for `/api/*` (500 → `{"error": "Internal server error"}`, no traceback). CSP + `Referrer-Policy` + `Permissions-Policy` | `TestErrorsAndHeaders` |
| 16 | Profile edit `district_id` → 500 on non-numeric, dangling id on unknown | Low | Validated | `test_profile_bad_district_rejected` |
| 17 | N+1: notification lists (incident + districts per row); M09 history/notes/actions (author per row) | Performance | Eager loading | `test_notification_and_response_lists_do_not_grow_per_row` |

### Authorization matrix (final, tested in `TestAuthorizationMatrix` + M05/M07/M09 suites)
```
Resource                         Citizen A       Authority A     Authority B     Unlinked auth   Admin
-------------------------------------------------------------------------------------------------------
Device A (list/update/rotate)    NO (403)        YES             NO (403)        NO (403)        YES
Unowned device (no authority)    NO              NO              NO              NO (was YES)    YES
Telemetry readings /latest       read (M01 public telemetry; citizens default to own district)
Hazard A: read (public fields)   YES             YES             YES             YES             YES
Hazard A: manage / M09 / M08     NO (403)        YES             NO (403)        NO (403)        YES
Private report A + image         own only        YES (district)  NO (404)        NO (404)        YES
Complaint by citizen A           own only        YES (filed to)  NO (404)        NO (404)        YES
Panel road/river/project A       NO              YES             NO (404)        NO (panel)      n/a (panel needs a linked authority)
Notifications                    own             own             own             own             own
Profile email/phone              own             own             own             own             all
```

### Input validation
- **Telemetry:** finite JSON numbers only; strings for type and unit; object readings; ≤ 50 per
  batch; ISO-8601 string timestamps, normalized to naive UTC (offsets such as `+05:45`
  converted). Units and ranges are unchanged (water level in metres).
- **Devices:** strict types, length limits and coordinate ranges; server-owned fields rejected.
- **Panel/forms:** status, traffic and complaint values limited to the form options; water level
  finite 0–50 m; progress 0–100.
- **Mass assignment:** no `Model(**json)` or `setattr` loops anywhere. Only allow-listed fields
  are written (M05.1 / M09 / M10).

### File security (M05/M06, re-verified)
- **Upload validation:** extension + MIME + decoded format must agree; 10 MB / 40 MP limits
  before decoding; re-encoded JPEG drops EXIF/GPS.
- **Storage:** server-generated `<uuid>.jpg` name; images live outside `static` and are served
  only by the authorized route.
- **Malicious filenames:** client filenames (`../../`, `..\..`, `<script>.jpg`) never touch the
  filesystem.
- **Analysis input:** the vision service accepts bytes only, from that validated stored file.

The tests are M05's upload suite plus the M10 matrix (cross-district report and image → 404).

### Privacy
- **M09 notes, actions and history** remain manager-only, and resolve/reject notes stay out of
  public fields (M09 tests unchanged).
- **Notifications** are owner-scoped: another user's id gives 404, and read-all touches only
  your own rows.
- **No secrets in responses:** API key hashes, raw payloads and `source_reference` appear in no
  response.
- **Profile contact details** are now private (#11).
- **Logging:** only one warning (report id + reason) and one Ollama exception `print`. No
  credentials, headers or private data are logged.

### CSRF / XSS
- **CSRF:** stays global. The only exemption is the device-key-authenticated telemetry
  endpoint. Tested with CSRF enabled: hazard status, M09 notes, PATCH hazard, notifications
  read-all and device key rotation all get 400 without a token and succeed with one.
- **XSS:** Jinja autoescape everywhere (no `|safe`). The three innerHTML sinks were fixed; the
  remaining `innerHTML` uses are static icon strings only.

### IoT security
- **Keys:** SHA-256 hashed at rest and shown once at creation or rotation. Rotation invalidates
  the old key immediately.
- **Device rules:** disabled devices get 401, and one device's key can't post as another.
  Ownership is enforced for authorities, including unlinked ones.

### Transaction reliability
- **M09:** the status change and history row are atomic, with compare-and-set transitions
  (unchanged; tested in M09).
- **Key rotation and registration:** single commit.
- **Validation before writes:** panel/complaint updates validate before mutating, so an invalid
  status leaves the complaint unchanged (tested).
- **Telemetry:** stores only valid readings, rejects the batch if none are valid, and invalid
  readings never reach the database (a NaN used to cause a 500 IntegrityError).

### Migration verification
- **Head round trip:** `c3d7f1a9b6e2` downgrade → upgrade on a copy of the dev DB, with row
  counts identical and `flask db check` clean.
- **Fresh install:** `init_db.py` builds the schema and is stamped at head; then upgrade (no-op)
  → check → downgrade → upgrade → check all pass (automated in
  `test_fresh_install_is_migration_tracked`).
- **History untouched:** no historical migration was modified and no new migration was needed.
- **Limitation:** an empty database still cannot be built by `flask db upgrade` alone, because
  the first migration assumes the pre-M01 schema. `init_db.py` is the supported path.

### Configuration hardening / HTTP headers
- **Production secret:** production refuses a missing or default `SECRET_KEY`. `.env.example`
  explains how to generate one. No secrets are printed.
- **Cookies:**
  - Session: `HttpOnly`, `SameSite=Lax` (`Strict` in production), `Secure` in production.
  - Remember-me: `HttpOnly`, `SameSite=Lax`, `Secure` in production.
  - Development stays on HTTP.
- **Headers:** `X-Content-Type-Options`, `X-Frame-Options` (existing), plus `Referrer-Policy:
  strict-origin-when-cross-origin`, `Permissions-Policy: camera=(self), geolocation=(self),
  microphone=()` and a CSP:
  - `default-src 'self'`; scripts from self + unpkg (Leaflet, Lucide)
  - styles from self + Google Fonts + unpkg; fonts from gstatic
  - images from self, data:, blob:, unpkg and OSM tiles
  - `connect-src 'self'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`,
    `frame-ancestors 'self'`

  `'unsafe-inline'` is still needed for scripts and styles because templates use inline blocks
  and `onclick` handlers.
- **CSP checked in Chrome:** the monitoring map (tiles, Leaflet, icons, fonts), `/report`
  (camera input, geolocation button), the AI assistant, the dashboard and the M09 response page
  all loaded with no console violations.

### Test results
- **Baseline (M09):** 558 passed, 79 warnings.
- **Final:** **`python -m pytest tests/ -q` → 678 passed, 44 warnings.**
- **New:** **120** tests in `tests/test_security_m10.py`. No existing test was changed.
- **Warnings 79 → 44:**
  - Removed the legacy `Query.get()` on the telemetry path and in the user loader. These ran on
    every telemetry request and every logged-in request.
  - Remaining: `Query.get()` in older non-security routes (`social.py`, `profile.py`, `main.py`,
    authority panel dashboard) and older tests, plus third-party SWIG `DeprecationWarning`s from
    the sentencepiece/torch stack. They are harmless and deferred.

### Remaining known limitations
- **No rate limiting or lockout.** Login, report submission and telemetry have no rate limit or
  account lockout (no infrastructure for it). Requests are only bounded by size limits
  (`MAX_CONTENT_LENGTH` 16 MB, 10 MB photos, 50 readings per batch).
- **Weak CSP for scripts.** The CSP needs `'unsafe-inline'`, so it does not stop inline-script
  injection on its own. A nonce-based CSP needs the templates' inline scripts and handlers moved
  out, which is a frontend refactor.
- **Public telemetry readings.** `/api/iot/latest` readings are public to logged-in users by M01
  design and include the numeric device pk (no credentials).
- **Community post photos** are still stored under public `static/uploads` with an extension
  allow-list and random name, without decode/re-encode as in M05 (documented since M05).
  `nosniff` prevents content-type confusion.
- **No unique `(user_id, post_id)` constraint on likes.** A race can double-like; there is no
  security impact.
- **The migration chain can't build an empty DB alone** (see migration verification).
- **No validation of deployment.** Nothing has been validated for production deployment,
  real-world emergency use or physical hardware.

### Deferred technical debt
- Remaining `Query.get()` legacy calls (44 warnings).
- Inline scripts and `onclick` handlers (blocking a strict CSP).
- A login/telemetry rate limiter if a reverse proxy or extension is introduced.
- `/api/iot/latest` could drop the internal device pk for citizens.
- Re-encoding community post photos like M05.

### Files
- **Created:** `app/services/form_validation.py`, `tests/test_security_m10.py`
- **Modified:**
  - `app/__init__.py`, `app/config.py`
  - `app/routes/iot.py`, `app/routes/auth.py`, `app/routes/authority_panel.py`,
    `app/routes/complaints.py`, `app/routes/projects.py`, `app/routes/rivers.py`,
    `app/routes/profile.py`
  - `app/services/risk_engine.py`, `app/services/notification_service.py`,
    `app/services/authority_response_service.py`
  - `app/templates/auth/authority_login.html`, `app/templates/pages/profile.html`,
    `app/templates/pages/ai_assistant.html`, `app/templates/pages/create_post.html`,
    `app/templates/pages/test_classify.html`
  - `init_db.py`, `.env.example`, `README.md`, `docs/PROJECT_PROGRESS.md`
- **Deleted:** none. **Migrations:** none.
- **Not committed:** M08 and M09 are still staged and uncommitted in the working tree. The M10
  changes are unstaged on top and were not mixed into the index.

### Next milestone
**M11 — Full Software Integration Testing** (not started).

### Git commit
```
feat(m10): harden security and reliability
```

### 🏷️ Status
**M10 — SECURITY/RELIABILITY HARDENING COMPLETE · 17 FINDINGS FIXED · NOT A PRODUCTION DEPLOYMENT**

---

# M11 — Full Software Integration Testing

> **Software integration has been verified using synthetic/test inputs. Physical IoT hardware has not
> yet been validated.** No claim of real flood or earthquake detection, MPU6050/JSN-SR04T field
> accuracy or emergency readiness is made.

### Objective
Prove that the complete pipeline works across components, and that a failure in one component does
not corrupt another. There are no new features.

### Integration architecture tested
```
synthetic telemetry / multipart photo report
  → device auth + validation (M01/M10) → M08 risk_service/risk_engine → M02 hazard_event_service
  → M04 affected districts → M03/M04 notification_service (dedup) → M07 dashboard_service
  → M09 authority_response_service (CAS transitions + audit) → resolution alert
citizen report → M05 image pipeline → M06 vision (deterministic stub) → M08 evidence grade → review
```
- **Driven through the real app:** every test goes through the HTTP API (Flask test client) and
  checks database rows (`Incident`, `SensorReading`, `CitizenReport`, `Notification`,
  `IncidentAffectedDistrict`, `IncidentStatusHistory`, `IncidentInvestigation`,
  `IncidentResponseAction`, `IoTDevice`), not just status codes.
- **Vision:** uses the existing M06 pixel-driven stub `PixelStub` (no model download, no network).
- **Seismic input** is synthetic vibration/tilt telemetry.

### End-to-end scenarios (`tests/test_integration_m11.py`, 15 tests)
| Test | Components proven together |
|---|---|
| `test_iot_flood_pipeline_end_to_end_through_resolution` | telemetry → risk → event → alerts → citizen and authority dashboards → escalation → investigate/note/confirm/response/action/resolve → resolution alert → unread / mark-read / mark-all; DB + FK checks at each step |
| `test_repeated_telemetry_does_not_spam_alerts` | 4× rising + 3× flooding → one event, 7 readings, exactly one detected + one escalated alert per recipient |
| `test_invalid_telemetry_does_not_corrupt_existing_state` | NaN/cm/bool/bad timestamp/bad key rejected; mixed batch stores only the valid reading; event and alerts unchanged except the valid evidence |
| `test_latest_readings_reach_dashboard_per_sensor_type` | old vs new `water_level` (by timestamp), `vibration`, `tilt` → correct latest on dashboard and `/api/iot/latest`; other authority's device hidden |
| `test_seismic_software_simulation_of_mpu6050_input` | default config: no event. With a configured threshold: an isolated spike → none; sustained motion → one `earthquake` "Abnormal ground motion signal" event at medium; more motion merges, never escalates; no magnitude or prediction wording; district B untouched; M08 assessment `elevated_motion` |
| `test_landslide_reports_flow_through_vision_dedup_and_authority_response` | 3 reports (2 reporters, one duplicate) → one incident (`report_count` 3); AI agree/unknown stored; grade `corroborated` (duplicate counted once) → rejected report ignored → `supported`; severity stays medium; M09 lifecycle; AI result untouched |
| `test_road_damage_ai_disagreement_stays_evidence` | citizen road_damage + AI landslide: type, severity, status, areas and alerts unchanged; grade shows the conflict; review page flags it; authority confirm → response → completed action → resolve; terminal afterwards |
| `test_vision_failure_and_report_write_failure_leave_consistent_state` | AI failure → report kept, `failed`, image served to the authority, re-analysis works; a DB failure while linking the report → 500, no report/incident/alert rows, no orphan image file |
| `test_affected_districts_target_alerts_and_keep_m09_primary_scope` | add B, C (duplicate 409) → their users alerted, D not; removing C keeps its history; escalation reaches current areas only; authority B sees but can't manage; D added after confirmation gets detected + confirmed once |
| `test_multi_signal_evidence_stays_within_event_scope` | flood A + landslide report B (AI) + motion B → three events; each assessment uses only its own river/devices/reports; A users alerted about A only; authority A gets 403/404 on B |
| `test_concurrent_confirmations_one_wins` | two confirmations in **separate app contexts / DB sessions**, the second fired after the first validated → one 200, one 409; one history row; one confirmed alert per recipient |
| `test_notification_failure_rolls_back_whole_operation` | notification failure → telemetry 500 with **no** incident/alert/reading rows; retry succeeds; a failing confirmation leaves status and history unchanged |
| `test_cross_component_authorization_on_live_state` | citizen, other authority, unlinked authority and admin against live hazards, reports, images and devices; wrong device key 401; nothing changed |
| `test_private_data_never_leaks_through_integrated_apis` | 13 endpoints × (2 citizens, other-district authority): no keys, hashes, raw payload, storage/model paths, report text, notes, actions, resolution note or `source_reference`. The managing authority sees notes but never credentials or paths |
| `test_dashboard_reflects_integrated_state_and_stays_read_only` | multi-district hazards, devices, readings, AI reports, response counts; admin / district filter / authority / citizen scopes match the rows; DB snapshot unchanged |

### Findings fixed during M11
1. **`source_reference` was shown to every authority.** `GET /api/hazards*` serialized internal
   fields for *any* authority, so district-B authorities could see which device/user/report
   produced a district-A hazard. Fixed: internal fields only when
   `authority_response_service.can_manage(current_user, incident)` (admin or the event's district
   authority). The existing M02 test (own-district authority sees it) still passes.
2. **Failed requests weren't rolled back per request.** A request that raised relied only on the
   app-context teardown to roll back. When several requests share one app context (tests,
   scripts), a failed telemetry request left its flushed event and reading in the session.
   - Production (one app context per request) was not affected. A standalone reproduction
     confirmed the rollback happens there.
   - Added a `teardown_request` rollback on error, so the all-or-nothing guarantee holds
     regardless of context lifetime.

Both are covered by tests that fail on the pre-M11 code (verified in a temporary worktree of
`5611746`: exactly these 2 failed, the other 13 passed).

### Flood pipeline
The M01/M08 rules are unchanged: < 80% normal, 80–100% rising (medium), ≥ 100% flooding (high),
water level in **metres**. These are current engineering rules, not validated real-world
thresholds.

### Seismic software simulation
Synthetic MPU6050-style input only:
- The thresholds are configured inside the test (production default: unset → no automatic event).
- No magnitude is invented and nothing is predicted.

### Notifications
- **One alert per lifecycle step:** detected, escalated (per severity level), confirmed and
  resolved each fire once per recipient.
- **Silent steps:** investigating, response, notes and actions send nothing.
- **Recipients:** users whose home district is affected (citizens and authority users, including
  unlinked authority accounts), the responsible authority's users, and admins.
- **Ownership and read state:** owner-scoped, with unread counts, mark-read and mark-all verified.
- **Failure guarantee (actual):** notifications are written in the same transaction as the event
  or status change, so a notification failure aborts the whole operation: the request gets a 500
  and the device or user can retry. Nothing is half-written, but the evidence in that request is
  not stored either.

### Authority response
The full lifecycle is checked:
- history rows, actors and timestamps
- internal notes, and the public description unchanged
- the action lifecycle with server-set `completed_at`
- the required resolution note
- terminal states and invalid transitions
- the concurrency conflict

### Security integration
The M05/M09/M10 scopes hold on live, multi-component state: citizen, authority A, authority B,
unlinked authority and admin. Device keys can't impersonate each other. The full M10 suite still
passes.

### Dashboard integration
Summary counts, hazard lists, devices, latest readings, AI reports, M09 response counts and admin
statistics match the database rows for every scope. The admin district filter works, and the
dashboard performs no writes.

### Database verification
FK relationships were checked after the flows:
- every alert → its incident
- readings → device
- report → incident
- note/action → incident + author
- affected-district rows → incident

### Migration verification
- **Dev DB:** at head `c3d7f1a9b6e2`; `flask db check` reports no new operations.
- **Supported fresh install** (disposable file DB): `init_db.py` stamps the head, then
  `flask db check` is clean. A smoke run through the HTTP API on that file DB (separate app
  context per request) gave one high flood event, 3 readings, the citizen's detected + escalated
  alerts, and a dashboard showing it.
- **Also automated:** `tests/test_security_m10.py::test_fresh_install_is_migration_tracked`.
- **Unchanged limitation:** `flask db upgrade` alone still can't build an empty database (the first
  historical migration assumes the pre-M01 schema). `init_db.py` is the supported path. No
  migration was modified or added.

### Test results
- **Baseline (verified before changes):** 678 passed, 44 warnings.
- **Final:** **`python -m pytest tests/ -q` → 693 passed, 44 warnings** (678 + 15 new; warning count unchanged)
- **New:** 15 integration tests. No existing test was changed.

### Known limitations
- **Synthetic input only.** All sensor input is synthetic. No ESP32, JSN-SR04T or MPU6050 has
  been connected, so timing, noise, power, Wi-Fi drops and real reporting intervals are untested.
- **No real model in tests.** Vision AI uses the deterministic stub; the real SigLIP path is
  covered only by M06's one real-model test.
- **Concurrency model.** Concurrency is simulated with two app contexts on SQLite's shared
  in-memory connection. It proves the compare-and-set logic, not multi-process/multi-host
  behaviour under load.
- **Notification failure loses evidence.** It discards the whole request, including the readings
  (no partial save, no retry queue).
- **No load or soak testing.** No browser-level end-to-end automation beyond the manual Chrome
  checks of M07, M09 and M10.
- **Documentation conflict (DHT22), resolved after M11.** The DHT22 has been removed from the final
  hardware documentation (see "Hardware architecture update — DHT22 removed"). M11 tests use only
  `water_level`, `vibration` and `tilt`.

### Files
- **Created:** `tests/test_integration_m11.py`
- **Modified:**
  - `app/routes/hazard_events.py`: `source_reference` only for the event's managers
  - `app/__init__.py`: per-request rollback on error
  - `docs/PROJECT_PROGRESS.md`
- **Deleted:** none
- **Migrations:** none

### Next milestone
**H01 — ESP32 Hardware Foundation** (not started).

### Git commit
```
test(m11): add full software integration testing
```

### 🏷️ Status
**M11 — FULL SOFTWARE INTEGRATION TESTING COMPLETE · SOFTWARE INTEGRATION VERIFIED · PHYSICAL HARDWARE NOT YET VALIDATED**

---

## Hardware architecture update — DHT22 removed (after M11)

The DHT22 temperature/humidity sensor is **no longer part of the final X-MAN hardware**. It only
ever provided environmental context, never drove a risk rule, and no other environmental sensor
replaces it.

**Final hardware:**
```
ESP32 #1 — Flood
└── JSN-SR04T waterproof ultrasonic sensor → water_level (metres)

ESP32 #2 — Seismic
└── GY-521 (MPU6050) → vibration (mg), tilt (°)

Smartphone
├── Camera → landslide / road-damage evidence
└── GPS → citizen report location
```

**Effect on software: none.**
- **Code:** no code, firmware, model, migration or test depended on the DHT22. The only code
  mention was the example text in the `POST /api/iot/devices` docstring, which was updated.
- **Sensor types:** the final hardware uses `water_level` (m), `vibration` (mg) and `tilt` (°).
- **API unchanged:** the telemetry API, units and validation table are unchanged. The generic
  `temperature`, `humidity` and `rainfall` types are still accepted by the validation table, but no
  final device sends them and no risk rule uses them.

**Documentation changed:**
- `README.md`: hardware tree, flood/seismic node notes, telemetry table, component list, and
  not-required list.
- This file: the pre-M07 hardware entry is updated in place with a note; the M08 hardware
  dependency and the M11 conflict note are updated.

Physical hardware is still **not built or validated**.

**Next milestone:** M11.5 — Product Quality (see below), then M12 and H01.

---

# M11.5 — Product Quality: Accounts, Dashboards and Design System

Inserted before H01. No ESP32, firmware or hardware architecture changes. No security or RBAC rule
was weakened. Backend hazard, risk and notification logic is unchanged; only presentation and
read-only aggregation were added.

### Audit (before implementation)
| Question | Finding |
|---|---|
| Profile data | `users` had `phone` (free text, not unique, unvalidated) and no name, address, location or verification flag |
| Registration | username, email and password only. No district was ever set. Login is username-only |
| District empty data — root cause | (1) **Code:** "Select your district" only linked to `/districts`, read-only pages; nothing saved the choice. `POST /select-district` existed but no page called it, **and it crashed** (`flash` not imported). Registration set no district, so the dashboard always said "Nationwide". (2) **Data:** the dev DB had never been seeded (0 roads, 0 projects, 0 authorities, 1 river), although the repo ships an offline OSM importer. (3) `app/routes/district.py` was a dead, unregistered duplicate blueprint |
| Citizen dashboard | Stats counted the *displayed* lists (`roads|length` of a 5-item list). Active hazards were queried (unscoped) but **never rendered**. No own reports, alerts or map |
| Authority dashboard | Pre-M02: complaints, projects, roads and rivers only. No hazards, reports, AI, devices, readings or response work. Admins could not open it |
| Real vs placeholder | Landing stats were static ("77", "7", "4", "24/7"); `static/images/` was empty |
| Reverse geocoding | Not available (only Nominatim forward search), so `current_address` is never auto-filled |

### User/profile schema (migration `e7a2c4d9f310`, revises `c3d7f1a9b6e2`)
- **New `users` columns:** `full_name`, `phone_verified` (NOT NULL, default false), `permanent_address`,
  `current_latitude`, `current_longitude`, `current_address`, `location_updated_at`.
- **Unique phone:** a unique index `uq_users_phone` on `phone`, now stored in **E.164**.
- **Data migration:**
  - Existing phones are normalized when they are valid Nepal mobiles; anything else is left as-is.
  - If two users share a number, only the lowest user id keeps it and the duplicates become NULL
    (otherwise the unique index can't be created).
- **Verified:** on a DB copy with valid, invalid and duplicate legacy phones: upgrade → downgrade →
  upgrade, `flask db check` clean. The local dev DB was backed up to
  `instance/hackforge.pre-product-quality.db` and upgraded.

### Mobile, address and GPS behaviour
- **Mobile** (`account_service.normalize_mobile`):
  - Nepal formats accepted: `98XXXXXXXX`, `977…`, `+977…`, `00977…`, with spaces, dashes or
    brackets → `+977XXXXXXXXXX`.
  - Valid Nepal mobiles have 10 digits starting 96/97/98. Other countries only as `+<code>…` (8–15
    digits).
  - Unique per account, enforced in the app and by the DB index.
  - `phone_verified` is always false: **no SMS is sent and nothing is verified.** The number is
    stored only to prepare for future emergency-SMS integration. Changing the number resets the
    flag.
- **Permanent address:** typed by the user, stored separately, required at registration.
- **Current location:**
  - Captured only when the user clicks **"Use my current location"**, using the browser
    Geolocation API. It is never requested on page load.
  - States shown: detecting, detected (coordinates and accuracy), permission denied, unavailable,
    timeout, unsupported, insecure (non-HTTPS), with a retry button.
  - Coordinate fields are filled only after a real success.
  - The server re-validates finite numbers, ranges, and that latitude and longitude come together.
  - `current_address` is saved only when the user types it, and only alongside real coordinates.
  - It never overwrites the permanent address. It can be deleted on the profile page.
- **Privacy:** phone, address, coordinates and full name appear only on the owner's and admins'
  profile view. They are in no API response (tested across the dashboard, hazards, notifications
  and reports APIs).

### Authentication UX
- **Login** (citizen and authority):
  - Split layout: photo panel plus glass form card.
  - Labelled inputs, a show/hide password toggle and a remember-me option.
  - An inline error with `aria-invalid`. One message for an unknown user or a wrong password (no
    account enumeration), returning **401** (was 200 with a flash).
  - A busy state on submit, only after client-side validity passes.
  - CSRF, the M10 same-site `next` rule and username-only login are unchanged.
- **Registration:**
  - Fields: full name, username (pattern), email (lower-cased, case-insensitive uniqueness),
    mobile, password (≥ 8) and confirmation, district, permanent address, and an optional current
    location with the explicit button.
  - On errors the form re-renders (400) with per-field messages and kept values. The password is
    never echoed.
  - A uniqueness race at commit is handled.

### District fix
- **Saving the district:** `POST /select-district` now validates the id, saves it, and returns the
  user to a same-site `next`. It is used by:
  - the dashboard's "Set your district" form
  - "Set as my district" on every district page
  - registration, which now requires a district
- **District page** (`district_service.district_overview`):
  - active hazards (including M04 extra districts) with severity
  - rivers with status and levels
  - road segments with **real total counts** and status breakdown (list capped at 12)
  - projects with progress
  - authorities, recent community posts, and population/area (Wikidata)
  - a map of hazards that have real coordinates
- **Robustness:** an unknown district → 404. Bad `district_id` filters on `/roads/status` and
  `/rivers/status` no longer 500.
- **Data:** the dev DB now holds the repo's real offline data (`import_nepal_data.py`: 96 road
  segments across 56 districts and 116 rivers across 67 districts, from the bundled OSM snapshot,
  plus the seeded authorities and projects).
- **Cleanup:** the dead `app/routes/district.py` was removed.

### Citizen dashboard (`district_service.citizen_home`)
- **Content:** every number is a COUNT over real rows.
  - Local hazard status: active hazards affecting the user's district, the highest severity, and a
    per-severity breakdown.
  - The nationwide active count, unread alerts, the 6 latest alerts, and the user's own report
    total, status counts and latest 5.
  - Rivers and road segments in the district, and a local map.
- **Empty states** for no hazards, alerts, reports, rivers, roads or coordinates, plus a district
  prompt when none is set.
- **Excluded from the citizen view:** other users' reports, private descriptions,
  `source_reference`, devices, AI analysis and M09 notes.

### Authority dashboard (`dashboard_service.authority_operations`)
- **Content** (same scope rules as M07/M10):
  - active hazards in the jurisdiction with M09 note and open-action counts, linking to the M09
    response page
  - severity summary and "awaiting investigation"; photo reports to review (M05 visibility) with
    the M06 AI label and confidence and a "differs from citizen" flag
  - open response actions, IoT devices owned by the authority (freshness, latest readings)
  - the operational map
  - complaints, projects, rivers and road status
- **Navigation:** one shared navbar for all panel pages.
- **Admins** have no single jurisdiction, so they are sent to the system-wide `/monitoring` console.
- **Unlinked authorities and citizens** are turned away as before.

### Design system (`app/static/css/xman.css`)
- **Style mix:** aurora atmosphere (fixed radial gradients behind everything) + glass surfaces
  (near-opaque fills: 86–94%) + bento grid (12 columns with span utilities) + a utilitarian
  information layer. It replaces the ~740-line inline "vintage" theme in `base.html`; the old
  unused `static/css/base.css`, `variables.css` and `js/main.js` were removed.
- **Kept contract:** every old token and class name, so all ~40 templates restyle consistently.
  Light and dark themes share tokens.
- **Tokens:** typography (Inter, Space Grotesk for display, Noto Sans Devanagari), spacing, radii,
  shadows, glass, status and **emergency severity** (critical/high/medium/low/normal). Severity
  always shows as **text + icon + colour** (`ui.sev`), and map markers also encode it by size.
- **Shared components:**
  - `components/ui.html`: severity, status, hazard row, empty state, map
  - `components/photo.html`: photo with credit
  - `auth_visual`, `authority_nav`, `location_js`, `auth_form_js`
- **Rewritten pages:** landing, login, register, authority login, citizen dashboard, districts,
  district detail, profile/edit, authority dashboard, credits. All other pages inherit the system.

### Real images (`app/static/images/`, `app/image_credits.py`, `/credits`)
- **Source:** 7 photographs from **Wikimedia Commons** (CC BY 2.0/4.0, CC BY-SA 3.0/4.0):
  Himalaya, Chola Valley, the Sunkoshi–Tamakoshi confluence and highway, a road through the
  landslide-prone Trishuli cut, Sauraha after the 2017 flood, the Kathmandu valley, and terraced
  hills.
- **Processing:** downloaded once and resized/re-encoded locally (98–271 KB, no EXIF), so there
  are no hot-links.
- **Attribution:** author and licence shown next to each photo; `/credits` lists source and
  licence links.
- **Where used:** landing hero and hazard cards, auth visuals and empty states. Never behind dense
  operational data.
- **Citizen photos:** report photos remain private and are never used.

### 3D / depth (CSS only, no 3D engine)
- **Elements:**
  - an isometric stack of terrain tiles with a hazard pin
  - a floating glass orb
  - tilted glass alert cards and subtle perspective tilt on hover
  - layered shadows and inner highlights on cards, and a skewed brand mark
- **Labelling:** the landing alert cards are labelled "Example alert" (not presented as real
  data).
- **Accessibility:** all animation and tilt are disabled under `prefers-reduced-motion`, and blur
  under `prefers-reduced-transparency`.

### Responsive and accessibility
- **Checked in Chrome on a seeded scratch DB:**
  - desktop, plus 390 px phone width via same-origin iframes (the window could not be resized)
  - landing, login (error state), register (location timeout shown honestly), citizen dashboard
  - district page, authority dashboard (light + dark)
  - inherited road-status and notification pages
  - no console errors
- **Accessibility features:**
  - skip link, landmarks, labelled inputs with `aria-invalid`/`aria-describedby` errors, and
    visible `:focus-visible` rings
  - status as text everywhere, nothing essential behind hover, and ≥ 44 px form controls
- **Mobile:** the authority navbar becomes a scrollable row.
- **Translations:** 152 new strings with Nepali translations.

### Tests
- **New:** `tests/test_product_quality.py`, **79 tests**:
  - mobile normalization (8 valid, 14 invalid) and coordinates (8 invalid + valid)
  - registration persistence, optional location (never invented), 17 rejection cases with nothing
    created, password never echoed, explicit-click location control
  - login: same 401 message for unknown user and wrong password, safe `next`, CSRF fields
  - profile: E.164 + verification reset, duplicate phone, location set/clear without touching the
    address, bad coordinates; private fields only for owner/admin and absent from 4 APIs
  - citizen dashboard real counts/scope/own reports/map, zero-data states, district prompt and
    persistence, invalid selection and `next` ignored
  - district page with data (real total beyond the list cap), empty and 404, no private report data
  - authority dashboard scoped data (no other-district hazards/devices/reports, no key hash),
    admin → console, unlinked/citizen turned away, shared nav
  - counted landing stats; every image exists, is small and is credited; design-system and
    accessibility basics present
- **Existing tests changed (2, both caused by intentional schema changes):**
  - `test_security_m10.py` fixture: the six users shared phone `9800000000`, which the new unique
    index forbids, so each now has a distinct E.164 number.
  - `test_security_m10.py::test_fresh_install_is_migration_tracked`: it hard-coded the M09 head.
    It now asks `flask db heads` and requires the fresh install to be stamped at exactly that head
    (equally strict, and survives future migrations).

**Full suite: 772 passed (693 existing + 79 new), 31 warnings** (was 44: the rewritten routes use `db.session.get` instead of legacy `Query.get()`; the remainder are pre-existing legacy `Query.get()` calls in untouched code)

### Security status
- **Unchanged rules:** M10 authorization, the CSRF exemption only for device telemetry, the CSP
  and headers, and M05/M09 privacy.
- **New private fields** (phone, address, coordinates, name) are owner/admin-only in HTML and
  absent from every API.
- **Selection redirects:** the district-selection redirect uses the same-site `next` rule.
- **Images:** Commons photos are public illustrations only.

### Known limitations
- **No SMS and no phone verification:** `phone_verified` is always false. Login is still by
  username (unchanged).
- **No reverse geocoding**, so the current address is user-typed. Location capture needs HTTPS
  (or localhost) in browsers.
- **Maps** show only hazards with real coordinates. There are no district boundaries/centroids in
  the data, and tiles need internet.
- **Data coverage:** real data covers roads/rivers in 56/67 districts (OSM names, seeded statuses
  per `import_nepal_data.py`). Authorities and projects exist only for Sindhuli/Kathmandu (seed
  data).
- **Stray dev-DB row:** the dev DB still contains a stray `Test District` (id 78, "Test Province")
  that makes the landing page show 78 districts / 8 provinces. It was left in place pending the
  owner's decision. *(Resolved in FQA: see "Dev-DB cleanup".)*
- **Not fully restyled:** older inner pages (projects, travel, social, complaints) inherit the new
  system but were not rebuilt; some still have inline layout styles.
- **Visual review** was manual (Chrome); there is no automated visual regression.

### Next milestone
**M12 — Admin Control + Emergency Web Push** (below), then H01.

### 🏷️ Status
**M11.5 — PRODUCT QUALITY, ACCOUNTS, DASHBOARDS AND DESIGN SYSTEM COMPLETE · NO SMS · NO HARDWARE CHANGES**

---

# M12 — Admin Control + Emergency Web Push Notifications

Software, account and notification infrastructure only. No H01 work, no firmware, no hardware changes.
No new User/Authority/District/Incident/Notification systems: M12 extends the existing models and
plugs into the existing M03/M04 notification service.

### Baseline
- **772 passed** before M12. That is the 693 committed at M11 plus the 79 uncommitted M11.5 tests;
  both milestones are still uncommitted.

### Admin control center (`/admin`, `app/routes/admin.py`, `app/services/admin_service.py`)
- **Access:** a blueprint `before_request` guard. Anonymous users are sent to log in; any non-admin
  gets **403**, including routes added later. A test walks every `/admin` rule as a citizen.
  - Detail pages 404 when the id is not of the expected role, so citizen pages can't browse
    authority or admin users.
- **Overview** (all real counts): authorities and authority accounts, citizens, disabled accounts,
  districts, active hazards, push-enabled users and active subscriptions, notifications in the last
  24 h, recent emergency-level hazards, and per-layer delivery status (SMS shown as "Not implemented").
- **Citizens** (`/admin/citizens`):
  - A district list with database counts (citizens and push-enabled per district, plus "No district").
  - Clicking a district filters the list. Search covers name, username and email (LIKE wildcards
    escaped). Also an account-status filter.
  - **25 per page**; filters survive paging.
  - Columns: name, district, account status, notification-permission state, emergency push on/off,
    registration date.
- **Citizen detail:**
  - Email, mobile (with verified flag), district, permanent address and registration/last login.
  - Notification counts, emergency-alert state, sound preference, and push devices (browser
    user-agent and dates only).
  - **Current location:** only "shared / not shared" and when, never coordinates. The public profile
    page now shows coordinates to the **owner only**; admins see "Current location shared". This
    changes one M11.5 test.
- **Authorities** (`/admin/authorities`): district filter, search (name/category), status filter
  (has an active account / all accounts disabled / no account linked), pagination. Columns: district,
  account status, emergency notification capability (in-app only vs in-app + push), device count,
  last activity (latest `last_login_at`).
- **Authority detail:** the district it controls, linked accounts (status, must-change-password,
  alert state, push, last login), its IoT devices (`device_id`, status, last seen; never key hashes),
  active hazards affecting its district (linked to the M09 response page), open response actions and
  office details.
- **Account actions** (POST + CSRF):
  - Enable or disable citizen and authority accounts. Admin accounts and the admin themself are not
    managed here.
  - Reset an authority password.
- **Notification status** (`/admin/notifications`), all read-only:
  - Web Push configured or not, VAPID contact, emergency threshold and allowed push services
    (environment settings).
  - Permission-state breakdown, active/disabled/failing subscriptions and users with sound off.
  - Recent hazard notifications grouped by hazard/event with recipient counts and which layers apply.
- **Audit:** there is no audit table in the existing architecture, so admin actions are logged as
  `admin_action admin=<id> action=<enable|disable|reset_password> target_user=<id>`, without secrets.

### Account status and password reset
- **New `users` fields:**
  - `is_active` overrides Flask-Login's `UserMixin.is_active`. A disabled user can't log in, and
    `user_loader` drops existing sessions.
  - `must_change_password`.
  - `last_login_at`, set on login.
- **Disabled login:** the "account disabled" message only appears after a correct password (no
  account probing).
- **Password reset design:**
  - The admin **never sees an existing password**: only the werkzeug one-way hash exists, and it is
    never rendered.
  - The admin types a temporary password twice (≥ 8 characters). It is stored only as a hash,
    `must_change_password` is set, and the action is logged without the password.
- **After a reset:**
  - The temporary password opens only `/profile/change-password` (and logout). Every other page
    redirects there, and `/api/*` returns 403.
  - The change requires the temporary password, a new password of ≥ 8 characters (was 6) that differs
    from the current one, and clears the flag.
- **Restrictions:** reset is only offered for authority accounts. An authority calling the endpoint
  gets 403.

### Emergency notification architecture (three layers)
```
IoT / citizen report / authority
  -> hazard_event_service (source of truth; M02 dedup)
  -> notification_service.notify_hazard   LAYER 1: Notification rows (M03/M04 targeting + per-user dedup)
       -> emergency_dispatcher.queue(rows actually created)
  -> hazard commit (_commit_or_rollback) -> emergency_dispatcher.flush()
       -> LAYER 3: Web Push to recipients' enabled subscriptions
  LAYER 2: every open X-MAN page polls GET /api/emergency/active (the user's own unread emergency rows)
  (future: an SMS sender inside the dispatcher; none exists)
```
- **No new targeting:** recipients are the existing `hazard_recipients`. That means citizens whose
  home district is affected (primary + M04 additional districts), authorities responsible for those
  districts, and admins. Unaffected citizens get nothing. Districts come from server-side
  relationships, never from the client.
- **No new dedup:** a push is only sent for a notification row that `notify_hazard` just created.
  - Repeated evidence (no new row) → no push.
  - High → critical (a new escalation row per severity) → a new push.
  - An area expansion reaches only the newly covered users.
- **Emergency threshold:** `EMERGENCY_MIN_SEVERITY` (default `high`). An invalid value falls back to
  `high`; inside the dispatcher an unknown value means critical-only, never "everything".
  - At or above it, detected/escalated/confirmed alerts raise the in-website alarm and an urgent
    push (`Urgency: high`, `requireInteraction`).
  - The all-clear (resolved) for an emergency-level hazard is pushed as a normal notification, with
    no alarm.
  - Lower severities stay in-app only, as before.
- **Transaction safety:**
  - Pushes go out **after** the hazard commit, so a failed or slow push never rolls back or blocks
    the hazard.
  - On rollback the queue is discarded. As a second guard, `flush()` re-loads each queued row and
    requires `(id, user_id, dedup_key)` to match, so a rolled-back notification is never pushed.
  - (A global `after_rollback` listener was rejected: savepoint rollbacks in `_save` fire it too.)
- **Failure handling** (best-effort):
  - 2xx → `last_used_at`. 404/410 → the subscription is disabled.
  - Other failures increment `failure_count`; disabled after 5 consecutive.
  - Network errors count as failures. Any unexpected error inside the dispatcher is caught, rolled
    back and logged by exception type only.
  - Endpoints and keys are never logged.
- **Payload:** public notification fields only (the same title/message as layer 1: no description,
  resolution notes or `source_reference`), plus a same-origin URL, tag `xman-hazard-<id>` and the
  severity.

### Web Push implementation (`app/services/web_push.py`)
- **Crypto:** RFC 8291 aes128gcm encryption and an RFC 8292 VAPID ES256 JWT, on `cryptography` (now in
  `requirements.txt`; it was already installed). No other new dependency.
  - Verified **byte-exact against the RFC 8291 Appendix A test vector**. Tests also decrypt every push
    as a browser would and verify the JWT signature against the public key.
- **Server keys:** `VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` from the environment.
  `flask push-keys` prints a fresh pair. The private key is never stored in the DB, rendered or
  returned (tested across every page and API for each role). Unset keys mean push is disabled, while
  layers 1 and 2 still work.
- **SSRF protection:** the server POSTs to client-supplied endpoints, so only `https` URLs on known
  push services are accepted (`WEB_PUSH_ALLOWED_HOSTS`: FCM, Mozilla, Windows, Apple), with no
  credentials and at most 1000 characters. Keys must decode to a valid P-256 point and a 16-byte
  auth secret.

### Subscriptions and preferences (`push_subscriptions`; `users.emergency_alert_state` / `emergency_sound_enabled`)
- **`push_subscriptions` table:**
  - Columns: `id, user_id (indexed), endpoint (unique), p256dh_key, auth_key, user_agent, enabled,
    created_at, updated_at, last_used_at, failure_count`.
  - The endpoint and keys are never returned by any API or page.
- **`emergency_alert_state`:** `not_requested | granted | denied | unsupported | disabled_by_user`.
  - Only a real subscription sets `granted`; turning alerts off sets `disabled_by_user`.
  - A browser-reported `denied`/`unsupported` is recorded only when the user has no active
    subscription and hasn't opted out (another device's report can't switch off a working phone).
- **Reconciliation:** the page always reconciles browser `Notification.permission` + `PushManager`
  subscription + the stored state. A database boolean is never taken as permission.
- **APIs** (login required, own account only, CSRF via `X-CSRFToken`):
  - `GET /api/push/config` · `POST /api/push/subscribe` (upsert by endpoint; always bound to the
    session user, and a `user_id` in the body is ignored).
  - `POST /api/push/unsubscribe` deletes all of the caller's subscriptions; notification history is
    kept.
  - `POST /api/push/state` · `POST /api/push/test` (own devices only, 1 per 30 s) ·
    `POST /api/emergency/sound` · `GET /api/emergency/active`.
- **Shared browsers:** a browser endpoint re-subscribed by another logged-in user moves to that user
  (it's the same physical browser).

### Browser side
- **Service worker** (`/sw.js`, served from the root for full scope, `no-cache`):
  - `push` → `showNotification` (tag, renotify, `requireInteraction` for emergencies, "Open X-MAN"
    action) and a message to open tabs so the in-website alert appears immediately.
  - `notificationclick` focuses or opens a **same-origin** path only.
  - No caching or offline logic.
- **Opt-in** (`components/emergency_optin.html` on the citizen dashboard):
  - Shown only if push is configured, the state is `not_requested`, and the browser supports it on a
    secure context.
  - Shows the required explanation, an "Enable emergency alert sound" checkbox, **Enable Emergency
    Alerts** and **Not Now** (snoozed for 7 days in that browser).
  - `Notification.requestPermission()` is called only inside the click handler, never on load.
- **Settings** (`/notifications/settings`, linked from both sidebars):
  - Web emergency alerts ON/OFF, Emergency sound ON/OFF, browser permission, push subscription, and
    device count.
  - Enable, Test Emergency Notification, Turn Off Emergency Alerts, and Preview sound.
  - Shows the required "notification records remain available" wording and the honest delivery
    statement.
- **In-website alert** (layer 2, `static/js/emergency.js` + `components/emergency_alert.html`, every
  signed-in page):
  - Content: "Emergency disaster alert", hazard title, public message, severity (icon + word +
    colour), affected districts, local time, **View hazard** (marks read), **Mute alarm**, **Dismiss**
    (marks read), and "+N more".
  - All text is set with `textContent`. Polls every 30 s and on tab focus.
- **Sound:**
  - Web Audio beep-beep every 1.5 s, stopping by itself after 10 cycles (~15 s). Mute or Escape
    stops it.
  - Plays once per alert per browser session. Respects `emergency_sound_enabled`.
  - If the browser hasn't allowed audio yet (autoplay policy), the alert says so and offers "Play
    alarm" instead of trying to bypass it. Any click or key on the site unlocks audio.
  - Muting sound never affects the database notification or push delivery (tested).

### Security summary (all tested)
- **Admin access:** citizens and authorities get 403 on every admin route; anonymous users are sent
  to log in.
- **Password reset:** an authority can't reset another authority's password. Passwords and hashes
  never appear in pages or logs.
- **Push isolation:** push routes require login. Subscriptions can't be attached to, tested against
  or deleted for another user. Unsafe endpoints and keys are rejected.
- **No secret leakage:** the VAPID private key and subscription secrets appear in no page or API.
- **CSRF** is enforced on admin and push POSTs (tested with CSRF on).
- **XSS:** admin pages escape user content (tested with `<script>`/`<img onerror>` names).
- **Unchanged:** existing M05/M09/M10 rules.

### Migration
- **`f3b8d2e6a417_m12_admin_control_web_push`** (revises `e7a2c4d9f310`). Additive:
  - five `users` columns with server defaults (existing users stay active, are not forced to change
    their password, and start `not_requested`)
  - the `push_subscriptions` table
- **Verified:** upgrade → `flask db check` (clean) → downgrade → upgrade on a copy of the dev DB.
  Fresh install via `init_db.py` is stamped at the new head (tests).
- **Known pre-existing limitation:** a bare `flask db upgrade` on an empty file cannot run the whole
  history (an early migration expects tables that `init_db.py` creates). The supported fresh path is
  `init_db.py`, as before.

### Tests
- **New `tests/test_admin_push_m12.py` — 72 tests:**
  - admin access for every route and role; real overview counts
  - authority list/filter/search/status/pagination, detail without secrets, the full reset flow
    (forced change, API 403, bad temp passwords, role restrictions, authority-to-authority blocked),
    disable/enable ending sessions, audit log without secrets
  - citizen list/district counts/filters/pagination/privacy/disable
  - subscription binding, upsert, shared browser, 7 unsafe endpoints, 5 bad-key shapes, not
    configured, unsubscribe isolation with history kept, permission states, test-push isolation and
    rate limit, sound validation, auth on all push routes, service worker
  - dispatch: all three layers with targeting, VAPID JWT verification, repeated evidence vs
    escalation, below-threshold, configurable/invalid threshold, confirm/resolve lifecycle, area
    expansion, opted-out/disabled users, muted user, read alert leaves layer 2, 410 cleanup, failure
    limit, push failure never breaks hazards (no secrets in logs), rolled-back rows never pushed,
    public-only payload
  - pages and security: no auto-prompt, opt-in copy, overlay only when signed in, private key and
    subscription secrets never exposed, escaping, CSRF
  - fresh-install schema and the RFC 8291 vector
  - A module-level autouse fake push service guarantees no test reaches the network.
- **Changed existing test (1):** `test_product_quality.py::test_private_fields_only_for_owner_and_admin`.
  Admins no longer see coordinates on the public profile (owner-only, per M12's privacy rule).
- **Full suite:** **844 passed, 31 warnings** (772 before M12 + 72 new; warning count unchanged — all are pre-existing legacy `Query.get()` calls in untouched code)

### Real-world limitations (stated plainly)
- **Delivery claim:** X-MAN can deliver browser push emergency notifications outside the website when
  the user's browser/device supports Web Push, permission is granted, and the device has network
  connectivity. Delivery is **not guaranteed**, and nothing reaches an offline device until it
  reconnects (TTL 1 h).
- **Requirements:** Web Push needs HTTPS (localhost counts as secure for development), a supported
  browser, an active service worker, user permission and a subscription. iOS Safari only supports it
  for a site added to the Home Screen.
- **OS/browser control:** the browser and OS decide whether notifications are shown, whether they
  make a sound, focus/do-not-disturb, and battery/background restrictions. X-MAN requests normal
  notification behaviour and does not try to force a sound.
- **Alarm sound:** the website alarm only plays after the user has interacted with the page (browser
  autoplay policy); this is not bypassed.
- **Synchronous sending:** pushes are sent in the request that changed the hazard (5 s timeout per
  endpoint). A worker queue is needed before very large subscriber counts.
- **Not tested against a real push service in this environment:** a live push could not be completed
  here because the browser's permission prompt cannot be accepted by automation. Encryption and VAPID
  are verified against the RFC test vector and by decryption/signature checks.
- **Admin settings are read-only:** emergency settings come from the environment. There is no audit
  table (actions go to the application log), and admins can't create accounts in the UI (README
  snippet, as before).
- **No SMS.** Phone numbers stay unverified, stored only as preparation for a future SMS channel.

### Exact current state
- **Committed** as `9fc5b38` (M11.5 + M12).
- **Migration head:** `f3b8d2e6a417`.
- **Hardware:** physical hardware is still not built or validated.

### Next milestone
**H01 — ESP32 Hardware Foundation** (not started).

### 🏷️ Status
**M12 — ADMIN CONTROL + EMERGENCY WEB PUSH COMPLETE · THREE NOTIFICATION LAYERS · NO SMS · NO HARDWARE CHANGES**

---

# FQA — Final Software QA / Pre-Hardware Freeze

The last software pass before H01: find → fix → test → verify. No new features and no hardware or
firmware work. Starting point: `9fc5b38`, **844 passed, 31 warnings**.

### How it was tested
- **Automated:**
  - the full pytest suite
  - the five standalone scripts from the README, run against a real database
  - a migration round trip on a copy of the dev DB
- **Route crawler** (a scratch script, not in the repo):
  - every registered route × 7 roles (anonymous, citizen of district A, citizen of district B,
    authority A, authority B, an unlinked authority, admin)
  - valid / other-district / junk path ids
  - empty, junk form, junk JSON (NaN-like, `1e309`, bools, negative/huge paging), malformed JSON
    and JSON-array bodies
  - flags any 5xx, and searches every response for secrets (VAPID private key, push endpoint/keys,
    device API key and its hash, password hash, `source_reference`) and for owner-only data
    (address, coordinates, report/complaint text, response actions)
- **Live Chrome QA** on a copy of the dev DB, seeded through the real HTTP flows:
  - flood and motion telemetry, citizen photo reports with the real SigLIP model, every role
  - an in-page audit loaded every page in iframes at 390 px (phone), 844 px (phone landscape),
    768 px (tablet) and 1280 px (desktop), for citizen, authority, admin, anonymous and Nepali UI
  - it checked JS errors, broken images, horizontal overflow, clipped buttons/headings and dead
    internal links, alongside the Chrome console
- **Query counts:** SQL queries counted per page on the seeded DB (N+1 sanity).

### Defects found and fixed
| # | Defect | Fix | Regression test (`tests/test_final_qa.py` unless noted) |
|---|---|---|---|
| 1 | `GET /roads/<id>` → **500** (template never existed; nothing linked to it) | dead route removed (README updated) | `test_dead_road_detail_route_is_gone` |
| 2 | `?district_id=abc` → **500** on `/authorities/directory`, `/projects/tracker`, `/social/feed` | same digit check as `/roads/status` | `test_junk_district_filters` |
| 3 | JSON array/number body → **500** on `/ai/classify`, `/ai/generate`, `/language/translate` | `form_validation.json_text`: object body, string field, ≤ 4000 chars (text sent to Ollama) | `test_non_object_json_bodies` |
| 4 | Complaint form: junk ids → **500**; unknown authority/district stored (SQLite doesn't enforce FKs) → orphan rows; empty category → **500**; unlisted category/urgency accepted | all validated against the form's options; unknown ids rejected | `test_invalid_complaints_are_rejected_without_rows` |
| 5 | Complaint ticket = 4 random digits under a unique index: with ~100 complaints per district per year a collision (**500**) was about a coin flip | `PREFIX-YEAR-XXXXXX` from `secrets`, re-drawn until unused | `test_ticket_numbers_never_collide` |
| 6 | **Privacy:** public profiles listed the user's complaints with description text to any logged-in user (complaint detail is private since M10) | complaints shown to the owner and admins only | `test_complaint_text_not_on_other_users_profiles` |
| 7 | **Privacy:** community post photos were stored byte-for-byte in public `static/uploads`, **including the phone's EXIF GPS**; any file with an image extension was accepted | the M05 report pipeline (`process_image`, now public): type-checked, size/dimension-limited, re-encoded JPEG without EXIF | `test_post_photo_is_reencoded_without_exif_gps`, `test_non_images_rejected` |
| 8 | Posts: unvalidated `district_id` (orphan rows; **500** for users without a district) | validated | `test_invalid_district_rejected` |
| 9 | Like/comment on a non-existent post created orphan rows | 404 | `test_like_and_comment_need_a_real_post` |
| 10 | River update of exactly 0 m (and project progress 0 %) stored as NULL in the update log | 0 kept | `test_zero_water_level_is_recorded` |
| 11 | `/language/set/<lang>` redirected to the raw `Referer` (open redirect) | same-site referrer only | `test_language_switch_redirects_only_on_site` |
| 12 | Service worker followed a notification's stored URL on click without re-checking it (push-time sanitising only) | URL re-checked on click: same-origin paths only | `test_service_worker_only_ever_opens_x_man_pages` (runs `sw.js` in Node against a mocked worker global) |
| 13 | Emergency alert headline always English (stored text), even for Nepali readers, including the Web Push shown while X-MAN is closed | `notification_service.localized_title` builds the headline from structured fields in the reader's language (page: session/user language; push: recipient's saved language); severity label in the alert translated | `TestLocalisedAlerts` |
| 14 | Alert message repeated the river name ("Rising detected: Kamala River · Kamala River") | names already in the title are skipped | `test_headline_in_reader_language` |
| 15 | Raw keys shown as labels ("road_damage", "landslide") on the report form, My Reports, the review page and notifications | `ui.hazard_name` everywhere | `test_hazard_labels_are_human_readable` (+ updated M06/M11.5 assertions) |
| 16 | Report page GPS: every failure showed one vague message | reuses the M11.5 location widget (denied / unavailable / timeout / unsupported / insecure, coordinates only on success) | `test_hazard_labels_are_human_readable` |
| 17 | "unknown · Model confidence 0.02" read as "2 % sure it is unknown" (the number is the best hazard score below the threshold) | `ui.ai_result`: "No hazard recognised · best match 0.02 (needs 0.60)" on the review page, authority dashboard and monitoring | `test_unknown_ai_result_explains_the_threshold` |
| 18 | Social feeds loaded **every user** per page view; the hashtag feed was unbounded and treated `%`/`_` as wildcards | only post authors loaded; hashtag feed limited to 50, wildcards escaped | `test_junk_district_filters` (hashtag `%`) |
| 19 | 31 test warnings: legacy `Query.get()` in 7 routes and 2 test files | `db.session.get` / `db.get_or_404` | warning count 31 → 2 |
| 20 | `test_ui.py` / `test_theme.py` asserted the pre-M11.5 vintage design (fonts, inline styles, "no blue") and failed | rewritten for the X-MAN design system (tokens in both themes, no FOUC, toggle, fonts) | both scripts pass |
| 21 | `app/static/uploads/` not git-ignored (users' post photos could be committed); stray `EOF` line in `.gitignore` | ignored (the tracked demo image is kept); `EOF` removed | — |
| 22 | 9 user-facing strings without Nepali (flash messages, AI wording) | added | — |

### Verified without defects
- **Authentication:**
  - Registration covers every invalid case: username, duplicate username/email/mobile, Nepal mobile
    format, password length/confirmation, district, address, coordinate range. It shows per-field
    errors, keeps values and never echoes the password. Valid sign-up stores the optional location.
  - Login gives the same message for an unknown user and a wrong password.
  - "Account disabled" only appears after a correct password. A disabled account's open session ends.
  - Forced change after an admin reset:
    - the temporary password only opens change-password (pages redirect, API 403)
    - after the change, the temporary password stops working and the new one works
  - Protected pages redirect to `/auth/login?next=…`; APIs return 401 JSON.
- **Authorization:**
  - Authority B gets 403 on authority A's hazards: response page, history, actions, investigations,
    status, PATCH, affected districts.
  - Devices are 403 for authority B too: key rotation and enable/disable.
  - Reports are 404 to other citizens and other districts' authorities, for both detail and photo.
  - Admin routes return 403 to non-admins.
  - Citizen-supplied `severity`, `status`, `source` and `incident_id` are ignored on reports.
- **Uploads** (in Chrome, through the real API):
  - JPG, PNG and WebP are accepted.
  - Rejected: `.txt`, fake image content, a truncated JPEG, 11 MB, 12000×12000 px, content that
    doesn't match the extension, no photo, bad hazard type, NaN/out-of-range coordinates, no CSRF
    token.
- **IoT** (CSRF enabled, as on the real server):
  - Every bad input is 400: NaN, Infinity, `1e309`, bool, string, null, wrong unit, unknown sensor,
    malformed JSON, array body, non-object reading, form body.
  - Wrong/unknown device, rotated-out key and disabled device are 401.
  - The flood sequence 4.2 → 5.7 m merges into **one** incident with 6 pieces of evidence and
    exactly one "detected" + one "escalated" notification.
  - Vibration produces one "abnormal ground motion" event. The UI and docs make no magnitude or
    prediction claims.
- **Vision AI** (real SigLIP model, local files):
  - The landslide photo was labelled landslide at 0.997.
  - A highway photo and an unrelated photo came back unknown.
  - The citizen's hazard type, the report status and the hazard severity/status never change from
    AI.
  - Accepting a report changes only the report. Vision disabled → 503, and the report is kept.
- **Notifications:**
  - Layer 1 targeting and dedup hold, per the existing suites.
  - Layer 2 in Chrome: a live critical hazard appeared within one poll. With the page interacted
    with, the alarm sounded and stopped by itself after ~15 s. Without interaction, the "Play alarm"
    fallback showed.
  - Mute stops the alarm. Navigation doesn't replay it (once per alert per tab session). Dismiss
    marks the alert read. "+N more" works. Mobile layout works.
  - Layer 3: see *Web Push status* below.
- **Service worker** (Chrome): registered at scope `/`, activated, controlling the page, `update()`
  works; the push/click handlers are covered by the Node harness.
- **Settings page:** reflects the real browser state (permission not requested, no subscription).
  The sound preference persists across reload.
- **Browser storage:** session and remember cookies are HttpOnly. localStorage holds only theme and
  "Not now"; sessionStorage holds only alarmed alert ids. `/api/push/config` exposes only the public
  key.
- **Responsive / Nepali:** no overflow, clipped buttons, broken images, JS errors or dead links on
  any audited page at any width, in English or Nepali.
- **Performance:** query counts per page are 2–22 and bounded (no N+1). Synchronous Web Push
  remains a documented scaling limit.
- **Database:**
  - linear migration chain, single head `f3b8d2e6a417`; `flask db check` clean
  - upgrade → downgrade two revisions → upgrade on a copy of the dev DB
  - fresh install via `init_db.py` (tests)
  - dev DB: `PRAGMA integrity_check` ok, **no foreign-key violations**, no duplicate districts,
    rivers, roads or authorities

### Web Push real-service status (stated plainly)
- **Covered by tests:**
  - encryption is byte-exact against RFC 8291 Appendix A
  - every test push is decrypted as a browser would
  - the VAPID JWT signature is verified against the public key
  - the service worker handlers are exercised (Node harness)
  - registration in Chrome works
- **Not covered:** **a real delivery through FCM/Mozilla was not validated.** Chrome's native
  notification-permission prompt cannot be accepted by automation, so no real subscription could
  be created in this environment. Validate by hand once:
  1. `flask push-keys` → `.env`
  2. "Enable Emergency Alerts"
  3. "Test Emergency Notification"

### Remaining limitations (genuine, documented)
- **Web Push:** real-service delivery is unvalidated (above). Pushes are sent synchronously. Delivery
  needs a supported browser, permission, HTTPS (or localhost) and network; the OS decides display
  and sound. **No SMS.**
- **Warnings:** the 2 remaining test warnings come from the third-party `sentencepiece` SWIG
  bindings, loaded only when the real SigLIP model runs. Not fixable here.
- **Readings and hazard text are public by design:** `/api/iot/latest` readings are visible to any
  logged-in user (M01 decision), and hazard `description` is a public field (authority-written;
  citizens' report text is never copied into it).
- **Newari/Maithili** page text falls back to Nepali. Free text (authority-typed titles, river/road
  names) is not translated.
- **Not validated:** no physical hardware has been built or validated (JSN-SR04T, MPU6050/GY-521).
  SigLIP is zero-shot and not validated on Nepal imagery.

### Tests
- **Final:** **872 passed, 2 warnings, 0 failed, 0 skipped, 0 errors**: 844 + 28 new in
  `tests/test_final_qa.py` (plus `tests/sw_harness.js`, which its Node-based test runs; skipped
  automatically where Node isn't installed).
- **Changed existing assertions (all to the corrected behaviour):**
  - `test_admin_push_m12.py` fixture users have `language='en'`: pushes now use the recipient's
    language, and those tests assert English text.
  - `test_product_quality.py`, `test_vision_m06.py`: readable AI labels.
  - `test_hazard_event_service.py`, `test_iot_water_level.py`: `db.session.get`.
- **Standalone scripts:** `test_nepal_data.py`, `test_features.py`, `test_language.py`, `test_ui.py`
  and `test_theme.py` all pass (after the cleanup below).

### Recommendation
**Freeze the software and move to H01.** Every defect found in this pass was fixed and is covered by
a regression test. The remaining items are documented limitations or need real hardware or a manual
push check.

### Dev-DB cleanup: stray `Test District` (resolved)
- **Audit:** district 78 (`Test District`, "Test Province") was referenced by exactly one row: river 1
  (`Test River`). Every other district-referencing table had zero references: users, authorities,
  road segments, projects, bridges, IoT devices, posts, complaints, incidents, affected districts,
  citizen reports. Nothing referenced river 1 (river updates, devices, incidents, bridges), and no
  other district used "Test Province".
- **Origin:** both rows were created in the same second on 2026-09-30 (before the M01 commit) with
  the fixture names used only in `tests/`. They are leaked test data from an ad-hoc run against the
  dev DB. They are already present in the pre-M06 backup. No seed, init or application code
  creates them.
- **Cleaned:**
  - backup `instance/hackforge.pre-fqa-cleanup.db`, then one transaction that deletes only that
    river and that district (each delete guarded by id + name)
  - result: 77 districts, 7 provinces, 96 road segments (56 districts), 115 rivers (66 districts),
    7 authorities, 2 projects
  - `PRAGMA integrity_check` ok, no foreign-key violations, no orphan district references
- **Not needed:** no migration (development data only; the schema is unchanged) and no seed/init
  change. A fresh `init_db.py` + `seed_data.py` + `import_nepal_data.py` gives 77 districts,
  7 provinces and no test rows.
- **After cleanup:** the landing page shows "77 districts · 7 provinces" (was 78 / 8), and
  `test_nepal_data.py` passes.

### 🏷️ Status
**FQA — FINAL SOFTWARE QA COMPLETE · SOFTWARE FROZEN (872 passed, 2 third-party warnings) · NEXT: H01 (not started)**

---

# SA — Super Admin Control Center (final software feature, then freeze)

One deliberate addition after FQA, on top of the frozen `4895b39`. H01 was **not** started; no
hardware or firmware was touched.

### Architecture decision: no second login
The M12 `admin` role was already the highest application role, guarded server-side on every
`/admin/*` rule (blueprint `before_request`), with CSRF-protected session login, hashed passwords,
account disable and forced password change. A separate Super Admin login would have duplicated all of
that and added a second attack surface without adding a privilege boundary, so **`admin` is the
Super Admin** and `/admin` was extended in place (same blueprint, service and design system).
- No "normal admin" tier exists, so there is no admin-vs-super-admin boundary to enforce. Instead, no
  admin can disable, reset, force-change or end the sessions of **any** admin account (including
  their own) from the web UI: user actions are limited to citizen and authority accounts (404
  otherwise). Admin accounts are provisioned on the server only (README snippet); there are no
  default or hard-coded credentials.
- Rate limiting: the existing architecture has none (no limiter dependency); not added (see
  limitations).

### Capabilities (`/admin/...`, admin role only)
| Page | What it shows / does |
|---|---|
| `/admin` | Dashboard from live DB counts: citizens / authority accounts / admins (active, disabled); IoT total, enabled, disabled, recently seen, stale, offline, never, by district, by sensor type, last telemetry; active hazards by severity, type and affected district; reports pending / accepted / rejected / AI-analyzed / AI disagreement; notification delivery, unread totals, push health; system health summary; recent audit entries |
| `/admin/users` | Accounts by role and status; Super Admin list (read-only) |
| `/admin/citizens`, `/<id>` | Search, district/status filter, pagination, registration, last login, report count, notification state. Detail: account, own reports, notification/push state, audit history; disable / re-enable, reset password, force password change, end all sessions |
| `/admin/authorities`, `/<id>` | Directory (district, linked accounts, status, devices, last activity). Detail: accounts with the same per-account actions, district hazards, devices, open response actions, audit history, **Deactivate / Reactivate authority** |
| `/admin/devices`, `/<id>` | IoT Device Control Center: search, district, sensor type, status filter (online / stale / offline / never / disabled), 30 s status poll. Detail: device facts (no key material), latest reading per sensor, telemetry history (sensor and 1 h / 6 h / 24 h / 7 d filters, 50 per page), **Connect / Disconnect**, **Rotate API key** |
| `/admin/hazards`, `/<id>` | All hazards in all districts: type, severity, lifecycle, primary + affected districts, source, created/updated, evidence count, notification state. Detail: status history, photo evidence, notification layers per event, **administrative intervention** (valid lifecycle transitions only) |
| `/admin/reports` | All citizen reports: id, type, district, status, reporter, submitted, AI result (+ disagreement flag), review state; accept/reject through the M05 review path |
| `/admin/notifications` | M12 delivery status + unread totals; states that there is no broadcast button |
| `/admin/push` | Subscriptions total / active / disabled / failing, by user, recent failures; disable a subscription |
| `/admin/audit` | Append-only audit log with search and action / target / result filters |
| `/admin/health` | Latest telemetry / hazard / emergency notification, readings (24 h), device connectivity, refused-telemetry and 5xx counters, refused admin actions (24 h), schema revision, push configured |

### IoT control semantics
- **Connect** = `enabled = true`: authenticated telemetry is accepted again.
- **Disconnect** = `enabled = false`: telemetry with that device's key is refused (HTTP 401) by the
  existing `authenticate_device`. The page says "Device disabled by Super Admin." with who, when and why.
- **Super Admin can disable an IoT device's authenticated access, but cannot physically disconnect
  the ESP32.** The node may still be powered and on Wi-Fi and will keep trying to send; the UI says so.
- **Offline** ("Offline — no telemetry received recently") is a separate, derived state: `online`
  ≤ 5 min, `stale` ≤ 60 min, `offline` older, `never` no telemetry. It is the same rule as Disaster
  Monitoring (`dashboard_service.freshness`), computed at read time and never written to
  `IoTDevice.status` (the operator setting is unchanged). Disabled always wins over freshness.
- **Rotate key:** new `secrets.token_urlsafe(32)`, only its SHA-256 is stored, and the old key fails
  at commit. Post/Redirect/Get, see "Key rotation fix" below.

### Authority / citizen deactivation model
Nothing is ever hard-deleted from the Super Admin UI. No delete feature was added: deactivation
covers every requirement, and nothing needed true deletion.
- **Deactivate authority** disables every linked account and ends their sessions. Hazards, citizen
  reports, response records, status history and devices are preserved; the authority's devices keep
  reporting (disable them separately). Requires a reason + typed `DISABLE AUTHORITY`. Reactivate
  re-enables the accounts. Deactivating an authority with no linked account is refused (and audited).
- **Disable account** (citizen or authority) blocks login and ends sessions; all records stay.
  Requires a reason + typed `DISABLE ACCOUNT`.
- **Session termination is real:** new `users.session_version`. `User.get_id()` is
  `"<id>:<version>"` and `load_user` rejects any other version, so bumping it ends every session
  *and* remember-me cookie. Disable, password reset and "End all sessions" bump it, so re-enabling an
  account never revives a session from before the disable. Sessions created before this release
  (bare `"<id>"`) count as version 0, so the upgrade signs nobody out.
- **Password reset** (now for citizens too): the admin sets a temporary password (hash only), the
  user must change it at next login, and sessions end. "Force password change" sets only the flag.
  Current passwords are never visible (only one-way hashes exist).

### Hazard and report intervention
- Hazard: only transitions in `VALID_STATUS_TRANSITIONS` are offered and accepted. They go through
  `hazard_event_service.transition_event_status` (compare-and-set, an `IncidentStatusHistory` row with
  the admin as actor and `Super Admin intervention: <reason>` as note, normal lifecycle
  notifications). Requires a reason + typed `CHANGE HAZARD STATUS`. Evidence, history and audit rows
  cannot be edited.
- Reports: accept/reject via `citizen_report_service.review_report` (never your own report, never
  twice), reason required. Photo, description and hazard type are never changed.
- Notifications: no new architecture. Hazard Event → Notification Service → DB notification /
  website emergency alert / Web Push, unchanged. There is no button that sends notifications.

### Audit log
- New `audit_logs` table: actor id + username/role snapshot, action, target type/id/label, reason
  (required, ≤ 500 chars), safe summary, success flag, timestamp.
- Every action is recorded, including refusals (e.g. invalid transition, already disabled, unlinked
  authority). Requests rejected before the action (missing reason, wrong typed phrase, bad form value)
  change nothing and are not recorded.
- Append-only: SQLAlchemy `before_update` / `before_delete` listeners raise, and `/admin/audit` is
  GET-only.
- Never recorded: passwords, temporary passwords, password hashes, API keys or their hashes, VAPID
  keys, push endpoints/keys, session secrets. Summaries are built from usernames, device ids and
  statuses; the reason is the operator's own text.

### Security
- Server-side authorization on every rule: citizen/authority → 403, anonymous → login. Tested by
  iterating every `/admin` rule and method, with direct GETs and POSTs.
- CSRF on every new POST (tested with CSRF enabled); Jinja autoescaping on every new page (XSS tests
  with device names, hazard titles and audit reasons); IDOR (admin targets 404, unknown ids 404).
- Pages never render: password hashes, device key hashes, push endpoints / `p256dh` / `auth`, the
  VAPID private key, the secret key, or citizens' current-location coordinates.

### Database changes
Migration **`a9c4e2f81d57`** (revises `f3b8d2e6a417`), additive only: `users.session_version`
(int, default 0) and the `audit_logs` table with indexes on `created_at`, `action` and
`(target_type, target_id)`. Tested: fresh install (`init_db.py`) at head + `flask db check`;
downgrade to M12 (table and column gone); upgrade again + check (`test_super_admin.py`); and an
upgrade of a copy of the real dev DB (f3b8d2e6a417 → a9c4e2f81d57). No old migration was modified.
The dev DB itself was then backed up to `instance/hackforge.pre-super-admin.db` and upgraded
(`integrity_check` ok, `flask db check` clean). Existing deployments: run `flask db upgrade`.

### Tests
`tests/test_super_admin.py` (40 tests):
- authorization: every rule × method for citizen and authority, anonymous, admin-on-admin IDOR, no
  broadcast route
- IoT: list/filter/search/status; reason + typed-phrase enforcement; disable → telemetry 401, enable →
  201; key rotation shown once and old key invalid; no key hash on any page; telemetry history
  filters/pagination; authority device API untouched
- authorities: deactivate/reactivate with session end and history preserved; unlinked refusal;
  password-reset audit
- citizens: directory; disable/re-enable without session revival; end sessions; force change + reset;
  own reports only
- hazards: filters; intervention through the lifecycle with history + notifications + audit; closed
  hazard
- reports: view/filter/review/double review; authority blocked
- push: state without secrets; disable
- audit: append-only, GET-only, filters, escaping, no credentials
- security: CSRF, versioned session ids (legacy, forged, bumped), remember-me revocation, XSS, health
  counters
- dashboard numbers; migration

Changed existing assertions in `test_admin_push_m12.py`, all to the new required behaviour:
- admin POSTs now send `reason` (and the typed phrase for disables)
- citizens can now be reset (admins still cannot)
- the audit log line uses `action=RESET_PASSWORD`
- the route-guard test substitutes any `<int:…>` parameter
- the fresh-install test accepts any head

### Chrome QA (dev server on a migrated **copy** of the dev DB, seeded with QA-only data)
- Citizen session: every Super Admin page and a direct POST → 403. A pre-existing (bare-id) session
  cookie still worked, confirming the backward-compatible session format.
- Super Admin: 24 pages (including every filter state and each device) → 200 with no leaked secrets
  (the only hit was the env-var *name* in the "Web Push not configured" hint).
- Disconnect through the confirmation dialog → "Device disabled by Super Admin." with the reason;
  telemetry 401. A wrong typed phrase (HTML pattern bypassed) → the server refuses with a clear
  message. Rotate key → shown once; absent from cookies, localStorage, sessionStorage and a reload;
  refused while disabled; accepted after Connect; a wrong key gets 401.
- Authority deactivation through the dialog (consequences listed, typed phrase), citizen reset / end
  sessions / disable / enable, hazard intervention, report review and push disable all succeeded and
  all appear in the audit log (16 entries, no temporary password on the page).
- The 30 s status poll fired and kept the badges correct. Console: no errors. No JS-readable cookies
  (the session is HttpOnly); localStorage empty; sessionStorage holds only the existing
  `xman-alarmed` flag.
- Responsive: all 14 page types measured at 390 px and 768 px. **Bug found and fixed:**
  `/admin/notifications` overflowed at 390 px (the pre-existing "Not configured: set VAPID_…" badge
  could not wrap). The disabled-device banner was also reworded so the reason no longer runs into the
  next sentence.

### Limitations
- One role: there is no lower "normal admin" tier, and admin accounts are managed on the server only.
- No login rate limiting (not part of the existing architecture).
- No permanent deletion of authorities or citizens: deactivation only, by design.
- Health counters (refused telemetry, 5xx) are per process and reset on restart; details are in the
  application log. A refused telemetry payload is never stored.
- The hazard intervention commits through `hazard_event_service`, and the audit row is committed right
  after it. The status-history row (actor, reason, time) is written atomically with the change.
- Long explanatory sentences on the new pages are in English; navigation, headings and dialog labels
  are translated to Nepali.

- **Final:** **`python -m pytest tests/ -q` → 912 passed, 2 warnings, 0 failed** (872 + 40 new). The 2
  warnings are the same third-party SWIG `DeprecationWarning`s as at FQA.

### Key rotation fix (after `9ca046b`)
The first version rendered the new key in the POST response, so reloading that page re-submitted the
form and rotated the key again. Now it is **Post/Redirect/Get**:
1. `POST /admin/devices/<id>/rotate-key` (Super Admin, reason, typed `ROTATE KEY`, audited) rotates
   the key: the new hash is stored and the old key is invalid at commit.
2. The plaintext goes into `admin_service`'s one-time store: process memory only, bound to that admin
   and that device, expiring after 5 minutes. The session cookie gets only `'<device>:<random token>'`.
3. The POST answers `302` to `/admin/devices/<id>`.
4. That GET takes the key from the store (removing it) and shows it once with `Cache-Control: no-store`.

Every later GET is read-only, so a reload, Back/Forward, navigating away and back, or reopening the
device shows no key and changes nothing; `GET /rotate-key` is 405. The plaintext is never in the
database, the cookie, a URL, browser storage, the flash or a log. A token replayed by another admin,
used on another device's page or used after 5 minutes yields nothing.
- ponytail: the store is per process. That is correct for the current single-process server
  (`run.py`). Behind several workers the redirected GET could land on another process and the key
  would be lost (rotate again); a shared short-lived cache would then be needed.
- Tests: `TestKeyRotation` in `test_super_admin.py` (+16 tests: GET/refresh/repeat never rotate, PRG
  302, shown once, not in cookie/session/URL/scripts/logs/DB dump, old key 401 / new key 201, second
  rotation, missing reason / wrong phrase (6 cases), citizen/authority/anonymous blocked, binding to
  admin + device, expiry). Replaces the single old rotation test.
- Chrome: rotate through the dialog → server log `POST /rotate-key 302` then `GET /admin/devices/1
  200` with the key once; F5 (`navigation.type=reload`, no resubmit prompt) → no key, no rotation;
  away and Back (`back_forward`), Forward, reopen → no key, no rotation; old key 401, new key 201;
  the audit log shows exactly the two explicit rotations; key absent from the URL, JS-readable
  cookies (none: the session is HttpOnly), localStorage, sessionStorage, the audit page and the
  server log; no console errors. The smoke test of every section passed again.

### Migration check
Revision **`a9c4e2f81d57`**, file `migrations/versions/a9c4e2f81d57_super_admin_audit_log_session_version.py`,
`down_revision = 'f3b8d2e6a417'` (M12), the only head; `flask db current` = `a9c4e2f81d57 (head)` and
`flask db check` = "No new upgrade operations detected" on the dev DB. Schema: `audit_logs` (12
columns, indexes `ix_audit_logs_created_at`, `ix_audit_logs_action`, `ix_audit_logs_target`) and
`users.session_version`. No other Super Admin schema change.

### 🏷️ Status
**SA — SUPER ADMIN CONTROL CENTER COMPLETE · KEY ROTATION ONE-TIME (PRG) · SOFTWARE FROZEN (927 passed, 2 third-party warnings) · NEXT: H01 (not started)**

---

# H01.5 — IoT Device Provisioning (Super Admin UI)

Pre-hardware gap closed: a Super Admin can register an ESP32 from the IoT Control Center instead of
a hand-made `POST /api/iot/devices`. The verified architecture is unchanged (telemetry, risk engine,
hazard events, notifications untouched). No physical hardware connected yet: nothing here proves
real telemetry works.

### Provisioning workflow
1. `/admin/devices` → **Register device** → `/admin/devices/new` (Super Admin only, same session login).
2. Fields: device ID, name, district (existing Nepal districts), **monitoring** (flood / water level,
   or other), river (only the selected district's rivers, each labelled with its danger level, or
   "no danger level set: readings are stored but not assessed"), firmware version, latitude +
   longitude, location description, description, and a required audit reason.
3. `POST` (CSRF) → validated server-side → device created (`status=active`, `enabled`) → `302` to the
   device page, which shows the API key **once** through the same one-time store as key rotation (PRG).
4. Device page **Edit device settings** (`POST /admin/devices/<id>/edit`, reason, audited): operator
   status, river (same district only; can be changed, not removed), firmware version, location
   description, latitude + longitude (both, or both empty = keep). These are the fields the PATCH API
   already allows; `enabled` keeps its own audited connect/disconnect action.

### Server-owned device location
- `IoTDevice.district_id` / `river_id` are set only here (or the existing API). The edit form cannot
  change the district, device ID, key or authority; extra form fields are ignored (explicit allow-list).
- Telemetry is unchanged: the device is identified by its header credentials; any `district`,
  `district_id`, `river_id` or `device_id` in the JSON body is ignored. The reading is tied to the
  registered district and river (test: a payload claiming Lalitpur still updates Kathmandu's Bagmati,
  creates a Kathmandu flood event and notifies Kathmandu citizens/authority + admins, not Lalitpur).

### Explicit river association
- Monitoring = flood / water level → a river is required (server-side; the UI also marks it required).
  A new water-level device therefore never relies on the telemetry fallback "first river in the
  district" (Kathmandu has Bagmati, Bishnumati and Manohara).
- The river must belong to the selected district (re-checked server-side; the JS filter is convenience).

### Security model
- Super Admin only (`/admin/*` `before_request`): citizens and authorities 403, anonymous → login.
  Role hierarchy and login unchanged. CSRF on both POSTs.
- Key: `IoTDevice.generate_api_key()`; only the SHA-256 hash is stored. The plaintext is held in the
  in-process one-time store (admin + device bound, 5 min), shown once with `Cache-Control: no-store`;
  never in the DB, a URL, the session cookie, browser storage, the flash, the audit log or the server log.
- Audit: `REGISTERED_DEVICE` (target = new device id; refusals audited with target `new`) and
  `UPDATED_DEVICE` (old → new values). Like every other Super Admin action, a missing reason and a
  403 for a non-admin are refused without an audit row.
- No migration: the two new audit action names are values of an existing string column.

### Tests
`tests/test_device_provisioning.py` (+33): admin opens the page; citizen/authority 403; anonymous →
login; CSRF; valid registration (district, river, coordinates); key shown once, absent from
reload/cookies/scripts/logs; plaintext not in the DB dump; audit row; 13 refusals (unknown/blank/
non-numeric district, river of another district, unknown river, missing flood river, latitude
without longitude and vice versa, out-of-range / NaN coordinates, bad device ID, blank name, unknown
monitoring), each audited; duplicate device ID; "other" monitoring without river/coordinates; no mass
assignment; telemetry cannot override the district and resolves to the registered river → flood event
→ district notifications; edit allowed fields + audit; edit refusals; edit 403 for non-admins.
Existing key-rotation tests unchanged and passing.
- **Final:** **`python -m pytest tests/ -q` → 960 passed, 2 warnings, 0 failed** (927 + 33 new; same 2
  third-party SWIG warnings). Migration: none; `flask db heads`/`current` = `a9c4e2f81d57 (head)`,
  `flask db check` = "No new upgrade operations detected".

### Chrome QA (throwaway copy of the dev DB, local server)
Admin → IoT devices → Register device → Kathmandu → river list became exactly Bagmati (3.5 m),
Bishnumati (3 m), Manohara (2.5 m) → Bagmati → registered ESP32-FLOOD-001 → key shown once (43 chars)
→ reload: no key → listed with Kathmandu / Bagmati River → detail shows Kathmandu + Bagmati River +
`REGISTERED_DEVICE` history → citizen gets 403 → no console errors. Key absent from URL,
JS-readable cookies, localStorage, sessionStorage, server log and DB.

### Known limitations
- `POST /api/iot/devices` (JSON API) still works for admins/authorities and is not audited; it does not
  know the "monitoring" choice, so it does not force a river.
- "Monitoring" is a provisioning choice, not a stored column; legacy devices without a river still use
  the telemetry fallback (first river in the district).
- No authority is assigned from the UI (the authority device list shows only devices with its
  `authority_id`); notifications target districts, so alerts are unaffected.
- A district cannot be changed after registration (register a new device instead).
- The one-time key store is per process (see the SA key-rotation note).

### Next
**H01 — physical hardware**: flash ESP32-FLOOD-001 with its key, send real `readings` and verify the path
end to end. Not started.

### 🏷️ Status
**H01.5 — IoT DEVICE PROVISIONING COMPLETE (960 passed) · NEXT: H01 physical hardware (not started)**


---

## M-LIVE-02 — Server-Side Mobile Evidence Foundation

### Purpose
The server-side contract for the future **Android mobile field node** (camera + GPS + local
active-landslide detector). The phone itself is **not built**: there is no Android code, no live
camera detection and no real-world landslide detection in this milestone. A camera node is a third
evidence source next to the ESP32 flood node and the MPU6050 seismic prototype, which are unchanged.
The phone produces evidence; X-MAN stays the authority for hazard events, severity, districts and
notifications.

### Architecture
```
camera_node device (IoTDevice.kind, provisioned by Super Admin, own key)
  -> POST /api/iot/evidence (same Bearer device auth as telemetry; sensors get 403)
  -> node_evidence_service: metadata allow-list, frames through citizen_report_service.process_image,
     idempotency, device-row lock + hourly limit, capture-time and GPS plausibility, hold policy
  -> NodeEvidence row
  -> hazard_event_service.report_hazard('landslide', 'medium', 'iot', escalate=False,
                                        district_id = device.district_id, detected_at = captured_at)
     (existing M02 create/merge, M03/M04 targeting + dedup, M12 Web Push — nothing new)
  -> after commit: vision_service.classify on the last frame (ai_* fields only, best-effort)
```
No second event, dedup, notification, image-sanitizing or authentication system was added.

### Migration
`e7413efdd252` (parent `a9c4e2f81d57`), additive only: `iot_devices.kind` (String(20), NOT NULL,
server default `'sensor'`, so every existing device is a sensor) and the `node_evidence` table
(unique `(device_id, client_event_id)` = `uq_node_evidence_device_event`, indexes on device_id,
district_id, incident_id, received_at). Verified on a copy of the dev DB: upgrade → `flask db check`
("No new upgrade operations detected") → downgrade → upgrade; one head. The dev DB was backed up
before `flask db upgrade`.

### Endpoint contract — `POST /api/iot/evidence`
- Auth: `Authorization: Bearer <device_id>:<api_key>` (or `X-Device-ID` + `X-API-Key`); the device
  must be `kind = camera_node`. CSRF-exempt like telemetry (no cookie involved); browser routes keep CSRF.
- `multipart/form-data`:
  - `metadata` (JSON object). Allowed: `client_event_id` (required, `^[A-Za-z0-9_-]{8,64}$`, generated
    once on the phone and reused on every retry), `captured_at` (required, ISO 8601), `latitude` +
    `longitude` (together), `gps_accuracy_m` (0–100000), `gps_fix_at`, `device_score` (0–1),
    `model`, `model_version`, `app_version`, `battery_pct` (0–100), `network_type`.
    Server-owned keys (`severity, district, district_id, status, confirmed, authority, authority_id,
    recipients, incident_id, event_type, hazard_type, source, received_at, affected_districts,
    device_id, review_status`) → **400**, not ignored. Any other unknown key or form field → 400.
  - `frame_0` (required), `frame_1`, `frame_2` (optional; pre-event, peak, post-event). JPG/PNG/WEBP
    with a matching extension and `image/*` type. More than 3, gaps, repeats → 400.
- Responses: **201** `{"success": true, "duplicate": false, "evidence_id", "incident_id", "status"}`;
  **200** same shape with `"duplicate": true` for a repeated `(device, client_event_id)`; 400 invalid;
  401 bad/disabled/decommissioned credentials; 403 not a camera node; 413 too large; 429 hourly limit.
  Never returns keys, hashes, filenames or paths.
- Other routes: `GET /api/iot/evidence/<id>/frames/<n>` (admin, or the authority of the evidence's
  district; others 404, logged out 401; `private, no-store`); `POST /api/iot/evidence/<id>/review`
  (`accepted|rejected`, same visibility, session + CSRF; changes the evidence only, never the hazard).

### Server-owned context
Hazard type `landslide`, severity `medium`, source `iot`, status `detected`, `escalate=False`,
district = the device's provisioned district. `device_score` is stored and shown to reviewers only.
Repeated evidence merges through the existing `find_active_related_event` (district + 5 km / 24 h);
an authority escalates/confirms through the existing hazard lifecycle. `detected_at` of a **new**
incident is the accepted `captured_at` (when the node observed it); `received_at` is always server time.

### Idempotency design
`(device_id, client_event_id)` is unique. A duplicate is detected before any work and re-checked after
the device row lock; it returns the stored evidence (200) and writes nothing: no row, no file, no
incident, no notification. Retries of a stored event succeed even when the hourly limit is reached, so
the phone can clear its queue. A retry with different frames is not merged (the first upload wins).

### Capture-time and hold policy (stored, never silently deleted)
- `captured_at` more than 5 min in the future → `held` (`future_capture`); older than
  `NODE_MAX_EVIDENCE_AGE_HOURS` (72) → `held` (`stale_capture`). No incident is opened.
- The node's own evidence led to an incident that was **rejected** within
  `NODE_HOLD_AFTER_REJECTION_HOURS` (24, from the rejection history row) → `held` (`after_rejection`),
  unless an active related landslide already exists (attaching opens nothing new). After the window
  normal processing resumes; a rejection never silences a node permanently.

### GPS validation policy (`gps_status`, `location_source` recorded on every row)
- `accepted` → the phone fix is used for the incident: present, `gps_accuracy_m ≤ NODE_MAX_GPS_ACCURACY_M`
  (50), `|captured_at − gps_fix_at| ≤ NODE_MAX_GPS_FIX_AGE_SECONDS` (300) and within
  `NODE_MAX_DISTANCE_KM` (1.0, haversine) of the registered node location.
- `missing` / `inaccurate` (incl. unknown accuracy) / `stale_fix` / `outside_radius` → the phone's
  coordinates are stored as reported; the **registered** location is used for the incident.
- Node without registered coordinates → `no_reference`: GPS recorded, never trusted; the incident is
  district-level (no coordinates).
- The district never comes from GPS: no reverse geocoding, no automatic reassignment.

### Rate-limit policy
`NODE_MAX_EVIDENCE_PER_HOUR` (6) stored evidence items per device per rolling hour (held items count),
429 above it. Transaction-safe without new services: the request first `UPDATE`s its own device row
(`last_seen`), which takes SQLite's write lock (PostgreSQL: a row lock) until commit, then counts and
inserts. Tested with 6 real threads on a file-backed SQLite DB (limit 2 → exactly 2×201 + 4×429, one
incident); with the lock removed the same test fails (3/3 runs).

### Security decisions
- `authenticate_device()` (shared with telemetry): refuses `status == 'decommissioned'` even when
  `enabled` is still true; the key check is `hmac.compare_digest` over the stored SHA-256 hash (storage
  and key rotation unchanged).
- A camera node's telemetry accepts **only** `battery` (new sensor type, `%`, 0–100, no risk rule):
  a phone key can't send `water_level`/`vibration`/`tilt` and drive flood (river fallback) or motion rules.
  ESP32s are not required to send battery.
- `kind` is chosen once at Super Admin registration (explicit radio, audited in `REGISTERED_DEVICE`);
  the edit form and `PATCH /api/iot/devices/<id>` cannot change it (PATCH → 400); the JSON
  registration API always creates sensors. Conversion = register a new device (documented limitation).
  A camera node cannot have a river.
- Frames: M05 sanitizer (format check, decompression-bomb guard, orientation, ≤2560 px, JPEG
  re-encode, EXIF/GPS dropped), `<uuid4hex>.jpg` names, stored in `instance/uploads/evidence/`
  (gitignored), served only by id + index after a visibility check; tampered stored names are not read.
- Evidence and frames are visible to admins and the evidence district's authority only (citizens and
  other districts 404). Reviewer pages escape all device metadata (tested with script payloads).
- AI failure (missing model, inference error, even a crash in the AI step) never loses evidence and
  never turns a committed upload into a 500.
- Risk: `assess_visual` gains a separate `field_node` source and a `field_node_only` grade when there
  is no citizen report. A node is never counted as a reporter, so citizen grades are unchanged.

### Admin / reviewer UI
`/admin/devices/new`: required **Device kind** (Sensor / Camera node — "trusted identity for field
evidence uploads"); monitoring/river only for sensors. Device page: kind, evidence total, last
evidence time, per-status counts, 10 newest items (status/hold reason, GPS state, AI, review, hazard
link, frame links). `/reports/review`: a "Field-node evidence" section (source = field node, node,
capture/received time, GPS check + accuracy, battery, model/app version, device score marked
unverified, frames, AI, review buttons).

### Files changed
`app/models/iot_device.py`, `app/models/node_evidence.py` (new), `app/models/__init__.py`,
`app/routes/iot.py`, `app/routes/admin.py`, `app/routes/reports.py`,
`app/services/node_evidence_service.py` (new), `app/services/citizen_report_service.py`
(vision-field writing extracted into `record_vision_analysis`, behaviour unchanged),
`app/services/admin_service.py`, `app/services/risk_engine.py`, `app/services/risk_service.py`,
`app/config.py`, `app/templates/admin/device_register.html`, `app/templates/admin/device_detail.html`,
`app/templates/pages/review_reports.html`, `migrations/versions/e7413efdd252_mlive02_camera_node_evidence.py`
(new), `tests/test_node_evidence.py` (new), `tests/test_device_provisioning.py` (its form now sends the
required `kind=sensor`), `tests/test_iot_water_level.py` (expected sensor-type set + `battery`),
`tests/test_super_admin.py` (migration test: head is now `e7413efdd252`; it downgrades explicitly to
`f3b8d2e6a417` and back, `flask db check` clean), `docs/PROJECT_PROGRESS.md`.

### Tests
`tests/test_node_evidence.py`: 157 tests (auth incl. decommissioned/rotation/constant-time, sensor 403,
each forbidden field, metadata validation, frames 1/3/4/gaps/invalid/bomb/oversize/EXIF, idempotency,
dedup into node and citizen incidents, timestamps, GPS states, hold window, rate limit incl. threads,
AI success/failure/crash, risk sources, notification targeting + no push at medium + push after
authority escalation, frame/review authorization and traversal, battery telemetry, secrets in
response/DB/logs/pages, XSS, provisioning). Full suite: **`python -m pytest tests/ -q` → 1117 passed, 2 warnings, 0 failed** (960 + 157; same 2 third-party SWIG warnings).

### Manual smoke test (local server on a throwaway, migrated copy of the dev DB; port 5055; curl)
Throwaway camera node `SMOKE-CAM-01` (Kathmandu) → multipart upload → **201**
`{"duplicate":false,"evidence_id":1,"incident_id":1,"status":"attached"}` → DB: evidence `attached`,
GPS `accepted`, one sanitized `<uuid>.jpg` on disk; incident `landslide/medium/iot/detected`, district
Kathmandu, `source_reference evidence_1`; `hazard_detected` notifications for the Kathmandu citizen and
the admin. Same `client_event_id` again → **200** `"duplicate":true`, same ids. `severity` in metadata →
**400**. Device disabled via `admin_service.set_device_enabled` → same key → **401**. The key does not
appear in the server log. Vision was disabled for the smoke test (no model download); AI is covered by
stub-classifier tests only.

### Known limitations
- No Android app, no live detection, no field validation: every threshold is an engineering default.
- `kind` can't be converted; register a new device. The admin "disable" message still says "ESP32".
- The incident ↔ evidence link uses two commits, like M05 reports: if the second fails the evidence stays
  `received` without `incident_id` (the incident's `source_reference` still names it).
- Existing dedup excludes events without coordinates from a GPS-located match (and vice versa), so a
  node event and a coordinate-less event in the same district stay separate (unchanged M02 behaviour).
- Frames of rejected evidence are kept (no retention job yet). No server-side "re-run analysis" for
  evidence. Bearer keys need TLS outside a LAN demo (same as the ESP32s).
- The rate limit counts stored items only; invalid requests are not limited.

### Next milestone
**M-LIVE-03 — Native Android Field Node Skeleton**: provisioned camera node → manual test evidence →
authenticated upload → X-MAN → existing incident → existing notification, without automatic
landslide detection. Not started.

### 🏷️ Status
**M-LIVE-02 — SERVER-SIDE MOBILE EVIDENCE FOUNDATION COMPLETE (1117 passed) · NEXT: M-LIVE-03 Android skeleton (not started)**


---

## M-LIVE-03 — Native Android Field Node Skeleton

**This milestone does not implement automatic landslide detection.** The app is a *manual* test-evidence
uploader: a person captures 1–3 frames and presses **Send Test Evidence**. There is no MotionGate, no
optical flow, no on-device model, no continuous or background camera, no foreground service and no
automatic trigger. It proves the path:

```
Android phone (registered camera_node identity)
  -> CameraX capture (manual) + platform GPS fix
  -> authenticated multipart POST /api/iot/evidence (M-LIVE-02 contract, unchanged)
  -> NodeEvidence -> existing landslide Incident (report_hazard) -> existing notifications
```
No server code changed in this milestone.

### Project structure (`mobile/android/`, independent Gradle build; the Flask app is untouched)
```
settings.gradle.kts, build.gradle.kts, gradle.properties, gradlew(.bat), gradle/wrapper/  (Gradle 9.8.0, SHA-256 pinned)
app/build.gradle.kts
app/src/main/AndroidManifest.xml
app/src/main/java/np/xman/fieldnode/
  EvidencePackage.kt   local package model + states, client_event_id (UUID v4)
  EvidenceStore.kt     app-private package storage (files/evidence/<client_event_id>/)
  EvidenceMetadata.kt  the `metadata` JSON (allow-listed keys only)
  Upload.kt            response -> state mapping, multipart body, HttpURLConnection transport, uploader
  Credentials.kt       CredentialStore (Keystore ciphertext), NodeConfig, ServerUrlPolicy
  Platform.kt          KeystoreCipher, SharedPreferences store, battery/network, GPS, JPEG encoder
  MainActivity / ProvisionActivity / CaptureActivity / ResultActivity
app/src/main/res/      layouts, strings, network_security_config (HTTPS only), data_extraction_rules (no backup)
app/src/debug/res/xml/network_security_config.xml   debug-only cleartext (see Server URL)
app/src/test/          JVM unit tests        app/src/androidTest/   on-device Keystore tests
```
Build: JDK 17 + Android SDK, `cd mobile/android && ./gradlew assembleDebug testDebugUnitTest`
(`local.properties` with `sdk.dir` is machine-specific and git-ignored).

### Versions (checked against the official release feeds on 2026-10-04)
- compileSdk **37**, targetSdk **37** (Android 17; `platforms;android-37.0`), minSdk **26** (Android 8.0)
- Android Gradle Plugin **9.4.1** (latest stable) with AGP's built-in Kotlin: Kotlin Gradle plugin **2.2.10**
- Gradle **9.8.0**, JDK **17** (Eclipse Temurin 17.0.20), build-tools 36.0.0
- Dependencies (all free, no Google Play Services): `androidx.activity:activity-ktx:1.13.0`,
  `androidx.camera:camera-camera2/-lifecycle/-view:1.6.2`. Tests: JUnit 4.13.2, `org.json:json:20260814`
  (JVM tests only), `androidx.test:runner:1.7.0`, `androidx.test.ext:junit:1.3.0`. No AppCompat, no
  OkHttp, no WorkManager, no ML libraries.

### Provisioning flow
Super Admin registers the node (device kind **Camera node**, M-LIVE-02) → the one-time API key is shown
once → on the phone, **Provisioning**: server URL, device ID, API key → **Save**. The phone is an
infrastructure node, not a citizen account: no login/registration. "Clear credentials" deletes the
stored values and the Keystore key (captured evidence is kept). **Test connection** only checks
reachability through the public `/api/health` and sends no credentials: X-MAN has no authenticated
device health endpoint and none was added, so credentials are proven by the first evidence upload.

### Credential security
- The API key is encrypted with an AES-256-GCM key generated inside the **Android Keystore** (not
  exportable); only IV + ciphertext are stored in app-private SharedPreferences. Never in source,
  Gradle files, URLs, query strings, logs, UI after saving, or plaintext prefs (verified on the phone).
- The key field is never pre-filled; the provisioning screen sets `FLAG_SECURE` (no screenshots/recents).
- `allowBackup=false` + data-extraction rules exclude everything from cloud backup and device transfer.
- Only log line for uploads: `authenticated upload attempted` (never the header, key or device ID).
- Normal system certificate validation; no trust-all, no hostname bypass, no pinning yet (to be
  evaluated for production). Redirects are not followed, so the Authorization header can't be replayed elsewhere.

### Server URL
Release builds: HTTPS only (network security config + `ServerUrlPolicy`). Debug builds: `http://` is
also accepted, **only** for localhost / 10.x / 172.16–31.x / 192.168.x (development against a local
X-MAN). The platform config can't express IP ranges, so the debug config allows cleartext and the app
enforces the private-address rule. URLs with credentials, query or fragment are refused. No Flask
production setting was changed. **HTTP is development-only; production must use HTTPS.**

### Camera
CameraX `Preview` + `ImageCapture` bound to the capture screen's lifecycle (stops when the screen
closes). Up to 3 frames; thumbnails; "Clear frames". Each frame is decoded, rotated upright, scaled to
≤1600 px and re-encoded as a fresh JPEG (no EXIF written) into app-private storage, never the gallery.
This is for bandwidth only: the server's `process_image()` remains the security boundary.
Camera permission is requested on the capture screen with the rationale "Camera access is required to
capture field evidence."; after a denial a button re-asks once or opens the app settings.

### GPS
Platform `LocationManager` GPS provider via `LocationManagerCompat.getCurrentLocation` (no Play
Services), requested only when the user presses **Get GPS fix**, with the rationale shown. The screen
shows latitude/longitude, accuracy and fix time. No fix → no coordinates are sent (never cached or
invented); the user can retry. Permission denied → evidence can still be sent, with a warning; X-MAN
uses the registered node location. The phone never sends a district.

### Upload contract (M-LIVE-02, unchanged)
`POST <server>/api/iot/evidence`, `Authorization: Bearer <device_id>:<api_key>`, multipart:
`metadata` (JSON) + `frame_0..frame_2` (`frame_N.jpg`, `image/jpeg`). Metadata sent: `client_event_id`
(UUID v4), `captured_at` (first frame, device clock, ISO 8601 UTC), `latitude`/`longitude`/
`gps_accuracy_m`/`gps_fix_at` only with a real fix, `app_version`, `battery_pct`, `network_type`
(`wifi`/`cellular`/`ethernet`/`unknown`/`none`; no SSID, MAC or IP). **Not sent:** `device_score`,
`model`, `model_version` (no detector exists) and every server-owned field.

### Local states, retry and storage
`DRAFT → READY → UPLOADING → UPLOADED | FAILED_RETRYABLE | FAILED_PERMANENT`.
"Send Test Evidence" freezes the metadata (READY); every attempt resends the same `client_event_id` and
identical metadata. Frames stay in `files/evidence/<id>/` until X-MAN confirms (201, or 200 with
`duplicate: true`); then only the small result record is kept. Responses: 201 → uploaded; 200 duplicate →
uploaded ("already accepted"); 400/403/413 (other 4xx) → FAILED_PERMANENT, never retried (discard
button); 401 → "Camera node credentials invalid or revoked. Re-provision this device." (retry allowed
after re-provisioning; no automatic rotation); 429 → rate-limited, retry later; 5xx / network / timeout
→ FAILED_RETRYABLE. A package interrupted mid-upload (app killed) reloads as FAILED_RETRYABLE.
Retry is a manual "Retry upload" button. **No WorkManager**: automatic background upload isn't required
yet and a manual foreground retry with persisted packages already guarantees that network loss can't
destroy evidence.

### Tests
**AUTOMATED (JVM, `./gradlew testDebugUnitTest`) — 45 passed, 0 failed:** client_event_id generation,
uniqueness and server-regex compatibility; persistence round trip; metadata required fields, allow-list,
forbidden fields absent, no detector claims, GPS omitted without a fix, unknown accuracy not invented,
invalid battery omitted; response mapping for 201, 200 duplicate, 200 non-duplicate, 400, 401, 403,
404, 413, 429, 5xx, network failure, held evidence (no incident), long errors truncated; multipart part
names/filenames/types, 1–3 frames, no local paths; store: frames survive restart, max 3 frames, READY
needs a frame, interrupted upload → retryable, ids can't escape the evidence folder; uploader: success
stores ids and drops frames, network failure keeps frames and retries reuse the same id + identical
metadata, 400 never retried, uploaded never resent, drafts not uploaded, duplicate accepted, 401
message, 429; no key/`Bearer` in logs or on disk, no key or forbidden field in the body; credentials:
encrypted at rest, retrievable, clear removes everything + key, lost Keystore key → no key (no crash),
validation messages never echo the key; server URL policy (HTTPS, LAN-HTTP debug only, public HTTP
refused, no userinfo/query/fragment).
Lint (`lintDebug`): 0 errors; 33 warnings, all accepted for this prototype: 21 HardcodedText + 6
SetTextI18n (English-only UI), 2 ButtonStyle, 2 UseKtx, 1 MissingApplicationIcon, 1
InsecureBaseConfiguration (the intended debug-only cleartext config).

**MANUAL ANDROID TESTS (physical Redmi 12, model 23053RN02A, Android 15 / API 35, HyperOS; USB + `adb`):**
- Instrumented `KeystoreCredentialTest` on the phone: **OK (2 tests)**: real Android Keystore round
  trip, no plaintext key in `shared_prefs/camera_node.xml`, clear deletes the Keystore key.
- Debug APK installed with `adb install` (HyperOS refuses Gradle's `-g` install flag); X-MAN reached
  through `adb reverse tcp:5055` as `http://localhost:5055` (no LAN exposure, no firewall change).
- Provisioned as `PHONE-LANDSLIDE-TEST-001`; on the phone only `server_url`, `device_id`, `api_key_iv`,
  `api_key_ciphertext` were stored, and the plaintext key did not appear in the prefs file.
- Captured 3 frames by hand → **Send Test Evidence** → **201**, app shows "UPLOADED – Accepted by
  X-MAN", frames removed from the phone afterwards. Location permission had not been granted, so no
  GPS was sent (server `gps_status = missing`); a GPS fix was **not** obtained in this session, so the
  GPS fields were not exercised on the device (covered by unit tests only).
- Network-loss test: server stopped → new package → **FAILED_RETRYABLE** "Network unavailable…",
  3 frames + metadata kept in app-private storage → server restarted → **Retry upload** → **201** with
  the **same** `client_event_id`.
- Disabled-device test: node disabled in Super Admin → new package → HTTP **401** → app shows "Camera
  node credentials invalid or revoked. Re-provision this device.", frame kept.
- Logcat after the session (117,937 lines): no API key, no `Bearer`, no device ID; the app's only line
  was `authenticated upload attempted` (7×).

**SERVER SMOKE TESTS (local X-MAN on a throwaway, migrated copy of the dev DB; never the dev DB):**
- Node registered through the real Super Admin route (`/admin/devices/new`, kind camera_node,
  Kathmandu, no registered coordinates; `REGISTERED_DEVICE` audited); one-time key from the device page.
- Phone upload → NodeEvidence #1 `attached`, 3 sanitized frames, battery 97, `wifi`, app
  `0.1.0-mlive03`, no device_score/model, `gps_status missing` → `location_source district`;
  Incident #1 **landslide / medium / iot / detected / Kathmandu**, `source_reference evidence_1`;
  `hazard_detected` (medium) notifications to the Kathmandu citizen and the admins through the existing system.
- Duplicate: the phone's own frozen metadata (read from app storage) replayed with the same key and
  `client_event_id` → **200 `duplicate: true`**, same evidence_id 1 / incident_id 1; evidence, incident
  and notification counts unchanged (1 / 1 / 3). (The app itself never resends an accepted package.)
- Retried package → merged into Incident #1 (report_count 2), no new notifications.
- Disabled device (`DISABLED_DEVICE` audited) → 401, nothing stored.
- Cleanup: credentials cleared on the phone (prefs empty, Keystore key deleted), test packages
  deleted, `adb reverse` removed, throwaway DB / frames / key / logs deleted. The dev DB contains no
  test node and no evidence.
- Full X-MAN Python suite: **`python -m pytest tests/ -q` → 1117 passed, 2 warnings, 0 failed, 0 errors** (unchanged: no server code changed).

### Known limitations
- No automatic detection, no continuous/background camera, no automatic background upload (manual retry).
- GPS fix not exercised on the physical phone in this session; `stale_fix`/`accepted` paths are server-tested only.
- Physical test used USB `adb reverse` to a local HTTP server, not HTTPS over a real network.
- English-only UI, no launcher icon, one evidence package handled at a time in the UI ("Open last evidence").
- No certificate pinning; device clock trusted for `captured_at` (server validates plausibility).
- HyperOS needs "Install via USB" and "USB debugging (Security settings)" for adb install/input.

### Next milestone
**M-LIVE-04 — Native Android continuous camera pipeline + MotionGate + temporal state machine.** Not started.

### 🏷️ Status
**M-LIVE-03 — NATIVE ANDROID FIELD NODE SKELETON COMPLETE (manual uploader; phone → X-MAN proven on a Redmi 12) · NEXT: M-LIVE-04 (not started)**


---

## M-LIVE-04 — Continuous Camera Pipeline + MotionGate + Temporal State Machine

**Not landslide detection.** The phone detects *persistent local visual change* and turns it into a
"visual evidence candidate". No prediction, no calibrated probability, no severity, no emergency: X-MAN
stays authoritative (server code unchanged; same `/api/iot/evidence` contract). No ML model or ML
dependency was added. Commit: `feat(mlive): add continuous camera monitoring pipeline` (hash in `git log`).

### Architecture (`mobile/android/app/src/main/java/np/xman/fieldnode/`)
```
MonitorActivity  CameraX Preview + ImageAnalysis (YUV, STRATEGY_KEEP_ONLY_LATEST, own single thread),
                 bound only between Start/Stop; screen kept on; leaving the screen stops monitoring
  -> FrameSampler      (MonitorConfig.kt) rate limit 1 frame / 500 ms; Y plane block-averaged to 64x48
  -> MotionGate        (MotionGate.kt) deterministic local-change test between consecutive samples
  -> MonitorStateMachine (MonitorStateMachine.kt) pure temporal confirmation, timestamps as inputs
  -> MonitorController (MonitorController.kt) glue: keyframes, GPS at confirmation, store, upload, diagnostics
  -> KeyframeCollector / EvidenceAssembler (KeyframeCollector.kt) -> M-LIVE-03 EvidenceStore / EvidenceMetadata
     / EvidenceUploader (unchanged upload protocol, same client_event_id on every retry)
```
No foreground service, no background camera, no WorkManager, no video, no unbounded buffer: the controller
holds one previous 64x48 grid and at most three JPEG keyframes; a Bitmap is created only for a keyframe.

### MotionGate (exact algorithm)
1. z-normalize each 64x48 grid: (v − mean) / max(std, 4) — removes uniform brightness offset and exposure gain.
2. 16x12 cells of 4x4 grid pixels; a cell changed if mean |Δz| > 0.5 (averaging rejects pixel/JPEG noise).
3. 0 changed cells → STATIC; < 3 → NOISE.
4. SHAKE if some whole-frame shift of ±2 grid pixels (≈±20 camera pixels at 640 px) brings the mean residual
   to ≤ 0.6 × the unshifted residual (the frames are a translation of each other).
5. > 50 % of cells changed → GLOBAL_CHANGE (lighting, pan, reflections).
6. Largest 4-connected group of changed cells < 3 → NOISE (scattered); else LOCAL_MOTION.
Assumes a mounted phone, ~500 ms between samples and a textured scene. It cannot tell a slope movement from
a person, vehicle, animal, branch or rain streak.

### State machine
`STOPPED → MONITORING → POSSIBLE_EVENT → CONFIRMING → CONFIRMED_EVIDENCE → UPLOAD_PENDING → UPLOADED → COOLDOWN → MONITORING`, plus `DEGRADED`.
- MONITORING: LOCAL_MOTION → POSSIBLE_EVENT (keyframe 1, "around detection").
- POSSIBLE_EVENT: 3 local-motion samples → CONFIRMING; 2 consecutive non-motion samples → MONITORING (keyframes dropped).
- CONFIRMING: 4 s window; ≥ 60 % of samples local motion → CONFIRMED_EVIDENCE (keyframe 2), otherwise or after
  3 consecutive misses → MONITORING. A single transient sample can never produce evidence (minimum ≈ 5.5 s of change).
- CONFIRMED_EVIDENCE: one GPS request (platform layer); next sample = keyframe 3 ("after"); package stored when
  GPS answered (or 35 s) and the after-frame arrived (or 3 s) → UPLOAD_PENDING.
- UPLOAD_PENDING: auto-upload ON → upload → UPLOADED → COOLDOWN; failed/offline or auto-upload OFF → COOLDOWN with
  the package kept on the phone (READY / FAILED_RETRYABLE, same client_event_id, manual retry as in M-LIVE-03).
- COOLDOWN: 60 s, motion ignored. DEGRADED: camera error (nothing analysed) → camera OPEN again → MONITORING.
- Safety timeouts: CONFIRMED_EVIDENCE 45 s, UPLOAD_PENDING 120 s. Stop/camera error during collection still
  saves the confirmed candidate (GPS marked unavailable). Stop from any state → STOPPED, counters reset per session.

### Configuration (`MonitorConfig`, single place)
analysisIntervalMs 500 · grid 64x48 · cellSize 4 · cellThreshold 0.5 · minChangedCells 3 · minRegionCells 3 ·
maxLocalFraction 0.5 · maxShakeShift 2 · shakeResidualRatio 0.6 · minStd 4 · possibleHitsToConfirm 3 ·
possibleMaxMisses 2 · confirmWindowMs 4000 · confirmMinMotionRatio 0.6 · confirmMaxConsecutiveMisses 3 ·
cooldownMs 60000 · evidenceTimeoutMs 45000 · uploadTimeoutMs 120000 · afterFrameTimeoutMs 3000 · gpsTimeoutMs 35000.
Engineering defaults, not validated against real slope failures.

### Evidence, GPS, metadata
≤ 3 keyframes (detection, confirmed, after), upright JPEG ≤ 1600 px, no EXIF, app-private storage. `captured_at`
= detection time. GPS requested once at confirmation; package records `gpsNote` ("fix", "unavailable: no location
permission / GPS switched off / no fix obtained / no fix in time / monitoring stopped before a fix"); no fix → no
coordinates (registered coordinates are never sent as GPS). Motion-gate packages send `model: motion-gate`,
`model_version: mlive04-1` (names the deterministic trigger); never `device_score`. Manual packages unchanged.
Auto-upload is an explicit checkbox, OFF by default.

### Tests
- Android JVM: **86 passed, 0 failed** (45 M-LIVE-03 + 41 new): MotionGate (identical, sensor noise, local change,
  brightness offset/gain, lighting + local change, shake shifts, totally different frame, scattered noise, threshold
  boundaries, flat scene), FrameSampler (stride, unsigned bytes), state machine (possible event, transient → back,
  persistence → evidence, intermittent window, early reset, full flow + cooldown, failed upload, timeouts, degraded +
  recovery, stop resets, minimum time to evidence), controller (static creates nothing, one bounded 3-frame package +
  one GPS request + upload, cooldown, transient keeps nothing, no-GPS note, GPS timeout + late answer ignored,
  offline keeps frames + id, manual mode READY, stop during collection saves, rate limit, camera error, per-session
  diagnostics), assembler (bounded frames, stable id, slot never re-encoded, old packages load as manual).
- Lint: 0 errors (warnings: hard-coded UI text, no launcher icon, button style, debug-only cleartext config).
- Build: debug + release OK. X-MAN Python suite: **`python -m pytest tests/ -q` → 1117 passed, 2 warnings, 0 failed**. Server code: unchanged.

### Physical test (Redmi 12, Android 15 / HyperOS, USB `adb reverse` to a throwaway local X-MAN; disposable node `PHONE-LANDSLIDE-TEST-004`)
- Start monitoring: live preview, Android camera service shows the app as camera client; **Stop**: client gone,
  app CPU 30–40 % → 0–3 %, status OFF.
- Static scene, phone propped, 2 min: 235 frames at 2.0 frames/s → static 223, noise 7, global_change 4, shake 0;
  **0 local motion, 0 possible events, 0 candidates**.
- One quick hand pass: possible visual events, no candidate from the pass itself. In the following seconds movement
  in the background of the scene (fabric / something moving at the frame edge, visible in the uploaded keyframes)
  lasted ~5 s and **was confirmed as a candidate** — correct for "persistent local visual change", and a clear
  example of why the gate must not be called landslide detection (region-of-interest masking needed later).
- Deliberate ~10 s hand movement: possible event → confirming → candidate → GPS requested → upload 201 → cooldown.
- Server (throwaway DB): 4 automatic candidates during the session, each 3 sanitized frames, `device_model
  motion-gate / mlive04-1`, no device_score, app `0.2.0-mlive04`; GPS states `missing` (no fix indoors),
  `inaccurate` (indoor fix > 50 m), `no_reference` (fix received, node has no registered coordinates → not
  trusted); all merged into one landslide / medium / iot / detected Kathmandu incident (report_count 4), notifications
  sent once (3), never escalated.
- Not physically exercised: camera shake rejection (unit-tested only), DEGRADED/recovery (unit-tested only), offline
  candidate on the phone (unit-tested; the manual-retry path was proven on the phone in M-LIVE-03), long-duration
  battery drain.
- Performance: ~28 camera frames/s delivered, ~2/s analysed (the rest closed immediately); app CPU 28–42 % of one core
  while monitoring (preview + analysis), total PSS ~139 MB; 0–3 % after Stop.
- Cleanup: phone credentials + Keystore key cleared, test packages deleted, adb reverse removed, throwaway DB/frames/key
  deleted; logcat (116,147 lines) contained no API key, no `Bearer`, no device ID. Dev DB untouched.
- Found and fixed during the test: the FPS figure spanned stop/start gaps (diagnostics are now per session; 0 when stopped).

### Known limitations
- Change detector only: people, animals, vehicles, vegetation, rain and background movement produce candidates; no
  region-of-interest mask yet; night/IR not handled; thresholds untuned on real slopes.
- Foreground only (screen on, app visible); no unattended background operation, no automatic background retry.
- CameraX still delivers ~28 frames/s that are dropped; a lower camera frame rate could save power (not done).
- Shake test assumes small translations; rotation/zoom-like shake may pass as GLOBAL_CHANGE or NOISE, not SHAKE.
- Auto-upload of untuned candidates creates real (medium) X-MAN incidents: keep it OFF outside tests.

### Next milestone
**M-LIVE-05** (not started): region-of-interest masking + on-device lightweight classifier evaluation on recorded slope footage.

### 🏷️ Status
**M-LIVE-04 — CONTINUOUS CAMERA PIPELINE + MOTIONGATE + TEMPORAL STATE MACHINE COMPLETE (visual change only; not landslide detection)**


---

## M-LIVE-05 — ROI-Based Visual Monitoring (final mobile-node milestone)

**Still deterministic visual-change monitoring — not landslide detection.** The user selects the area to
monitor; only that area can produce "possible visual events" and "visual evidence candidates". No ML, no new
dependency, no background camera, no new upload protocol, **no server change**. Commit:
`feat(mlive): add ROI-based visual monitoring` (hash in `git log`). **Android/mobile feature development is now
frozen** (critical bug fixes only); next: physical flood hardware.

### ROI design
- `NormRect` (`Roi.kt`): fractions of the frame (0..1), so it survives any camera resolution. Built only through
  `of()` / `decode()`: corners in any order, clamped to the frame, refused if not finite or if a side is < 10 %
  (zero-area and unusably tiny regions are impossible); `copy()` is private. Persisted in app-private prefs.
- Drawn on the upright preview: `RoiOverlayView` over a FIT_CENTER `PreviewView` (whole 4:3 frame visible, the
  overlay computes the same content rectangle) — yellow outline + "Selected area" / "Monitoring selected area".
  Locked while monitoring; "Use full frame" resets it; the monitoring screen is portrait-locked so a drawn area
  always means the same part of the scene.
- `toSensor(rotationDegrees)` maps upright fractions into the camera buffer (0/90/180/270, unit-tested both ways).
- Default = full frame → exactly the M-LIVE-04 pipeline.
- Camera modes: screen visible → **preview only** (area selection, nothing analysed); Start → preview + analysis;
  Stop or leaving the screen → camera **released**. Keyframes have the monitored area outlined for reviewers.

### MotionGate integration (exact changes)
- `FrameSampler.downsample(..., roi)`: samples ≤ 5x5 evenly spaced pixels per grid cell inside the ROI (never an
  empty cell) into the same 64x48 grid — a small area gets more detail at the same cost.
- `MotionGate.compare()` is unchanged (z-normalization, 0.5 cell threshold, ≥ 3 changed cells, shake by ±2-pixel
  shift, > 50 % = global, ≥ 3-cell connected region). New `MotionGate.classify(roiPrev, roiCur, framePrev, frameCur)`:
  the ROI result decides; when the ROI says LOCAL_MOTION the whole-frame result can veto it — frame SHAKE → SHAKE
  (the camera moved, so the scene slid under the ROI), frame GLOBAL_CHANGE → GLOBAL_CHANGE (lighting, or something
  covering most of the view). Motion outside the ROI can never create a hit. Without a frame grid (ROI = full
  frame) `classify == compare`.
- Same `MonitorStateMachine` (no second state machine), same `MonitorConfig` thresholds (persistence 3 samples,
  4 s window ≥ 60 %, 60 s cooldown, timeouts); new config only `NormRect.MIN_SIDE = 0.1`.
- Evidence: same `KeyframeCollector` (≤ 3), `EvidenceStore`, `EvidenceMetadata` (`model_version` now
  `mlive05-1`), uploader and `/api/iot/evidence`. GPS once at confirmation, never invented. Auto-upload checkbox
  kept, OFF by default, its state shown in the status. Diagnostics and status lines are per monitoring session.

### Tests
- Android JVM: **108 passed, 0 failed** (86 previous + 22 new): ROI accepted / any corner order, clamping, zero-area
  and tiny rejected (incl. the 0.1 float boundary), default/decode fallback, rotation round trips, same scene region
  at 320x240 and 1280x960, small ROI fills every cell; MotionGate on ROI: identical static, noise rejected, local
  change inside → candidate, motion outside → static (while the full frame would fire), small change visible only
  thanks to ROI detail, brightness offset/gain rejected, shake vetoed, large whole-view change vetoed, full-frame
  ROI ≡ M-LIVE-04; controller: static area nothing, persistent outside motion nothing, transient inside no
  confirmation, persistent inside one bounded 3-frame READY package (auto-upload off), stop/degraded/recovery,
  auto-upload default off; per-session status reset.
- Lint: 0 errors. Debug + release build OK. X-MAN Python suite: **`python -m pytest tests/ -q` → 1117 passed, 2 warnings, 0 failed**.

### Redmi 12 physical test (Android 15/HyperOS, USB `adb reverse` → throwaway local X-MAN, disposable node `PHONE-LANDSLIDE-TEST-005`)
- Preview-only mode on opening the screen; area drawn by drag → saved (0.524, 0.100)–(0.970, 0.965), exactly the
  value computed from the FIT_CENTER geometry; yellow outline + label visible (the dimming outside the area is not
  visible over the camera surface on this device).
- **A – static** (area 44 % x 86 %, nobody in view, 2 min): 276 frames → static 275, **0 motion, 0 possible events,
  0 candidates**. (A first attempt was invalid: a person walked through the room into the area — correctly detected;
  those two packages were deleted from the phone without upload.)
- **B – motion outside the area** (10 s, watched on screen): motion samples in area 33 → 33, possible events 1 → 1,
  global 34 → 34: **no effect**. (An earlier attempt had fingers inside the box — keyframes showed it.)
- **C – movement inside**: ~3 s wave → possible visual events 1 → 5, motion samples 33 → 50, back to monitoring,
  **no candidate**; a sub-second pass fell between the 2/s samples and registered nothing.
- **D – persistent movement inside**: status "confirming persistent change" → "visual evidence candidate" →
  GPS fix ±8.7 m → auto-upload 201.
- **E – Stop**: camera clients 1 → 0, CPU → 0.0 %, status "Camera: released", frames analysed frozen. Screen
  timeout while stopped also released the preview camera (onStop).
- **F – X-MAN (throwaway DB)**: NodeEvidence attached, 3 sanitized frames (area outlined), `motion-gate / mlive05-1`,
  no device_score, `gps_status no_reference` (fix recorded, node has no registered coordinates) → district location;
  Incident landslide / medium / iot / detected, Kathmandu; `hazard_detected` notifications via the existing system.
- Performance: monitoring with an area 39–55 % of one core (M-LIVE-04 full frame 28–42 %; extra whole-frame context
  grid + 4:3 binding), PSS 124–139 MB (unchanged), 0 % after Stop. ~28 camera frames/s delivered, 2/s analysed.
- Cleanup: phone credentials + Keystore key cleared, packages and saved area deleted, adb reverse removed, throwaway
  DB/frames/key deleted; logcat (117,888 lines) had no API key, no `Bearer`, no device ID. Dev DB untouched.
- Found and fixed during the test: status lines (last event, GPS, upload) carried over from a previous session.

### Known limitations
- Change detection only: a person, animal or object moving inside the area produces candidates (seen in test).
- Whole-frame veto: a large movement elsewhere (> 50 % of the view) can mask a simultaneous change inside the area;
  only translation shake is recognized, no stabilization; a tilted/moved phone needs the area redrawn.
- Sub-second events can fall between the 2/s samples; persistence by design needs ≈ 5.5 s of change.
- Foreground only (screen on, app visible); portrait-locked monitoring screen; no night/IR handling.
- CPU somewhat higher with an area selected; ~28 frames/s still delivered and dropped by CameraX.
- Auto-upload creates real (medium) X-MAN incidents: keep it OFF outside tests.

### Next milestone
**Physical flood hardware** (ESP32 + JSN-SR04T flood node, H01). Mobile/Android development is frozen.

### 🏷️ Status
**M-LIVE-05 — ROI-BASED VISUAL MONITORING COMPLETE · MOBILE NODE FROZEN · NEXT: PHYSICAL FLOOD HARDWARE**
