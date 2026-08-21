import requests
import json

class NepalGeoService:
    """Nepal geographic data from OpenStreetMap (free, no API key)."""
    
    def __init__(self):
        self.overpass_url = 'https://overpass-api.de/api/interpreter'
        self.nominatim_url = 'https://nominatim.openstreetmap.org/search'
        # Overpass answers 406 to requests without a real User-Agent, so every
        # query below was failing silently and returning None.
        self.headers = {'User-Agent': 'NepalSathi/1.0 (district intelligence)'}
    
    def get_nepal_boundary(self):
        """Get Nepal country boundary."""
        query = """
        [out:json];
        relation["ISO3166-1"="NP"][admin_level=2];
        out geom;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('elements'):
                    return data['elements'][0]
        except Exception as e:
            print(f'Nepal boundary error: {e}')
        
        return None
    
    def get_district_boundary(self, district_name):
        """Get district boundary from OSM."""
        query = f"""
        [out:json];
        relation["name"="{district_name}"]["admin_level"="6"]["boundary"="administrative"];
        out geom;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if data.get('elements'):
                    return data['elements'][0]
        except Exception as e:
            print(f'District boundary error: {e}')
        
        return None
    
    def get_roads_in_district(self, district_name, road_types=None):
        """Get major roads in a district."""
        if road_types is None:
            road_types = ['highway=motorway', 'highway=trunk', 'highway=primary', 'highway=secondary']
        
        road_filter = '|'.join(road_types)
        
        query = f"""
        [out:json];
        area["name"="{district_name}"]["admin_level"="6"]->.a;
        way(area.a)[{road_filter}];
        out geom;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                roads = []
                
                for element in data.get('elements', []):
                    tags = element.get('tags', {})
                    roads.append({
                        'id': element.get('id'),
                        'name': tags.get('name', tags.get('ref', 'Unnamed Road')),
                        'highway': tags.get('highway', 'unknown'),
                        'geometry': element.get('geometry', []),
                    })
                
                return roads
        except Exception as e:
            print(f'Roads error: {e}')
        
        return []
    
    def get_rivers_in_district(self, district_name):
        """Get rivers in a district."""
        query = f"""
        [out:json];
        area["name"="{district_name}"]["admin_level"="6"]->.a;
        way(area.a)["waterway"="river"];
        out geom;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                rivers = []
                
                for element in data.get('elements', []):
                    tags = element.get('tags', {})
                    rivers.append({
                        'id': element.get('id'),
                        'name': tags.get('name', 'Unnamed River'),
                        'waterway': tags.get('waterway', 'river'),
                        'geometry': element.get('geometry', []),
                    })
                
                return rivers
        except Exception as e:
            print(f'Rivers error: {e}')
        
        return []
    
    def search_location(self, query):
        """Search for a location in Nepal."""
        params = {
            'q': f'{query}, Nepal',
            'format': 'json',
            'limit': 5
        }
        
        headers = {
            'User-Agent': 'NepalSathi/1.0 (https://github.com/ayushrijal83-ops/x-man)'
        }
        
        try:
            response = requests.get(self.nominatim_url, params=params, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f'Location search error: {e}')
        
        return []
    
    def get_all_district_boundaries(self):
        """Get all 77 district boundaries."""
        query = """
        [out:json];
        relation["admin_level"="6"]["boundary"="administrative"]["ISO3166-2"~"^NP-"];
        out tags;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=120)
            if response.status_code == 200:
                data = response.json()
                districts = []
                
                for element in data.get('elements', []):
                    tags = element.get('tags', {})
                    districts.append({
                        'id': element.get('id'),
                        'name': tags.get('name', 'Unknown'),
                        'iso_code': tags.get('ISO3166-2', ''),
                        'province': tags.get('province', ''),
                    })
                
                return districts
        except Exception as e:
            print(f'All districts error: {e}')
        
        return []
    
    def get_major_highways(self):
        """Get major highways of Nepal."""
        query = """
        [out:json];
        area["ISO3166-1"="NP"]->.a;
        way(area.a)["highway"~"motorway|trunk|primary"]["name"];
        out geom;
        """
        
        try:
            response = requests.post(self.overpass_url, data={'data': query}, headers=self.headers, timeout=60)
            if response.status_code == 200:
                data = response.json()
                highways = []
                
                for element in data.get('elements', []):
                    tags = element.get('tags', {})
                    name = tags.get('name', '')
                    if name:
                        highways.append({
                            'id': element.get('id'),
                            'name': name,
                            'highway': tags.get('highway'),
                            'ref': tags.get('ref', ''),
                        })
                
                return highways
        except Exception as e:
            print(f'Highways error: {e}')
        
        return []