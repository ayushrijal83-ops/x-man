# -*- coding: utf-8 -*-
"""Self-check for multi-language support. Run: python test_language.py"""
import re
from app import create_app
from app.models.user import User


def main():
    app = create_app()
    client = app.test_client()
    with app.app_context():
        user = User.query.filter_by(username='demo_citizen').first()
        uid = user.id
        # pin a known starting point -- the other suites mutate this row,
        # which made this test order-dependent
        user.language = 'ne'
        from app.extensions import db
        db.session.commit()
    with client.session_transaction() as s:
        s['_user_id'] = str(uid)
        s['_fresh'] = True

    # default language is Nepali, navbar renders translated
    page = client.get('/dashboard').get_data(as_text=True)
    assert 'ड्यासबोर्ड' in page, 'default (ne) navbar not translated'
    assert 'lang-selector' in page, 'selector missing from dashboard'

    # each language switches the navbar
    expected = {
        'en': 'Dashboard',
        'ne': 'ड्यासबोर्ड',
        'newari': 'जिल्ला',      # Newari districts label
        'maithili': 'जिला',       # Maithili districts label
    }
    for code, word in expected.items():
        r = client.get('/language/set/%s' % code, headers={'Referer': '/dashboard'})
        assert r.status_code == 302, code
        page = client.get('/dashboard').get_data(as_text=True)
        assert word in page, 'lang %s did not render %r' % (code, word)

    # preference persisted to the user row, not just the session
    with app.app_context():
        assert User.query.get(uid).language == 'maithili', 'language not saved to DB'

    # session persists across requests without re-setting
    assert 'जिला' in client.get('/districts').get_data(as_text=True), 'session did not persist'

    # unsupported language is rejected, current choice untouched
    client.get('/language/set/klingon', headers={'Referer': '/dashboard'})
    with client.session_transaction() as s:
        assert s['language'] == 'maithili', 'junk language was accepted'

    # JSON endpoints
    client.get('/language/set/ne', headers={'Referer': '/dashboard'})
    assert client.get('/language/get/dashboard').get_json()['translation'] == 'ड्यासबोर्ड'
    assert len(client.get('/language/languages').get_json()) == 4

    # selector reaches logged-out pages too
    out = client.__class__(app, app.response_class)
    for path in ('/', '/auth/login', '/auth/register', '/auth/authority/login'):
        assert 'lang-selector' in out.get(path).get_data(as_text=True), path

    # no template still carries a hand-rolled citizen navbar
    import glob, io, os
    stale = [f for f in glob.glob('app/templates/**/*.html', recursive=True)
             if '<nav class="navbar">' in io.open(f, encoding='utf-8').read()
             and 'components' not in f.replace(os.sep, '/')]
    assert not stale, 'duplicated navbars remain: %s' % stale

    print('all language checks passed')


if __name__ == '__main__':
    main()
