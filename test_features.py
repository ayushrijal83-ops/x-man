# -*- coding: utf-8 -*-
"""Regression tests for bugs found during the live feature sweep.

Each of these was invisible while the database held only 3 roads and 3 rivers,
and became wrong once the full Nepal dataset was imported.
Run: python test_features.py
"""
import re
from app import create_app
from app.extensions import db
from app.models import District, RoadSegment, River, User, Post


def csrf(client, path):
    html = client.get(path).get_data(as_text=True)
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else None


def main():
    app = create_app()
    fails = []

    with app.app_context():
        user = User.query.filter_by(username='demo_citizen').first()
        uid, home_id = user.id, user.district_id
        home = District.query.get(home_id) if home_id else None

    client = app.test_client()
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True

    # 1. dashboard must not claim "Your District: X" while listing other districts
    body = client.get('/dashboard').get_data(as_text=True)
    if home:
        with app.app_context():
            local_rivers = River.query.filter_by(district_id=home_id).all()
        if local_rivers:
            shown = re.findall(r'<strong>([A-Za-z ]+River)</strong>', body)
            with app.app_context():
                names = {r.name for r in local_rivers}
            for nm in shown:
                if nm not in names:
                    fails.append('dashboard shows %r which is not in %s' % (nm, home.name))
        # the scope label must be present so a nationwide fallback is not
        # mistaken for local data
        if 'Nationwide' not in body and home.name not in body:
            fails.append('dashboard has no scope label on its cards')

    # 2. no "Nonem" -- rivers without a gauge reading render as a dash
    for path in ('/dashboard', '/rivers/status'):
        if 'Nonem' in client.get(path).get_data(as_text=True):
            fails.append('%s renders "Nonem" for a null water level' % path)

    # 3. travel planner must scope to the route, cap risk, and not double-count
    tok = csrf(client, '/travel/planner')
    res = client.post('/travel/planner', data={
        'csrf_token': tok, 'from_location': 'Sindhuli',
        'to_location': 'Kathmandu', 'travel_time': 'flexible'})
    html = res.get_data(as_text=True)
    stats = re.findall(r'stat-value">([^<]+)</div>\s*<div class="stat-label">([^<]+)<', html)
    stats = {label.strip().lower(): val.strip() for val, label in stats}

    risk = int(stats.get('risk score', '0'))
    if not 0 <= risk <= 100:
        fails.append('risk score %d outside 0-100' % risk)

    hours = float(stats.get('est. travel time', '0h').rstrip('h'))
    if hours > 24:
        fails.append('estimated travel time %.1fh is not a real journey '
                     '(summing every road in Nepal?)' % hours)

    warnings = re.findall(r'(Road [A-Z ]+: [^<]+)<', html)
    if len(warnings) != len(set(warnings)):
        fails.append('travel planner lists duplicate warnings: %s' % warnings)

    # a rising river on the route must actually raise a warning
    if 'Kamala' not in html:
        fails.append('rising Kamala River produced no travel warning '
                     '(is "rising" missing from the risky-status list?)')

    # 4. feed and trending must agree -- "No posts found" beside "3 trending"
    body = client.get('/social/feed').get_data(as_text=True)
    trending_counts = [int(n) for n in re.findall(r'#\w+ \((\d+)\)', body)]
    has_posts = 'No posts' not in body
    if not has_posts and trending_counts:
        fails.append('feed shows no posts but trending claims %s' % trending_counts)

    # the all-districts escape hatch works
    all_body = client.get('/social/feed?district_id=all').get_data(as_text=True)
    with app.app_context():
        total_posts = Post.query.count()
    if total_posts and 'No posts' in all_body:
        fails.append('district_id=all still shows an empty feed (%d posts exist)' % total_posts)

    # 5. every page still renders
    for path in ('/dashboard', '/roads/status', '/rivers/status', '/districts',
                 '/projects/tracker', '/authorities/directory', '/complaints/new',
                 '/travel/planner', '/ai/assistant', '/social/feed', '/posts/create',
                 '/profile/me'):
        r = client.get(path, follow_redirects=True)
        if r.status_code >= 400:
            fails.append('%s -> HTTP %d' % (path, r.status_code))

    if fails:
        print('FAILURES (%d):' % len(fails))
        for f in fails:
            print('   %s' % f)
        raise SystemExit(1)
    print('feature checks OK: dashboard scoping, null levels, travel routing, feed/trending agree')


if __name__ == '__main__':
    main()
