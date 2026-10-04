"""Risk engine service for NepalSathi.

Deterministic, explainable risk calculations for river/road status
based on sensor telemetry and configured thresholds.
"""
import math
from dataclasses import dataclass, field
from datetime import datetime



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
    # M-LIVE-02: node health heartbeat (camera nodes). Stored only; no risk rule reads it.
    'battery': {'unit': '%', 'range': (0, 100), 'description': 'Battery level'},
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

    # NaN fails every comparison, so it would slip through the range check below (M10)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return False, f"Value for {sensor_type} must be a finite number"

    if unit and unit != expected['unit']:
        return False, f"Invalid unit for {sensor_type}: expected {expected['unit']}, got {unit}"

    min_val, max_val = expected['range']
    if value < min_val or value > max_val:
        return False, f"Value {value} {expected['unit']} out of range [{min_val}, {max_val}] for {sensor_type}"

    return True, None

# ---------------------------------------------------------------------------
# M08: multi-signal rules. Pure functions over evidence the caller gathered;
# no database, no events, no notifications. Every outcome carries its reasons.
# Numbers below are configurable engineering rules, not validated science.
# ---------------------------------------------------------------------------

# Flood trend: change between the earliest and latest valid reading in the window.
TREND_MIN_READINGS = 3
TREND_MIN_SPAN_SECONDS = 300
TREND_MIN_CHANGE_M = 0.05

# Abnormal-motion rule: needs N valid readings in the window. Thresholds come from
# config and are None (rule disabled) until the real MPU6050 node is characterized.
MOTION_MIN_READINGS = 3
VIBRATION_VALIDATION_MAX_MG = SENSOR_TYPES['vibration']['range'][1]


@dataclass
class RiskAssessment:
    """Explainable result of one rule evaluation. Not a probability."""
    hazard_type: str
    level: str
    action: str = 'none'  # 'none' | 'report_event'
    severity: str = None  # suggested severity when action == 'report_event'
    reasons: list = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    sources: list = field(default_factory=list)
    district_id: int = None
    assessed_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def action_warranted(self):
        return self.action == 'report_event'

    def to_dict(self):
        return {
            'hazard_type': self.hazard_type,
            'level': self.level,
            'action': self.action,
            'severity': self.severity,
            'reasons': list(self.reasons),
            'evidence': dict(self.evidence),
            'sources': list(self.sources),
            'district_id': self.district_id,
            'assessed_at': self.assessed_at.isoformat() + 'Z',
        }


def valid_readings(readings):
    """Only quality='good' readings count as evidence; others are counted, never used."""
    return sorted((r for r in readings if r.quality == 'good' and r.value is not None),
                  key=lambda r: r.recorded_at)


def water_level_trend(readings):
    """'increasing' | 'decreasing' | 'steady' | 'insufficient' from valid readings.

    change = latest - earliest valid value by recorded_at; needs >= TREND_MIN_READINGS
    readings spanning >= TREND_MIN_SPAN_SECONDS. Describes recent change, not a forecast.
    """
    good = valid_readings(readings)
    result = {'trend': 'insufficient', 'readings': len(good), 'change_m': None, 'span_seconds': None,
              'rate_m_per_hour': None}
    if len(good) < TREND_MIN_READINGS:
        return result
    span = (good[-1].recorded_at - good[0].recorded_at).total_seconds()
    result['span_seconds'] = span
    if span < TREND_MIN_SPAN_SECONDS:
        return result
    change = round(good[-1].value - good[0].value, 3)
    if change >= TREND_MIN_CHANGE_M:
        trend = 'increasing'
    elif change <= -TREND_MIN_CHANGE_M:
        trend = 'decreasing'
    else:
        trend = 'steady'
    result.update(change_m=change, rate_m_per_hour=round(change / (span / 3600), 3), trend=trend)
    return result


