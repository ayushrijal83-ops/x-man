from app import create_app
from app.extensions import db
from app.models import District, Authority, RoadSegment, River, Project
from datetime import datetime

def seed_districts():
    """Seed all 77 districts of Nepal."""
    districts = [
        # Koshi Province (14 districts)
        {'name': 'Bhojpur', 'province': 'Koshi', 'headquarters': 'Bhojpur'},
        {'name': 'Dhankuta', 'province': 'Koshi', 'headquarters': 'Dhankuta'},
        {'name': 'Ilam', 'province': 'Koshi', 'headquarters': 'Ilam'},
        {'name': 'Jhapa', 'province': 'Koshi', 'headquarters': 'Bhadrapur'},
        {'name': 'Khotang', 'province': 'Koshi', 'headquarters': 'Diktel'},
        {'name': 'Morang', 'province': 'Koshi', 'headquarters': 'Biratnagar'},
        {'name': 'Okhaldhunga', 'province': 'Koshi', 'headquarters': 'Okhaldhunga'},
        {'name': 'Panchthar', 'province': 'Koshi', 'headquarters': 'Phidim'},
        {'name': 'Sankhuwasabha', 'province': 'Koshi', 'headquarters': 'Khandbari'},
        {'name': 'Solukhumbu', 'province': 'Koshi', 'headquarters': 'Salleri'},
        {'name': 'Sunsari', 'province': 'Koshi', 'headquarters': 'Inaruwa'},
        {'name': 'Taplejung', 'province': 'Koshi', 'headquarters': 'Taplejung'},
        {'name': 'Terhathum', 'province': 'Koshi', 'headquarters': 'Myanglung'},
        {'name': 'Udayapur', 'province': 'Koshi', 'headquarters': 'Gaighat'},
        
        # Madhesh Province (8 districts)
        {'name': 'Bara', 'province': 'Madhesh', 'headquarters': 'Kalaiya'},
        {'name': 'Dhanusha', 'province': 'Madhesh', 'headquarters': 'Janakpur'},
        {'name': 'Mahottari', 'province': 'Madhesh', 'headquarters': 'Jaleshwar'},
        {'name': 'Parsa', 'province': 'Madhesh', 'headquarters': 'Birgunj'},
        {'name': 'Rautahat', 'province': 'Madhesh', 'headquarters': 'Gaur'},
        {'name': 'Saptari', 'province': 'Madhesh', 'headquarters': 'Rajbiraj'},
        {'name': 'Sarlahi', 'province': 'Madhesh', 'headquarters': 'Malangwa'},
        {'name': 'Siraha', 'province': 'Madhesh', 'headquarters': 'Siraha'},
        
        # Bagmati Province (13 districts)
        {'name': 'Bhaktapur', 'province': 'Bagmati', 'headquarters': 'Bhaktapur'},
        {'name': 'Chitwan', 'province': 'Bagmati', 'headquarters': 'Bharatpur'},
        {'name': 'Dhading', 'province': 'Bagmati', 'headquarters': 'Dhading Besi'},
        {'name': 'Dolakha', 'province': 'Bagmati', 'headquarters': 'Charikot'},
        {'name': 'Kathmandu', 'province': 'Bagmati', 'headquarters': 'Kathmandu'},
        {'name': 'Kavrepalanchok', 'province': 'Bagmati', 'headquarters': 'Dhulikhel'},
        {'name': 'Lalitpur', 'province': 'Bagmati', 'headquarters': 'Lalitpur'},
        {'name': 'Makwanpur', 'province': 'Bagmati', 'headquarters': 'Hetauda'},
        {'name': 'Nuwakot', 'province': 'Bagmati', 'headquarters': 'Bidur'},
        {'name': 'Ramechhap', 'province': 'Bagmati', 'headquarters': 'Manthali'},
        {'name': 'Rasuwa', 'province': 'Bagmati', 'headquarters': 'Dhunche'},
        {'name': 'Sindhuli', 'province': 'Bagmati', 'headquarters': 'Kamalamai'},
        {'name': 'Sindhupalchok', 'province': 'Bagmati', 'headquarters': 'Chautara'},
        
        # Gandaki Province (11 districts)
        {'name': 'Baglung', 'province': 'Gandaki', 'headquarters': 'Baglung'},
        {'name': 'Gorkha', 'province': 'Gandaki', 'headquarters': 'Gorkha'},
        {'name': 'Kaski', 'province': 'Gandaki', 'headquarters': 'Pokhara'},
        {'name': 'Lamjung', 'province': 'Gandaki', 'headquarters': 'Besisahar'},
        {'name': 'Manang', 'province': 'Gandaki', 'headquarters': 'Chame'},
        {'name': 'Mustang', 'province': 'Gandaki', 'headquarters': 'Jomsom'},
        {'name': 'Myagdi', 'province': 'Gandaki', 'headquarters': 'Beni'},
        {'name': 'Nawalpur', 'province': 'Gandaki', 'headquarters': 'Kawasoti'},
        {'name': 'Parbat', 'province': 'Gandaki', 'headquarters': 'Kusma'},
        {'name': 'Syangja', 'province': 'Gandaki', 'headquarters': 'Putalibazar'},
        {'name': 'Tanahun', 'province': 'Gandaki', 'headquarters': 'Damauli'},
        
        # Lumbini Province (12 districts)
        {'name': 'Arghakhanchi', 'province': 'Lumbini', 'headquarters': 'Sandhikharka'},
        {'name': 'Banke', 'province': 'Lumbini', 'headquarters': 'Nepalgunj'},
        {'name': 'Bardiya', 'province': 'Lumbini', 'headquarters': 'Gulariya'},
        {'name': 'Dang', 'province': 'Lumbini', 'headquarters': 'Ghorahi'},
        {'name': 'Eastern Rukum', 'province': 'Lumbini', 'headquarters': 'Rukumkot'},
        {'name': 'Gulmi', 'province': 'Lumbini', 'headquarters': 'Tamghas'},
        {'name': 'Kapilvastu', 'province': 'Lumbini', 'headquarters': 'Taulihawa'},
        {'name': 'Parasi', 'province': 'Lumbini', 'headquarters': 'Ramgram'},
        {'name': 'Palpa', 'province': 'Lumbini', 'headquarters': 'Tansen'},
        {'name': 'Pyuthan', 'province': 'Lumbini', 'headquarters': 'Pyuthan'},
        {'name': 'Rolpa', 'province': 'Lumbini', 'headquarters': 'Liwang'},
        {'name': 'Rupandehi', 'province': 'Lumbini', 'headquarters': 'Siddharthanagar'},
        
        # Karnali Province (10 districts)
        {'name': 'Dailekh', 'province': 'Karnali', 'headquarters': 'Dailekh'},
        {'name': 'Dolpa', 'province': 'Karnali', 'headquarters': 'Dunai'},
        {'name': 'Humla', 'province': 'Karnali', 'headquarters': 'Simikot'},
        {'name': 'Jajarkot', 'province': 'Karnali', 'headquarters': 'Khalanga'},
        {'name': 'Jumla', 'province': 'Karnali', 'headquarters': 'Jumla'},
        {'name': 'Kalikot', 'province': 'Karnali', 'headquarters': 'Manma'},
        {'name': 'Mugu', 'province': 'Karnali', 'headquarters': 'Gamgadhi'},
        {'name': 'Salyan', 'province': 'Karnali', 'headquarters': 'Salyan'},
        {'name': 'Surkhet', 'province': 'Karnali', 'headquarters': 'Birendranagar'},
        {'name': 'Western Rukum', 'province': 'Karnali', 'headquarters': 'Musikot'},
        
        # Sudurpashchim Province (9 districts)
        {'name': 'Achham', 'province': 'Sudurpashchim', 'headquarters': 'Mangalsen'},
        {'name': 'Baitadi', 'province': 'Sudurpashchim', 'headquarters': 'Baitadi'},
        {'name': 'Bajhang', 'province': 'Sudurpashchim', 'headquarters': 'Jayaprithvi'},
        {'name': 'Bajura', 'province': 'Sudurpashchim', 'headquarters': 'Martadi'},
        {'name': 'Dadeldhura', 'province': 'Sudurpashchim', 'headquarters': 'Dadeldhura'},
        {'name': 'Darchula', 'province': 'Sudurpashchim', 'headquarters': 'Darchula'},
        {'name': 'Doti', 'province': 'Sudurpashchim', 'headquarters': 'Doti'},
        {'name': 'Kailali', 'province': 'Sudurpashchim', 'headquarters': 'Dhangadhi'},
        {'name': 'Kanchanpur', 'province': 'Sudurpashchim', 'headquarters': 'Bhimdatta'},
    ]
    
    for district_data in districts:
        district = District(**district_data)
        db.session.add(district)
    
    db.session.commit()
    print(f"✅ Seeded {len(districts)} districts")

