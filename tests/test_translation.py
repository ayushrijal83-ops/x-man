# -*- coding: utf-8 -*-
"""Page content, not just the sidebar, must follow the language switch."""
from app.extensions import db
from app.models import District
from app.models.user import User

PAGES = ['/dashboard', '/districts', '/roads/status', '/rivers/status',
         '/projects/tracker', '/authorities/directory', '/complaints/new',
         '/travel/planner', '/ai/assistant', '/social/feed', '/posts/create',
         '/profile/me']

# One page-content string per page that must be translated, plus its Nepali form.
EXPECT = {
    '/dashboard': ('Road Segments', 'सडक खण्डहरू'),
    '/districts': ('Select your district to see local information',
                   'स्थानीय जानकारी हेर्न आफ्नो जिल्ला छान्नुहोस्'),
    '/roads/status': ('Live Road Status', 'प्रत्यक्ष सडक अवस्था'),
    '/rivers/status': ('Monitor river levels and flood risks', 'नदीको सतह र बाढीको जोखिम अनुगमन गर्नुहोस्'),
    '/projects/tracker': ('Development Project Tracker', 'विकास आयोजना ट्र्याकर'),
    '/authorities/directory': ('Authority Directory', 'निकाय निर्देशिका'),
    '/complaints/new': ('Submit Complaint', 'उजुरी पेश गर्नुहोस्'),
    '/travel/planner': ('Plan Your Journey', 'आफ्नो यात्रा योजना बनाउनुहोस्'),
    '/ai/assistant': ('Travel Advice', 'यात्रा सल्लाह'),
    '/social/feed': ('All Categories', 'सबै श्रेणीहरू'),
    '/posts/create': ('Add Photo (optional)', 'फोटो थप्नुहोस् (वैकल्पिक)'),
    '/profile/me': ('Reputation', 'प्रतिष्ठा'),
}


def _login(app, client):
    with app.app_context():
        district = District(name='Sindhuli', province='Bagmati')
        db.session.add(district)
        db.session.flush()
        user = User(username='citizen', email='c@x.np', role='citizen', district_id=district.id)
        user.set_password('pw')
        db.session.add(user)
        db.session.commit()
    client.post('/auth/login', data={'username': 'citizen', 'password': 'pw'})


def test_pages_translate_content_both_ways(app, client):
    _login(app, client)

    client.get('/language/set/ne')
    for page in PAGES:
        english, nepali = EXPECT[page]
        body = client.get(page, follow_redirects=True).get_data(as_text=True)
        assert nepali in body, '%s not translated to Nepali' % page
        assert english not in body, '%s still shows English' % page

    client.get('/language/set/en')
    for page in PAGES:
        english, _ = EXPECT[page]
        body = client.get(page, follow_redirects=True).get_data(as_text=True)
        assert english in body, '%s did not switch back to English' % page


def test_auth_pages_translate(app, client):
    for page, english, nepali in [
            ('/auth/login', 'Welcome Back', 'पुनः स्वागत छ'),
            ('/auth/register', 'Create Account', 'खाता खोल्नुहोस्'),
            ('/auth/authority/login', 'Authority Login', 'निकाय लगइन')]:
        client.get('/language/set/ne')
        body = client.get(page).get_data(as_text=True)
        assert nepali in body, page
        assert english not in body, page

        client.get('/language/set/en')
        assert english in client.get(page).get_data(as_text=True), page


def test_database_status_values_are_translated(app, client):
    from app.services.page_strings import page_translation
    assert page_translation('ne', 'blocked') == 'अवरुद्ध'
    assert page_translation('en', 'blocked') == 'blocked'
    assert page_translation('newari', 'blocked') == 'अवरुद्ध'   # falls back to Nepali
    assert page_translation('ne', 'not a known string') == 'not a known string'


def test_ui_keys_still_work(app):
    """The old t('key') lookups must not regress."""
    from app.services.translation_service import TranslationService
    ts = TranslationService()
    assert ts.get_translation('ne', 'dashboard') == 'ड्यासबोर्ड'
    assert ts.get_translation('newari', 'road_status') == 'लं अवस्था'
    assert ts.get_translation('en', 'dashboard') == 'Dashboard'
