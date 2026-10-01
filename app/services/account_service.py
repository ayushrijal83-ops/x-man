"""Account contact/address/location validation (product-quality milestone).

Mobile numbers are stored in E.164 so a future emergency-SMS integration can use them directly.
Nothing here sends SMS or verifies ownership: phone_verified stays False until a real
verification flow exists.
"""
import math
import re

MAX_ADDRESS = 300
MAX_NAME = 120
# Nepal mobile numbers are 10 digits starting 96x/97x/98x (NTC, Ncell, Smart, UTL ranges).
NEPAL_MOBILE = re.compile(r'^9[678]\d{8}$')
_SEPARATORS = re.compile(r'[\s\-().]')


class AccountError(ValueError):
    pass


def normalize_mobile(raw):
    """Return an E.164 number or raise AccountError.

    Accepts Nepal mobiles as 98XXXXXXXX, 977 98XXXXXXXX, +977-98XXXXXXXX or 00977...;
    other countries only in international form (+<country code><number>, 8-15 digits).
    """
    if not isinstance(raw, str) or not raw.strip():
        raise AccountError('Mobile number is required')
    number = _SEPARATORS.sub('', raw.strip())
    if number.startswith('00'):
        number = '+' + number[2:]
    if number.startswith('+'):
        digits = number[1:]
        if not digits.isdigit() or not 8 <= len(digits) <= 15:
            raise AccountError('Enter the mobile number in international form, e.g. +977 98XXXXXXXX')
        if digits.startswith('977') and not NEPAL_MOBILE.match(digits[3:]):
            raise AccountError('Nepal mobile numbers have 10 digits and start with 96, 97 or 98')
        return '+' + digits
    if not number.isdigit():
        raise AccountError('Mobile number may only contain digits, spaces, dashes and a leading +')
    national = number[3:] if len(number) == 13 and number.startswith('977') else number
    if not NEPAL_MOBILE.match(national):
        raise AccountError('Nepal mobile numbers have 10 digits and start with 96, 97 or 98')
    return '+977' + national


def clean_text(raw, name, limit, required=False):
    value = (raw or '').strip() if isinstance(raw, (str, type(None))) else None
    if value is None:
        raise AccountError(f'{name} must be text')
    if required and not value:
        raise AccountError(f'{name} is required')
    if len(value) > limit:
        raise AccountError(f'{name} must be at most {limit} characters')
    return value or None


def parse_coordinates(lat_raw, lon_raw):
    """(lat, lon) floats, or (None, None) when both are empty. Raises AccountError."""
    lat_raw = '' if lat_raw is None else str(lat_raw).strip()
    lon_raw = '' if lon_raw is None else str(lon_raw).strip()
    if not lat_raw and not lon_raw:
        return None, None
    if not lat_raw or not lon_raw:
        raise AccountError('Latitude and longitude must be provided together')
    try:
        lat, lon = float(lat_raw), float(lon_raw)
    except ValueError:
        raise AccountError('Location coordinates must be numbers')
    if not (math.isfinite(lat) and math.isfinite(lon)) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise AccountError('Location coordinates are out of range')
    return lat, lon


USERNAME = re.compile(r'^[A-Za-z0-9_.-]{3,30}$')
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
MIN_PASSWORD = 8


def validate_registration(form, user_model, district_model, db):
    """Return (clean_data, errors) for the citizen registration form. errors maps field -> message."""
    data, errors = {}, {}

    def field(name, func):
        try:
            data[name] = func()
        except AccountError as e:
            errors[name] = str(e)

    field('full_name', lambda: clean_text(form.get('full_name'), 'Full name', MAX_NAME, required=True))

    def username():
        value = (form.get('username') or '').strip()
        if not USERNAME.match(value):
            raise AccountError('Username must be 3-30 letters, digits, dots, dashes or underscores')
        if user_model.query.filter_by(username=value).first():
            raise AccountError('This username is already taken')
        return value
    field('username', username)

    def email():
        value = (form.get('email') or '').strip().lower()
        if len(value) > 120 or not EMAIL.match(value):
            raise AccountError('Enter a valid email address')
        if user_model.query.filter(db.func.lower(user_model.email) == value).first():
            raise AccountError('This email is already registered')
        return value
    field('email', email)

    def mobile():
        value = normalize_mobile(form.get('mobile'))
        if user_model.query.filter_by(phone=value).first():
            raise AccountError('This mobile number is already registered')
        return value
    field('mobile', mobile)

    password = form.get('password') or ''
    if len(password) < MIN_PASSWORD:
        errors['password'] = f'Password must be at least {MIN_PASSWORD} characters'
    elif password != (form.get('confirm_password') or ''):
        errors['confirm_password'] = 'Passwords do not match'
    data['password'] = password

    field('permanent_address', lambda: clean_text(form.get('permanent_address'), 'Permanent address', MAX_ADDRESS,
                                                  required=True))

    def district():
        raw = (form.get('district_id') or '').strip()
        if not raw.isascii() or not raw.isdigit() or not db.session.get(district_model, int(raw)):
            raise AccountError('Choose your district')
        return int(raw)
    field('district_id', district)

    def location():
        return parse_coordinates(form.get('current_latitude'), form.get('current_longitude'))
    try:
        data['current_latitude'], data['current_longitude'] = location()
    except AccountError as e:
        errors['current_location'] = str(e)
    field('current_address', lambda: clean_text(form.get('current_address'), 'Current address', MAX_ADDRESS))
    return data, errors


