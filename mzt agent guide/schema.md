# MAT Database Schema

This document represents the exact SQLite database schema used by the Modular Assistant Toolkit (MAT) as implemented in `server.py` (`init_db()`).

## SQLite `CREATE TABLE` Definitions

```sql
CREATE TABLE IF NOT EXISTS mat_officers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('admin', 'officer', 'caller', 'governor')),
    accessible_tools TEXT DEFAULT 'dashboard,mat_complaints,finder,file_reservations,police_complaints,chat',
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    fcm_token TEXT
);

CREATE TABLE IF NOT EXISTS mat_complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_number TEXT,
    subject TEXT NOT NULL,
    complaint_type TEXT DEFAULT 'عام',
    status TEXT DEFAULT 'جديد',
    priority TEXT DEFAULT 'عادي',
    notes TEXT,
    assigned_officer_id INTEGER REFERENCES mat_officers(id),
    created_by_id INTEGER REFERENCES mat_officers(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),
    paper_date TEXT,
    complainant_category TEXT DEFAULT 'مواطن',
    respondent_category TEXT DEFAULT 'مواطن',
    summary TEXT,
    has_signature INTEGER DEFAULT 0,
    no_pending_lawsuit_declared INTEGER DEFAULT 0,
    workflow_stage TEXT DEFAULT 'draft_scan',
    is_minor_police_complaint INTEGER DEFAULT 1,
    ai_provider TEXT,
    ai_model TEXT,
    ai_extracted_json TEXT,
    ai_analysis TEXT,
    ai_solution_recommendation TEXT,
    ai_recommended_action TEXT,
    ai_confidence REAL,
    officer_action TEXT,
    officer_notes TEXT,
    officer_reviewed_by_id INTEGER REFERENCES mat_officers(id),
    officer_reviewed_at TEXT,
    section_head_notes TEXT,
    section_recommended_action TEXT,
    section_head_id INTEGER REFERENCES mat_officers(id),
    section_head_at TEXT,
    governor_decision TEXT,
    governor_final_action TEXT,
    governor_notes TEXT,
    governor_id INTEGER REFERENCES mat_officers(id),
    governor_decided_at TEXT,
    nearest_station TEXT,
    police_directorate TEXT,
    liwa_name TEXT,
    station_lat REAL,
    station_lon REAL,
    linked_appointment_id INTEGER,
    linked_file_number TEXT,
    last_followup_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
    party_type TEXT NOT NULL CHECK(party_type IN ('شاكي', 'مشتكى_عليه')),
    party_category TEXT DEFAULT 'مواطن',
    name TEXT NOT NULL,
    phone TEXT,
    national_id TEXT,
    address TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_complaint_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER REFERENCES mat_complaints(id) ON DELETE CASCADE,
    stored_filename TEXT NOT NULL,
    original_filename TEXT,
    mime_type TEXT NOT NULL,
    file_size INTEGER DEFAULT 0,
    page_order INTEGER DEFAULT 1,
    ocr_raw_text TEXT,
    uploaded_by_id INTEGER REFERENCES mat_officers(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_complaint_workflow_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
    actor_id INTEGER REFERENCES mat_officers(id),
    actor_role TEXT,
    stage_from TEXT,
    stage_to TEXT,
    action_taken TEXT NOT NULL DEFAULT '',
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_llm_settings (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL DEFAULT 'gemini',
    model_name TEXT DEFAULT 'gemini-2.5-flash',
    api_base_url TEXT DEFAULT '',
    api_key TEXT DEFAULT '',
    is_enabled INTEGER DEFAULT 1,
    updated_by_id INTEGER REFERENCES mat_officers(id),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
    appointment_date TEXT NOT NULL,
    appointment_time TEXT NOT NULL,
    appointment_type TEXT DEFAULT 'فردي' CHECK(appointment_type IN ('فردي', 'مشترك')),
    status TEXT DEFAULT 'مُجدول',
    location TEXT DEFAULT 'مكتب قسم الشكاوي',
    notes TEXT,
    requested_by_id INTEGER REFERENCES mat_officers(id),
    parent_appointment_id INTEGER REFERENCES mat_appointments(id),
    created_by_id INTEGER REFERENCES mat_officers(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_appointment_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    appointment_id INTEGER NOT NULL REFERENCES mat_appointments(id) ON DELETE CASCADE,
    party_id INTEGER NOT NULL REFERENCES mat_parties(id) ON DELETE CASCADE,
    call_status TEXT DEFAULT 'لم_يُتصل',
    called_at TEXT,
    called_by_id INTEGER REFERENCES mat_officers(id),
    attendance TEXT DEFAULT 'منتظر',
    notes TEXT,
    UNIQUE(appointment_id, party_id)
);

CREATE TABLE IF NOT EXISTS mat_activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES mat_officers(id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_simple_appointments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_number TEXT NOT NULL,
    visitor_name TEXT NOT NULL,
    phone TEXT,
    national_id TEXT,
    station_name TEXT,
    appointment_date TEXT NOT NULL,
    appointment_time TEXT NOT NULL,
    status TEXT DEFAULT 'مُجدول',
    notes TEXT,
    requested_by_id INTEGER REFERENCES mat_officers(id),
    parent_appointment_id INTEGER REFERENCES mat_simple_appointments(id),
    created_by_id INTEGER REFERENCES mat_officers(id),
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_search_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    area_name TEXT NOT NULL UNIQUE,
    closest_station TEXT NOT NULL,
    directorate TEXT NOT NULL,
    search_count INTEGER DEFAULT 1,
    last_searched_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES mat_officers(id),
    message TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_reserved_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_number TEXT NOT NULL UNIQUE,
    officer_id INTEGER NOT NULL REFERENCES mat_officers(id),
    notes TEXT,
    reserved_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_file_custody_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reserved_file_id INTEGER NOT NULL REFERENCES mat_reserved_files(id) ON DELETE CASCADE,
    from_officer_id INTEGER REFERENCES mat_officers(id),
    to_officer_id INTEGER NOT NULL REFERENCES mat_officers(id),
    status TEXT DEFAULT 'accepted',
    notes TEXT,
    transferred_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES mat_officers(id),
    username TEXT NOT NULL,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    accessible_tools TEXT,
    last_chat_seen TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    last_seen TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS mat_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    actor_id INTEGER REFERENCES mat_officers(id),
    timestamp TEXT DEFAULT (datetime('now', 'localtime')),
    details TEXT
);
```

