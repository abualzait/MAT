# Police Complaints Intake & Approval Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an end-to-end AI-assisted Police Complaints Intake, Officer Action & Notes, Section Head Recommendation, and Electronic Governor Decision section (`⚖️ الشكاوى الأمنية الذكية`) integrated across the MAT toolkit (GIS Nearest Police Station lookup, Simple Appointments auto-creation, Physical File Custody reservation, Notifications/FCM, 90-day follow-up rule, and `.docx` export based on `complaint_form_editable.docx`).

**Architecture:** Modular zero-dependency Python backend extensions (`mat_llm_engine.py`, `mat_complaints_service.py`) wired into `server.py`, paired with an isolated Vanilla JS frontend module (`complaints/js/police_complaints.js`) inside `complaints/app.html` and `complaints/login.html`. All data lives in SQLite `mat_*` tables synced with `data_backup.json`, with scanned forms stored safely outside static routes in `data/complaint_scans/`.

**Tech Stack:** Python 3 standard library (`http.server`, `sqlite3`, `urllib.request`, `zipfile`, `xml.etree.ElementTree`, `json`, `base64`, `hashlib`, `uuid`), SQLite 3, Vanilla HTML5/CSS3/ES6 JS, `unittest`.

## Global Constraints

- **Workspace Isolation:** Work strictly inside `c:\Users\Abual\AntiGravity Workspace\Amman Police Stations`.
- **Zero External Pip Dependencies:** Backend must run on `python:3.11-slim` (`Dockerfile`) using Python standard library only (`urllib.request`, `sqlite3`, `zipfile`, `xml.etree.ElementTree`, etc.). Do NOT require `pip install` packages at runtime.
- **`mat` Naming Standard:** SQLite tables prefixed `mat_*`, indexes prefixed `idx_mat_*`, API routes under `/api/v1/mat/`, environment variables `MAT_*`.
- **Version Sync (`v1.46.0`):** Increment `1.45.20` (and stale `1.45.11` badge in `app.html`) to `v1.46.0` across all UI badges, asset query params (`?v=1.46.0`), `server.py`, `README.md`, `index.html`, `Police_Station_Finder.html`, and `mzt agent guide/`.
- **Security Rules:** Parameterized SQL (`?`) only; CSRF Double Submit Cookie enforced on all state-changing API calls; strict RBAC (`governor` exclusively for Governor decisions, `admin` for Section Head recommendation & LLM settings, `officer`/`admin` for Intake & Officer Action/Notes); file uploads validated by magic bytes + extension allow-list + 10 MB cap + UUID storage outside static web root (`data/complaint_scans/`) + `X-Content-Type-Options: nosniff`; zero raw `innerHTML` with unescaped DB/OCR/LLM text; API keys masked on read and excluded from `data_backup.json` and client responses; test servers listen on `127.0.0.1` only.

---

## File Structure & Responsibilities

| File | Action | Responsibility |
| :--- | :--- | :--- |
| `server.py` | Modify | DB schema & migrations (`init_db`), `backup_db_to_json` / `restore_db_from_json`, cookie `HttpOnly` hardening, security headers, API route registration, global search update |
| `mat_llm_engine.py` | Create | Multi-provider LLM Vision client (Gemini, OpenAI/Compatible, Ollama), settings persistence/masking, prompt & structured JSON extraction/analysis parser |
| `mat_complaints_service.py` | Create | Scan validation & secure storage, Arabic GIS address-to-station matching (`data/amman_areas.json`), complaint workflow state machine, Officer/Section Head/Governor actions, toolkit auto-integrations (`mat_simple_appointments`, `mat_reserved_files`, notifications), 90-day counter, `.docx` export from `complaint_form_editable.docx` |
| `complaints/login.html` | Modify | Add `governor` (`عطوفة المتصرف`) login avatar, `defaultUsersMap` entry, sync `1.46.0` |
| `complaints/app.html` | Modify | Add `#tab-police-complaints`, split-view scanner/review workspace, modals (Detail/Officer/Section Head/Governor, LLM Settings, Scan Preview), officer role/permission inputs, load `police_complaints.js`, sync `v1.46.0` |
| `complaints/js/app.js` | Modify | Add `governor` role label, sidebar navigation item for `police_complaints`, default tab routing for `governor`, `loadAdminPermissions()` & `loadOfficersTable()` updates, global search section for `police_complaints` |
| `complaints/js/police_complaints.js` | Create | Complete UI controller for scan upload/drag-drop/camera/paste, client PDF-to-image helper (canvas fallback), dynamic multi-party forms, live station lookup, Officer action & notes form, Section Head referral form, Governor decision controls, 90-day follow-up UI, print/DOCX export, Admin LLM settings |
| `complaints/css/design-system.css` | Modify | Styles for split-view intake, workflow stage pills, AI recommendation panel, 90-day warning badges, print-friendly official complaint layout |
| `tests/test_police_complaints.py` | Create | Unit tests for DB migration, LLM provider payloads/parsing/masking, scan validation, GIS matching, workflow & integrations, 90-day logic, `.docx` export |
| `tests/test_police_complaints_api.py` | Create | End-to-end HTTP integration tests against `MatServerHandler` on `127.0.0.1` covering auth, CSRF, RBAC, full complaint lifecycle, and automated toolkit records |
| `index.html`, `Police_Station_Finder.html`, `README.md`, `mzt agent guide/*.md` | Modify | Version sync (`v1.46.0`) and full documentation update |

---

### Task 1: Database Schema Migrations, `governor` Role, and Backup/Restore Sync

**Files:**
- Modify: `server.py:314-482` (`backup_db_to_json`, `restore_db_from_json`)
- Modify: `server.py:541-781` (`init_db`)
- Modify: `server.py:1184-1234` (`api_login` `default_names` & `HttpOnly` session cookie)
- Test: `tests/test_police_complaints.py`

**Interfaces:**
- Produces SQLite tables/columns:
  - `mat_officers` supports `role IN ('admin', 'officer', 'caller', 'governor')` and seeds `('عطوفة المتصرف', 'governor', '12345', 'governor', 'dashboard,police_complaints,finder,chat')`
  - `mat_complaints` extended columns: `paper_date`, `complainant_category`, `respondent_category`, `summary`, `has_signature`, `no_pending_lawsuit_declared`, `workflow_stage`, `is_minor_police_complaint`, `ai_provider`, `ai_model`, `ai_extracted_json`, `ai_analysis`, `ai_solution_recommendation`, `ai_recommended_action`, `ai_confidence`, `officer_action`, `officer_notes`, `officer_reviewed_by_id`, `officer_reviewed_at`, `section_head_notes`, `section_recommended_action`, `section_head_id`, `section_head_at`, `governor_decision`, `governor_final_action`, `governor_notes`, `governor_id`, `governor_decided_at`, `nearest_station`, `police_directorate`, `liwa_name`, `station_lat`, `station_lon`, `linked_appointment_id`, `linked_file_number`, `last_followup_at`
  - `mat_parties` extended column: `party_category`
  - New tables: `mat_complaint_scans`, `mat_complaint_workflow_log`, `mat_llm_settings`
  - New indexes: `idx_mat_complaints_stage`, `idx_mat_complaints_followup`, `idx_mat_complaint_scans_cid`, `idx_mat_complaint_log_cid`