def seed_authorities():
    """Seed authorities for demo districts."""
    # Get Sindhuli district
    sindhuli = District.query.filter_by(name='Sindhuli').first()
    kathmandu = District.query.filter_by(name='Kathmandu').first()
    
    if sindhuli:
        authorities = [
            {
                'name': 'Sindhuli Road Division Office',
                'category': 'road',
                'district_id': sindhuli.id,
                'phone': '047-520123',
                'email': 'road.sindhuli@nepal.gov.np',
                'address': 'Kamalamai Municipality, Sindhuli',
                'office_hours': '10:00 AM - 5:00 PM'
            },
            {
                'name': 'Sindhuli District Police',
                'category': 'police',
                'district_id': sindhuli.id,
                'phone': '100',
                'email': 'police.sindhuli@nepal.gov.np',
                'address': 'Kamalamai, Sindhuli',
                'office_hours': '24/7'
            },
            {
                'name': 'Sindhuli Electricity Authority',
                'category': 'electricity',
                'district_id': sindhuli.id,
                'phone': '1912',
                'email': 'nea.sindhuli@nepal.gov.np',
                'address': 'Kamalamai, Sindhuli',
                'office_hours': '10:00 AM - 4:00 PM'
            },
            {
                'name': 'Sindhuli Water Supply Office',
                'category': 'water',
                'district_id': sindhuli.id,
                'phone': '047-520456',
                'email': 'water.sindhuli@nepal.gov.np',
                'address': 'Kamalamai, Sindhuli',
                'office_hours': '10:00 AM - 5:00 PM'
            },
            {
                'name': 'Sindhuli Health Office',
                'category': 'health',
                'district_id': sindhuli.id,
                'phone': '102',
                'email': 'health.sindhuli@nepal.gov.np',
                'address': 'Kamalamai, Sindhuli',
                'office_hours': '24/7'
            },
        ]
        
        for auth_data in authorities:
            authority = Authority(**auth_data)
            db.session.add(authority)
        
        print(f"✅ Seeded {len(authorities)} authorities for Sindhuli")
    
    if kathmandu:
        authorities = [
            {
                'name': 'Kathmandu Road Division Office',
                'category': 'road',
                'district_id': kathmandu.id,
                'phone': '01-4412345',
                'email': 'road.kathmandu@nepal.gov.np',
                'address': 'Babarmahal, Kathmandu',
                'office_hours': '10:00 AM - 5:00 PM'
            },
            {
                'name': 'Kathmandu Metropolitan Police',
                'category': 'police',
                'district_id': kathmandu.id,
                'phone': '100',
                'email': 'police.kathmandu@nepal.gov.np',
                'address': 'Ranipokhari, Kathmandu',
                'office_hours': '24/7'
            },
        ]
        
        for auth_data in authorities:
            authority = Authority(**auth_data)
            db.session.add(authority)
        
        print(f"✅ Seeded {len(authorities)} authorities for Kathmandu")
    
    db.session.commit()

