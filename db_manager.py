from app import create_app
from app.extensions import db
from app.models.user import User
from sqlalchemy import inspect
import sys
import os
import sqlite3

def init_db():
    app = create_app()
    with app.app_context():
        db.create_all()
        print("Database initialized!")

def create_test_user():
    app = create_app()
    with app.app_context():
        user = User.query.filter_by(username="testuser").first()
        if user:
            print("Test user already exists")
        else:
            user = User(username="testuser", email="test@example.com")
            user.set_password("password123")
            db.session.add(user)
            db.session.commit()
            print("Test user created!")
            print("Username: testuser")
            print("Password: password123")

def list_users():
    app = create_app()
    with app.app_context():
        users = User.query.all()
        if users:
            print(f"Total users: {len(users)}")
            for u in users:
                print(f"  {u.id}. {u.username} - {u.email}")
        else:
            print("No users found")

def show_tables():
    app = create_app()
    with app.app_context():
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        if tables:
            print("Database tables:")
            for table in tables:
                print(f"  - {table}")
        else:
            print("No tables found")

def check_db():
    db_file = "instance/hackforge.db"
    if os.path.exists(db_file):
        size = os.path.getsize(db_file)
        print(f"Database file: {db_file}")
        print(f"Size: {size} bytes")
        
        conn = sqlite3.connect(db_file)
        cursor = conn.cursor()
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        print(f"Tables: {len(tables)}")
        for table in tables:
            print(f"  - {table[0]}")
        
        conn.close()
    else:
        print(f"Database file not found: {db_file}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "init":
            init_db()
        elif cmd == "create-user":
            create_test_user()
        elif cmd == "list":
            list_users()
        elif cmd == "tables":
            show_tables()
        elif cmd == "check":
            check_db()
        else:
            print("Commands: init, create-user, list, tables, check")
    else:
        print("Usage: python db_manager.py [init|create-user|list|tables|check]")