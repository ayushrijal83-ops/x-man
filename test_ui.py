# -*- coding: utf-8 -*-
"""Render-check every page after the UI redesign. Run: python test_ui.py"""
import glob, io, os, re
from app import create_app
from app.models.user import User

CITIZEN = [
    '/', '/dashboard', '/districts', '/roads/status', '/rivers/status',
    '/projects/tracker', '/authorities/directory', '/complaints/new',
    '/complaints/', '/travel/planner', '/ai/assistant', '/social/feed',
    '/posts/create', '/profile/me', '/profile/edit', '/ai/test-classify',
]
PUBLIC = ['/', '/auth/login', '/auth/register', '/auth/authority/login']

EMOJI = re.compile(
    '[\U0001F000-\U0001FAFF←-⇿⌀-⏿①-⓿'
    '■-➿⬀-⯿⤴⤵]'
)


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
        if '--brand-600' not in body:
            failures.append((path, 'design tokens missing'))
        if 'lucide' not in body:
            failures.append((path, 'lucide not loaded'))
        if 'class="sidebar"' not in body:
            failures.append((path, 'sidebar missing'))
        found = EMOJI.findall(body)
        if found:
            failures.append((path, 'emoji rendered: %r' % found[:5]))

    # public pages: no sidebar, but styled and emoji-free
    anon = app.test_client()
    for path in PUBLIC:
        r = anon.get(path, follow_redirects=True)
        body = r.get_data(as_text=True)
        if r.status_code >= 400:
            failures.append((path, 'HTTP %s' % r.status_code))
            continue
        if '--brand-600' not in body:
            failures.append((path, 'design tokens missing'))
        found = EMOJI.findall(body)
        if found:
            failures.append((path, 'emoji rendered: %r' % found[:5]))

    # no emoji left in any template source
    for f in glob.glob('app/templates/**/*.html', recursive=True):
        hits = EMOJI.findall(io.open(f, encoding='utf-8').read())
        if hits:
            failures.append((f.replace(os.sep, '/'), 'emoji in source: %r' % hits[:5]))

    # Inter + Devanagari wired up
    home = anon.get('/').get_data(as_text=True)
    assert 'Noto+Sans+Devanagari' in home, 'Devanagari font not loaded'
    assert 'Source+Sans+3' in home, 'body font not loaded'
    assert 'Playfair+Display' in home, 'serif heading font not loaded'

    if failures:
        print('FAILURES (%d):' % len(failures))
        for p, why in failures:
            print('   %-28s %s' % (p, why))
        raise SystemExit(1)
    print('all %d pages render, styled, zero emoji' % (len(CITIZEN) + len(PUBLIC)))


if __name__ == '__main__':
    main()