def seed_roads():
    """Seed road segments for demo."""
    sindhuli = District.query.filter_by(name='Sindhuli').first()
    kathmandu = District.query.filter_by(name='Kathmandu').first()
    
    if sindhuli and kathmandu:
        roads = [
            {
                'name': 'BP Highway - Khurkot to Sindhuli',
                'highway': 'BP Highway',
                'district_id': sindhuli.id,
                'from_location': 'Khurkot',
                'to_location': 'Sindhuli',
                'distance_km': 45,
                'status': 'open',
                'traffic_level': 'low'
            },
            {
                'name': 'BP Highway - Sindhuli to Bardibas',
                'highway': 'BP Highway',
                'district_id': sindhuli.id,
                'from_location': 'Sindhuli',
                'to_location': 'Bardibas',
                'distance_km': 40,
                'status': 'open',
                'traffic_level': 'moderate'
            },
            {
                'name': 'BP Highway - Dhulikhel to Khurkot',
                'highway': 'BP Highway',
                'district_id': kathmandu.id,
                'from_location': 'Dhulikhel',
                'to_location': 'Khurkot',
                'distance_km': 50,
                'status': 'partial',
                'traffic_level': 'heavy'
            },
        ]
        
        for road_data in roads:
            road = RoadSegment(**road_data)
            db.session.add(road)
        
        print(f"✅ Seeded {len(roads)} road segments")
        db.session.commit()

