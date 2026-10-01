# -*- coding: utf-8 -*-
"""Render-check every page with the X-MAN design system (xman.css). Run: python test_ui.py"""
from app import create_app
from app.models.user import User

CITIZEN = [
    '/', '/dashboard', '/districts', '/roads/status', '/rivers/status',
    '/projects/tracker', '/authorities/directory', '/complaints/new',
    '/complaints/', '/travel/planner', '/ai/assistant', '/social/feed',
    '/posts/create', '/profile/me', '/profile/edit', '/ai/test-classify',
]
PUBLIC = ['/', '/auth/login', '/auth/register', '/auth/authority/login']


def main():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        uid = User.query.filter_by(username='demo_citizen').first().id
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True

    failures = []
    for path in CITIZEN:
        r = client.get(path, follow_redirects=True)
        body = r.get_data(as_text=True)
        if r.status_code >= 400:
            failures.append((path, 'HTTP %s' % r.status_code))
            continue
        # design system actually applied
        if 'css/xman.css' not in body:
            failures.append((path, 'design system stylesheet missing'))
        if 'lucide' not in body:
            failures.append((path, 'lucide not loaded'))
        if 'class="sidebar"' not in body:
            failures.append((path, 'sidebar missing'))

    # public pages: no sidebar, but styled
    anon = app.test_client()
    for path in PUBLIC:
        r = anon.get(path, follow_redirects=True)
        body = r.get_data(as_text=True)
        if r.status_code >= 400:
            failures.append((path, 'HTTP %s' % r.status_code))
            continue
        if 'css/xman.css' not in body:
            failures.append((path, 'design system stylesheet missing'))

    # Inter + Space Grotesk + Devanagari wired up
    home = anon.get('/').get_data(as_text=True)
    assert 'Noto+Sans+Devanagari' in home, 'Devanagari font not loaded'
    assert 'family=Inter' in home, 'body font not loaded'
    assert 'Space+Grotesk' in home, 'display font not loaded'

    if failures:
        print('FAILURES (%d):' % len(failures))
        for p, why in failures:
            print('   %-28s %s' % (p, why))
        raise SystemExit(1)
    print('all %d pages render with the X-MAN design system' % (len(CITIZEN) + len(PUBLIC)))


if __name__ == '__main__':
    main()