def assess_flood(current_level, danger_level, window_readings, district_id=None):
    """M01 semantics decide (status of the current reading vs the danger level); the window
    adds corroboration and trend as evidence. Trend never creates or escalates an event."""
    base = assess_water_level_risk(current_level, danger_level)
    good = valid_readings(window_readings)
    ignored = len(window_readings) - len(good)
    trend = water_level_trend(window_readings)
    corroborating = 0
    if base['status'] in ('rising', 'flooding'):
        corroborating = sum(1 for r in good if compute_river_status(r.value, danger_level) == base['status'])

    reasons = [base['reason']]
    if base['status'] == 'unknown':
        reasons.append('No usable danger level: insufficient evidence, no event')
    if trend['trend'] != 'insufficient':
        reasons.append(f"Trend over {int(trend['span_seconds'])} s: {trend['trend']} ({trend['change_m']:+.3f} m)")
    if corroborating > 1:
        reasons.append(f"{corroborating} valid readings in the window agree on '{base['status']}'")
    if ignored:
        reasons.append(f'{ignored} reading(s) with non-good quality ignored')

    warranted = base['alert_required'] and base['risk_level'] >= 2
    return RiskAssessment(
        hazard_type='flood', level=base['status'],
        action='report_event' if warranted else 'none',
        severity={2: 'medium', 3: 'high'}.get(base['risk_level']) if warranted else None,
        reasons=reasons,
        evidence={'current_level_m': current_level, 'danger_level_m': danger_level,
                  'percentage': base['percentage'], 'risk_level': base['risk_level'],
                  'valid_readings': len(good), 'ignored_readings': ignored,
                  'corroborating_readings': corroborating, 'trend': trend},
        sources=['iot'], district_id=district_id,
    )


def assess_motion(vibration_readings, tilt_readings, vibration_threshold_mg=None, tilt_change_deg=None,
                  district_id=None):
    """Abnormal ground-motion evidence from one device (MPU6050-class prototype).

    elevated_motion when, within the caller's window, either
      - >= MOTION_MIN_READINGS valid vibration readings are >= vibration_threshold_mg, or
      - >= MOTION_MIN_READINGS valid tilt readings span (max - min) >= tilt_change_deg.
    Unset thresholds = rule disabled ('uncharacterized'). Not an earthquake detector or
    predictor, no magnitude: it only says this device's motion signal is abnormal.
    """
    vib, tilt = valid_readings(vibration_readings), valid_readings(tilt_readings)
    ignored = len(vibration_readings) + len(tilt_readings) - len(vib) - len(tilt)
    tilt_change = round(max(r.value for r in tilt) - min(r.value for r in tilt), 3) if tilt else None
    evidence = {'vibration_readings': len(vib), 'tilt_readings': len(tilt), 'ignored_readings': ignored,
                'vibration_threshold_mg': vibration_threshold_mg, 'tilt_change_threshold_deg': tilt_change_deg,
                'max_vibration_mg': max((r.value for r in vib), default=None), 'tilt_change_deg': tilt_change}
    reasons = []
    if ignored:
        reasons.append(f'{ignored} reading(s) with non-good quality ignored')

    usable_vibration = vibration_threshold_mg is not None and 0 < vibration_threshold_mg <= VIBRATION_VALIDATION_MAX_MG
    if vibration_threshold_mg is not None and not usable_vibration:
        reasons.append(f'Vibration threshold must be in (0, {VIBRATION_VALIDATION_MAX_MG}] mg '
                       '(telemetry validation cap): vibration rule disabled')
    usable_tilt = tilt_change_deg is not None and tilt_change_deg > 0
    if not usable_vibration and not usable_tilt:
        reasons.append('Motion thresholds not configured: hardware characterization required, no event')
        return RiskAssessment('earthquake', 'uncharacterized', reasons=reasons, evidence=evidence,
                              sources=['iot'], district_id=district_id)

    over = [r for r in vib if r.value >= vibration_threshold_mg] if usable_vibration else []
    evidence['vibration_over_threshold'] = len(over)
    triggers = []
    if len(over) >= MOTION_MIN_READINGS:
        triggers.append(f'{len(over)} vibration readings >= {vibration_threshold_mg} mg')
    if usable_tilt and len(tilt) >= MOTION_MIN_READINGS and tilt_change >= tilt_change_deg:
        triggers.append(f'tilt changed {tilt_change} deg (>= {tilt_change_deg}) over {len(tilt)} readings')
    if triggers:
        return RiskAssessment('earthquake', 'elevated_motion', action='report_event', severity='medium',
                              reasons=['Abnormal ground-motion signal: ' + '; '.join(triggers)] + reasons,
                              evidence=evidence, sources=['iot'], district_id=district_id)
    if over:
        reasons.append(f'{len(over)} reading(s) over threshold, {MOTION_MIN_READINGS} needed: single spikes ignored')
    return RiskAssessment('earthquake', 'normal_motion', reasons=reasons or ['Motion within configured limits'],
                          evidence=evidence, sources=['iot'], district_id=district_id)


