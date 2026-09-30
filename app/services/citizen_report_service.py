"""Citizen Report Service (M05): photo evidence -> hazard event.

A report is evidence; the Incident is the hazard. Submitting a report:
  validate -> re-encode image -> store file -> CitizenReport row
  -> hazard_event_service.report_hazard(source='citizen_report')  (M02 dedup, M03/M04 alerts)
No vision AI here (M06). A photo never confirms or escalates a hazard.
"""
import io
import math
import os
import re
import uuid
import warnings
from datetime import datetime

from flask import current_app
from PIL import Image, ImageOps

from app.extensions import db
from app.models import CitizenReport, District
from app.models.citizen_report import VISUAL_HAZARD_TYPES, REPORT_REVIEW_STATUSES
from app.services import notification_service
from app.services.hazard_event_service import report_hazard

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB upload limit (app-wide MAX_CONTENT_LENGTH is 16 MB)
MAX_IMAGE_PIXELS = 40_000_000  # ~40 MP: phone photos fit; decompression bombs don't
MAX_STORED_SIDE = 2560  # stored copy is downscaled to this longest side
ALLOWED_FORMATS = {'jpg': 'JPEG', 'jpeg': 'JPEG', 'png': 'PNG', 'webp': 'WEBP'}  # extension -> real format
MAX_DESCRIPTION = 1000
MAX_LOCATION = 200
# A citizen report is unverified evidence: it opens/joins an event at 'medium'
# and can never escalate it. Severity changes come from authorities (or M06 later).
REPORT_SEVERITY = 'medium'
_STORED_NAME = re.compile(r'^[0-9a-f]{32}\.jpg$')


class ReportError(ValueError):
    """Validation failure; `status` is the HTTP status to return."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def upload_dir():
    return current_app.config.get('REPORT_UPLOAD_DIR') or \
        os.path.join(current_app.instance_path, 'uploads', 'reports')


def image_path(report):
    """Absolute path of a report's stored image, or None if the stored name is not ours."""
    if not report.image_filename or not _STORED_NAME.match(report.image_filename):
        return None
    return os.path.join(upload_dir(), report.image_filename)


def _parse_float(value, name):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ReportError(f'{name} must be a number')
    if not math.isfinite(number):
        raise ReportError(f'{name} must be a finite number')
    return number


def _parse_location(form):
    lat_raw, lon_raw = (form.get('latitude') or '').strip(), (form.get('longitude') or '').strip()
    if not lat_raw and not lon_raw:
        return None, None  # GPS denied / not entered: district is enough
    if not lat_raw or not lon_raw:
        raise ReportError('Latitude and longitude must be provided together')
    latitude, longitude = _parse_float(lat_raw, 'Latitude'), _parse_float(lon_raw, 'Longitude')
    if not -90 <= latitude <= 90:
        raise ReportError('Latitude must be between -90 and 90')
    if not -180 <= longitude <= 180:
        raise ReportError('Longitude must be between -180 and 180')
    return latitude, longitude


def _parse_text(form, key, limit):
    value = (form.get(key) or '').strip()
    if len(value) > limit:
        raise ReportError(f'{key} must be at most {limit} characters')
    return value or None


def _process_image(file_storage):
    """Validate an untrusted upload and return clean JPEG bytes.

    The original bytes are never stored: the image is decoded, checked against
    its claimed extension, orientation-fixed, downscaled and re-encoded, which
    also drops EXIF (including the phone's embedded GPS) and any trailing data.
    """
    if file_storage is None or not file_storage.filename:
        raise ReportError('A photo is required')
    extension = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if extension not in ALLOWED_FORMATS:
        raise ReportError('Photo must be a JPG, PNG or WEBP image')
    if not (file_storage.mimetype or '').startswith('image/'):
        raise ReportError('Photo must be an image')

    data = file_storage.stream.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ReportError('Photo is larger than 10 MB', status=413)
    if not data:
        raise ReportError('Photo is empty')

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)  # warn -> reject
            with Image.open(io.BytesIO(data)) as probe:
                real_format = probe.format
                width, height = probe.size
                probe.verify()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise ReportError('Photo dimensions are too large')
    except Exception:
        raise ReportError('Photo is not a valid image')
    if real_format != ALLOWED_FORMATS[extension]:
        raise ReportError('Photo content does not match its file type')
    if width * height > MAX_IMAGE_PIXELS:
        raise ReportError('Photo dimensions are too large')

    try:
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((MAX_STORED_SIDE, MAX_STORED_SIDE))
            if image.mode != 'RGB':
                image = image.convert('RGB')
            out = io.BytesIO()
            image.save(out, format='JPEG', quality=85, optimize=True)  # no exif= -> metadata dropped
            return out.getvalue()
    except ReportError:
        raise
    except Exception:
        raise ReportError('Photo could not be processed')


