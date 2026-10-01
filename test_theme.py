# -*- coding: utf-8 -*-
"""X-MAN design-system theme checks (light + dark). Run: python test_theme.py"""
import io
import re

from app import create_app
from app.models.user import User

PAGES = ['/dashboard', '/districts', '/roads/status', '/rivers/status',
         '/projects/tracker', '/social/feed', '/ai/assistant', '/profile/me',
         '/complaints/new', '/travel/planner', '/authorities/directory', '/notifications/settings']
PUBLIC = ['/', '/auth/login', '/auth/register', '/auth/authority/login']
TOKENS = ['--bg-page', '--bg-surface', '--text-primary', '--brand-primary', '--sev-critical', '--sev-high',
          '--sev-medium', '--sev-low', '--focus-ring']


def main():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        uid = User.query.filter_by(username='demo_citizen').first().id
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True

    fails = []
    css = io.open('app/static/css/xman.css', encoding='utf-8').read()
    base = io.open('app/templates/base.html', encoding='utf-8').read()

    # 1. both themes define every core token
    dark = css.split('[data-theme="dark"]', 1)[1] if '[data-theme="dark"]' in css else ''
    for token in TOKENS:
        if token + ':' not in css.split('[data-theme="dark"]')[0]:
            fails.append(('xman.css', 'light theme missing %s' % token))
        if token + ':' not in dark:
            fails.append(('xman.css', 'dark theme missing %s' % token))
    if 'prefers-reduced-motion' not in css:
        fails.append(('xman.css', 'no reduced-motion handling'))

    # 2. no invalid colour literals (typo guard)
    for m in re.findall(r'#[0-9a-zA-Z]{3,8}\b', css):
        if not re.fullmatch(r'#[0-9a-fA-F]{3,8}', m):
            fails.append(('xman.css', 'invalid colour literal %s' % m))

    # 3. anti-FOUC: theme applied in <head>, before <body>
    if "localStorage.getItem('theme')" not in base.split('<body')[0]:
        fails.append(('base.html', 'theme not restored before first paint (FOUC)'))

    # 4. every rendered page carries the stylesheet and a theme toggle
    for path in PAGES:
        body = client.get(path, follow_redirects=True).get_data(as_text=True)
        if 'theme-toggle' not in body:
            fails.append((path, 'no theme toggle'))
        if 'css/xman.css' not in body:
            fails.append((path, 'design system stylesheet missing'))
    anon = app.test_client()
    for path in PUBLIC:
        body = anon.get(path, follow_redirects=True).get_data(as_text=True)
        if 'css/xman.css' not in body:
            fails.append((path, 'design system stylesheet missing'))

    if fails:
        print('FAILURES (%d):' % len(fails))
        for where, why in fails:
            print('   %-34s %s' % (where, why))
        raise SystemExit(1)
    print('X-MAN theme clean: both modes define every token, toggle on all %d signed-in pages' % len(PAGES))


if __name__ == '__main__':
    main()
