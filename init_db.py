from app import create_app
from app.extensions import db
from app.models import (
    User, District, Post, Authority, Complaint, Project,
    RoadSegment, RoadUpdate, River, RiverUpdate, Incident,
    Comment, Like, Notification, Bridge, ProjectUpdate, AuthorityResponse
)

def init_database():
    """Initialize database with all tables."""
    app = create_app()
    with app.app_context():
        # Drop all tables (for clean start)
        db.drop_all()
        print("Dropped all existing tables")
        
        # Create all tables
        db.create_all()
        print("Created all tables successfully!")
        
        # Print created tables
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print("\nTables created:")
        for table in tables:
            print(f"  - {table}")

if __name__ == "__main__":
    init_database()