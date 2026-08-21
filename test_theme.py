# -*- coding: utf-8 -*-
"""Vintage theme + dark mode checks. Run: python test_theme.py"""
import glob, io, os, re
from app import create_app
from app.models.user import User

# colours the vintage theme must never reintroduce
BANNED = [
    '#3b82f6', '#6366f1', '#8b5cf6', '#7c3aed', '#6d28d9',  # blue / indigo / purple
    '#1e3c72', '#2a5298',                                    # old brand blue
    '#dbeafe', '#e0e7ff', '#1e40af', '#3730a3',              # blue tints
    '#f5f3ff', '#ede9fe',                                    # purple tints
]

PAGES = ['/dashboard', '/districts', '/roads/status', '/rivers/status',
         '/projects/tracker', '/social/feed', '/ai/assistant', '/profile/me',
         '/complaints/new', '/travel/planner', '/authorities/directory']
PUBLIC = ['/', '/auth/login', '/auth/register', '/auth/authority/login']


def main():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        uid = User.query.filter_by(username='demo_citizen').first().id
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True

    fails = []

    # 1. no banned colour survives anywhere in template source
    for f in glob.glob('app/templates/**/*.html', recursive=True):
        src = io.open(f, encoding='utf-8').read().lower()
        for c in BANNED:
            if c in src:
                fails.append((f.replace(os.sep, '/'), 'banned colour %s' % c))

    # 2. vintage tokens present, both themes defined
    base = io.open('app/templates/base.html', encoding='utf-8').read()
    for token in ['#FAF6F0', '#8B4513', '#C41E3A', '#D4A574', '#2C1810', '#1A1210']:
        if token not in base:
            fails.append(('base.html', 'missing vintage token %s' % token))
    if '[data-theme="dark"]' not in base:
        fails.append(('base.html', 'no dark theme block'))
    if "Playfair+Display" not in base:
        fails.append(('base.html', 'serif display font not loaded'))
    if 'Noto+Sans+Devanagari' not in base:
        fails.append(('base.html', 'Devanagari font not loaded'))

    # 3. anti-FOUC: theme applied in <head>, before <body>
    head = base.split('<body')[0]
    if "localStorage.getItem('theme')" not in head:
        fails.append(('base.html', 'theme not restored before first paint (FOUC)'))

    # 4. every rendered page carries a toggle and the dark palette
    for path in PAGES:
        body = client.get(path, follow_redirects=True).get_data(as_text=True)
        if 'theme-toggle' not in body:
            fails.append((path, 'no theme toggle'))
        if '[data-theme="dark"]' not in body:
            fails.append((path, 'dark palette not shipped'))
        low = body.lower()
        for c in BANNED:
            if c in low:
                fails.append((path, 'banned colour rendered: %s' % c))

    anon = app.test_client()
    for path in PUBLIC:
        body = anon.get(path, follow_redirects=True).get_data(as_text=True)
        if 'theme-toggle' not in body:
            fails.append((path, 'no theme toggle'))
        low = body.lower()
        for c in BANNED:
            if c in low:
                fails.append((path, 'banned colour rendered: %s' % c))

    # 5. no hardcoded hex left outside base.html (would ignore the theme)
    for f in glob.glob('app/templates/**/*.html', recursive=True):
        if f.endswith('base.html'):
            continue
        hits = re.findall(r'#[0-9a-fA-F]{3,8}\b', io.open(f, encoding='utf-8').read())
        if hits:
            fails.append((f.replace(os.sep, '/'), 'hardcoded colours: %s' % hits[:4]))

    # 6. no invalid css colour literals (typo guard) -- style block only,
    #    since the JS below it contains selector strings like '#theme-icon'
    style_block = base.split('<style>')[1].split('</style>')[0]
    for m in re.findall(r'#[0-9a-zA-Z]{3,8}\b', style_block):
        if not re.fullmatch(r'#[0-9a-fA-F]{3,8}', m):
            fails.append(('base.html', 'invalid colour literal %s' % m))

    if fails:
        print('FAILURES (%d):' % len(fails))
        for where, why in fails:
            print('   %-34s %s' % (where, why))
        raise SystemExit(1)
    print('vintage theme clean: no blue/purple, both modes defined, toggle on all %d pages'
          % (len(PAGES) + len(PUBLIC)))


if __name__ == '__main__':
    main()
