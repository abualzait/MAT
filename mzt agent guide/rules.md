# Project Rules & Development Guidelines — MAT (Amman Police Stations)

## Project Overview
- **Project Name:** MAT (Modular Assistant Toolkit) / Amman Police Stations & Administrative Support System
- **Current Version:** v1.45.3
- **Scope:** Digital assistance toolkit for Amman Governorate / Ministry of Interior (complaints management, appointment scheduling, file custody tracking, live chat, area search, and police station GIS finder).

## Core Rules & Conventions
1. **Workspace Scope & Isolation:**
   - Work strictly within `c:\Users\Abual\AntiGravity Workspace\Amman Police Stations`.
   - Never modify parallel workspace projects unless explicitly directed.

2. **Automatic Project Version Incrementation & Syncing:**
   - Maintain active project version `v1.45.3` across all documentation (`README.md`), UI version badges (`app.html`, `login.html`, `index.html`), and station finder (`Police_Station_Finder.html`).
   - Automatically increment version numbers on every structural or feature modification.

3. **Naming Conventions (`mat` Standard):**
   - **Database Tables & Indexes:** Prefix all SQLite tables with `mat_` (e.g., `mat_complaints`, `mat_officers`, `mat_appointments`, `mat_reserved_files`, `mat_chat_messages`). Indexes must start with `idx_mat_`.
   - **API Endpoints:** Prefix all microservice routes with `/api/v1/mat/` (e.g., `/api/v1/mat/login`, `/api/v1/mat/complaints`, `/api/v1/mat/appointments`).
   - **Environment Variables:** Upper-case `MAT_*` keys in `.env` (e.g. `MAT_PORT=5001`, `MAT_SECRET_KEY`).

4. **Zero-Dependency Core Stack:**
   - Lightweight Python web server (`server.py`) using standard libraries (`http.server`, `sqlite3`, `json`, `hashlib`).
   - Vanilla HTML, JS, CSS frontend with responsive mobile-first architecture and glassmorphic UI elements.
