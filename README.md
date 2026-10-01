# NepalSathi

**District intelligence for Nepal.** Road closures, river levels, and infrastructure projects for all 77 districts — reported by the people who live there, tracked against the authorities who maintain them.

<p>
  <img alt="Python" src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="Flask" src="https://img.shields.io/badge/Flask-3.0-000000?logo=flask&logoColor=white">
  <img alt="SQLite" src="https://img.shields.io/badge/SQLite-003B57?logo=sqlite&logoColor=white">
  <img alt="Ollama" src="https://img.shields.io/badge/LLM-Ollama%20(local)-black">
  <img alt="Languages" src="https://img.shields.io/badge/i18n-EN%20%7C%20ने%20%7C%20नेवा%20%7C%20मै-8B4513">
</p>

---

## Contents

- [What it does](#what-it-does)
- [Tech stack](#tech-stack)
- [Hardware](#hardware)
- [Quick start](#quick-start)
- [Loading Nepal data](#loading-nepal-data)
- [Where the data comes from](#where-the-data-comes-from)
- [Multi-language support](#multi-language-support)
- [Theming](#theming)
- [Project structure](#project-structure)
- [Route reference](#route-reference)
- [Testing](#testing)
- [Known limitations](#known-limitations)
- [Roadmap](#roadmap)

---

## What it does

| Feature | Description |
| --- | --- |
| **Road status** | Segment-level conditions across 34 highways, with closure and traffic state per district |
| **River monitoring** | Water levels against danger marks, with `normal` / `rising` / `flooding` derived from the ratio |
| **Project tracking** | Public works with budget, spend, contractor, and completion percentage |
| **Complaints** | File an issue against the responsible authority and track it to a response |
| **Travel planner** | Route risk score built from live road status and river levels on that corridor |
| **AI assistant** | Ask about conditions in Nepali or English, answered by a local LLM — no API key, no data leaves the machine |
| **Community feed** | District-scoped posts with photo upload and AI auto-classification (category, severity, language) |
| **Authority panel** | Separate login where authorities update the roads, rivers, and projects they own |
| **Disaster monitoring** | `/monitoring`: role-scoped view of active hazards (summary, Leaflet map, list), IoT devices with latest readings and freshness, citizen photo reports with AI evidence, and your alerts. Periodically refreshed (30 s polling), not real-time |
| **Four languages** | English, Nepali, Newari (Nepal Bhasa), Maithili |
| **Light + dark themes** | Warm vintage palette, preference persisted in `localStorage` |

### Screenshots

> Drop images into `docs/screenshots/` and link them here — the landing page, dashboard, and dark-mode river status make the strongest first impression.

---

## Tech stack

- **Backend** — Flask 3.0 (application-factory pattern), SQLAlchemy, Flask-Login, Flask-WTF (CSRF), Flask-Migrate
- **Database** — SQLite by default; any SQLAlchemy URL via `DATABASE_URL`
- **Frontend** — Jinja2 templates, vanilla JavaScript, hand-written CSS design system (no framework, no build step)
- **AI** — [Ollama](https://ollama.com) running `qwen2.5:0.5b` locally
- **Icons / fonts** — Lucide, Playfair Display + Source Sans 3 + Noto Sans Devanagari

---

## Hardware

Final prototype hardware. **Not built or tested yet:** there is no firmware, wiring or GPIO
code in this repo, and the JSN-SR04T has not been validated in our setup.

```
ESP32 #1 — flood node
├── JSN-SR04T waterproof ultrasonic sensor → water level
└── DHT22 → temperature / humidity (environmental context only, not a flood detector)

ESP32 #2 — seismic node
└── MPU6050 accelerometer + gyroscope → abnormal ground-motion prototype

Existing smartphone
└── Camera + GPS → citizen landslide / road-damage reports (/report)
```

**Sensors provide evidence; X-MAN interprets it.** No device or phone declares "flood",
"earthquake" or "confirmed landslide":

```
physical sensor → ESP32 → telemetry → X-MAN ingestion → risk engine → hazard event → notifications
```

### Flood node (ESP32 #1)

- The JSN-SR04T measures the **distance from the sensor down to the water surface**. Water level
  is derived from a fixed reference height: `water_level_m = (reference_height_cm − distance_cm) / 100`,
  where the reference height is the distance from the sensor face to the zero mark of the gauge.
- For the running-water demonstration the sensor points into a **stilling/measurement chamber**
  connected to the channel. Water in the chamber follows the channel level, so turbulent,
  rippling surface flow does not become the measurement target.
- The DHT22 adds temperature and humidity for context. It never triggers a flood on its own.

### Seismic node (ESP32 #2)

- The MPU6050 is mounted on a stable platform and reports motion as `vibration` (mg) and
  `tilt` (°).
- It is a **prototype for detecting abnormal ground motion**. It is not a certified seismometer
  or earthquake early-warning instrument, and it does not predict earthquakes.

### Telemetry contract (sensor-model agnostic)

Devices send measurements to `POST /api/iot/telemetry` using logical sensor types. The backend
doesn't know or care which chip produced them, so a different sensor model needs no API change.

| Sensor type | Unit | Range | Source in this prototype |
| --- | --- | --- | --- |
| `water_level` | `m` | 0–50 | JSN-SR04T (firmware converts its cm distance into a water level in metres) |
| `temperature` | `°C` | -40–85 | DHT22 |
| `humidity` | `%` | 0–100 | DHT22 |
| `vibration` | `mg` | 0–1000 | MPU6050 |
| `tilt` | `°` | -180–180 | MPU6050 |

Readings with a different unit or out of range are rejected (for example `"unit": "cm"` for
`water_level`). Devices authenticate with their own hashed API key (`Authorization: Bearer
<device_id>:<api_key>`).

### Component list

| Component | Qty |
| --- | --- |
| ESP32 DevKit | 2 |
| JSN-SR04T waterproof ultrasonic sensor | 1 |
| MPU6050 accelerometer/gyroscope | 1 |
| DHT22 temperature/humidity sensor | 1 |
| Breadboard | 2 |
| Jumper wire set | 2 |
| USB cable | 2 |
| USB power supply / power bank | 2 |
| JSN-SR04T mounting / protection | 1 |
| MPU6050 stable mounting platform | 1 |
| Running-water channel / container | 1 |
| Stilling / measurement chamber | 1 |
| Existing smartphone | 1 |

**Not required:** HC-SR04 (replaced by the waterproof JSN-SR04T), hydrostatic pressure sensor,
HFS-DC06 microwave motion sensor, rain sensor, water pump, relay, MOSFET, Raspberry Pi, Arduino,
separate GPS module, dedicated camera, GSM module, third ESP32.

---

## Quick start

### Prerequisites

- Python 3.10+
- [Ollama](https://ollama.com) — optional; the AI degrades to a rule-based fallback without it

### 1. Install

```bash
git clone https://github.com/<your-user>/nepalsathi.git
cd nepalsathi

python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

### 2. Configure

```bash
cp .env.example .env           # copy .env.example on Windows
```

| Variable | Purpose | Default |
| --- | --- | --- |
| `SECRET_KEY` | Flask session signing — **change this** | `dev-key-change-me` |
| `DATABASE_URL` | SQLAlchemy connection string | SQLite file |
| `AI_PROVIDER` | `ollama` | `ollama` |
| `AI_MODEL` | Ollama model tag | `qwen2.5:0.5b` |
| `OLLAMA_URL` | Ollama endpoint | `http://localhost:11434` |
| `FLASK_ENV` | `development` / `production` | `development` |

### 3. Create the database

```bash
python init_db.py      # creates all tables (WARNING: drops existing ones)
python seed_data.py    # 77 districts, authorities, baseline roads/rivers/projects
```

### 4. Create a user

The database ships empty of users, and `*.db` is gitignored — so create one:

```bash
python -c "
from app import create_app
from app.extensions import db
from app.models import User, District
app = create_app()
with app.app_context():
    u = User(username='demo_citizen', email='citizen@demo.com', role='citizen',
             district_id=District.query.filter_by(name='Sindhuli').first().id)
    u.set_password('demo1234')
    db.session.add(u); db.session.commit()
    print('created demo_citizen / demo1234')
"
```

> Sindhuli is the richest demo district — it has BP Highway segments, three rivers including a `rising` Kamala, and active projects.

### 5. Set up Ollama (optional)

```bash
ollama pull qwen2.5:0.5b
ollama serve
```

Check it from the app at `/ai/health`. Without Ollama the assistant falls back to keyword-based answers, and post classification uses a keyword classifier.

### 6. Run

```bash
python run.py
```

Open <http://127.0.0.1:5000>.

---

## Loading Nepal data

Two scripts populate real geography. The import is **idempotent** — re-running updates rows in place rather than duplicating.

```bash
python import_nepal_data.py          # fast, offline: cached snapshot + seed data
python import_nepal_data.py --refresh # re-harvest from OpenStreetMap first (~30 min)
python import_nepal_data.py --seed-only
```

To refresh the OpenStreetMap cache on its own:

```bash
python harvest_osm.py                 # resumable; writes app/data/osm_snapshot.json incrementally
```

`harvest_osm.py` queries the free Overpass API one district at a time (~25 s each, so a full pass is slow). It saves after every district and skips ones it already has, so you can stop and restart it freely.

**After a full import:**

| Table | Rows |
| --- | --- |
| Districts | 77 (all with population, 74 with area) |
| Road segments | 97 across 56 districts, 34 highways |
| Rivers | 115 across 66 districts |

---

## Where the data comes from

No single source has everything, so the import layers three — and is explicit about which field came from where.

| Data | Source | Real or seeded |
| --- | --- | --- |
| District population, area | **Wikidata** (via OSM's Wikidata IDs), cached in `app/data/district_stats.json` | ✅ Real |
| Road and river **names** | **OpenStreetMap Overpass**, cached in `app/data/osm_snapshot.json` | ✅ Real |
| Highway corridors and routing | `seed_nepal_data.py` | 📋 Curated |
| Road **status** and traffic level | `seed_nepal_data.py` | 📋 Seeded — OSM has no such tags |
| River **water levels** | `seed_nepal_data.py` | 📋 Seeded — see below |

> **On river levels:** these are representative demo figures, not live gauge readings. Nepal's DHM publishes real hydrology at [dhm.gov.np](https://www.dhm.gov.np) and [hydrology.gov.np](https://hydrology.gov.np), but neither exposes a reachable JSON API (probed: 404s and connection failures), and OpenStreetMap carries no water-level tags. Rivers that OSM confirms exist but which have no gauge reading are stored with `NULL` levels and status `unknown`, and render as `—` rather than a fabricated number.

**No API keys are required.** Overpass, Nominatim, and Wikidata are all free and unauthenticated. The running web app makes **no server-side external calls** — it reads only the two cached JSON files, so the app works fully offline once data is imported.

---

## Multi-language support

Four languages, switched from the sidebar. Preference is stored in the session and persisted to the user row.

| Code | Language |
| --- | --- |
| `en` | English |
| `ne` | नेपाली (Nepali) |
| `newari` | नेवारी (Nepal Bhasa) |
| `maithili` | मैथिली (Maithili) |

Translations live in a dictionary in `app/services/translation_service.py` — no database, no `.po` files. A `t()` helper is injected into every template by a context processor, so `{{ t('road_status') }}` works anywhere.

```
GET  /language/set/<lang>      switch language
GET  /language/get/<key>       one translated string as JSON
GET  /language/languages       list supported languages
POST /language/translate       free-text translation via Ollama
```

> Navigation and shared UI strings are translated. Page body copy is still English — see [Known limitations](#known-limitations).

---

## Theming

A single design system in `app/templates/base.html` drives every page through CSS custom properties. Light and dark are the same tokens with different values, so no component defines a colour twice.

- **Light** — warm cream paper, saddle brown, brass accents
- **Dark** — deep coffee, gold and copper
- Theme is applied by a blocking `<head>` script **before first paint**, so there is no flash of the wrong theme on load
- Preference persists in `localStorage` and syncs across open tabs
- All text passes WCAG AA contrast in both modes

To retheme the whole app, edit the `:root` and `[data-theme="dark"]` blocks — nothing else needs to change.

---

## Project structure

```
app/
├── __init__.py              application factory, blueprint registration,
│                            t() context processor, metres filter
├── config.py                environment-driven config
├── extensions.py            db, login_manager, csrf, migrate
├── models/                  17 SQLAlchemy models
│   ├── user.py  district.py  road.py  river.py  project.py
│   ├── authority.py  complaint.py  post.py  comment.py  like.py
│   └── bridge.py  incident.py  notification.py  ...
├── routes/                  one blueprint per feature area
│   ├── main.py  auth.py  roads.py  rivers.py  projects.py
│   ├── complaints.py  authorities.py  authority_panel.py
│   ├── travel.py  social.py  posts.py  profile.py
│   ├── ai_routes.py  language.py  api.py
├── services/
│   ├── ai_service.py        Ollama client + rule-based fallback
│   ├── translation_service.py
│   └── nepal_geo_service.py Overpass / Nominatim client
├── templates/
│   ├── base.html            design system: tokens, components, theme toggle
│   ├── components/          navbar.html, lang_selector.html
│   ├── pages/  auth/  authority/
├── static/
└── data/                    cached real-world data (committed)
    ├── district_stats.json  population + area from Wikidata
    └── osm_snapshot.json    road + river names from OpenStreetMap

seed_nepal_data.py           highway corridors, river systems, gauge figures
import_nepal_data.py         layered, idempotent importer
harvest_osm.py               resumable OpenStreetMap harvester
init_db.py  seed_data.py     schema + baseline seed
```

---

## Route reference

<details>
<summary><b>Expand full route list</b></summary>

**Public / auth**
```
GET      /                                    landing
GET|POST /auth/login  /auth/register
GET|POST /auth/authority/login  /auth/authority/register
GET      /auth/logout
```

**Core**
```
GET      /dashboard
GET      /districts        /district/<id>
POST     /select-district
GET      /roads/status     /roads/<id>
GET      /rivers/status
POST     /rivers/<id>/update
GET      /projects/tracker /projects/<id>
POST     /projects/<id>/update
GET      /authorities/directory
```

**Complaints & travel**
```
GET      /complaints/      /complaints/<id>
GET|POST /complaints/new
GET|POST /travel/planner
```

**Community**
```
GET      /social/feed                     ?district_id=all to see every district
GET      /social/post/<id>  /social/hashtag/<tag>
POST     /social/post/<id>/like  /social/post/<id>/comment
GET|POST /posts/create
GET      /profile/me  /profile/<id>
GET|POST /profile/edit  /profile/change-password
```

**AI & language**
```
GET      /ai/assistant  /ai/health
POST     /ai/generate  /ai/classify
GET      /ai/district-summary/<id>
GET      /language/set/<lang>  /language/get/<key>  /language/languages
POST     /language/translate
```

**Disaster monitoring** (hazard, IoT, report and notification APIs: see `docs/PROJECT_PROGRESS.md`)
```
GET      /monitoring                          dashboard page (any logged-in user, content by role)
GET      /api/dashboard?district_id=<id>      JSON for the page; district_id is admin-only
```

**Authority panel** (separate login)
```
GET      /authority/dashboard  /authority/complaints  /authority/roads
GET      /authority/rivers  /authority/projects
POST     /authority/roads/<id>/update  /authority/rivers/<id>/update
POST     /authority/projects/<id>/update
```

</details>

---

## Testing

Five suites, each runnable on its own. They need a database with a `demo_citizen` user (see [step 4](#4-create-a-user)).

```bash
python test_nepal_data.py   # data integrity: counts, status/level consistency, no duplicates
python test_features.py     # regression tests for previously-fixed bugs
python test_ui.py           # every page renders, styled, zero emoji
python test_theme.py        # no blue/purple survives, both themes defined, toggle everywhere
python test_language.py     # all four languages switch and persist
```

What they actually guard against, all of which were real bugs:

- Dashboard claiming *"Your District: X"* while listing another district's roads
- Travel planner summing every road in Nepal (115 h for a 6 h trip, risk score of 350)
- A `rising` river producing no flood warning
- `NULL` water levels rendering as `Nonem`
- Community feed showing *"No posts found"* beside trending topics claiming posts exist
- Emoji or hardcoded hex colours creeping back into templates

---

## Known limitations

Stated plainly, because a demo that overstates itself is worse than one that doesn't.

- **River levels are not live.** See [Where the data comes from](#where-the-data-comes-from).
- **The AI does not read the database.** `AIService.generate()` uses a hardcoded context string, so the assistant can contradict the app's own data — it may report no flood warning for a river the dashboard shows as `rising`.
- **`qwen2.5:0.5b` is small.** Good enough for short factual answers; its free-text translation into Nepali is poor and into Newari/Maithili barely works. Set `AI_MODEL` to something larger if that matters.
- **Authorities only exist for Sindhuli and Kathmandu** (7 rows), so the complaint form can offer an authority from the wrong district.
- **Only navigation is translated.** Page body copy is still English in all four languages.
- **Newari and Maithili strings need a native speaker's review** — they are reasonable approximations, not verified translations.
- **Travel routing is name and district matching**, not a real path search over the road network.
- **Lucide and Google Fonts load from CDN**, so the UI needs network access for icons and fonts. Vendor them locally before an offline demo.
- **`geo_routes.py` is dead code** — it defines `/geo/*` endpoints but the blueprint is never registered.

---

## Roadmap

- [ ] Parse DHM's published hydrology tables for real gauge readings
- [ ] Feed live road/river rows into the AI prompt so answers match the database
- [ ] Seed authorities for all 77 districts
- [ ] Translate page body copy, not just navigation
- [ ] Native-speaker review of Newari and Maithili
- [ ] Real routing over the road graph
- [ ] Vendor Lucide and fonts for offline use
- [ ] Map view of district boundaries (OSM geometry is already fetchable)

---

## Contributing

Issues and pull requests welcome. Please run the five test suites before opening a PR.

## Acknowledgements

- [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors — road and river data, ODbL
- [Wikidata](https://www.wikidata.org) — district population and area, CC0
- [Ollama](https://ollama.com) and the Qwen team — local inference
- [Lucide](https://lucide.dev) — icons

## License

No license file is present yet. Add one before publishing — without it, default copyright applies and others cannot legally reuse the code. [MIT](https://choosealicense.com/licenses/mit/) is a common choice for hackathon projects.
