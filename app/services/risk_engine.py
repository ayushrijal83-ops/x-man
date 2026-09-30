"""Risk engine service for NepalSathi.

Deterministic, explainable risk calculations for river/road status
based on sensor telemetry and configured thresholds.
"""


def compute_river_status(current_level, danger_level):
    """Compute river status from current and danger levels.

    Matches the existing level_status() in seed_nepal_data.py exactly:
    - 'unknown' if levels are None or danger_level <= 0
    - 'flooding' if current >= danger (100%+)
    - 'rising' if current >= 80% of danger
    - 'normal' otherwise (< 80%)

    Args:
        current_level: Current water level in meters (float or None)
        danger_level: Danger/flood threshold in meters (float or None)

    Returns:
        str: One of 'normal', 'rising', 'flooding', 'unknown'
    """
    if current_level is None or danger_level is None or danger_level <= 0:
        return 'unknown'

    pct = current_level / danger_level

    if pct >= 1.0:
        return 'flooding'
    if pct >= 0.80:
        return 'rising'
    return 'normal'


def compute_river_risk_level(current_level, danger_level):
    """Compute numeric risk level for a river.

    Args:
        current_level: Current water level in meters
        danger_level: Danger threshold in meters

    Returns:
        dict: {'level': int, 'label': str, 'percentage': float}
              level: 0-3 (0=unknown, 1=normal, 2=rising, 3=flooding)
    """
    status = compute_river_status(current_level, danger_level)

    if status == 'unknown':
        return {'level': 0, 'label': 'Unknown', 'percentage': None}

    if current_level is None or danger_level is None or danger_level <= 0:
        pct = None
    else:
        pct = round((current_level / danger_level) * 100, 1)

    risk_map = {
        'normal': {'level': 1, 'label': 'Normal'},
        'rising': {'level': 2, 'label': 'Rising'},
        'flooding': {'level': 3, 'label': 'Flooding'},
    }

    result = risk_map.get(status, {'level': 1, 'label': 'Normal'})
    result['percentage'] = pct
    return result


def evaluate_sensor_quality(value, sensor_type, expected_range=None):
    """Evaluate the quality of a sensor reading.

    Args:
        value: The sensor reading value
        sensor_type: Type of sensor (water_level, temperature, etc.)
        expected_range: Optional tuple of (min, max) for validation

    Returns:
        str: 'good', 'suspect', or 'bad'
    """
    if value is None:
        return 'bad'

    ranges = {
        'water_level': (0, 50),
        'temperature': (-40, 85),
        'humidity': (0, 100),
        'rainfall': (0, 500),
        'vibration': (0, 1000),
        'tilt': (-180, 180),
    }

    min_val, max_val = expected_range or ranges.get(sensor_type, (None, None))

    if min_val is not None and value < min_val:
        return 'suspect'
    if max_val is not None and value > max_val:
        return 'suspect'

    return 'good'


def compute_travel_risk_score(roads, rivers, incidents):
    """Compute travel risk score from road, river, and incident data.

    This is the deterministic rule-based scoring used by the travel planner.

    Args:
        roads: List of RoadSegment objects
        rivers: List of River objects
        incidents: List of Incident objects

    Returns:
        dict: {'score': int, 'warnings': list, 'travel_score': int, 'recommendation': str}
    """
    risk_score = 0
    warnings = []

    for road in roads:
        if road.status == 'blocked':
            risk_score += 50
            warnings.append(f"Road BLOCKED: {road.name}")
        elif road.status == 'partial':
            risk_score += 25
            warnings.append(f"Road PARTIALLY OPEN: {road.name}")

    for incident in incidents:
        if incident.severity == 'critical':
            risk_score += 40
            warnings.append(f"CRITICAL: {incident.category}")
        elif incident.severity == 'high':
            risk_score += 20
            warnings.append(f"HIGH: {incident.category}")

    risky_river_statuses = ['rising', 'flooding', 'high']
    for river in rivers:
        if river.status in risky_river_statuses:
            risk_score += 30
            warnings.append(f"River {river.status.upper()}: {river.name}")

    warnings = list(dict.fromkeys(warnings))
    risk_score = min(risk_score, 100)

    if risk_score >= 100:
        travel_score = 1
        recommendation = "Travel NOT RECOMMENDED"
        explanation = "Multiple critical issues detected."
    elif risk_score >= 70:
        travel_score = 2
        recommendation = "Travel with EXTREME CAUTION"
        explanation = "Several significant issues detected."
    elif risk_score >= 40:
        travel_score = 3
        recommendation = "Travel with CAUTION"
        explanation = "Some issues detected. Allow extra time."
    elif risk_score >= 15:
        travel_score = 4
        recommendation = "Travel conditions GENERALLY GOOD"
        explanation = "Minor issues detected."
    else:
        travel_score = 5
        recommendation = "Travel conditions EXCELLENT"
        explanation = "No significant issues detected."

    return {
        'risk_score': risk_score,
        'warnings': warnings,
        'travel_score': travel_score,
        'recommendation': recommendation,
        'explanation': explanation,
    }


def assess_water_level_risk(current_level, danger_level, sensor_quality='good'):
    """Assess risk from a water level sensor reading.

    Args:
        current_level: Current water level in meters
        danger_level: Danger threshold in meters
        sensor_quality: Quality of the sensor reading ('good', 'suspect', 'bad')

    Returns:
        dict: Risk assessment with status, level, alert_required, reason
    """
    if sensor_quality == 'bad':
        return {
            'status': 'unknown',
            'risk_level': 0,
            'alert_required': False,
            'reason': 'Sensor reading quality is bad',
            'percentage': None,
        }

    status = compute_river_status(current_level, danger_level)
    risk_info = compute_river_risk_level(current_level, danger_level)

    alert_required = status in ('rising', 'flooding')
    if sensor_quality == 'suspect':
        alert_required = False

    return {
        'status': status,
        'risk_level': risk_info['level'],
        'risk_label': risk_info['label'],
        'alert_required': alert_required,
        'reason': f"Water level at {risk_info['percentage']}% of danger mark" if risk_info['percentage'] else 'No danger level configured',
        'percentage': risk_info['percentage'],
    }


SENSOR_TYPES = {
    'water_level': {'unit': 'm', 'range': (0, 50), 'description': 'Water level'},
    'temperature': {'unit': '°C', 'range': (-40, 85), 'description': 'Temperature'},
    'humidity': {'unit': '%', 'range': (0, 100), 'description': 'Humidity'},
    'rainfall': {'unit': 'mm', 'range': (0, 500), 'description': 'Rainfall'},
    'vibration': {'unit': 'mg', 'range': (0, 1000), 'description': 'Vibration'},
    'tilt': {'unit': '°', 'range': (-180, 180), 'description': 'Tilt angle'},
}


def validate_sensor_reading(sensor_type, value, unit=None):
    """Validate a sensor reading against expected type/unit/range.

    Args:
        sensor_type: The sensor type string
        value: The numeric value
        unit: Optional unit string to validate

    Returns:
        tuple: (is_valid: bool, error_message: str or None)
    """
    if sensor_type not in SENSOR_TYPES:
        return False, f"Unsupported sensor type: {sensor_type}"

    expected = SENSOR_TYPES[sensor_type]

    if unit and unit != expected['unit']:
        return False, f"Invalid unit for {sensor_type}: expected {expected['unit']}, got {unit}"

    min_val, max_val = expected['range']
    if value < min_val or value > max_val:
        return False, f"Value {value} {expected['unit']} out of range [{min_val}, {max_val}] for {sensor_type}"

    return True, None