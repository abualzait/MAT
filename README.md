# MAT — حقيبة الأدوات المساعدة
### Modular Assistant Toolkit

> **Official Arabic Name:** "حقيبة الأدوات المساعدة"  
> **Full Acronym Definition:** Modular Assistant Toolkit  
> **Project Version:** 1.20.0  
> **Official Short URL:** [https://abualzait.github.io/MAT](https://abualzait.github.io/MAT)  
> **Direct Live Deployment:** [https://mat-ee756.containers.snapdeploy.app](https://mat-ee756.containers.snapdeploy.app)  
> **Cloud Secret Key:** `mat_secret_key_2026_prod`

---

## 📋 Overview & Strategic Vision

**MAT (Modular Assistant Toolkit)** is a highly scalable, modular digital workspace designed for governorate departments and official administrative support, built to dynamically accommodate custom tools, specialized departmental screens, and future horizontal expansion under the Ministry of Interior.

It operates seamlessly in offline and local network environments with zero external dependencies, providing local administrative support, citizen complaints management, appointment booking, file reservation tracking, and area/police station lookup utilities.

---

## 🏗️ Architecture & Structural Naming Convention Blueprint (`mat`)

Developers onboarding onto the MAT workspace must strictly follow the **`mat`** structural naming convention standard across all architectural layers:

### 1. Database Layer (`mat_` Prefix)
All SQLite database tables, indexes, views, and foreign key references must strictly use the **`mat_`** prefix:

| Legacy Table Name | MAT Database Table Name | Description |
| :--- | :--- | :--- |
| `officers` | `mat_officers` | Administrative officers and system users |
| `complaints` | `mat_complaints` | Citizens' complaints and case records |
| `parties` | `mat_parties` | Complaint complainants and respondents |
| `appointments` | `mat_appointments` | Departmental appointment bookings |
| `appointment_parties` | `mat_appointment_parties` | Attendees for scheduled appointments |
| `activity_log` | `mat_activity_log` | Detailed user action audit trails |
| `simple_appointments` | `mat_simple_appointments` | Fast-track appointment bookings |
| `search_logs` | `mat_search_logs` | Area and police station search metrics |
| `chat_messages` | `mat_chat_messages` | Internal administrative team messaging |
| `reserved_files` | `mat_reserved_files` | Physical file reservation index |
| `file_custody_log` | `mat_file_custody_log` | Chain of custody history for files |
| `sessions` | `mat_sessions` | Active user authentication sessions |
| `audit_logs` | `mat_audit_logs` | High-level system audit log entries |

* **Indexes:** Must be prefixed with `idx_mat_*` (e.g. `idx_mat_complaints_status`, `idx_mat_parties_name`).

### 2. API Routing Namespace (`/api/v1/mat/`)
All backend HTTP microservices and API routes follow the `/api/v1/mat/` endpoint standard:

- **Authentication:** `/api/v1/mat/login`, `/api/v1/mat/logout`, `/api/v1/mat/me`
- **Complaints & Cases:** `/api/v1/mat/complaints`, `/api/v1/mat/parties`
- **Appointments:** `/api/v1/mat/appointments`, `/api/v1/mat/simple-appointments`
- **File Custody:** `/api/v1/mat/reservations`, `/api/v1/mat/reservations/transfer`
- **Internal Messaging:** `/api/v1/mat/chat/messages`, `/api/v1/mat/chat/poll`
- **GIS / Finder:** `/api/v1/mat/areas`, `/api/v1/mat/search`

### 3. Code Structures & Components (`Mat*` & `mat*`)
- **Classes & Backend Handlers:** PascalCase with `Mat` prefix (e.g., `MatServerHandler`, `MatUserController`).
- **Configuration & Client State:** CamelCase with `mat` prefix (e.g., `matConfig`, `matState`, `MatApp`).

### 4. Environment Variables (`MAT_*`)
System parameters are stored inside `.env` using uppercase **`MAT_*`** environment variable keys:

```env
MAT_ENV=production
MAT_PORT=5001
MAT_HOST=0.0.0.0
MAT_DB_PATH=complaints.db
MAT_API_PREFIX=/api/v1/mat
MAT_SECRET_KEY=mat_secret_key_2026
```

---

## 🚀 Quick Start & Execution

### Prerequisites
- Python 3.8+ (Uses built-in standard libraries `http.server`, `sqlite3`, `json`, `hashlib`)

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

---

## 🛠️ Data & Migration Safety

On server startup, `init_db()` automatically performs zero-downtime schema migrations, renaming legacy database tables (if present) to the new `mat_` prefix standard while preserving all existing user records and historical activity log data.
