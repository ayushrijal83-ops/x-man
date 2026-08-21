# -*- coding: utf-8 -*-
"""Comprehensive Nepal seed data: highways, river systems, gauge readings.

Used by import_nepal_data.py as the fallback (and as the structural backbone
that OSM data is merged onto -- OSM has road/river names but no status,
traffic level, or water level, so those come from here).
"""

# ---------------------------------------------------------------------------
# HIGHWAYS
# Each entry: (district, from_location, to_location, distance_km, status, traffic)
# Districts must match District.name exactly.
# ---------------------------------------------------------------------------
HIGHWAYS = {
    'Mahendra Highway': {
        'ref': 'NH01', 'total_km': 1027,
        'note': 'East-West Highway, Nepal\'s longest',
        'segments': [
            ('Jhapa',       'Kakarbhitta',  'Damak',        58,  'open',     'moderate'),
            ('Morang',      'Damak',        'Biratnagar',   52,  'open',     'heavy'),
            ('Sunsari',     'Itahari',      'Inaruwa',      31,  'open',     'heavy'),
            ('Saptari',     'Kanchanrup',   'Rajbiraj',     40,  'open',     'moderate'),
            ('Siraha',      'Lahan',        'Mirchaiya',    27,  'open',     'moderate'),
            ('Dhanusha',    'Dhalkebar',    'Janakpur',     35,  'open',     'heavy'),
            ('Mahottari',   'Bardibas',     'Jaleshwar',    42,  'open',     'moderate'),
            ('Sarlahi',     'Lalbandi',     'Malangwa',     38,  'open',     'moderate'),
            ('Rautahat',    'Chandranigahapur', 'Gaur',     45,  'open',     'moderate'),
            ('Bara',        'Nijgadh',      'Kalaiya',      44,  'open',     'heavy'),
            ('Parsa',       'Pathlaiya',    'Birgunj',      32,  'open',     'severe'),
            ('Chitwan',     'Bharatpur',    'Narayangadh',  28,  'open',     'heavy'),
            ('Nawalpur',    'Kawasoti',     'Gaindakot',    36,  'open',     'moderate'),
            ('Parasi',      'Bardaghat',    'Ramgram',      30,  'open',     'moderate'),
            ('Rupandehi',   'Butwal',       'Bhairahawa',   22,  'open',     'severe'),
            ('Kapilvastu',  'Chandrauta',   'Taulihawa',    38,  'open',     'low'),
            ('Dang',        'Lamahi',       'Ghorahi',      40,  'open',     'moderate'),
            ('Banke',       'Kohalpur',     'Nepalgunj',    16,  'open',     'heavy'),
            ('Bardiya',     'Gulariya',     'Rajapur',      35,  'open',     'low'),
            ('Kailali',     'Lamki',        'Dhangadhi',    48,  'open',     'moderate'),
            ('Kanchanpur',  'Attariya',     'Mahendranagar', 30, 'open',     'moderate'),
        ],
    },
    'Prithvi Highway': {
        'ref': 'NH04', 'total_km': 174,
        'note': 'Kathmandu to Pokhara',
        'segments': [
            ('Kathmandu',   'Kalanki',      'Naubise',      26,  'open',     'severe'),
            ('Dhading',     'Naubise',      'Malekhu',      42,  'partial',  'heavy'),
            ('Chitwan',     'Mugling',      'Ghumaune',     33,  'open',     'heavy'),
            ('Tanahun',     'Ghumaune',     'Damauli',      38,  'open',     'moderate'),
            ('Kaski',       'Damauli',      'Pokhara',      35,  'open',     'heavy'),
        ],
    },
    'BP Highway': {
        'ref': 'NH13', 'total_km': 158,
        'note': 'Banepa-Bardibas, shortest Kathmandu-Terai link',
        'segments': [
            ('Kavrepalanchok', 'Banepa',    'Dhulikhel',    5,   'open',     'moderate'),
            ('Kavrepalanchok', 'Dhulikhel', 'Khurkot',      52,  'partial',  'moderate'),
            ('Sindhuli',    'Khurkot',      'Sindhulimadi', 42,  'open',     'low'),
            ('Sindhuli',    'Sindhulimadi', 'Bardibas',     59,  'open',     'moderate'),
        ],
    },
    'Araniko Highway': {
        'ref': 'NH03', 'total_km': 115,
        'note': 'Kathmandu to the Tibet border at Kodari',
        'segments': [
            ('Bhaktapur',   'Kathmandu',    'Bhaktapur',    13,  'open',     'severe'),
            ('Kavrepalanchok', 'Bhaktapur', 'Dhulikhel',    17,  'open',     'heavy'),
            ('Sindhupalchok', 'Dhulikhel',  'Barhabise',    52,  'partial',  'moderate'),
            ('Sindhupalchok', 'Barhabise',  'Kodari',       33,  'restricted', 'low'),
        ],
    },
    'Tribhuvan Highway': {
        'ref': 'NH02', 'total_km': 189,
        'note': 'Nepal\'s first highway, Kathmandu to Birgunj',
        'segments': [
            ('Kathmandu',   'Kathmandu',    'Thankot',      12,  'open',     'heavy'),
            ('Makwanpur',   'Naubise',      'Hetauda',      86,  'partial',  'moderate'),
            ('Makwanpur',   'Hetauda',      'Pathlaiya',    27,  'open',     'heavy'),
            ('Parsa',       'Pathlaiya',    'Birgunj',      32,  'open',     'severe'),
        ],
    },
    'Karnali Highway': {
        'ref': 'NH11', 'total_km': 232,
        'note': 'Surkhet to Jumla, Nepal\'s most difficult highway',
        'segments': [
            ('Surkhet',     'Birendranagar', 'Bhalubang',   48,  'open',     'low'),
            ('Dailekh',     'Bhalubang',    'Dailekh',      55,  'partial',  'low'),
            ('Kalikot',     'Dailekh',      'Manma',        72,  'restricted', 'low'),
            ('Jumla',       'Manma',        'Khalanga',     57,  'partial',  'low'),
        ],
    },
    'Siddhartha Highway': {
        'ref': 'NH10', 'total_km': 182,
        'note': 'Sunauli border to Pokhara',
        'segments': [
            ('Rupandehi',   'Bhairahawa',   'Butwal',       22,  'open',     'heavy'),
            ('Palpa',       'Butwal',       'Tansen',       58,  'partial',  'moderate'),
            ('Syangja',     'Tansen',       'Waling',       52,  'open',     'moderate'),
            ('Kaski',       'Waling',       'Pokhara',      50,  'open',     'moderate'),
        ],
    },
    'Koshi Highway': {
        'ref': 'NH06', 'total_km': 115,
        'note': 'Biratnagar to Hile',
        'segments': [
            ('Morang',      'Biratnagar',   'Itahari',      22,  'open',     'heavy'),
            ('Sunsari',     'Itahari',      'Dharan',       16,  'open',     'heavy'),
            ('Dhankuta',    'Dharan',       'Dhankuta',     54,  'open',     'moderate'),
            ('Dhankuta',    'Dhankuta',     'Hile',         23,  'open',     'low'),
        ],
    },
    'Mid-Hill Highway': {
        'ref': 'NH08', 'total_km': 1776,
        'note': 'Pushpalal Highway, under construction',
        'segments': [
            ('Panchthar',   'Chiyo Bhanjyang', 'Phidim',    45,  'partial',  'low'),
            ('Terhathum',   'Phidim',       'Myanglung',    52,  'partial',  'low'),
            ('Okhaldhunga', 'Ghurmi',       'Okhaldhunga',  48,  'partial',  'low'),
            ('Baglung',     'Kusma',        'Baglung',      36,  'open',     'low'),
            ('Surkhet',     'Chinchu',      'Birendranagar', 42, 'open',     'moderate'),
            ('Dadeldhura',  'Dadeldhura',   'Doti',         55,  'partial',  'low'),
        ],
    },
    'Madan Bhandari Highway': {
        'ref': 'NH07', 'total_km': 300,
        'note': 'Under construction',
        'segments': [
            ('Udayapur',    'Gaighat',      'Chatara',      44,  'partial',  'low'),
            ('Sunsari',     'Chatara',      'Shantinagar',  38,  'partial',  'low'),
        ],
    },
}

