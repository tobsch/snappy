#!/usr/bin/env python3
"""Multiroom Audio Web Interface - FastAPI Application"""

from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from routers import pages, api

# Paths
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
PROJECT_DIR = BASE_DIR.parent
CONFIG_FILE = PROJECT_DIR / "speaker_config.json"

# App setup
app = FastAPI(title="Multiroom Audio", version="1.0.0")

# Static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Share templates and config path with routers
app.state.templates = templates
app.state.config_file = CONFIG_FILE
app.state.project_dir = PROJECT_DIR

# Include routers
app.include_router(pages.router)
app.include_router(api.router, prefix="/api")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