## Database Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_parties_phone ON mat_parties(phone);
CREATE INDEX IF NOT EXISTS idx_parties_name ON mat_parties(name);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON mat_complaints(status);
CREATE INDEX IF NOT EXISTS idx_appointments_date ON mat_appointments(appointment_date);
CREATE INDEX IF NOT EXISTS idx_simple_appts_date ON mat_simple_appointments(appointment_date);
CREATE INDEX IF NOT EXISTS idx_simple_appts_case ON mat_simple_appointments(case_number);
CREATE INDEX IF NOT EXISTS idx_simple_appts_name ON mat_simple_appointments(visitor_name);
CREATE INDEX IF NOT EXISTS idx_search_logs_count ON mat_search_logs(search_count);

-- v1.46.0 Police Complaints Indexes
CREATE INDEX IF NOT EXISTS idx_mat_complaints_stage ON mat_complaints(workflow_stage);
CREATE INDEX IF NOT EXISTS idx_mat_complaints_followup ON mat_complaints(last_followup_at);
CREATE INDEX IF NOT EXISTS idx_mat_complaint_scans_cid ON mat_complaint_scans(complaint_id);
CREATE INDEX IF NOT EXISTS idx_mat_complaint_log_cid ON mat_complaint_workflow_log(complaint_id);
```

## Zero-Downtime Migration & Seeding Notes (`init_db`)
- **Legacy `mat_officers` Upgrade:** If an existing `mat_officers` table's `CHECK(role IN (...))` definition lacks `'governor'`, `init_db()` rebuilds it safely inside a transaction with `PRAGMA foreign_keys=OFF` while copying all existing rows (`mat_officers_new -> mat_officers`).
- **Additive Column Migrations:** `_ensure_table_columns()` verifies and adds missing extended columns on `mat_complaints`, `mat_parties` (`party_category`), `mat_sessions` (`last_chat_seen`), `mat_appointments`, `mat_simple_appointments`, and `mat_file_custody_log`, backfilling `last_followup_at` for existing complaint rows.
- **Default Governor Account & Tool Access:** Ensures default user `'governor'` (`عطوفة المتصرف`, role `'governor'`, tools `'dashboard,police_complaints,finder,chat'`) exists, and appends `police_complaints` to existing `'admin'`, `'officer'`, and `'governor'` users on migration.
