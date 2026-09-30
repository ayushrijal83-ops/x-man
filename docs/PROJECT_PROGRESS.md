# NepalSathi - Project Progress

## Current Status: M04 Alert Deduplication + Affected Areas Complete (M03 Notifications, M02 Hazard Events, M01 Hardware Readiness)

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
- M05 — Mobile Camera Citizen Reporting (see the M04 section at the end).
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
