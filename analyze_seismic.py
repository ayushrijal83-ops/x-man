import sqlite3
import statistics
from datetime import datetime

conn = sqlite3.connect('instance/hackforge.db')
cursor = conn.cursor()

# Get all vibration readings for device_id=1 (ESP32-SEISMIC-001)
cursor.execute("""
    SELECT value, recorded_at 
    FROM sensor_readings 
    WHERE device_id = 1 AND sensor_type = 'vibration' 
    ORDER BY recorded_at ASC
""")
rows = cursor.fetchall()

values = [r[0] for r in rows]
timestamps = [datetime.fromisoformat(r[1]) for r in rows]

print("SEISMIC DEMO CHARACTERIZATION")
print("=" * 50)

print(f"\nTotal readings: {len(values)}")
print(f"Time range: {timestamps[0]} to {timestamps[-1]}")
print(f"Duration: {(timestamps[-1] - timestamps[0]).total_seconds():.0f} seconds")

# Basic stats
print(f"\nMin: {min(values):.2f} mg")
print(f"Max: {max(values):.2f} mg")
print(f"Mean: {statistics.mean(values):.2f} mg")
print(f"Median: {statistics.median(values):.2f} mg")

# Percentiles
sorted_vals = sorted(values)
def percentile(p):
    idx = int(len(sorted_vals) * p / 100)
    return sorted_vals[min(idx, len(sorted_vals)-1)]

print(f"P90: {percentile(90):.2f} mg")
print(f"P95: {percentile(95):.2f} mg")
print(f"P99: {percentile(99):.2f} mg")

# Look for runs/clusters
print("\n--- Run Analysis ---")
# Group consecutive readings by time gaps
threshold_gap = 5.0  # seconds
runs = []
current_run = [values[0]]
current_time = timestamps[0]

for i in range(1, len(values)):
    gap = (timestamps[i] - current_time).total_seconds()
    if gap <= threshold_gap:
        current_run.append(values[i])
        current_time = timestamps[i]
    else:
        runs.append(current_run)
        current_run = [values[i]]
        current_time = timestamps[i]
runs.append(current_run)

print(f"Number of continuous runs (gap <= {threshold_gap}s): {len(runs)}")
for i, run in enumerate(runs):
    if len(run) >= 3:
        print(f"  Run {i+1}: {len(run)} readings, "
              f"mean={statistics.mean(run):.2f}, "
              f"max={max(run):.2f}, "
              f"min={min(run):.2f}")

# Check for distinct periods - look at time gaps
print("\n--- Time Gap Analysis ---")
gaps = []
for i in range(1, len(timestamps)):
    gap = (timestamps[i] - timestamps[i-1]).total_seconds()
    gaps.append(gap)

print(f"Gap stats: min={min(gaps):.2f}s, max={max(gaps):.2f}s, "
      f"median={statistics.median(gaps):.2f}s, mean={statistics.mean(gaps):.2f}s")

# Large gaps might indicate separate sessions
large_gaps = [(i, g) for i, g in enumerate(gaps) if g > 10]
print(f"\nLarge gaps (>10s): {len(large_gaps)}")
for idx, gap in large_gaps[:10]:
    print(f"  After reading {idx}: {gap:.1f}s gap "
          f"({timestamps[idx]} -> {timestamps[idx+1]})")

# Histogram-like buckets
print("\n--- Value Distribution ---")
buckets = {}
for v in values:
    b = int(v // 5) * 5
    buckets[b] = buckets.get(b, 0) + 1
for b in sorted(buckets.keys()):
    bar = '#' * min(buckets[b] // 20, 50)
    print(f"  {b:3d}-{b+4:3d} mg: {buckets[b]:4d} {bar}")

# Identify strongest continuous motion period
print("\n--- Strongest Continuous Motion Period ---")
# Use a sliding window of, say, 30 readings
window_size = 30
best_window = None
best_mean = 0
for i in range(len(values) - window_size + 1):
    window = values[i:i+window_size]
    mean_val = statistics.mean(window)
    if mean_val > best_mean:
        best_mean = mean_val
        best_window = (i, i+window_size-1, timestamps[i], timestamps[i+window_size-1])

if best_window:
    print(f"  Best {window_size}-reading window: readings {best_window[0]}-{best_window[1]}")
    print(f"  Time: {best_window[2]} to {best_window[3]}")
    print(f"  Mean: {best_mean:.2f} mg")
    window_vals = values[best_window[0]:best_window[1]+1]
    print(f"  Range: {min(window_vals):.2f} - {max(window_vals):.2f} mg")
    print(f"  Duration: {(best_window[3] - best_window[2]).total_seconds():.1f} seconds")

conn.close()