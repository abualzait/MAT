# MAT Architecture & Directory Structure

This document outlines the folder structure, core modules, environment configuration, and deployment instructions for the MAT project (`v1.46.5`).

## Directory Map

```text
Amman Police Stations/
├── .env                           # Local environment variables (gitignored)
├── .env.example                   # Sample environment variables template
├── .gitignore                     # Ignores DBs, secrets, tiles, scratch/, data/complaint_scans/
├── Dockerfile                     # Container image definition (Python 3.11-slim, ports 7860 & 8080)
├── docker-compose.yml             # Local/prod container orchestration with persistent mat_data volume
├── server.py                      # Core Python HTTP server (MatServerHandler, RBAC, CSRF, DB migrations, FCM)
├── mat_llm_engine.py              # Multi-provider Vision LLM OCR & analysis engine (Gemini, OpenAI, Ollama)
├── mat_complaints_service.py      # Smart Police Complaints service (scan storage, GIS matching, 90d rule, DOCX export)
├── complaint_form_editable.docx   # Official Arabic Ministry/Governorate Word template used for .docx export
├── complaints.db                  # Seed SQLite database (gitignored)
├── mat_complaints.db              # Active runtime SQLite database (gitignored)
├── data_backup.json               # Continuous JSON state snapshot for container restart recovery (gitignored)
├── key.json                       # Google Service Account JSON key for FCM push notifications (gitignored)
├── index.html                     # Portal landing & redirect page (v1.46.5)
├── Police_Station_Finder.html     # GIS Interactive Map tool (Offline/Online Leaflet, 9 Liwas, 8,750+ POIs)
├── firebase-messaging-sw.js       # Service worker for FCM push notifications
├── amman_logo.png                 # Official governorate emblem
├── leaflet.css / leaflet.js       # Bundled Leaflet assets for offline use
├── mzt agent guide/               # Mandatory Agent Guidance Docs (rules, dictionary, features, schema, architecture, api)
├── complaints/
│   ├── app.html                   # Main dashboard shell, Smart Police Complaints tab, Governor & LLM modals (v1.46.5)
│   ├── login.html                 # User avatar quick-login & secret code portal (including governor avatar)
│   ├── css/
│   │   └── design-system.css      # Civic Horizon glassmorphic styling, Police Complaints layout, & print CSS (?v=26)
│   └── js/
│       ├── app.js                 # Core navigation, RBAC sidebar builder, appointments, reservations, chat (?v=1.46.5)
│       ├── police_complaints.js   # XSS-safe Smart Police Complaints UI, OCR intake, workflow panels (?v=1.46.5)
│       └── map.js                 # Dashboard map helper integration
├── data/
│   ├── amman_areas.json           # 597+ Amman areas mapped to nearest police stations, directorates, & Liwas
│   ├── amman_liwas.geojson        # GeoJSON boundary polygons for the 9 Liwas of Amman Governorate
│   └── complaint_scans/           # Runtime storage for UUID-named uploaded scans (gitignored & HTTP-blocked)
├── tiles/                         # Offline Leaflet map tiles (gitignored)
└── tests/
    ├── test_police_complaints.py      # Unit & service tests (utilities, LLM engine, workflow, DB migrations)
    └── test_police_complaints_api.py  # Live HTTP integration tests (RBAC, CSRF, uploads, headers, FCM, LLM API)
```

## Core Stack Overview
1. **Backend:** Python 3 standard library only (`http.server`, `socketserver`, `sqlite3`, `json`, `hashlib`, `urllib.request`, `zipfile`, `xml.etree.ElementTree`, `email.parser`, `tempfile`) — zero external `pip` dependencies.
2. **Frontend:** Vanilla HTML5, CSS3 (`design-system.css?v=26`), Vanilla ES6 JavaScript (`police_complaints.js?v=1.46.5`, `app.js?v=1.46.5`).
3. **Storage & Media:** SQLite 3 in WAL mode (`mat_complaints.db` / `MAT_DB_PATH`) + atomic UUID scan file storage (`MAT_SCANS_DIR`, default `data/complaint_scans/`) + official `.docx` template (`complaint_form_editable.docx`).
4. **AI Vision & Notifications:** Multi-provider REST Vision LLM client (`mat_llm_engine.py`) + Firebase Cloud Messaging v1 (`server.py`).

## Security & Path Isolation Boundaries
- `_normalize_url_path()` and `_is_blocked_static_path()` in `server.py` strip query/fragment strings, block `//`, `/\`, `..`, null bytes, dotfiles (`.env`, `.git`, `.superpowers`), `data/complaint_scans/`, `tests/`, `scratch/`, `docs/`, `mzt agent guide/`, `key.json`, `data_backup.json`, `*.db`, and `*.py` from static HTTP access (`403`).
- Uploaded scans are only served via authenticated, role-gated `GET /api/v1/mat/police-complaints/scans/{scan_id}` using `resolve_scan_path()` confinement checks and `Cache-Control: no-store`.
- All responses attach `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN`.

## Environment Variables (`MAT_*`)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `MAT_ENV` | `production` | Runtime environment identifier |
| `PORT` / `MAT_PORT` | `5001` | Listening HTTP port (`PORT` takes precedence for Cloud Run / HF Spaces) |
| `MAT_HOST` | `0.0.0.0` | Bind address |
| `MAT_DB_PATH` | `mat_complaints.db` | SQLite database file path (seeded from `complaints.db` if missing) |
| `MAT_API_PREFIX` | `/api/v1/mat` | API base prefix |
| `MAT_SECRET_KEY` | `mat_secret_key_2026` | Emergency admin secret key verification |
| `MAT_SCANS_DIR` | `data/complaint_scans` | Directory for validated scan images & PDFs |
| `MAT_LLM_PROVIDER` | `gemini` | Default fallback Vision LLM provider (`gemini`, `openai`, `ollama`) |
| `MAT_LLM_MODEL` | *(provider default)* | Default fallback model (`gemini-2.5-flash`, `gpt-4o`, `llama3.2-vision`) |
| `MAT_GEMINI_API_KEY` | `""` | Env fallback API key for Google Gemini |
| `MAT_OPENAI_API_KEY` | `""` | Env fallback API key for OpenAI |
| `MAT_OPENAI_BASE_URL` | `""` | Custom OpenAI-compatible base URL |
| `MAT_OLLAMA_URL` | `http://localhost:11434` | Ollama server base URL |

## Setup, Testing & Deployment

### Local Development
1. Ensure Python 3.8+ is installed.
2. Configure `.env` (see `.env.example` and table above).
3. Start the server:
   ```bash
   python server.py
   ```
4. Access the portal at `http://localhost:5001`.

### Verification Suite
Run all unit & live HTTP integration tests:
```bash
python -m unittest discover -s tests -v
```

### Docker / Cloud Deployment
- **Docker Compose:** `docker-compose up -d --build` maps port `8080` and mounts persistent volume `mat_data:/data`.
- **Cloud Hosting (Cloud Run / Hugging Face Spaces):** `Dockerfile` exposes `7860` and `8080` and runs `python server.py`. Ensure `MAT_SECRET_KEY`, `MAT_DB_PATH` / `/data` persistence, `MAT_SCANS_DIR`, and any LLM API keys are configured via container environment secrets.