def seed_rivers():
    """Seed rivers for demo districts."""
    sindhuli = District.query.filter_by(name='Sindhuli').first()
    kathmandu = District.query.filter_by(name='Kathmandu').first()
    
    if sindhuli:
        rivers = [
            {
                'name': 'Kamala River',
                'district_id': sindhuli.id,
                'current_level': 3.2,
                'danger_level': 4.0,
                'status': 'rising'
            },
            {
                'name': 'Sunkoshi River',
                'district_id': sindhuli.id,
                'current_level': 5.1,
                'danger_level': 7.0,
                'status': 'normal'
            },
        ]
        
        for river_data in rivers:
            river = River(**river_data)
            db.session.add(river)
        
        print(f"✅ Seeded {len(rivers)} rivers for Sindhuli")
    
    if kathmandu:
        rivers = [
            {
                'name': 'Bagmati River',
                'district_id': kathmandu.id,
                'current_level': 2.5,
                'danger_level': 3.5,
                'status': 'normal'
            },
        ]
        
        for river_data in rivers:
            river = River(**river_data)
            db.session.add(river)
        
        print(f"✅ Seeded {len(rivers)} rivers for Kathmandu")
    
    db.session.commit()

def seed_projects():
    """Seed demo projects."""
    sindhuli = District.query.filter_by(name='Sindhuli').first()
    
    if sindhuli:
        projects = [
            {
                'name': 'Kamala Bridge Construction',
                'district_id': sindhuli.id,
                'category': 'bridge',
                'description': 'Construction of new bridge over Kamala River',
                'location': 'Kamalamai Municipality',
                'total_budget': 25.0,
                'spent_budget': 16.25,
                'progress_percent': 65,
                'status': 'on_schedule',
                'contractor': 'XYZ Construction Company',
                'start_date': datetime(2024, 1, 1),
                'expected_completion': datetime(2024, 12, 31)
            },
            {
                'name': 'BP Highway Expansion',
                'district_id': sindhuli.id,
                'category': 'road',
                'description': 'Expansion of BP Highway section',
                'location': 'Khurkot to Sindhuli',
                'total_budget': 50.0,
                'spent_budget': 40.0,
                'progress_percent': 80,
                'status': 'on_schedule',
                'contractor': 'ABC Infrastructure',
                'start_date': datetime(2023, 6, 1),
                'expected_completion': datetime(2024, 6, 30)
            },
        ]
        
        for project_data in projects:
            project = Project(**project_data)
            db.session.add(project)
        
        print(f"✅ Seeded {len(projects)} projects for Sindhuli")
        db.session.commit()

def main():
    """Run all seed functions."""
    app = create_app()
    with app.app_context():
        print("\n🌱 Starting database seeding...\n")
        
        seed_districts()
        seed_authorities()
        seed_roads()
        seed_rivers()
        seed_projects()
        
        print("\n✅ Database seeding completed successfully!")
        print("\n📊 Summary:")
        print(f"  - Districts: {District.query.count()}")
        print(f"  - Authorities: {Authority.query.count()}")
        print(f"  - Road Segments: {RoadSegment.query.count()}")
        print(f"  - Rivers: {River.query.count()}")
        print(f"  - Projects: {Project.query.count()}")

if __name__ == '__main__':
    main()