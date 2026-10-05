# SEISMIC NOTIFICATION DIAGNOSIS

## Summary

| Step | Status | Details |
|------|--------|---------|
| 1. Telemetry | **PASS** | ESP32-SEISMIC-001 vibration readings arriving every ~2 seconds, stored as SensorReading records with quality='good' |
| 2. Sensor readings stored | **PASS** | 2192 vibration readings stored in sensor_readings table for device_id=1 (values 55-70 mg) |
| 3. Seismic event detection | **FAIL** | Motion thresholds not configured → `assess_motion()` returns `level='uncharacterized'`, `action='none'` |
| 4. Incident creation | **FAIL** | No earthquake incident created (0 earthquake incidents in database) |
| 5. Severity | **N/A** | No incident created |
| 6. Sindhuli assignment | **N/A** | No incident created |
| 7. Notification creation | **FAIL** | No notifications for earthquake events (only QA H03.10 test notifications exist) |
| 8. Sindhuli recipient targeting | **N/A** | No notification created |
| 9. Browser delivery/display | **N/A** | No notification created |

---

## ROOT CAUSE

**Category B: Telemetry reached server but seismic event detector did not trigger**

The motion detection thresholds are **not configured** in the environment:
- `MOTION_VIBRATION_THRESHOLD_MG = None` (not set in .env)
- `MOTION_TILT_CHANGE_THRESHOLD_DEG = None` (not set in .env)

In `app/services/risk_engine.py:assess_motion()` (lines 389-397):
```python
usable_vibration = vibration_threshold_mg is not None and 0 < vibration_threshold_mg <= VIBRATION_VALIDATION_MAX_MG
usable_tilt = tilt_change_deg is not None and tilt_change_deg > 0
if not usable_vibration and not usable_tilt:
    reasons.append('Motion thresholds not configured: hardware characterization required, no event')
    return RiskAssessment('earthquake', 'uncharacterized', reasons=reasons, evidence=evidence,
                          sources=['iot'], district_id=district_id)
```

When both thresholds are `None`, the function returns early with `action='none'` (default), so `action_warranted` is `False`.

In `app/services/risk_service.py:evaluate_motion()` (line 83):
```python
if assessment.action_warranted and device.district_id:
    report_hazard('earthquake', ...)  # NEVER EXECUTED
```

No `report_hazard()` call → no Incident created → no notification sent.

---

## EVIDENCE

### Database State (instance/hackforge.db)
- **iot_devices**: ESP32-SEISMIC-001 exists (id=1, district_id=34=Sindhuli, no lat/lon)
- **sensor_readings**: 2192 vibration readings (55-70 mg, quality='good'), 0 tilt readings
- **incidents**: 3 incidents (all QA H03.10 tests: flood/road_damage/landslide, all 'rejected'), 0 earthquake incidents
- **incident_affected_districts**: Empty
- **notifications**: 3 notifications (all for QA H03.10 tests, user_id=2, district=69=Achham)
- **users**: User 'ram' (id=3) exists in Sindhuli (district_id=34) - citizen
- **authorities**: 5 authorities exist for Sindhuli district

### Config Values (runtime)
```
MOTION_VIBRATION_THRESHOLD_MG: None
MOTION_TILT_CHANGE_THRESHOLD_DEG: None
EMERGENCY_MIN_SEVERITY: high
```

### Code Path
1. `app/routes/iot.py:ingest_telemetry()` (line 250-251) → calls `risk_service.evaluate_motion(device)`
2. `app/services/risk_service.py:evaluate_motion()` (line 80-97) → calls `motion_assessment(device)`
3. `app/services/risk_service.py:motion_assessment()` (line 67-77) → calls `risk_engine.assess_motion()` with thresholds from config (both None)
4. `app/services/risk_engine.py:assess_motion()` (line 369-413) → returns `RiskAssessment(level='uncharacterized', action='none')`
5. Back in `evaluate_motion()`: `assessment.action_warranted` is `False` → `report_hazard()` **never called**

---

## EXACT FILE/FUNCTION RESPONSIBLE

**Primary**: `app/services/risk_engine.py:assess_motion()` lines 389-397
- Returns early with "uncharacterized" when thresholds are not configured

**Secondary**: `app/config.py` lines 36-39
- Reads thresholds from environment variables; defaults to `None` when unset

**Configuration**: `.env` file missing:
```
MOTION_VIBRATION_THRESHOLD_MG=<value>
MOTION_TILT_CHANGE_THRESHOLD_DEG=<value>
```

---

## RECOMMENDED MINIMAL FIX

Configure the motion detection thresholds in `.env` (values need hardware characterization):

```bash
# Example values - MUST be validated against actual MPU6050 hardware behavior
MOTION_VIBRATION_THRESHOLD_MG=100
MOTION_TILT_CHANGE_THRESHOLD_DEG=10
```

**Note**: The vibration readings during the test were 55-70 mg. If the threshold is set above ~70 mg, the test shaking would still not trigger. Threshold values must be determined from hardware characterization.

---

## IMPORTANT

- **Do NOT modify firmware** (user instruction)
- **Do NOT modify secrets** (user instruction)  
- **Do NOT change thresholds yet** (user instruction - diagnosis only)
- **Do NOT commit** (user instruction)