# HackForge

Reusable hackathon development foundation with Flask backend, responsive frontend, and local LLM support.

## Quick Start

1. Clone repository
2. Create virtual environment: python -m venv venv
3. Activate: venv\Scripts\activate (Windows) or source venv/bin/activate (Mac/Linux)
4. Install: pip install -r requirements.txt
5. Setup: copy .env.example to .env
6. Initialize DB: flask db init && flask db migrate && flask db upgrade
7. Run: python run.py

## Features

- Flask application factory pattern
- Authentication (register, login, logout)
- SQLAlchemy database
- Responsive CSS
- Health check endpoint
- AI service ready
- Security headers
- CSRF protection

## Documentation

See docs/ folder for detailed documentation.