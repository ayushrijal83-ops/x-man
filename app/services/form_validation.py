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
