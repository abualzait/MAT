# MAT Architecture & Directory Structure

This document outlines the folder structure, core files, and deployment instructions for the MAT project.

## Directory Map

```
Amman Police Stations/
├── .env                       # Environment variables (e.g. MAT_PORT, MAT_SECRET_KEY)
├── server.py                  # Core Python backend (Zero-dependency custom HTTP server)
├── complaints.db              # SQLite Database (seeded automatically if not present)
├── mat_complaints.db          # Active SQLite Database
├── key.json                   # Google Service Account JSON key (for FCM push notifications)
├── app.html                   # Main application dashboard layout (Glassmorphism design)
├── index.html                 # Main entry point (Login routing)
├── login.html                 # User authentication view
├── Police_Station_Finder.html # GIS Interactive Map tool (Offline/Online Leaflet)
├── firebase-messaging-sw.js   # Service worker for FCM push notifications
├── amman_logo.png             # Application logo icon
├── .github/                   # GitHub Actions (if any)
├── mzt agent guide/           # Mandatory Agent Guidance Docs (rules.md, schema.md, etc.)
├── data/                      # Backup and raw database snapshots (`data_backup.json`)
├── tiles/                     # Offline leaflet map tiles directory
└── complaints/                # Additional complaint related views or assets
```

## Core Stack Overview
1. **Backend:** Python 3 standard library `http.server` & `sqlite3` (No external pip dependencies).
2. **Frontend:** Vanilla HTML5, CSS3 (Glassmorphism), Vanilla JavaScript.
3. **Storage:** SQLite 3 database (`mat_complaints.db`).
4. **Push Notifications:** Firebase Cloud Messaging (FCM v1 API via `server.py`).

## Setup & Boot Instructions

To run the project locally without Docker:

1. Ensure Python 3 is installed.
2. Create or verify `.env` file exists with:
   ```env
   MAT_PORT=5001
   MAT_HOST=0.0.0.0
   MAT_SECRET_KEY=your_secure_secret_key
   ```
3. Run the server from the terminal:
   ```bash
   python server.py
   ```
4. Access the portal at `http://localhost:5001`.

## Production Hosting & Deployment (Docker)

The project includes a `Dockerfile` and `docker-compose.yml` for containerized production hosting (and compatibility with cloud providers like Hugging Face Spaces).

### Using Docker Compose:
1. Simply run:
   ```bash
   docker-compose up -d --build
   ```
2. The service will map to port **8080** and run under a persistent volume `mat_data` to protect your `mat_complaints.db` and backups.

### Hugging Face / Cloud Deployment:
The Dockerfile is configured to expose ports `7860` (Hugging Face default) and `8080`. Ensure environment variables like `PORT` and `MAT_SECRET_KEY` are securely provided in your cloud hosting settings.