def submit_report(user, form, file_storage):
    """Create a CitizenReport and attach it to a new or existing Incident.

    Returns (report, incident_created). Raises ReportError.
    """
    hazard_type = (form.get('hazard_type') or '').strip()
    if hazard_type not in VISUAL_HAZARD_TYPES:
        raise ReportError(f'hazard_type must be one of {VISUAL_HAZARD_TYPES}')

    district_raw = (form.get('district_id') or '').strip()
    if not district_raw.isascii() or not district_raw.isdigit():
        raise ReportError('district_id is required and must be an integer')
    district = db.session.get(District, int(district_raw))
    if not district:
        raise ReportError('Invalid district_id', status=404)

    latitude, longitude = _parse_location(form)
    description = _parse_text(form, 'description', MAX_DESCRIPTION)
    location = _parse_text(form, 'location', MAX_LOCATION)
    jpeg = _process_image(file_storage)

    directory = upload_dir()
    os.makedirs(directory, exist_ok=True)
    filename = f'{uuid.uuid4().hex}.jpg'
    path = os.path.join(directory, filename)
    with open(path, 'xb') as f:  # 'x': never overwrite
        f.write(jpeg)

    try:
        report = CitizenReport(reporter_id=user.id, district_id=district.id, hazard_type=hazard_type,
                               description=description, location=location, latitude=latitude,
                               longitude=longitude, image_filename=filename, status='submitted')
        db.session.add(report)
        db.session.flush()
        label = hazard_type.replace('_', ' ').capitalize()
        incident, created = report_hazard(
            hazard_type, REPORT_SEVERITY, 'citizen_report', escalate=False,
            district_id=district.id,
            latitude=latitude,
            longitude=longitude,
            location=location,
            title=f'{label} reported by a citizen',
            # the citizen's description stays on the report (private); not copied to the public event
            source_reference=f'report_{report.id}',
            # the reporter gets a receipt instead of an emergency alert about their own report
            notify_exclude_user_ids=(user.id,),
        )
        report.incident_id = incident.id
        notification_service.notify_report_update(report)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if os.path.exists(path):
            os.remove(path)
        raise
    return report, created


def can_view(user, report):
    """Reporter, admin, or an authority responsible for the report's district."""
    if user.role == 'admin' or report.reporter_id == user.id:
        return True
    return user.role == 'authority' and user.authority is not None \
        and user.authority.district_id == report.district_id


def can_review(user, report):
    """Admin, or the authority responsible for the report's district — never your own report."""
    if report.reporter_id == user.id:
        return False
    if user.role == 'admin':
        return True
    return user.role == 'authority' and user.authority is not None \
        and user.authority.district_id == report.district_id


def visible_reports_query(user):
    query = CitizenReport.query
    if user.role == 'admin':
        return query
    if user.role == 'authority' and user.authority is not None:
        return query.filter(db.or_(CitizenReport.district_id == user.authority.district_id,
                                   CitizenReport.reporter_id == user.id))
    return query.filter(CitizenReport.reporter_id == user.id)


def review_report(reviewer, report, status):
    """Accept/reject a report. Changes only the report, never the Incident lifecycle."""
    if status not in REPORT_REVIEW_STATUSES:
        raise ReportError(f'status must be one of {REPORT_REVIEW_STATUSES}')
    if report.status != 'submitted':
        raise ReportError(f'Report was already {report.status}', status=409)
    report.status = status
    report.reviewed_by_id = reviewer.id
    report.reviewed_at = datetime.utcnow()
    notification_service.notify_report_update(report)
    db.session.commit()
    return report
