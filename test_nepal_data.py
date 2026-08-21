# -*- coding: utf-8 -*-
"""Checks for the imported Nepal dataset. Run: python test_nepal_data.py"""
from app import create_app
from app.extensions import db
from app.models import District, RoadSegment, River, User
from seed_nepal_data import HIGHWAYS, level_status


def main():
    app = create_app()
    client = app.test_client()
    fails = []

    with app.app_context():
        # districts
        assert District.query.count() == 77, 'expected 77 districts'
        no_pop = [d.name for d in District.query.filter(District.population.is_(None))]
        if no_pop:
            fails.append('districts without population: %s' % no_pop[:5])
        no_area = District.query.filter(District.area_sq_km.is_(None)).count()
        if no_area > 3:
            fails.append('%d districts without area (expected <=3)' % no_area)

        ktm = District.query.filter_by(name='Kathmandu').first()
        if not (1_500_000 < (ktm.population or 0) < 2_200_000):
            fails.append('Kathmandu population looks wrong: %s' % ktm.population)

        # every seeded highway present
        highways = {h for (h,) in db.session.query(RoadSegment.highway).distinct() if h}
        for name in HIGHWAYS:
            if name not in highways:
                fails.append('highway missing: %s' % name)

        # road rows are well formed
        for r in RoadSegment.query.all():
            if r.status not in ('open', 'partial', 'restricted', 'blocked', 'unknown'):
                fails.append('bad road status %r on %s' % (r.status, r.name))
            if r.traffic_level not in ('low', 'moderate', 'heavy', 'severe'):
                fails.append('bad traffic %r on %s' % (r.traffic_level, r.name))
            if r.district_id is None:
                fails.append('road with no district: %s' % r.name)

        # river rows are well formed and status matches the level
        for rv in River.query.all():
            if rv.status not in ('normal', 'rising', 'flooding', 'unknown'):
                fails.append('bad river status %r on %s' % (rv.status, rv.name))
            if rv.current_level is not None and rv.danger_level is not None:
                expect = level_status(rv.current_level, rv.danger_level)
                if rv.status != expect:
                    fails.append('%s: status %s but level %.1f/%.1f implies %s'
                                 % (rv.name, rv.status, rv.current_level,
                                    rv.danger_level, expect))
                if rv.current_level > rv.danger_level * 2:
                    fails.append('%s: implausible level %.1f' % (rv.name, rv.current_level))
            # no "River River" style names from OSM suffix handling
            if rv.name.lower().count('river') > 1 or ' Nadi River' in rv.name:
                fails.append('malformed river name: %s' % rv.name)
            if any('ऀ' <= ch <= 'ॿ' for ch in rv.name):
                fails.append('Devanagari duplicate river row: %s' % rv.name)

        # no duplicate (name, district) pairs -- proves the import is idempotent
        for Model in (RoadSegment, River):
            seen = set()
            for row in Model.query.all():
                key = (row.name, row.district_id)
                if key in seen:
                    fails.append('duplicate %s row: %s' % (Model.__name__, key))
                seen.add(key)

        # the demo districts must be complete
        for dname, min_roads, min_rivers in [('Sindhuli', 2, 3), ('Kathmandu', 1, 3)]:
            d = District.query.filter_by(name=dname).first()
            nr = RoadSegment.query.filter_by(district_id=d.id).count()
            nv = River.query.filter_by(district_id=d.id).count()
            if nr < min_roads:
                fails.append('%s has only %d roads' % (dname, nr))
            if nv < min_rivers:
                fails.append('%s has only %d rivers' % (dname, nv))

        # Sindhuli's Kamala must be the rising demo case
        kam = River.query.filter_by(name='Kamala River',
                                    district_id=District.query.filter_by(
                                        name='Sindhuli').first().id).first()
        if not kam or kam.status != 'rising':
            fails.append('Sindhuli Kamala River not in rising state')

        uid = User.query.filter_by(username='demo_citizen').first().id

    # pages still render with the fuller dataset
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True
    for path in ('/roads/status', '/rivers/status', '/districts', '/dashboard'):
        r = client.get(path, follow_redirects=True)
        if r.status_code >= 400:
            fails.append('%s -> HTTP %d' % (path, r.status_code))

    with app.app_context():
        counts = (District.query.count(), RoadSegment.query.count(), River.query.count())

    if fails:
        print('FAILURES (%d):' % len(fails))
        for f in fails:
            print('   %s' % f)
        raise SystemExit(1)
    print('nepal data OK: %d districts, %d road segments, %d rivers' % counts)


if __name__ == '__main__':
    main()
