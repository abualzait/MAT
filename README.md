# MAT — حقيبة الأدوات المساعدة
### Modular Assistant Toolkit

> **Official Arabic Name:** "حقيبة الأدوات المساعدة"  
> **Full Acronym Definition:** Modular Assistant Toolkit  
> **Project Version:** 1.46.14  
> **Official Short URL:** [https://abualzait.github.io/MAT](https://abualzait.github.io/MAT)  
> **Google Cloud Run Live URL:** [https://mat-toolkit-436287854556.europe-west1.run.app](https://mat-toolkit-436287854556.europe-west1.run.app)  
> **Cloud Secret Key:** `mat_secret_key_2026_prod`

---

## 💾 Volume Persistence & Storage
The application includes automatic persistent volume support (`/data`) to prevent data loss across container restarts:
- **Docker Compose:** Run `docker compose up -d` (uses the `mat_data` volume).
- **Docker CLI:** Run `docker run -d -p 8080:8080 -v mat_data:/data mat_toolkit`
- **Auto JSON Backup:** Database state is continuously saved to `data_backup.json` and restored on startup.
- **Complaint Scan Storage:** Uploaded complaint documents (`JPG`, `PNG`, `WEBP`, `PDF`) are validated via magic bytes and stored with UUID filenames inside `MAT_SCANS_DIR` (defaults to `data/complaint_scans/`), protected against direct unauthenticated static access.

## 📋 Overview & Strategic Vision

**MAT (Modular Assistant Toolkit)** is a highly scalable, modular digital workspace designed for governorate departments and official administrative support, built to dynamically accommodate custom tools, specialized departmental screens, and future horizontal expansion under the Ministry of Interior.

It operates seamlessly in offline and local network environments with zero external dependencies, providing:
- **Smart Police Complaints & Governor Workflow (`police_complaints`):** Document scanner intake (`JPG`/`PNG`/`WEBP`/`PDF`), multi-provider Vision LLM OCR & legal-administrative analysis (`mat_llm_engine.py`), officer review (`نظر الضابط`), section head referral (`تنسيب رئيس القسم`), electronic Administrative Governor decisions (`الحاكم الإداري`), GIS nearest police station matching, 90-day inactivity tracking (`كف طلب`), automated MAT appointment & file custody integration, and official `.docx` export (`complaint_form_editable.docx`).
- **Appointments & Call Center Management:** Fast-track appointment scheduling and phone follow-ups.
- **Physical File Custody Tracking:** Reservation and officer-to-officer chain-of-custody transfers.
- **GIS Police Station Directory:** Interactive Amman Governorate map, 9-Liwa boundaries, and 8,750+ searchable locations.
- **Internal Meeting Room & FCM Push Notifications:** Live internal team messaging and background push notifications.

---

## 🏗️ Architecture & Core Modules (`mat`)

### 1. Core Modules
- `server.py` — Zero-dependency Python HTTP server (`MatServerHandler`, `ThreadedHTTPServer`), SQLite migrations (`init_db()`), RBAC/CSRF/security header enforcement, and FCM push dispatch.
- `mat_llm_engine.py` — Pure-stdlib Vision LLM extraction and analysis engine supporting **Google Gemini**, **OpenAI** (or compatible endpoints), and local **Ollama**, with graceful `manual_fallback` and secret redaction.
- `mat_complaints_service.py` — Service layer for secure scan storage, Arabic text normalization, GIS nearest police station matching (`data/amman_areas.json`), 90-day stop rule calculations, workflow state transitions, automated MAT appointment/file-custody integration, and pure-stdlib `.docx` generation (`complaint_form_editable.docx`).
- `complaints/js/police_complaints.js` — XSS-safe DOM frontend module for the Smart Police Complaints workspace (`#tab-police-complaints`), scanner/drag-drop/paste/camera intake, role-specific action cards, admin LLM configuration modal, and printable official view.

### 2. Database Layer (`mat_` Prefix)
All SQLite database tables, indexes, views, and foreign key references use the **`mat_`** prefix:

| Legacy Table Name | MAT Database Table Name | Description |
| :--- | :--- | :--- |
| `officers` | `mat_officers` | Administrative officers, caller staff, section heads (`admin`), and Administrative Governor (`governor`) |
| `complaints` | `mat_complaints` | Citizen & police complaints, AI analysis, officer/section/governor workflow, GIS station & 90-day tracking |
| `parties` | `mat_parties` | Complaint complainants and respondents (with `party_category`) |
| `—` | `mat_complaint_scans` | Uploaded scan metadata (`stored_filename`, `mime_type`, `file_size`, `ocr_raw_text`) |
| `—` | `mat_complaint_workflow_log` | Stage-by-stage audit log for police complaints workflow transitions |
| `—` | `mat_llm_settings` | Single-row (`id=1`) configurable Vision LLM provider, model, base URL, and API key |
| `appointments` | `mat_appointments` | Departmental appointment bookings |
| `appointment_parties` | `mat_appointment_parties` | Attendees for scheduled appointments |
| `activity_log` | `mat_activity_log` | Detailed user action audit trails |
| `simple_appointments` | `mat_simple_appointments` | Fast-track appointment bookings (including auto-scheduled `اتصال هاتفي` calls) |
| `search_logs` | `mat_search_logs` | Area and police station search metrics |
| `chat_messages` | `mat_chat_messages` | Internal administrative team messaging |
| `reserved_files` | `mat_reserved_files` | Physical file reservation index (including auto-reserved `توديع عن طريق مركز أمني` / `توديع مغفور` files) |
| `file_custody_log` | `mat_file_custody_log` | Chain of custody history for files |
| `sessions` | `mat_sessions` | Active user authentication sessions |
| `audit_logs` | `mat_audit_logs` | High-level system audit log entries |

* **Indexes:** Prefixed with `idx_mat_*` or `idx_*` (e.g., `idx_mat_complaints_stage`, `idx_mat_complaints_followup`, `idx_mat_complaint_scans_cid`, `idx_mat_complaint_log_cid`, `idx_complaints_status`, `idx_parties_name`).

### 3. API Routing Namespace (`/api/v1/mat/`)
All backend HTTP microservices and API routes follow the `/api/v1/mat/` endpoint standard:

- **Authentication:** `/api/v1/mat/login`, `/api/v1/mat/logout`, `/api/v1/mat/me`
- **Smart Police Complaints & Workflow:**
  - `/api/v1/mat/police-complaints` (`GET`, `POST`)
  - `/api/v1/mat/police-complaints/{id}` (`GET`, `PUT`)
  - `/api/v1/mat/police-complaints/scan-extract` (`POST`)
  - `/api/v1/mat/police-complaints/scans/{scan_id}` (`GET`)
  - `/api/v1/mat/police-complaints/{id}/officer-action` (`POST`)
  - `/api/v1/mat/police-complaints/{id}/section-recommend` (`POST`)
  - `/api/v1/mat/police-complaints/{id}/governor-decision` (`POST`)
  - `/api/v1/mat/police-complaints/{id}/followup` (`POST`)
  - `/api/v1/mat/police-complaints/{id}/export-docx` (`GET`)
  - `/api/v1/mat/police-complaints/match-station` (`GET`)
- **AI / LLM Settings (Admin Only):**
  - `/api/v1/mat/llm-settings` (`GET`, `PUT`)
  - `/api/v1/mat/llm-settings/test` (`POST`)
- **Legacy Complaints & Parties:** `/api/v1/mat/complaints`, `/api/v1/mat/parties`
- **Appointments:** `/api/v1/mat/appointments`, `/api/v1/mat/simple-appointments`
- **File Custody:** `/api/v1/mat/reservations`, `/api/v1/mat/reservations/transfer`, `/api/v1/mat/reservations/respond`
- **Internal Messaging:** `/api/v1/mat/chat/messages`, `/api/v1/mat/chat/message`, `/api/v1/mat/chat/poll`, `/api/v1/mat/chat/archives`
- **GIS / Finder:** `/api/v1/mat/areas`, `/api/v1/mat/search`

### 4. Code Structures & Components (`Mat*` & `mat*`)
- **Classes & Backend Handlers:** PascalCase with `Mat` prefix (e.g., `MatServerHandler`, `ThreadedHTTPServer`).
- **Configuration & Client State:** CamelCase with `mat` prefix (e.g., `matConfig`, `MatApp`).

### 5. Environment Variables (`MAT_*`)
System parameters are stored inside `.env` using uppercase **`MAT_*`** environment variable keys:

```env
MAT_ENV=production
MAT_PORT=5001
MAT_HOST=0.0.0.0
MAT_DB_PATH=complaints.db
MAT_API_PREFIX=/api/v1/mat
MAT_SECRET_KEY=mat_secret_key_2026
MAT_SCANS_DIR=data/complaint_scans
MAT_LLM_PROVIDER=gemini
MAT_LLM_MODEL=gemini-2.5-flash
MAT_GEMINI_API_KEY=
MAT_OPENAI_API_KEY=
MAT_OPENAI_BASE_URL=
MAT_OLLAMA_URL=http://localhost:11434
```

---

## 🚀 Quick Start & Execution

### Prerequisites
- Python 3.8+ (Uses built-in standard libraries `http.server`, `sqlite3`, `json`, `hashlib`, `zipfile`, `xml.etree.ElementTree`, `urllib.request`)

### Running the Application

1. **Configure Environment:**
   ```bash
   cp .env.example .env
   ```

2. **Start the MAT Web Server:**
   ```bash
   python server.py
   ```

3. **Access the Portal:**
   - Web App: `http://localhost:5001/` or `http://localhost:5001/complaints/app`
   - Login Portal: `http://localhost:5001/complaints/login`
   - Police Station Finder: `http://localhost:5001/finder`

### Running Automated Tests
```bash
python -m unittest discover -s tests -v
```

---

## 🛠️ Data & Migration Safety

On server startup, `init_db()` automatically performs zero-downtime schema migrations:
- Renaming legacy database tables (if present) to the `mat_` prefix standard while preserving all records.
- Rebuilding `mat_officers` if needed to support the `'governor'` role constraint while keeping foreign keys intact.
- Safely adding extended `mat_complaints` / `mat_parties` / `mat_sessions` columns and creating `mat_complaint_scans`, `mat_complaint_workflow_log`, `mat_llm_settings`, and `idx_mat_*` indexes.
- Seeding default accounts including `عطوفة المتصرف` (`governor`) and granting `police_complaints` tool access to existing eligible roles (`admin`, `officer`, `governor`).