def set_current_location(user, latitude, longitude, address=None, now=None):
    """Store an explicitly shared location; never touches the permanent address."""
    from datetime import datetime
    user.current_latitude, user.current_longitude = latitude, longitude
    user.current_address = address
    user.location_updated_at = (now or datetime.utcnow()) if latitude is not None else None


def validate_profile_update(user, form, user_model, district_model, db):
    """Validate only the fields present in the form. Returns (changes, errors).

    changes may contain: username, email, full_name, phone (E.164 or None), phone_changed,
    permanent_address, district_id, bio, location=(lat, lon, address) or location_clear.
    """
    changes, errors = {}, {}

    def field(name, func):
        if name in form:
            try:
                changes[name] = func(form.get(name))
            except AccountError as e:
                errors[name] = str(e)

    def username(raw):
        value = (raw or '').strip()
        if value == user.username:
            return value
        if not USERNAME.match(value):
            raise AccountError('Username must be 3-30 letters, digits, dots, dashes or underscores')
        if user_model.query.filter(user_model.username == value, user_model.id != user.id).first():
            raise AccountError('This username is already taken')
        return value

    def email(raw):
        value = (raw or '').strip().lower()
        if len(value) > 120 or not EMAIL.match(value):
            raise AccountError('Enter a valid email address')
        if user_model.query.filter(db.func.lower(user_model.email) == value, user_model.id != user.id).first():
            raise AccountError('This email is already registered')
        return value

    def phone(raw):
        if not (raw or '').strip():
            return None  # removing a number is allowed on the profile
        value = normalize_mobile(raw)
        if user_model.query.filter(user_model.phone == value, user_model.id != user.id).first():
            raise AccountError('This mobile number is already registered')
        return value

    def district(raw):
        raw = (raw or '').strip()
        if not raw:
            return user.district_id
        if not raw.isascii() or not raw.isdigit() or not db.session.get(district_model, int(raw)):
            raise AccountError('Choose a valid district')
        return int(raw)

    field('username', username)
    field('email', email)
    field('phone', phone)
    field('full_name', lambda raw: clean_text(raw, 'Full name', MAX_NAME))
    field('permanent_address', lambda raw: clean_text(raw, 'Permanent address', MAX_ADDRESS))
    field('district_id', district)
    field('bio', lambda raw: clean_text(raw, 'Bio', 1000))
    if 'phone' in changes:
        changes['phone_changed'] = changes['phone'] != user.phone

    if form.get('clear_location') == '1':
        changes['location_clear'] = True
    elif 'current_latitude' in form or 'current_longitude' in form:
        try:
            lat, lon = parse_coordinates(form.get('current_latitude'), form.get('current_longitude'))
            address = clean_text(form.get('current_address'), 'Current address', MAX_ADDRESS)
            if lat is not None:
                changes['location'] = (lat, lon, address)
            elif address != user.current_address and user.current_latitude is not None:
                changes['current_address'] = address
        except AccountError as e:
            errors['current_location'] = str(e)
    return changes, errors


def apply_profile_update(user, changes):
    for key in ('username', 'email', 'full_name', 'permanent_address', 'district_id', 'bio', 'current_address'):
        if key in changes:
            setattr(user, key, changes[key])
    if 'phone' in changes:
        user.phone = changes['phone']
        if changes.get('phone_changed'):
            user.phone_verified = False  # a new number is never verified
    if changes.get('location_clear'):
        set_current_location(user, None, None, None)
    elif 'location' in changes:
        set_current_location(user, *changes['location'])
