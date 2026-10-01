"""Small parsers for form fields (M10). Return None on invalid input instead of raising,
so a bad value becomes a user-facing error, not a 500."""
import math


def finite_float(raw, low, high):
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and low <= value <= high else None


def int_in_range(raw, low, high):
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if low <= value <= high else None


def json_text(request, name, max_length, default=''):
    """A string field from a JSON object body; '' for a non-object body, a non-string or an
    over-long value (a JSON array or number used to be a 500)."""
    data = request.get_json(silent=True)
    value = data.get(name, default) if isinstance(data, dict) else default
    return value.strip() if isinstance(value, str) and len(value) <= max_length else ''
