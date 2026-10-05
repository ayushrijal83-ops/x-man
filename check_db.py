import sqlite3
conn = sqlite3.connect('instance/hackforge.db')
cursor = conn.cursor()

# Check the incident details and notifications
# The incident 4 is earthquake, medium severity, confirmed
# Notifications 4 and 5 are for user 3 (ram), hazard_detected and hazard_confirmed

# Check what is_emergency would return for these
# EMERGENCY_MIN_SEVERITY defaults to 'high'
# HAZARD_SEVERITY = ['low', 'medium', 'high', 'critical']
# rank('medium') = 1, rank('high') = 2
# is_emergency('hazard_detected', 'medium') = 1 >= 2 = FALSE
# is_emergency('hazard_confirmed', 'medium') = 1 >= 2 = FALSE

# Check ACTIVE_STATUSES
print("ACTIVE_STATUSES should be:", ['detected', 'investigating', 'confirmed', 'response'])
print("Incident 4 status: confirmed (active)")
print("Incident 4 severity: medium")
print("EMERGENCY_MIN_SEVERITY: high (default)")
print("Notification types: hazard_detected, hazard_confirmed (both in ALERT_TYPES)")
print()
print("Result: is_emergency() returns FALSE for medium severity -> alerts filtered out of /api/emergency/active")

# Check user 3's emergency settings
cursor.execute("SELECT emergency_alert_state, emergency_sound_enabled FROM users WHERE id = 3")
print("\nUser 3 settings:", cursor.fetchone())