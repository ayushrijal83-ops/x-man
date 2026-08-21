from flask import Blueprint, jsonify, request, render_template
from flask_login import login_required
from app.services.nepal_geo_service import NepalGeoService

geo_bp = Blueprint('geo', __name__)
geo_service = NepalGeoService()

@geo_bp.route('/test')
@login_required
def test_geo():
    """Test geo service page."""
    return render_template('pages/geo_test.html')

@geo_bp.route('/districts')
@login_required
def get_districts():
    """Get all districts from OSM."""
    districts = geo_service.get_all_district_boundaries()
    return jsonify(districts)

@geo_bp.route('/roads/<district_name>')
@login_required
def get_roads(district_name):
    """Get roads in a district."""
    roads = geo_service.get_roads_in_district(district_name)
    return jsonify(roads)

@geo_bp.route('/rivers/<district_name>')
@login_required
def get_rivers(district_name):
    """Get rivers in a district."""
    rivers = geo_service.get_rivers_in_district(district_name)
    return jsonify(rivers)

@geo_bp.route('/search')
@login_required
def search_location():
    """Search for a location."""
    query = request.args.get('q', '')
    if query:
        results = geo_service.search_location(query)
        return jsonify(results)
    return jsonify({'error': 'Query required'})

@geo_bp.route('/highways')
@login_required
def get_highways():
    """Get major highways."""
    highways = geo_service.get_major_highways()
    return jsonify(highways)