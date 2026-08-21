# -*- coding: utf-8 -*-
"""Harvest real road + river names per district from OpenStreetMap (Overpass).

Writes app/data/osm_snapshot.json so the import does not need a 30-minute
network run every time. Re-run with: python harvest_osm.py
"""
import json, os, sys, time
import requests

OVERPASS = 'https://overpass-api.de/api/interpreter'
# Overpass returns 406 without a real User-Agent.
HEADERS = {'User-Agent': 'NepalSathi/1.0 (district intelligence; contact: ayushruchal83@gmail.com)'}
OUT = os.path.join('app', 'data', 'osm_snapshot.json')

QUERY = """
[out:json][timeout:120];
area["name:en"="%(d)s"]["admin_level"="6"]["boundary"="administrative"]->.a;
(
  way(area.a)[highway~"^(motorway|trunk|primary|secondary)$"][name];
  way(area.a)[highway~"^(motorway|trunk|primary)$"][ref];
);
out tags;
way(area.a)[waterway="river"][name];
out tags;
"""


def fetch(district, attempt=1):
    try:
        r = requests.post(OVERPASS, data={'data': QUERY % {'d': district}},
                          headers=HEADERS, timeout=180)
        if r.status_code == 429 or r.status_code == 504:
            if attempt <= 3:
                time.sleep(20 * attempt)
                return fetch(district, attempt + 1)
            return None
        if r.status_code != 200:
            return None
        return r.json().get('elements', [])
    except Exception:
        if attempt <= 2:
            time.sleep(10)
            return fetch(district, attempt + 1)
        return None


def main():
    from app import create_app
    from app.models import District

    app = create_app()
    with app.app_context():
        names = [d.name for d in District.query.order_by(District.name).all()]

    snap = {}
    if os.path.exists(OUT):
        with open(OUT, encoding='utf-8') as f:
            snap = json.load(f)

    todo = [n for n in names if n not in snap]
    print('%d districts total, %d already harvested, %d to go'
          % (len(names), len(snap), len(todo)))

    for i, name in enumerate(todo, 1):
        t = time.time()
        els = fetch(name)
        if els is None:
            print('  [%2d/%d] %-20s FAILED' % (i, len(todo), name))
            continue

        roads, rivers = {}, set()
        for e in els:
            tg = e.get('tags', {})
            if tg.get('waterway') == 'river' and tg.get('name'):
                rivers.add(tg['name'])
            elif tg.get('highway'):
                key = tg.get('name') or tg.get('ref')
                if key:
                    roads[key] = tg.get('ref') or ''
        snap[name] = {'roads': roads, 'rivers': sorted(rivers)}

        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=1, sort_keys=True)

        print('  [%2d/%d] %-20s %2d roads %2d rivers (%.0fs)'
              % (i, len(todo), name, len(roads), len(rivers), time.time() - t))
        time.sleep(2)  # be polite to a free public API

    print('done -> %s (%d districts)' % (OUT, len(snap)))


if __name__ == '__main__':
    sys.exit(main())
