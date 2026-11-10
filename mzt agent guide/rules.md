# Project Rules & Development Guidelines — MAT (Amman Police Stations)

## Project Overview
- **Project Name:** MAT (Modular Assistant Toolkit) / Amman Police Stations & Administrative Support System
- **Current Version:** v1.46.0
- **Scope:** Digital assistance toolkit for Amman Governorate / Ministry of Interior (Smart Police Complaints & Governor Workflow, Vision LLM document extraction, appointment scheduling, file custody tracking, live chat, area search, and police station GIS finder).

## Core Rules & Conventions
1. **Workspace Scope & Isolation:**
   - Work strictly within `c:\Users\Abual\AntiGravity Workspace\Amman Police Stations`.
   - Never modify parallel workspace projects unless explicitly directed.

2. **Automatic Project Version Incrementation & Syncing:**
   - Maintain active project version `v1.46.0` across all documentation (`README.md`, `mzt agent guide/*.md`), backend banner (`server.py`), UI version badges (`complaints/app.html`, `complaints/login.html`, `index.html`), script/iframe cache-busting query strings (`complaints/js/app.js`, `complaints/js/police_complaints.js`), and station finder (`Police_Station_Finder.html`).
   - Automatically increment version numbers on every structural or feature modification.

3. **Naming Conventions (`mat` Standard):**
   - **Database Tables & Indexes:** Prefix all SQLite tables with `mat_` (e.g., `mat_complaints`, `mat_complaint_scans`, `mat_complaint_workflow_log`, `mat_llm_settings`, `mat_officers`, `mat_appointments`, `mat_reserved_files`, `mat_chat_messages`). New indexes must start with `idx_mat_`.
   - **API Endpoints:** Prefix all microservice routes with `/api/v1/mat/` (e.g., `/api/v1/mat/login`, `/api/v1/mat/police-complaints`, `/api/v1/mat/llm-settings`, `/api/v1/mat/appointments`).
   - **Environment Variables:** Upper-case `MAT_*` keys in `.env`:
     - Core: `MAT_ENV`, `MAT_PORT`, `MAT_HOST`, `MAT_DB_PATH`, `MAT_API_PREFIX`, `MAT_SECRET_KEY`, `PORT`
     - Complaint Scans: `MAT_SCANS_DIR` (defaults to `data/complaint_scans` relative to `BASE_DIR`)
     - AI Vision Engine (`mat_llm_engine.py`): `MAT_LLM_PROVIDER` (`gemini`|`openai`|`ollama`), `MAT_LLM_MODEL`, `MAT_GEMINI_API_KEY`, `MAT_OPENAI_API_KEY`, `MAT_OPENAI_BASE_URL`, `MAT_OLLAMA_URL`

4. **Roles & Tool Slugs (RBAC):**
   - **Valid Roles in `mat_officers.role`:** `'admin'`, `'officer'`, `'caller'`, `'governor'`.
     - `admin` (رئيس القسم): Full administrative privileges, LLM configuration, user permissions, and exclusive Section Head Referral (`تنسيب رئيس القسم`).
     - `officer` (ضابط): Complaint intake/scanning, editing pre-closure complaints, officer actions (`نظر الضابط`), execution updates, and follow-up logging.
     - `caller` (ضابط اتصال): Appointment scheduling and call follow-up; in Smart Police Complaints, visibility is restricted to complaints where `governor_final_action = 'اتصال هاتفي'` or `linked_appointment_id IS NOT NULL` (scan intake/export/edit forbidden).
     - `governor` (الحاكم الإداري / عطوفة المتصرف): Lands directly on `#tab-police-complaints`; holds exclusive authority for `/api/v1/mat/police-complaints/{id}/governor-decision` (`موافقة`, `رفض`, `تغيير_الإجراء`) and follow-up/90-day stop override; cannot modify complaint details or create intake drafts.
   - **Accessible Tool Slugs (`accessible_tools`):**
     - `dashboard` — لوحة التحكم والملخص
     - `police_complaints` — الشكاوى الأمنية الذكية (`#tab-police-complaints`)
     - `mat_complaints` / `complaints` — نظام المواعيد
     - `finder` / `stations` — دليل المراكز الأمنية
     - `file_reservations` / `reservations` — أداة حجز الملفات
     - `chat` — غرفة الاجتماعات
     - `admin_permissions` — الصلاحيات المتقدمة

5. **Zero-Dependency Core Stack & Security Hygiene:**
   - Lightweight Python 3 web server (`server.py`, `mat_llm_engine.py`, `mat_complaints_service.py`) using ONLY Python standard libraries (`http.server`, `sqlite3`, `json`, `hashlib`, `zipfile`, `xml.etree.ElementTree`, `urllib.request`, `email.parser`, `tempfile`).
   - Vanilla HTML, JS, CSS frontend (`complaints/app.html`, `complaints/js/police_complaints.js`, `complaints/js/app.js`, `complaints/css/design-system.css`).
   - **Security Rules:**
     - All state-changing API requests (`POST`, `PUT`, `DELETE` except `/api/v1/mat/login`) enforce `X-CSRF-Token` Double Submit Cookie validation (`csrf_token`).
     - Session cookies are `HttpOnly; SameSite=Lax; Path=/`.
     - Security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`) are attached to every response; directory listing is disabled (`403`).
     - `data/complaint_scans/`, `tests/`, `scratch/`, `docs/`, `mzt agent guide/`, `.env`, `key.json`, `data_backup.json`, `*.db`, `*.py`, and dotfiles are strictly blocked from static HTTP serving (`403`).
     - `complaints/js/police_complaints.js` uses strictly XSS-safe DOM builders (`createElement`, `textContent`, `replaceChildren`) with zero raw HTML string injection and zero native browser `alert`/`confirm`/`prompt` dialogs.
     - Never leak or echo raw LLM API keys in logs, error strings, or HTTP responses (`_mask_api_key`, `_redact_secret`).
     - Keep `data/complaint_scans/` ignored in `.gitignore` and never commit runtime DBs (`*.db`) or secrets (`.env`, `key.json`). Always track `complaint_form_editable.docx` as a required runtime template.