# ---------------------------------------------------------------------------
# RIVER SYSTEMS -- which districts each river runs through
# ---------------------------------------------------------------------------
RIVER_SYSTEMS = {
    'Koshi': {
        'Sunkoshi':   ['Sindhupalchok', 'Kavrepalanchok', 'Ramechhap', 'Sindhuli'],
        'Arun':       ['Sankhuwasabha', 'Bhojpur', 'Dhankuta'],
        'Tamor':      ['Taplejung', 'Panchthar', 'Terhathum'],
        'Dudhkoshi':  ['Solukhumbu', 'Okhaldhunga', 'Khotang'],
        'Likhu':      ['Ramechhap', 'Okhaldhunga'],
        'Indrawati':  ['Sindhupalchok', 'Kavrepalanchok'],
        'Saptakoshi': ['Sunsari', 'Saptari', 'Udayapur'],
    },
    'Gandaki': {
        'Kali Gandaki':  ['Mustang', 'Myagdi', 'Parbat', 'Syangja'],
        'Seti Gandaki':  ['Kaski', 'Tanahun'],
        'Marsyangdi':    ['Manang', 'Lamjung', 'Gorkha', 'Tanahun'],
        'Trishuli':      ['Rasuwa', 'Nuwakot', 'Dhading', 'Chitwan'],
        'Budhi Gandaki': ['Gorkha', 'Dhading'],
        'Daraudi':       ['Gorkha'],
        'Narayani':      ['Chitwan', 'Nawalpur', 'Parasi'],
    },
    'Karnali': {
        'Karnali':     ['Humla', 'Mugu', 'Dolpa', 'Jumla', 'Kalikot'],
        'Bheri':       ['Dolpa', 'Jajarkot', 'Surkhet'],
        'Seti':        ['Bajhang', 'Doti', 'Kailali'],
        'Thuli Bheri': ['Dolpa'],
        'Sani Bheri':  ['Western Rukum', 'Eastern Rukum', 'Jajarkot'],
    },
    'Bagmati': {
        'Bagmati':    ['Kathmandu', 'Lalitpur', 'Makwanpur', 'Sarlahi', 'Sindhuli'],
        'Bishnumati': ['Kathmandu'],
        'Manohara':   ['Kathmandu', 'Bhaktapur'],
        'Nakkhu':     ['Lalitpur'],
        'Hanumante':  ['Bhaktapur'],
    },
    'Other': {
        'Kamala':   ['Sindhuli', 'Dhanusha', 'Siraha'],
        'Kankai':   ['Ilam', 'Jhapa'],
        'Mahakali': ['Darchula', 'Baitadi', 'Kanchanpur'],
        'Mechi':    ['Taplejung', 'Ilam', 'Jhapa'],
        'Rapti':    ['Dang', 'Banke', 'Chitwan'],
        'Babai':    ['Dang', 'Bardiya'],
        'Mardi':    ['Kaski'],
        'West Rapti': ['Pyuthan', 'Rolpa', 'Banke'],
    },
}

