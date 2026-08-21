# -*- coding: utf-8 -*-
"""Import Nepal road, river and district data.

Layered on purpose, because no single source has everything:

  district population/area  -> Wikidata      (real, cached in app/data/)
  road + river NAMES        -> OpenStreetMap (real, cached in app/data/)
  road status / traffic     -> seed_nepal_data (OSM has no such tags)
  river water levels        -> seed_nepal_data (no reachable gauge API)

Idempotent: re-running updates rows in place instead of duplicating.

    python import_nepal_data.py            # snapshot + seed (fast, offline)
    python import_nepal_data.py --refresh  # re-harvest from OSM first (slow)
    python import_nepal_data.py --seed-only
"""
import json, os, sys

from app import create_app
from app.extensions import db
from app.models import District, RoadSegment, River
from seed_nepal_data import (iter_road_segments, iter_rivers, level_status,
                             RIVER_SYSTEMS, HIGHWAYS)

STATS_FILE = os.path.join('app', 'data', 'district_stats.json')
OSM_FILE = os.path.join('app', 'data', 'osm_snapshot.json')

# Wikidata labels these differently from the district table.
DISTRICT_ALIASES = {
    'Darchula District (Nepal)': 'Darchula',
    'Ilam District': 'Ilam',
    'Kanchanpur District': 'Kanchanpur',
    'Nawalpur District': 'Nawalpur',
    'Nawalparasi W': 'Parasi',
    'Sindhupalchowk': 'Sindhupalchok',
    'Tehrathum': 'Terhathum',
    'Western Rukum District': 'Western Rukum',
}

# OSM spelling variants that would otherwise duplicate a seeded highway.
HIGHWAY_ALIASES = {
    'Tribhuban Highway': 'Tribhuvan Highway',
    'NH41: Tribhuvan Highway': 'Tribhuvan Highway',
    'Mahendra Rajmarg': 'Mahendra Highway',
    'Prithivi Highway': 'Prithvi Highway',
    'Araniko Rajmarg': 'Araniko Highway',
    'Arniko Highway': 'Araniko Highway',
    'Sidhartha Highway': 'Siddhartha Highway',
    'Mid Hill Highway': 'Mid-Hill Highway',
    'Mid Hilly Highway': 'Mid-Hill Highway',
    'Pushpalal Highway': 'Mid-Hill Highway',        # Pushpalal is its official name
    'Bardibas Jaleshwor Highway': 'Bardibas Jaleshwar Highway',
    'Bhimdatta Panta Highway': 'Bhim Datta Panta Highway',
    'Pokhara Baglung Highway': 'Pokhara - Baglung Highway',
    'Khaireni-Gorkha Highway': 'Abukhaireni-Gorkha Highway',
    'Pasang Lhamu Highway-Tadi bridge': 'Pasang Lhamu Highway',
}


def clean_highway(name):
    """Normalise an OSM highway name.

    OSM packs multiple values into one tag with semicolons, and spells the
    same road several ways across districts.
    """
    name = (name or '').split(';')[0].strip()
    return HIGHWAY_ALIASES.get(name, name)

# "Nadi"/"Khola"/"Gad" already mean river/stream in Nepali, so OSM names like
# "Lohare Nadi" must not become "Lohare Nadi River".
_SUFFIXES = (' nadi', ' khola', ' gad', ' gadh', ' river', ' nala', ' kosi')


def normalise_river(raw):
    """Reduce an OSM waterway name to a comparable base name, or None."""
    name = raw.split('(')[0].strip()
    if not name or any('ऀ' <= ch <= 'ॿ' for ch in name):
        return None                      # Devanagari duplicates the English row
    low = name.lower()
    for suf in _SUFFIXES:
        if low.endswith(suf):
            name = name[:-len(suf)].strip()
            low = name.lower()
    if len(name) < 3 or not name[0].isalpha():
        return None
    return name.title()


def load_json(path):
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return {}


def import_district_stats(dmap):
    """Population and area from Wikidata."""
    stats = load_json(STATS_FILE)
    if not stats:
        print('  ! no district_stats.json -- skipping population/area')
        return 0, 0
    # fold the differently-labelled Wikidata keys onto district names
    for wd_name, db_name in DISTRICT_ALIASES.items():
        if wd_name in stats:
            stats.setdefault(db_name, stats[wd_name])

    updated = 0
    for name, d in dmap.items():
        s = stats.get(name)
        if not s:
            continue
        changed = False
        if s.get('population') and d.population != s['population']:
            d.population = s['population']
            changed = True
        if s.get('area_sq_km') and d.area_sq_km != s['area_sq_km']:
            d.area_sq_km = s['area_sq_km']
            changed = True
        if changed:
            updated += 1
    db.session.commit()
    covered = sum(1 for d in dmap.values() if d.population)
    return updated, covered


