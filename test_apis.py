import requests
import json

print("=" * 50)
print("TESTING NEPAL GEO APIS")
print("=" * 50)

# Test 1: Nominatim API
print("\n1. TESTING NOMINATIM API (Location Search)")
print("-" * 50)

response = requests.get(
    'https://nominatim.openstreetmap.org/search',
    params={
        'q': 'Sindhuli, Nepal',
        'format': 'json',
        'limit': 3
    },
    headers={'User-Agent': 'NepalSathi/1.0'}
)

if response.status_code == 200:
    data = response.json()
    print("✅ API Working!")
    print(f"Results: {len(data)}")
    for loc in data:
        name = loc.get('display_name', 'Unknown')
        lat = loc.get('lat', 'N/A')
        lon = loc.get('lon', 'N/A')
        print(f"  Name: {name}")
        print(f"  Lat: {lat}, Lon: {lon}")
        print("  ---")
else:
    print(f"❌ Error: {response.status_code}")

# Test 2: Overpass API - Using GET method
print("\n2. TESTING OVERPASS API (Highways)")
print("-" * 50)

# Simple query for testing
query = '[out:json];way["highway"="primary"]["name"](27.0,85.0,28.0,86.0);out tags 5;'

response = requests.get(
    'https://overpass-api.de/api/interpreter',
    params={'data': query},
    timeout=60
)

print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    elements = data.get('elements', [])
    print(f"✅ API Working!")
    print(f"Highways found: {len(elements)}")
    for road in elements[:5]:
        tags = road.get('tags', {})
        name = tags.get('name', 'Unnamed Road')
        print(f"  🛣️ {name}")
else:
    print(f"❌ Error: {response.status_code}")

# Test 3: Alternative - Use alternative Overpass server
print("\n3. TESTING ALTERNATIVE OVERPASS SERVER")
print("-" * 50)

query = '[out:json];way["waterway"="river"]["name"](26.0,80.0,31.0,89.0);out tags 5;'

response = requests.get(
    'https://overpass.kumi.systems/api/interpreter',
    params={'data': query},
    timeout=60
)

print(f"Status: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    elements = data.get('elements', [])
    print(f"✅ Alternative API Working!")
    print(f"Rivers found: {len(elements)}")
    for river in elements[:5]:
        tags = river.get('tags', {})
        name = tags.get('name', 'Unnamed River')
        print(f"  🌊 {name}")
else:
    print(f"❌ Error: {response.status_code}")

print("\n" + "=" * 50)
print("TEST COMPLETE")
print("=" * 50)