def assess_visual(hazard_type, reports, authority_source=False, district_id=None, node_evidence=()):
    """Evidence grade for a landslide/road_damage event from its linked citizen reports.

    Counted per distinct reporter (one person's repeated reports count once); rejected
    reports are excluded. AI agrees only when its label equals the event type (M06 already
    returns 'unknown' below its threshold). Grades:
      insufficient   no usable report
      single_report  one reporter, no AI agreement
      supported      one reporter + AI agreement, or >= 2 distinct reporters
      corroborated   >= 2 distinct reporters and >= 1 AI agreement
      field_node_only  no usable citizen report, but attached camera-node evidence (M-LIVE-02)
    Camera-node evidence (node_evidence) is a separate source: a node is never counted as a
    reporter and its AI results never count as a citizen AI agreement, so the citizen grades above
    are unchanged. Review-rejected and held evidence is excluded.
    Assessment only: never changes severity or status (action is always 'none').
    """
    usable = [r for r in reports if r.status != 'rejected']
    reporters = {r.reporter_id for r in usable}
    completed = [r for r in usable if r.ai_status == 'completed']
    agree = [r for r in completed if r.ai_label == hazard_type]
    conflict = [r for r in completed if r.ai_label not in (hazard_type, 'unknown', None)]
    evidence = {'reports': len(reports), 'usable_reports': len(usable), 'distinct_reporters': len(reporters),
                'rejected_reports': len(reports) - len(usable),
                'accepted_reports': sum(1 for r in usable if r.status == 'accepted'),
                'ai_agree': len(agree), 'ai_conflict': len(conflict),
                'ai_unknown': sum(1 for r in completed if r.ai_label == 'unknown'),
                'ai_not_available': len(usable) - len(completed),
                'max_ai_agree_confidence': max((r.ai_confidence for r in agree), default=None),
                'authority_source': authority_source}
    nodes = [e for e in node_evidence if e.status == 'attached' and e.review_status != 'rejected']
    evidence.update(field_node_evidence=len(nodes), distinct_field_nodes=len({e.device_id for e in nodes}),
                    field_node_ai_agree=sum(1 for e in nodes if e.ai_status == 'completed'
                                            and e.ai_label == hazard_type))
    sources = (['citizen_report'] if usable else []) + (['vision_ai'] if agree else []) + \
        (['field_node'] if nodes else []) + (['authority'] if authority_source else [])

    if len(reporters) >= 2 and agree:
        level = 'corroborated'
    elif len(reporters) >= 2 or (reporters and agree):
        level = 'supported'
    elif reporters:
        level = 'single_report'
    elif nodes:
        level = 'field_node_only'
    else:
        level = 'insufficient'
    reasons = [f'{len(reporters)} distinct reporter(s), {len(agree)} AI agreement(s)']
    if nodes:
        reasons.append(f"{len(nodes)} camera-node evidence item(s) from {evidence['distinct_field_nodes']} "
                       f"field node(s), {evidence['field_node_ai_agree']} with server AI agreement "
                       f"(not counted as reporters)")
    if conflict:
        reasons.append(f'{len(conflict)} AI result(s) suggest a different hazard type: needs human review')
    if evidence['rejected_reports']:
        reasons.append(f"{evidence['rejected_reports']} rejected report(s) excluded")
    if authority_source:
        reasons.append('Event was reported by an authority')
    if evidence['accepted_reports']:
        reasons.append(f"{evidence['accepted_reports']} report(s) accepted by a reviewer")
    reasons.append('AI scores are relative model scores, not probabilities; severity and status stay human decisions')
    return RiskAssessment(hazard_type, level, reasons=reasons, evidence=evidence, sources=sources,
                          district_id=district_id)