def import_roads(dmap, osm):
    """Seed segments carry the route and status; OSM adds real extra roads."""
    added = updated = skipped = 0
    for name, highway, district, frm, to, km, status, traffic in iter_road_segments():
        d = dmap.get(district)
        if not d:
            print('  ! unknown district for road: %s' % district)
            skipped += 1
            continue
        row = RoadSegment.query.filter_by(name=name, district_id=d.id).first()
        if row is None:
            row = RoadSegment(name=name, district_id=d.id)
            db.session.add(row)
            added += 1
        else:
            updated += 1
        row.highway = highway
        row.from_location = frm
        row.to_location = to
        row.distance_km = km
        row.status = status
        row.traffic_level = traffic
    db.session.commit()

    # real named highways OSM found that the seed corridors do not cover
    seeded = {r.name for r in RoadSegment.query.all()}
    extra = 0
    for district, payload in osm.items():
        d = dmap.get(district)
        if not d:
            continue
        for road_name, ref in (payload.get('roads') or {}).items():
            if not road_name or 'Highway' not in road_name:
                continue
            road_name = clean_highway(road_name)
            if road_name in HIGHWAYS:
                continue          # already covered by a seeded corridor
            label = '%s (%s)' % (road_name, district)
            if label in seeded:
                continue
            if RoadSegment.query.filter_by(name=label, district_id=d.id).first():
                continue
            db.session.add(RoadSegment(
                name=label, highway=road_name, district_id=d.id,
                from_location=district, to_location=district,
                distance_km=None, status='unknown', traffic_level='low'))
            seeded.add(label)
            extra += 1
    db.session.commit()
    return added, updated, extra, skipped


def import_rivers(dmap, osm):
    added = updated = skipped = 0
    for river, basin, district, cur, dang, status in iter_rivers():
        d = dmap.get(district)
        if not d:
            print('  ! unknown district for river: %s' % district)
            skipped += 1
            continue
        name = '%s River' % river
        row = River.query.filter_by(name=name, district_id=d.id).first()
        if row is None:
            row = River(name=name, district_id=d.id)
            db.session.add(row)
            added += 1
        else:
            updated += 1
        row.current_level = cur
        row.danger_level = dang
        row.status = status
    db.session.commit()

    # Use OSM to confirm a KNOWN major river also runs through a district the
    # seed list missed. Importing every OSM waterway instead would bury the
    # river page under hundreds of minor streams and Devanagari duplicates.
    major = {}
    for basin, rivers in RIVER_SYSTEMS.items():
        for river in rivers:
            major[normalise_river(river) or river.title()] = river

    known = {(r.name.lower(), r.district_id) for r in River.query.all()}
    extra = 0
    for district, payload in osm.items():
        d = dmap.get(district)
        if not d:
            continue
        for raw in (payload.get('rivers') or []):
            base = normalise_river(raw)
            if not base or base not in major:
                continue
            name = '%s River' % major[base]
            if (name.lower(), d.id) in known:
                continue
            # OSM confirms the river is here but carries no water-level tags,
            # so record its presence rather than invent a reading.
            db.session.add(River(name=name, district_id=d.id,
                                 current_level=None, danger_level=None,
                                 status='unknown'))
            known.add((name.lower(), d.id))
            extra += 1
    db.session.commit()
    return added, updated, extra, skipped


def main():
    args = sys.argv[1:]
    if '--refresh' in args:
        print('Refreshing OSM snapshot (this takes ~30 min)...')
        os.system('%s harvest_osm.py' % sys.executable)

    app = create_app()
    with app.app_context():
        dmap = {d.name: d for d in District.query.all()}
        print('Districts in database: %d' % len(dmap))

        osm = {} if '--seed-only' in args else load_json(OSM_FILE)
        if osm:
            print('OSM snapshot: %d districts harvested' % len(osm))
        else:
            print('OSM snapshot: none -- using seed data only')

        print('\n[1/3] District population and area (Wikidata)')
        up, covered = import_district_stats(dmap)
        print('      updated %d, now %d/%d districts have population' % (up, covered, len(dmap)))

        print('\n[2/3] Road segments')
        a, u, e, s = import_roads(dmap, osm)
        print('      %d added, %d updated, %d extra from OSM, %d skipped' % (a, u, e, s))

        print('\n[3/3] Rivers')
        a, u, e, s = import_rivers(dmap, osm)
        print('      %d added, %d updated, %d extra from OSM, %d skipped' % (a, u, e, s))

        print('\n--- totals ---')
        print('  districts      %d' % District.query.count())
        print('  road segments  %d across %d districts'
              % (RoadSegment.query.count(),
                 db.session.query(RoadSegment.district_id).distinct().count()))
        print('  rivers         %d across %d districts'
              % (River.query.count(),
                 db.session.query(River.district_id).distinct().count()))
        print('  highways       %d'
              % db.session.query(RoadSegment.highway).distinct().count())


if __name__ == '__main__':
    main()