# ---------------------------------------------------------------------------
# GAUGE READINGS -- (district, river): (current_level_m, danger_level_m)
#
# NOT from an API. DHM Nepal (dhm.gov.np / hydrology.gov.np) publishes real
# readings but exposes no reachable JSON endpoint, and OpenStreetMap carries
# no water-level tags at all. These are representative demo figures.
# ---------------------------------------------------------------------------
GAUGE_READINGS = {
    ('Sindhuli', 'Kamala'):      (3.2, 4.0),
    ('Sindhuli', 'Sunkoshi'):    (5.1, 7.0),
    ('Sindhuli', 'Bagmati'):     (3.0, 5.5),
    ('Kathmandu', 'Bagmati'):    (2.5, 3.5),
    ('Kathmandu', 'Bishnumati'): (1.8, 3.0),
    ('Kathmandu', 'Manohara'):   (1.2, 2.5),
    ('Lalitpur', 'Bagmati'):     (2.5, 3.5),
    ('Lalitpur', 'Nakkhu'):      (1.0, 2.0),
    ('Bhaktapur', 'Hanumante'):  (1.0, 2.0),
    ('Chitwan', 'Narayani'):     (6.5, 9.0),
    ('Chitwan', 'Rapti'):        (4.0, 6.0),
    ('Kaski', 'Seti Gandaki'):   (2.5, 4.0),
    ('Kaski', 'Mardi'):          (1.5, 3.0),
    ('Dhanusha', 'Kamala'):      (3.8, 4.5),
    ('Siraha', 'Kamala'):        (3.4, 4.5),
    ('Jhapa', 'Kankai'):         (2.9, 4.5),
    ('Sunsari', 'Saptakoshi'):   (6.2, 8.5),
    ('Saptari', 'Saptakoshi'):   (6.8, 8.5),
    ('Banke', 'Rapti'):          (4.4, 6.5),
    ('Bardiya', 'Babai'):        (3.6, 5.5),
    ('Kanchanpur', 'Mahakali'):  (5.0, 7.5),
    ('Kailali', 'Seti'):         (4.2, 6.0),
}

# default (current, danger) for a river with no specific gauge reading
DEFAULT_GAUGE = (2.0, 4.0)


def level_status(current, danger):
    """Derive river status from how close the level is to the danger mark."""
    if current is None or danger is None or danger <= 0:
        return 'unknown'
    pct = current / danger
    if pct >= 1.0:
        return 'flooding'
    if pct >= 0.80:
        return 'rising'
    return 'normal'


def iter_rivers():
    """Yield (river_name, basin, district_name, current, danger, status)."""
    for basin, rivers in RIVER_SYSTEMS.items():
        for river, districts in rivers.items():
            for district in districts:
                cur, dang = GAUGE_READINGS.get((district, river), DEFAULT_GAUGE)
                yield river, basin, district, cur, dang, level_status(cur, dang)


def iter_road_segments():
    """Yield (name, highway, district, frm, to, km, status, traffic)."""
    for highway, meta in HIGHWAYS.items():
        for district, frm, to, km, status, traffic in meta['segments']:
            yield ('%s - %s to %s' % (highway, frm, to),
                   highway, district, frm, to, km, status, traffic)


if __name__ == '__main__':
    roads = list(iter_road_segments())
    rivers = list(iter_rivers())
    print('highways: %d, segments: %d' % (len(HIGHWAYS), len(roads)))
    print('rivers: %d entries across %d districts'
          % (len(rivers), len({r[2] for r in rivers})))
    print('gauge readings: %d' % len(GAUGE_READINGS))
