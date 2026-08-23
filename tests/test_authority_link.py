"""Each authority user must see its own authority, never the first one."""
from app.extensions import db
from app.models import Authority, District
from app.models.user import User


def _make(username, authority_name, category, district):
    authority = Authority(name=authority_name, category=category, district_id=district.id)
    db.session.add(authority)
    db.session.flush()
    user = User(username=username, email=username + '@x.np', role='authority',
                district_id=district.id, authority_id=authority.id)
    user.set_password('pw')
    db.session.add(user)
    db.session.commit()


def test_each_authority_sees_its_own(app, client):
    with app.app_context():
        district = District(name='Sindhuli', province='Bagmati')
        db.session.add(district)
        db.session.flush()
        _make('road_user', 'Sindhuli Road Division Office', 'road', district)   # first authority
        _make('water_user', 'Sindhuli Water Supply Office', 'water', district)
        _make('police_user', 'Sindhuli District Police', 'police', district)

    for username, expected in [('water_user', 'Sindhuli Water Supply Office'),
                               ('police_user', 'Sindhuli District Police')]:
        client.post('/auth/authority/login', data={'username': username, 'password': 'pw'})
        page = client.get('/authority/dashboard').get_data(as_text=True)
        assert expected in page, username
        assert 'Road Division' not in page, username
        client.get('/auth/logout')


def test_unlinked_authority_user_is_not_given_someone_elses(app, client):
    with app.app_context():
        district = District(name='Sindhuli', province='Bagmati')
        db.session.add(district)
        db.session.flush()
        _make('road_user', 'Sindhuli Road Division Office', 'road', district)
        orphan = User(username='orphan', email='o@x.np', role='authority', district_id=district.id)
        orphan.set_password('pw')
        db.session.add(orphan)
        db.session.commit()

    client.get('/language/set/en')   # flash messages are translated; assert on English
    client.post('/auth/authority/login', data={'username': 'orphan', 'password': 'pw'})
    page = client.get('/authority/dashboard', follow_redirects=True).get_data(as_text=True)
    assert 'Road Division' not in page
    assert 'No authority is linked' in page