- [ ] **Step 1: Write the failing test in `tests/test_police_complaints.py`**

```python
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import server


class TestDatabaseMigrations(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_mat.db")
        self.backup_path = os.path.join(self.tmpdir.name, "backup.json")
        self.orig_db = server.DB_PATH
        self.orig_backup = server.BACKUP_JSON_PATH
        server.DB_PATH = self.db_path
        server.BACKUP_JSON_PATH = self.backup_path

    def tearDown(self):
        server.DB_PATH = self.orig_db
        server.BACKUP_JSON_PATH = self.orig_backup
        self.tmpdir.cleanup()

    def test_init_db_migrates_legacy_officers_constraint_and_creates_complaint_tables(self):
        # Create pre-existing legacy mat_officers table WITHOUT 'governor' role
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE mat_officers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'officer', 'caller')),
                accessible_tools TEXT DEFAULT 'mat_complaints,finder',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                fcm_token TEXT
            );
            INSERT INTO mat_officers (name, username, password_hash, salt, role)
            VALUES ('عروة', 'orwa', 'pbkdf2:abc', 'salt1', 'admin');
        """)
        conn.commit()
        conn.close()

        server.init_db()

        conn = server.get_db()
        # Governor account must exist and role check must allow 'governor'
        gov = conn.execute("SELECT username, role, accessible_tools FROM mat_officers WHERE username = 'governor'").fetchone()
        self.assertIsNotNone(gov)
        self.assertEqual(gov["role"], "governor")
        self.assertIn("police_complaints", gov["accessible_tools"])

        # Orwa must retain data and receive police_complaints access
        orwa = conn.execute("SELECT accessible_tools FROM mat_officers WHERE username = 'orwa'").fetchone()
        self.assertIn("police_complaints", orwa["accessible_tools"])

        # Extended columns on mat_complaints
        cols = {r[1] for r in conn.execute("PRAGMA table_info(mat_complaints)").fetchall()}
        for required_col in ("workflow_stage", "officer_action", "officer_notes", "section_head_notes",
                             "governor_decision", "nearest_station", "last_followup_at"):
            self.assertIn(required_col, cols)

        # New tables exist
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        self.assertTrue({"mat_complaint_scans", "mat_complaint_workflow_log", "mat_llm_settings"}.issubset(tables))
        conn.close()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_police_complaints.TestDatabaseMigrations -v`
Expected: FAIL (`AssertionError: None is not None` for `governor` and missing columns/tables).

- [ ] **Step 3: Implement schema migration, `governor` seed, `backup_db_to_json`/`restore_db_from_json`, and `api_login` updates in `server.py`**

In `server.py`:
1. In `init_db()` (`server.py:542-780`):
   - Update `CREATE TABLE IF NOT EXISTS mat_officers` to `CHECK(role IN ('admin', 'officer', 'caller', 'governor'))`.
   - Before inserting/seeding `governor`, inspect `sqlite_master` `sql` for `mat_officers`; if `'governor'` is not in the CHECK constraint, run safe table rebuild (`PRAGMA foreign_keys=OFF; BEGIN; CREATE TABLE mat_officers_new (...); INSERT INTO mat_officers_new (...) SELECT ... FROM mat_officers; DROP TABLE mat_officers; ALTER TABLE mat_officers_new RENAME TO mat_officers; COMMIT; PRAGMA foreign_keys=ON;`).
   - Add `CREATE TABLE IF NOT EXISTS mat_complaint_scans (...)`, `mat_complaint_workflow_log (...)`, `mat_llm_settings (...)`, and indexes `idx_mat_complaints_stage`, `idx_mat_complaints_followup`, `idx_mat_complaint_scans_cid`, `idx_mat_complaint_log_cid`.
   - Run `ALTER TABLE` checks on `mat_complaints` (adding all 30+ new columns if missing) and `mat_parties` (`party_category TEXT DEFAULT 'مواطن'`).
   - Ensure `accessible_tools` migration appends `,police_complaints` to existing officers if missing (`admin`/`officer` roles), and seed `'governor'` (`عطوفة المتصرف`) if not present in `mat_officers` (note: do this even when `existing['cnt'] > 0` so existing production DBs automatically get the `'governor'` user!).
2. In `backup_db_to_json()` (`server.py:324-340`):
   - Include `complaint_scans`, `complaint_workflow_log`, and `llm_settings` WITHOUT `api_key` (`SELECT id, provider, model_name, api_base_url, is_enabled, updated_by_id, updated_at FROM mat_llm_settings`).
3. In `restore_db_from_json()` (`server.py:350-480`):
   - Include new `mat_complaints` columns in restore `INSERT`, plus `party_category` on `mat_parties`, plus `complaint_scans`, `complaint_workflow_log`, and `llm_settings` (never overwriting an existing `api_key` with empty).
4. In `api_login()` (`server.py:1185-1225`):
   - Add `'governor': ('عطوفة المتصرف', 'governor')` to `default_names` fallback.
   - Change `cookie1 = f"session={token}; Path=/; HttpOnly; SameSite=Lax"` (keeping `csrf_token` readable by JS).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_police_complaints.TestDatabaseMigrations -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_police_complaints.py
git commit -m "feat(db): migrate mat_complaints, add governor role, scan & workflow tables"
```

---

### Task 2: Multi-Provider LLM Vision Extraction & Analysis Engine (`mat_llm_engine.py`)

**Files:**
- Create: `mat_llm_engine.py`
- Test: `tests/test_police_complaints.py`

**Interfaces:**
- Consumes: SQLite connection from `server.get_db()`, environment variables (`MAT_LLM_PROVIDER`, `MAT_GEMINI_API_KEY`, `MAT_OPENAI_API_KEY`, `MAT_OPENAI_BASE_URL`, `MAT_OLLAMA_URL`, `MAT_LLM_MODEL`)
- Produces:
  - `get_llm_settings(conn, mask_secret=True) -> dict` (`provider`, `model_name`, `api_base_url`, `is_enabled`, `api_key_configured`, `api_key_masked`, `source`)
  - `save_llm_settings(conn, user_id: int, payload: dict) -> dict`
  - `extract_and_analyze_complaint(file_bytes: bytes, mime_type: str, settings: dict) -> dict` returning:
    `{ "status": "ok"|"manual_fallback", "provider": str, "model": str, "extracted": {...}, "analysis": {...}, "raw_text": str, "message": str }`
  - `test_llm_connection(settings: dict) -> dict`

- [ ] **Step 1: Write failing tests for LLM settings masking, payload construction, and response parsing in `tests/test_police_complaints.py`**

```python
import json
import mat_llm_engine


class TestLlmEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_llm.db")
        self.backup_path = os.path.join(self.tmpdir.name, "backup.json")
        self.orig_db = server.DB_PATH
        self.orig_backup = server.BACKUP_JSON_PATH
        server.DB_PATH = self.db_path
        server.BACKUP_JSON_PATH = self.backup_path
        server.init_db()

    def tearDown(self):
        server.DB_PATH = self.orig_db
        server.BACKUP_JSON_PATH = self.orig_backup
        self.tmpdir.cleanup()

    def test_save_and_mask_llm_settings(self):
        conn = server.get_db()
        mat_llm_engine.save_llm_settings(conn, 1, {
            "provider": "gemini",
            "model_name": "gemini-2.5-flash",
            "api_key": "AIzaSyTestSecretKey12345",
            "is_enabled": 1
        })
        masked = mat_llm_engine.get_llm_settings(conn, mask_secret=True)
        self.assertEqual(masked["provider"], "gemini")
        self.assertTrue(masked["api_key_configured"])
        self.assertNotIn("AIzaSyTestSecretKey12345", json.dumps(masked))
        self.assertTrue(masked["api_key_masked"].endswith("2345"))

        # Updating model without re-entering api_key preserves existing key
        mat_llm_engine.save_llm_settings(conn, 1, {
            "provider": "gemini",
            "model_name": "gemini-2.5-pro",
            "api_key": "",
            "is_enabled": 1
        })
        unmasked = mat_llm_engine.get_llm_settings(conn, mask_secret=False)
        self.assertEqual(unmasked["api_key"], "AIzaSyTestSecretKey12345")
        self.assertEqual(unmasked["model_name"], "gemini-2.5-pro")
        conn.close()

    def test_extract_gemini_parses_structured_json_response(self):
        fake_llm_json = {
            "paper_date": "2026-11-10",
            "complainants": [{"party_category": "مواطن", "name": "خالد محمود", "national_id": "9901012345", "phone": "0795551111", "address": "جبل الحسين"}],
            "respondents": [{"party_category": "منشأة", "name": "كراج الأمل", "national_id": "", "phone": "0798882222", "address": "تلاع العلي شارع المدينة المنورة"}],
            "subject": "إغلاق ممر مشاة وتعدي على رصيف عام",
            "summary": "تقدم المواطن بشكوى ضد كراج سيارات يغلق الرصيف أمام العمارة ليلاً.",
            "has_signature": True,
            "no_pending_lawsuit_declared": True,
            "is_minor_police_complaint": True,
            "police_necessity_reason": "إزعاج وإغلاق طريق عام يتطلب متابعة مركز أمني دون نزاع قضائي كبير.",
            "ai_analysis": "الشكوى تتعلق بمخالفة نظامية وإغلاق ممر عام في منطقة تلاع العلي.",
            "ai_solution_recommendation": "توجيه تنبيه ومخاطبة المركز الأمني المختص لإزالة التعدي وتعهد بعدم التكرار.",
            "ai_recommended_action": "توديع عن طريق مركز أمني",
            "ai_confidence": 0.92
        }
        fake_resp_body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": "```json\n" + json.dumps(fake_llm_json, ensure_ascii=False) + "\n```"}]}}]
        }).encode("utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = fake_resp_body
        mock_resp.__enter__.return_value = mock_resp

        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "fake-key", "api_base_url": "", "is_enabled": 1}
        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as m_open:
            res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["extracted"]["subject"], "إغلاق ممر مشاة وتعدي على رصيف عام")
        self.assertEqual(res["analysis"]["ai_recommended_action"], "توديع عن طريق مركز أمني")
        self.assertTrue(res["analysis"]["is_minor_police_complaint"])
        self.assertTrue(m_open.called)

    def test_extract_returns_manual_fallback_when_api_key_missing(self):
        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "", "api_base_url": "", "is_enabled": 1}
        res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", settings)
        self.assertEqual(res["status"], "manual_fallback")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_police_complaints.TestLlmEngine -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'mat_llm_engine'`).

- [ ] **Step 3: Create `mat_llm_engine.py`**

Implement `mat_llm_engine.py` using pure Python stdlib (`os`, `json`, `re`, `base64`, `urllib.request`, `urllib.error`, `ssl`):
- Prompt `COMPLAINT_EXTRACTION_PROMPT` explicitly structured around `complaint_form_editable.docx`:
  - Extracts `paper_date`, `complainants[]` (`party_category` in `['مواطن', 'مؤسسة تجارية', 'مؤسسة حكومية']`, `name`, `national_id`, `phone`, `address`), `respondents[]` (`party_category` in `['مواطن', 'منشأة']`, `name`, `national_id`, `phone`, `address`), `subject`, `summary`, `has_signature`, `no_pending_lawsuit_declared`.
  - Analyzes `is_minor_police_complaint` (boolean), `police_necessity_reason`, `ai_analysis`, `ai_solution_recommendation`, `ai_recommended_action` (allowed enum: `'توديع عن طريق مركز أمني'`, `'اتصال هاتفي'`, `'توديع مغفور'`, `'حفظ / توجيه للقضاء المختص'`), `ai_confidence`.
- Provider dispatchers:
  - `_call_gemini(file_bytes, mime_type, settings, prompt)` -> `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` with `x-goog-api-key` header (NOT URL query param so key stays out of URLs!). Supports `image/*` and `application/pdf`.
  - `_call_openai(file_bytes, mime_type, settings, prompt)` -> `{base_url or https://api.openai.com/v1}/chat/completions` with `Bearer` auth and `image_url` data URI (rejects raw PDF cleanly with helpful message instructing user to use PNG/JPG or Gemini).
  - `_call_ollama(file_bytes, mime_type, settings, prompt)` -> `{base_url or http://localhost:11434}/api/chat` with `images: [b64]` and `format: "json"`.
- `_parse_llm_json(raw_text)` extracts JSON cleanly even if wrapped in Markdown code fences, and normalizes all defaults safely.
- `get_llm_settings(conn, mask_secret=True)` checks `mat_llm_settings` row `id=1` first, falling back to env vars (`MAT_LLM_PROVIDER`, `MAT_GEMINI_API_KEY`, `MAT_OPENAI_API_KEY`, `MAT_OPENAI_BASE_URL`, `MAT_OLLAMA_URL`, `MAT_LLM_MODEL`), and masks `api_key` whenever `mask_secret=True`.

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_police_complaints.TestLlmEngine -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mat_llm_engine.py tests/test_police_complaints.py
git commit -m "feat(ai): add multi-provider LLM Vision extractor and settings engine"
```

---

### Task 3: Secure Scan Storage, GIS Nearest Station Matcher, 90-Day Calculator, and Official `.docx` Exporter (`mat_complaints_service.py`)

**Files:**
- Create: `mat_complaints_service.py`
- Test: `tests/test_police_complaints.py`

**Interfaces:**
- Consumes: `data/amman_areas.json`, `complaint_form_editable.docx`
- Produces:
  - `normalize_arabic(text: str) -> str`
  - `match_nearest_police_station(address: str, base_dir: str) -> dict` (`matched`, `area_name`, `nearest_station`, `police_directorate`, `liwa_name`, `lat`, `lon`, `candidates`)
  - `validate_and_store_scan(raw_bytes: bytes, original_filename: str, scans_dir: str) -> dict` (`stored_filename`, `original_filename`, `mime_type`, `file_size`, `abs_path`)
  - `resolve_scan_path(stored_filename: str, scans_dir: str) -> str` (prevents traversal)
  - `compute_90_day_status(last_followup_at: str, workflow_stage: str) -> dict` (`days_elapsed`, `days_remaining`, `is_due_for_stop`, `warning_level`)
  - `export_complaint_docx(complaint_detail: dict, template_path: str) -> bytes`

- [ ] **Step 1: Write failing unit tests in `tests/test_police_complaints.py`**

```python
import io
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
import mat_complaints_service


class TestComplaintsUtilities(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scans_dir = os.path.join(self.tmpdir.name, "complaint_scans")
        os.makedirs(self.scans_dir, exist_ok=True)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_validate_and_store_scan_rejects_spoofed_and_oversized_files(self):
        # Spoofed .jpg containing HTML script
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(b"<script>alert(1)</script>", "evil.jpg", self.scans_dir)

        # Path traversal attempt in resolve_scan_path
        with self.assertRaises(ValueError):
            mat_complaints_service.resolve_scan_path("../server.py", self.scans_dir)

        # Valid PNG magic bytes
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        meta = mat_complaints_service.validate_and_store_scan(png_bytes, "../../scan 01.png", self.scans_dir)
        self.assertTrue(meta["stored_filename"].endswith(".png"))
        self.assertNotIn("..", meta["stored_filename"])
        self.assertEqual(meta["mime_type"], "image/png")
        resolved = mat_complaints_service.resolve_scan_path(meta["stored_filename"], self.scans_dir)
        self.assertTrue(os.path.isfile(resolved))

    def test_match_nearest_police_station_from_amman_areas(self):
        res = mat_complaints_service.match_nearest_police_station("عمان - تلاع العلي قرب الدوار", self.base_dir)
        self.assertTrue(res["matched"])
        self.assertIn("تلاع العلي", res["nearest_station"])
        self.assertTrue(res["police_directorate"])
        self.assertTrue(res["liwa_name"])

    def test_compute_90_day_status(self):
        old_date = (datetime.now() - timedelta(days=92)).strftime("%Y-%m-%d %H:%M:%S")
        res = mat_complaints_service.compute_90_day_status(old_date, "governor_approved")
        self.assertTrue(res["is_due_for_stop"])
        self.assertEqual(res["days_remaining"], 0)
        self.assertEqual(res["warning_level"], "expired")

    def test_export_complaint_docx_populates_template_text(self):
        template = os.path.join(self.base_dir, "complaint_form_editable.docx")
        detail = {
            "complaint": {
                "complaint_number": "PC-20261110-0001",
                "paper_date": "2026-11-10",
                "subject": "إغلاق مدخل عمارة",
                "summary": "قام المشتكى عليه بإغلاق المدخل بسيارته.",
                "officer_action": "اتصال هاتفي",
                "officer_notes": "تم التحقق من العنوان",
                "section_head_notes": "يرجى التوديع للمركز الأمني المختص",
                "section_recommended_action": "توديع عن طريق مركز أمني",
                "governor_decision": "موافقة",
                "governor_final_action": "توديع عن طريق مركز أمني",
                "governor_notes": "لا مانع حسب الأصول",
                "nearest_station": "مركز أمن تلاع العلي",
                "police_directorate": "مديرية شرطة شمال عمان"
            },
            "parties": [
                {"party_type": "شاكي", "party_category": "مواطن", "name": "خالد محمود", "national_id": "9901012345", "phone": "0795551111", "address": "تلاع العلي"},
                {"party_type": "مشتكى_عليه", "party_category": "منشأة", "name": "كراج الأمل", "national_id": "", "phone": "0798882222", "address": "تلاع العلي"}
            ]
        }
        docx_bytes = mat_complaints_service.export_complaint_docx(detail, template)
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
            xml_text = zf.read("word/document.xml").decode("utf-8")
        self.assertIn("خالد محمود", xml_text)
        self.assertIn("كراج الأمل", xml_text)
        self.assertIn("إغلاق مدخل عمارة", xml_text)
        self.assertIn("يرجى التوديع للمركز الأمني المختص", xml_text)
        self.assertIn("مركز أمن تلاع العلي", xml_text)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_police_complaints.TestComplaintsUtilities -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'mat_complaints_service'`).

- [ ] **Step 3: Implement utility functions in `mat_complaints_service.py`**

Implement in `mat_complaints_service.py`:
- `validate_and_store_scan`: checks max size (`10 * 1024 * 1024`), validates magic bytes (`\xff\xd8\xff` -> `image/jpeg`, `\x89PNG\r\n\x1a\n` -> `image/png`, `RIFF....WEBP` -> `image/webp`, `%PDF-` -> `application/pdf`), generates `f"{uuid.uuid4().hex}{ext}"`, writes atomically inside `scans_dir`, verifies `os.path.realpath(out).startswith(os.path.realpath(scans_dir) + os.sep)`.
- `resolve_scan_path`: enforces single basename + `realpath` boundary check.
- `match_nearest_police_station`: loads and caches `data/amman_areas.json`, normalizes Arabic (`أإآ->ا`, `ة->ه`, `ى->ي`, strips diacritics and punctuation), scores exact substring / token overlap against `area['name']` and `area['closest']`, returns best match + top 5 candidate stations.
- `compute_90_day_status`: parses `last_followup_at`, returns `days_elapsed`, `days_remaining = max(0, 90 - days_elapsed)`, `is_due_for_stop = days_elapsed >= 90` (unless already closed/stopped), `warning_level` (`normal` / `warning` >=75 / `expired` >=90 / `closed`).
- `export_complaint_docx`: reads `complaint_form_editable.docx` ZIP bytes, parses `word/document.xml` using `xml.etree.ElementTree`, fills:
  - Table 0 cell 0: formatted date (`التاريخ: YYYY / MM / DD م` + `رقم الشكوى: ...`)
  - Table 1 rows 1..N: Complainants (`الاسم الكامل`, `الرقم الوطني`, `رقم الهاتف`, `العنوان`)
  - Table 2 rows 1..N: Respondents (`الاسم الكامل`, `الرقم الوطني`, `رقم الهاتف`, `العنوان`)
  - Paragraph `موضوع الشكوى:`: appends subject
  - Table 3 rows 0..14: populates wrapped lines of `summary`
  - Table 3 row 16 (`مشروحات القسم:`): fills `مشروحات القسم` + `الإجراء المنسب` + `المركز الأمني المعني` + `ملاحظات الضابط` + `قرار الحاكم الإداري`
  - Repacks all other entries in the `.docx` archive intact (preserving header Coat of Arms `image1.png`, fonts, RTL layout, and tables!).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_police_complaints.TestComplaintsUtilities -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mat_complaints_service.py tests/test_police_complaints.py
git commit -m "feat(service): add secure scan storage, GIS matcher, 90-day counter, and DOCX export"
```

---

### Task 4: Workflow State Machine, Officer Actions & Notes, Governor Decisions, and Toolkit Integrations (`mat_complaints_service.py`)

**Files:**
- Modify: `mat_complaints_service.py`
- Test: `tests/test_police_complaints.py`

**Interfaces:**
- Consumes: SQLite `conn`, `user` dict (`user_id`, `username`, `name`, `role`), `log_activity`, `send_fcm_notification`
- Produces:
  - `list_complaints(conn, user, filters: dict) -> dict`
  - `get_complaint_detail(conn, complaint_id: int) -> dict | None`
  - `create_complaint_intake(conn, user: dict, payload: dict, base_dir: str) -> dict`
  - `update_complaint_details(conn, user: dict, complaint_id: int, payload: dict, base_dir: str) -> dict`
  - `record_officer_action(conn, user: dict, complaint_id: int, payload: dict) -> dict`
  - `record_section_head_recommendation(conn, user: dict, complaint_id: int, payload: dict) -> dict`
  - `record_governor_decision(conn, user: dict, complaint_id: int, payload: dict) -> dict`
  - `register_followup(conn, user: dict, complaint_id: int, action_type: str, notes: str) -> dict`
  - `PermissionError` / `ValueError` / `LookupError` mapped cleanly by HTTP layer.

- [ ] **Step 1: Write failing tests for the complete workflow and toolkit integrations in `tests/test_police_complaints.py`**

```python
class TestComplaintsWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmpdir.name, "test_wf.db")
        self.backup_path = os.path.join(self.tmpdir.name, "backup.json")
        self.orig_db = server.DB_PATH
        self.orig_backup = server.BACKUP_JSON_PATH
        server.DB_PATH = self.db_path
        server.BACKUP_JSON_PATH = self.backup_path
        server.init_db()
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        conn = server.get_db()
        self.officer = dict(conn.execute("SELECT id as user_id, name, username, role FROM mat_officers WHERE role='officer' LIMIT 1").fetchone())
        self.admin = dict(conn.execute("SELECT id as user_id, name, username, role FROM mat_officers WHERE role='admin' LIMIT 1").fetchone())
        self.governor = dict(conn.execute("SELECT id as user_id, name, username, role FROM mat_officers WHERE role='governor' LIMIT 1").fetchone())
        conn.close()

    def tearDown(self):
        server.DB_PATH = self.orig_db
        server.BACKUP_JSON_PATH = self.orig_backup
        self.tmpdir.cleanup()

    def test_full_workflow_officer_action_section_head_governor_modify_to_phone_call(self):
        conn = server.get_db()
        created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
            "paper_date": "2026-11-10",
            "subject": "مشكلة مواقف سيارات",
            "summary": "شكوى خفيفة حول الوقوف المتكرر أمام المحل.",
            "complainant_category": "مؤسسة تجارية",
            "respondent_category": "مواطن",
            "submit_stage": "draft_scan",
            "parties": [
                {"party_type": "شاكي", "party_category": "مؤسسة تجارية", "name": "شركة النور", "phone": "0791112222", "address": "الشميساني"},
                {"party_type": "مشتكى_عليه", "party_category": "مواطن", "name": "سامي عمر", "phone": "0793334444", "address": "تلاع العلي"}
            ]
        }, self.base_dir)
        cid = created["id"]
        self.assertIn("تلاع العلي", created["nearest_station"])

        # Officer reviews complaint, takes action & writes notes before sending to Section Head
        off_res = mat_complaints_service.record_officer_action(conn, self.officer, cid, {
            "officer_action": "توديع عن طريق مركز أمني",
            "officer_notes": "تمت معاينة المرفق والتحقق من عنوان المشتكى عليه في تلاع العلي.",
            "send_to_section_head": True
        })
        self.assertEqual(off_res["workflow_stage"], "pending_section_head")

        # Officer cannot issue governor decision
        with self.assertRaises(PermissionError):
            mat_complaints_service.record_governor_decision(conn, self.officer, cid, {"decision": "موافقة"})

        # Section head writes مشروحات القسم & recommends action
        sec_res = mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
            "section_head_notes": "ينسب بالتوديع عن طريق مركز أمن تلاع العلي.",
            "section_recommended_action": "توديع عن طريق مركز أمني",
            "nearest_station": "مركز أمن تلاع العلي"
        })
        self.assertEqual(sec_res["workflow_stage"], "pending_governor")

        # Governor modifies recommended action to اتصال هاتفي -> auto-creates appointment!
        gov_res = mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
            "decision": "تغيير_الإجراء",
            "governor_final_action": "اتصال هاتفي",
            "governor_notes": "يتم استدعاء الأطراف هاتفياً للصلح أولاً."
        })
        self.assertEqual(gov_res["workflow_stage"], "governor_modified")
        self.assertIsNotNone(gov_res["linked_appointment_id"])

        appt = conn.execute("SELECT * FROM mat_simple_appointments WHERE id = ?", (gov_res["linked_appointment_id"],)).fetchone()
        self.assertIsNotNone(appt)
        self.assertEqual(appt["case_number"], created["complaint_number"])

        # Officer performs post-approval execution action and notes
        exec_res = mat_complaints_service.record_officer_action(conn, self.officer, cid, {
            "officer_action": "اتصال هاتفي",
            "officer_notes": "تم الاتصال بالطرفين وتحديد موعد المراجعة.",
            "execution_status": "completed"
        })
        self.assertEqual(exec_res["workflow_stage"], "completed")
        conn.close()

    def test_governor_approval_station_referral_reserves_file(self):
        conn = server.get_db()
        created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
            "subject": "إزعاج من منشأة تجارية",
            "summary": "ضجيج ليلي متكرر",
            "submit_stage": "pending_section_head",
            "parties": [
                {"party_type": "شاكي", "name": "علي حسن", "phone": "0790001111", "address": "عبدون"},
                {"party_type": "مشتكى_عليه", "name": "مقهى الربيع", "phone": "0790002222", "address": "البيادر"}
            ]
        }, self.base_dir)
        cid = created["id"]
        mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
            "section_head_notes": "يرجى التوديع لمركز أمن البيادر",
            "section_recommended_action": "توديع عن طريق مركز أمني",
            "nearest_station": "مركز أمن البيادر"
        })
        gov_res = mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
            "decision": "موافقة",
            "governor_notes": "موافق"
        })
        self.assertEqual(gov_res["workflow_stage"], "governor_approved")
        self.assertEqual(gov_res["linked_file_number"], created["complaint_number"])
        res_file = conn.execute("SELECT * FROM mat_reserved_files WHERE file_number = ?", (created["complaint_number"],)).fetchone()
        self.assertIsNotNone(res_file)
        conn.close()
```

- [ ] **Step 2: Run tests to verify failure**

Run: `python -m unittest tests.test_police_complaints.TestComplaintsWorkflow -v`
Expected: FAIL (`AttributeError: module 'mat_complaints_service' has no attribute 'create_complaint_intake'`).

- [ ] **Step 3: Implement workflow state machine & toolkit auto-integrations in `mat_complaints_service.py`**

Implement cleanly with single shared helpers for:
- Logging workflow step to `mat_complaint_workflow_log` and `mat_activity_log`.
- `_auto_create_phone_appointment(conn, complaint, parties, actor_id)` -> inserts into `mat_simple_appointments` (avoiding duplicate creation if `linked_appointment_id` already exists!) and updates `linked_appointment_id`.
- `_auto_reserve_complaint_file(conn, complaint, actor_id)` -> reserves `complaint_number` in `mat_reserved_files` for the assigned officer or actor (skipping silently if already reserved, linking `linked_file_number`), inserts initial `mat_file_custody_log`.
- `_apply_post_approval_integrations(conn, complaint_id, final_action, actor_id)` -> executes `اتصال هاتفي` or `توديع عن طريق مركز أمني` / `توديع مغفور` integrations uniformly.
- `record_officer_action`: enforces `user['role'] in ('officer', 'admin')`; requires non-empty `officer_notes`; handles both pre-approval (`draft_scan`/`officer_reviewed`/`governor_rejected` -> `officer_reviewed` or `pending_section_head`) and post-approval (`governor_approved`/`governor_modified`/`in_execution` -> `in_execution` or `completed`); updates `last_followup_at` and logs action.
- `record_section_head_recommendation`: enforces `user['role'] == 'admin'`; saves `section_head_notes`, `section_recommended_action`, station fields, sets `workflow_stage = 'pending_governor'`.
- `record_governor_decision`: enforces `user['role'] == 'governor'`; validates `decision in ('موافقة', 'رفض', 'تغيير_الإجراء')`; if `تغيير_الإجراء`, requires `governor_final_action`; updates stage to `governor_approved`, `governor_rejected`, or `governor_modified`; triggers `_apply_post_approval_integrations` when approved or modified.
- `register_followup`: resets `last_followup_at = now` on follow-up OR sets `workflow_stage = 'stopped_90_days'` when `action_type == 'stop_90_days'` (validating `days_elapsed >= 90` or explicit `admin`/`governor` stop note).

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m unittest tests.test_police_complaints.TestComplaintsWorkflow -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add mat_complaints_service.py tests/test_police_complaints.py
git commit -m "feat(workflow): implement complaint intake, officer actions, governor decisions, and MAT integrations"
```

---

### Task 5: HTTP API Routes, Security Headers, Notifications & Global Search (`server.py`)

**Files:**
- Modify: `server.py:914-945` (`send_json` security headers + `read_json_body` size cap)
- Modify: `server.py:1071-1140` (`route_api_get`, `route_api_post`, `route_api_put`)
- Modify: `server.py:2030-2154` (`api_search` adding `police_complaints` results)
- Modify: `server.py:2885-2938` (API handler methods calling `mat_llm_engine` & `mat_complaints_service`)
- Test: `tests/test_police_complaints_api.py`

**Interfaces:**
- Routes added in `server.py`:
  - `GET /api/v1/mat/police-complaints` -> `api_get_police_complaints`
  - `GET /api/v1/mat/police-complaints/(\d+)` -> `api_get_police_complaint_detail`
  - `GET /api/v1/mat/police-complaints/scans/(\d+)` -> `api_get_police_complaint_scan`
  - `GET /api/v1/mat/police-complaints/(\d+)/export-docx` -> `api_export_police_complaint_docx`
  - `GET /api/v1/mat/police-complaints/match-station` -> `api_match_police_station`
  - `GET /api/v1/mat/llm-settings` -> `api_get_llm_settings`
  - `POST /api/v1/mat/police-complaints/scan-extract` -> `api_scan_extract_complaint`
  - `POST /api/v1/mat/police-complaints` -> `api_create_police_complaint`
  - `POST /api/v1/mat/police-complaints/(\d+)/officer-action` -> `api_police_complaint_officer_action`
  - `POST /api/v1/mat/police-complaints/(\d+)/section-recommend` -> `api_police_complaint_section_recommend`
  - `POST /api/v1/mat/police-complaints/(\d+)/governor-decision` -> `api_police_complaint_governor_decision`
  - `POST /api/v1/mat/police-complaints/(\d+)/followup` -> `api_police_complaint_followup`
  - `POST /api/v1/mat/llm-settings/test` -> `api_test_llm_settings`
  - `PUT /api/v1/mat/police-complaints/(\d+)` -> `api_update_police_complaint`
  - `PUT /api/v1/mat/llm-settings` -> `api_update_llm_settings`

- [ ] **Step 1: Write failing API integration tests in `tests/test_police_complaints_api.py`**

```python
import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

import server


class TestPoliceComplaintsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        server.DB_PATH = os.path.join(cls.tmpdir.name, "api_test.db")
        server.BACKUP_JSON_PATH = os.path.join(cls.tmpdir.name, "api_backup.json")
        server.init_db()
        cls.httpd = server.ThreadedHTTPServer(("127.0.0.1", 0), server.MatServerHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.tmpdir.cleanup()

    def _new_client(self):
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        return opener, jar

    def _req(self, opener, jar, method, path, body=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        for c in jar:
            if c.name == "csrf_token":
                headers["X-CSRF-Token"] = c.value
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with opener.open(req, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def test_rbac_csrf_and_end_to_end_http_flow(self):
        off_op, off_jar = self._new_client()
        adm_op, adm_jar = self._new_client()
        gov_op, gov_jar = self._new_client()

        status, _, _ = self._req(off_op, off_jar, "POST", "/api/v1/mat/login", {"username": "ehab"})
        self.assertEqual(status, 200)
        self.assertEqual(self._req(adm_op, adm_jar, "POST", "/api/v1/mat/login", {"username": "orwa"})[0], 200)
        self.assertEqual(self._req(gov_op, gov_jar, "POST", "/api/v1/mat/login", {"username": "governor"})[0], 200)

        # Officer uploads scan via base64 JSON -> manual_fallback when no API key configured
        png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode("ascii")
        st, _, raw = self._req(off_op, off_jar, "POST", "/api/v1/mat/police-complaints/scan-extract", {
            "filename": "handwritten.png",
            "file_base64": png_b64
        })
        self.assertEqual(st, 200)
        scan_res = json.loads(raw.decode("utf-8"))
        self.assertIn("scan_id", scan_res)

        # Create complaint linked to scan
        st, _, raw = self._req(off_op, off_jar, "POST", "/api/v1/mat/police-complaints", {
            "scan_ids": [scan_res["scan_id"]],
            "subject": "خلاف جوار خفيف",
            "summary": "نزاع على مواقف العمارة",
            "parties": [
                {"party_type": "شاكي", "name": "سالم", "phone": "0791234567", "address": "الشميساني"},
                {"party_type": "مشتكى_عليه", "name": "رامي", "phone": "0797654321", "address": "تلاع العلي"}
            ]
        })
        self.assertEqual(st, 201)
        cid = json.loads(raw.decode("utf-8"))["id"]

        # Officer records action & notes and submits to Section Head
        st, _, _ = self._req(off_op, off_jar, "POST", f"/api/v1/mat/police-complaints/{cid}/officer-action", {
            "officer_action": "توديع عن طريق مركز أمني",
            "officer_notes": "نوصي بالتوديع لمركز أمن تلاع العلي.",
            "send_to_section_head": True
        })
        self.assertEqual(st, 200)

        # Officer cannot access LLM settings (admin only)
        st, _, _ = self._req(off_op, off_jar, "GET", "/api/v1/mat/llm-settings")
        self.assertEqual(st, 403)

        # Admin (Section Head) recommends action
        st, _, _ = self._req(adm_op, adm_jar, "POST", f"/api/v1/mat/police-complaints/{cid}/section-recommend", {
            "section_head_notes": "توديع رسمي",
            "section_recommended_action": "توديع عن طريق مركز أمني",
            "nearest_station": "مركز أمن تلاع العلي"
        })
        self.assertEqual(st, 200)

        # Admin cannot issue Governor decision (governor only)
        st, _, _ = self._req(adm_op, adm_jar, "POST", f"/api/v1/mat/police-complaints/{cid}/governor-decision", {
            "decision": "موافقة"
        })
        self.assertEqual(st, 403)

        # Governor approves
        st, _, raw = self._req(gov_op, gov_jar, "POST", f"/api/v1/mat/police-complaints/{cid}/governor-decision", {
            "decision": "موافقة",
            "governor_notes": "يعتمد التوديع"
        })
        self.assertEqual(st, 200)

        # Protected scan download has nosniff header
        st, hdrs, _ = self._req(gov_op, gov_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan_res['scan_id']}")
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")

        # Export filled DOCX
        st, hdrs, doc_bytes = self._req(adm_op, adm_jar, "GET", f"/api/v1/mat/police-complaints/{cid}/export-docx")
        self.assertEqual(st, 200)
        self.assertTrue(doc_bytes.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m unittest tests.test_police_complaints_api -v`
Expected: FAIL (`404` on `/api/v1/mat/police-complaints/scan-extract`).

- [ ] **Step 3: Wire routes, security headers, size caps, FCM/chat role dispatchers, and global search into `server.py`**

1. Add `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN` in `send_json()` and `serve_file()`.
2. Enforce `MAX_REQUEST_BYTES = 16 * 1024 * 1024` in `read_json_body()`.
3. Import `mat_llm_engine` and `mat_complaints_service` in `server.py`.
4. Add route patterns to `route_api_get`, `route_api_post`, `route_api_put`.
5. Implement each handler method on `MatServerHandler` enforcing `require_auth()` / `require_role(...)`, calling `backup_db_to_json()` after mutations, and dispatching background FCM notifications on stage transitions (`pending_section_head` -> notify `admin`, `pending_governor` -> notify `governor`, `governor_*` -> notify `admin` & assigned `officer`/`caller`).
6. Extend `api_search()` to query `mat_complaints` + `mat_parties` and include `police_complaints` list in response.

- [ ] **Step 4: Run all Python tests to verify pass**

Run: `python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server.py tests/test_police_complaints_api.py
git commit -m "feat(api): add police complaints intake endpoints, RBAC, and global search integration"
```

---

### Task 6: Frontend UI Shell, Login Portal, Permissions Matrix & Design System (`login.html`, `app.html`, `app.js`, `design-system.css`)

**Files:**
- Modify: `complaints/login.html:296-355`
- Modify: `complaints/app.html:40-52`, `complaints/app.html:508-538`, `complaints/app.html:643-660`, `complaints/app.html:917-925`
- Modify: `complaints/js/app.js:113-125`, `complaints/js/app.js:180-325`, `complaints/js/app.js:377-399`, `complaints/js/app.js:401-472`, `complaints/js/app.js:1430-1515`
- Modify: `complaints/css/design-system.css`

**Interfaces:**
- `app.html` exposes tab `#tab-police-complaints`, modals `#modalPoliceComplaintDetail`, `#modalLlmSettings`, `#modalScanLightbox`.
- `app.js` calls `window.loadPoliceComplaintsTab()` when switching to `'police-complaints'`, and calls `window.openPoliceComplaintDetail(id)` from global search cards.
- `app.js` includes `police_complaints` in `renderDynamicNavigation()`, `loadAdminPermissions()`, and `loadOfficersTable()`.

- [ ] **Step 1: Update `complaints/login.html`**

- Add `governor` button in `#avatarGrid`:
  ```html
  <!-- Governor -->
  <button type="button" class="avatar-btn" onclick="selectUser('governor', this)">
      <div class="avatar-circle" style="background:#FEF3C7; color:#B45309;">🏛️</div>
      <span class="avatar-name">عطوفة المتصرف</span>
      <span class="avatar-role">الحاكم الإداري</span>
  </button>
  ```
- Add `'governor': { username: 'governor', name: 'عطوفة المتصرف', role: 'governor' }` to `defaultUsersMap`.

- [ ] **Step 2: Update `complaints/app.html` and `complaints/css/design-system.css`**

- Add `#tab-police-complaints` inside `<main class="main-content">` containing:
  - Header bar with KPI filter pills (`الكل`, `مسودة / مسح جديد`, `بانتظار رئيس القسم`, `بانتظار الحاكم الإداري`, `معتمدة / قيد التنفيذ`, `تجاوزت 90 يوماً`), search filter, `+ مسح شكوى جديدة`, and `⚙️ إعدادات الذكاء الاصطناعي (LLM)` (admin only).
  - Split-view **Scanner & AI Extraction Workspace** (`#scannerIntakeCard` collapsible/toggleable): Drag-and-drop scanner zone + file picker + camera/paste capture + uploaded page preview pane beside the extracted form (`التاريخ`, multi-row `بيانات المشتكين` with category selector `مواطن/مؤسسة تجارية/مؤسسة حكومية`, multi-row `بيانات المشتكى عليهم` with category selector `مواطن/منشأة`, `موضوع الشكوى`, `موجز الشكوى`, signature/no-lawsuit checkboxes, AI Recommendation Card, auto-matched Nearest Police Station + Map Preview link, and Officer Initial Action & Notes section).
  - Complaints queue table/cards container (`#policeComplaintsListContainer`).
- Add `#modalPoliceComplaintDetail` with:
  - Split pane showing scanned document image/PDF viewer + extracted party & summary data + 90-day countdown bar + linked Appointment / Reserved File / Nearest Station badges.
  - **بطاقة نظر الضابط بالشكوى:** Action select + Officer Notes textarea + Submit button (`حفظ إجراء وملاحظات الضابط` / `إرسال لرئيس القسم` / `تحديث حالة التنفيذ`).
  - **بطاقة تنسيب رئيس القسم (Admin only):** `مشروحات القسم` textarea + `الإجراء المنسب` select + Nearest Station confirm/override + `رفع للحاكم الإداري`.
  - **بطاقة قرار الحاكم الإداري (Governor only):** `موافقة` / `تغيير الإجراء المنسب` / `رفض` buttons + Final Action selector + Governor Decision Notes + `تثبيت القرار وتنفيذ التكامل التلقائي`.
  - Timeline log (`#pcWorkflowLogContainer`), 90-day Follow-up button, `📄 تصدير Word (.docx)`, and `🖨️ طباعة الكشف الرسمي`.
- Add `#modalLlmSettings` (Admin only) for selecting Provider (`Gemini` / `OpenAI` / `Ollama`), Model Name, Base URL, API Key (placeholder showing masked state), and `🧪 اختبار الاتصال`.
- Update `#modalNewOfficer` role `<select>` to include `<option value="governor">الحاكم الإداري (المتصرف)</option>` and checkbox `value="police_complaints"`.
- Update `#tab-admin_permissions` table header with `<th>الشكاوى الذكية</th>`.
- Load `<script src="/complaints/js/police_complaints.js?v=1.46.0"></script>` before `app.js`.
- Add clean Glassmorphic + Print styles in `complaints/css/design-system.css`.

- [ ] **Step 3: Update `complaints/js/app.js`**

- Add `'governor': 'الحاكم الإداري (المتصرف)'` to `roleLabels` in `renderUserInfo()` and `loadOfficersTable()`.
- Update `renderDynamicNavigation()` to add `⚖️ الشكاوى الأمنية الذكية` nav button (`switchTab('police-complaints')`) when `isAdmin || role === 'governor' || tools.includes('police_complaints')`.
- In `DOMContentLoaded`, if `user.role === 'governor'`, default to `switchTab('police-complaints')` so the Governor lands immediately on their approval queue.
- Update `switchTab('police-complaints')` to call `if (typeof loadPoliceComplaintsTab === 'function') loadPoliceComplaintsTab();`.
- Update `loadAdminPermissions()` & `loadOfficersTable()` tool map for `'police_complaints': 'الشكاوى الذكية'`.
- Update `performSearch()` to render `data.police_complaints` clickable results calling `openPoliceComplaintDetail(c.id)`.

- [ ] **Step 4: Commit UI shell changes**

```bash
git add complaints/login.html complaints/app.html complaints/js/app.js complaints/css/design-system.css
git commit -m "feat(ui): add police complaints tab, governor portal, permissions, and styles"
```

---

### Task 7: Frontend Scanner, AI Review, Officer/Section Head/Governor Logic (`complaints/js/police_complaints.js`)

**Files:**
- Create: `complaints/js/police_complaints.js`

**Interfaces:**
- Exposes globals used by `app.html` & `app.js`:
  - `loadPoliceComplaintsTab()`
  - `openPoliceComplaintDetail(id)`
  - `toggleScannerIntakePanel(forceOpen)`
  - `openLlmSettingsModal()`

- [ ] **Step 1: Implement `complaints/js/police_complaints.js` with strict XSS-safe DOM rendering**

Include:
1. Safe `pcEscape(str)` helper + DOM builder utilities (`createEl(tag, attrs, text)`). Never inject OCR/DB strings into unescaped `innerHTML`.
2. Scanner file selection (`<input type="file" accept="image/jpeg,image/png,image/webp,application/pdf">`), Drag-and-Drop zone, Clipboard paste (`paste` event for scanner/screenshot pasting), and Camera capture option.
3. Base64 conversion + `POST /api/v1/mat/police-complaints/scan-extract`:
   - Shows loading spinner `جاري قراءة الخط اليدوي وتحليل الشكوى بالذكاء الاصطناعي...`.
   - Displays uploaded scan preview (`<img>` or `<iframe/object>` using authenticated `/api/v1/mat/police-complaints/scans/<scan_id>`).
   - Populates extracted fields, multi-row complainants & respondents tables (with Add/Remove row buttons), AI Analysis & Recommendation card (`مشكلة خفيفة تتطلب شرطة` vs `غير مشمولة/قضائية`, التوصية بالحل، الإجراء المقترح), and calls `GET /api/v1/mat/police-complaints/match-station` whenever respondent address changes!
   - Also provides `"🗺️ معاينة في دليل المراكز"` shortcut switching to `stations` tab or opening `/finder?q=<address>`.
4. Save / Submit actions:
   - Employee can save draft (`draft_scan`) or submit directly to Section Head (`pending_section_head`) or record Officer initial action & notes right away!
5. Detail modal controller (`openPoliceComplaintDetail(id)`):
   - Renders role-aware panels:
     - **Officer panel (`officer` / `admin`):** Shows Action dropdown + Notes textarea + Save/Send or Update Execution Status (`in_execution` / `completed`).
     - **Section Head panel (`admin`):** Shows `مشروحات القسم`, `الإجراء المنسب`, Nearest Station override selector, `رفع للحاكم الإداري`.
     - **Governor panel (`governor` only):** Shows `✅ موافقة`, `✏️ تغيير الإجراء المنسب`, `❌ رفض`, New Action selector (shown on Modify), Governor notes, and instant status update + toolkit integration confirmation toast!
   - Renders 90-day counter pill + `"🔄 تسجيل متابعة الشاكي"` + `"⛔ تفعيل كف الطلب (90 يوماً)"` (when >= 90 days) + `"📄 تصدير نموذج Word (.docx)"` + `"🖨️ طباعة الكشف الرسمي"`.
6. Admin LLM Settings controller (`openLlmSettingsModal`, `saveLlmSettings`, `testLlmSettings`).

- [ ] **Step 2: Run browser syntax check / lint check on JS**

Run: `node --check complaints/js/police_complaints.js ; node --check complaints/js/app.js` (if Node.js is installed, or Python check + Playwright test in Task 8).

- [ ] **Step 3: Commit `police_complaints.js`**

```bash
git add complaints/js/police_complaints.js
git commit -m "feat(frontend): implement scanner OCR workflow, officer/governor actions, and MAT integrations"
```

---

### Task 8: Version Synchronization (`v1.46.0`), `mzt agent guide` Update, and End-to-End Verification

**Files:**
- Modify: `server.py:5`
- Modify: `complaints/app.html:42,919`
- Modify: `complaints/login.html:341`
- Modify: `complaints/js/app.js:381`
- Modify: `index.html:98`
- Modify: `Police_Station_Finder.html:1711`
- Modify: `README.md:6`
- Modify: `mzt agent guide/rules.md`, `mzt agent guide/dictionary.md`, `mzt agent guide/features.md`, `mzt agent guide/schema.md`, `mzt agent guide/architecture.md`, `mzt agent guide/api.md`

- [ ] **Step 1: Sync version `v1.46.0` across all project files & update `mzt agent guide/*.md`**

Ensure every file reflects `1.46.0` (including `?v=1.46.0` script tags and CSS `?v=25`), and all 6 mandatory guide files inside `mzt agent guide/` document the new `governor` role, new `mat_*` tables/columns/indexes, new `/api/v1/mat/police-complaints/*` and `/api/v1/mat/llm-settings` endpoints, and new architectural files (`mat_llm_engine.py`, `mat_complaints_service.py`, `complaints/js/police_complaints.js`).

- [ ] **Step 2: Run complete backend unit and API integration tests**

Run: `python -m unittest discover -s tests -v`
Expected: All unit & API integration tests PASS with zero errors.

- [ ] **Step 3: Run live `127.0.0.1` server & browser verification (Playwright or HTTP smoke test)**

Start server bound to `127.0.0.1` on a test port with a temporary DB copy, verify login as `ehab` -> scan/create -> officer action -> login as `orwa` -> section head recommend -> login as `governor` -> approve/modify -> verify auto-created appointment, reserved file, `.docx` export, and console zero errors, then stop server cleanly.

- [ ] **Step 4: Commit version sync and docs**

```bash
git add .
git commit -m "chore(v1.46.0): sync version numbers, update mzt agent guide, and verify police complaints module"
```
