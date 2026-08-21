# CLAUDE.md - HackForge Development Guide

## CRITICAL RULES

1. READ THIS FILE COMPLETELY before starting any work
2. CHECK docs/PROJECT_PROGRESS.md for current project state
3. REUSE existing components - Do NOT rebuild navigation, cards, forms
4. FOLLOW the existing architecture
5. RUN TESTS after implementation: pytest tests/
6. UPDATE docs/PROJECT_PROGRESS.md before stopping
7. DO NOT expose secrets - Use .env file
8. DO NOT add dependencies without justification
9. USE Git branches - Never work directly on main
10. COMMIT frequently with descriptive messages

## Architecture Summary

- Stack: Flask + SQLAlchemy + Jinja2 + Vanilla JS
- AI: Ollama (local) with cloud fallback
- Frontend: Server-rendered with reusable components
- Database: SQLite (dev) / PostgreSQL (production)
- Authentication: Flask-Login with password hashing

## Key Directories

app/models/          - Database models
app/routes/          - Route handlers
app/services/        - Business logic
app/templates/       - Jinja2 templates
app/static/          - Static files (CSS, JS)
docs/                - Documentation
tests/               - Test files