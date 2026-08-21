# \# CLAUDE.md - NepalSathi Development Guide

# 

# \## Project Overview

# NepalSathi is an AI-powered district intelligence platform for Nepal. It connects citizens, travelers, and government authorities through roads, rivers, projects, and community information.

# 

# \## Tech Stack

# \- Flask + SQLAlchemy + SQLite

# \- Jinja2 Templates

# \- Vanilla JS + CSS

# \- Ollama (local LLM) - optional

# 

# \## Current Status

# \- 17 database models created

# \- 77 districts seeded

# \- All core routes working

# \- Templates complete

# \- AI service has fallback (Ollama optional)

# 

# \## Key Files

# \- `app/\_\_init\_\_.py` - Application factory

# \- `app/models/` - Database models

# \- `app/routes/` - Route handlers

# \- `app/services/ai\_service.py` - AI integration

# \- `app/templates/` - HTML templates

# \- `init\_db.py` - Reset database

# \- `seed\_data.py` - Seed districts

# \- `add\_demo\_data.py` - Add demo content

# 

# \## Database Reset

# ```bash

# python init\_db.py

# python seed\_data.py

# python add\_demo\_data.py

