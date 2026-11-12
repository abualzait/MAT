import hashlib
import io
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from unittest import mock

import server
import mat_llm_engine
import mat_complaints_service



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
        try:
            # Governor account must exist and role check must allow 'governor'
            gov = conn.execute(
                "SELECT username, role, accessible_tools FROM mat_officers WHERE username = 'governor'"
            ).fetchone()
            self.assertIsNotNone(gov)
            self.assertEqual(gov["role"], "governor")
            self.assertIn("police_complaints", gov["accessible_tools"])

            # Orwa must retain data and receive police_complaints access
            orwa = conn.execute(
                "SELECT accessible_tools FROM mat_officers WHERE username = 'orwa'"
            ).fetchone()
            self.assertIn("police_complaints", orwa["accessible_tools"])

            # Extended columns on mat_complaints
            cols = {r[1] for r in conn.execute("PRAGMA table_info(mat_complaints)").fetchall()}
            for required_col in (
                "workflow_stage",
                "officer_action",
                "officer_notes",
                "section_head_notes",
                "governor_decision",
                "nearest_station",
                "last_followup_at",
            ):
                self.assertIn(required_col, cols)

            # New tables exist
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "mat_complaint_scans",
                    "mat_complaint_workflow_log",
                    "mat_llm_settings",
                }.issubset(tables)
            )
        finally:
            conn.close()

    def test_init_db_preserves_existing_officers_foreign_keys_and_indexes(self):
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE mat_officers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'officer', 'caller')),
                accessible_tools TEXT DEFAULT 'dashboard,mat_complaints,finder,chat',
                is_active INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime')),
                fcm_token TEXT
            );
            CREATE TABLE mat_complaints (
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
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE mat_parties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
                party_type TEXT NOT NULL CHECK(party_type IN ('شاكي', 'مشتكى_عليه')),
                name TEXT NOT NULL,
                phone TEXT,
                national_id TEXT,
                address TEXT,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE mat_sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES mat_officers(id),
                username TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                accessible_tools TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                last_seen TEXT DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE mat_chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES mat_officers(id),
                message TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO mat_officers (id, name, username, password_hash, salt, role, fcm_token)
            VALUES
                (1, 'عروة', 'orwa', 'pbkdf2:hash1', 'salt1', 'admin', 'fcm-orwa'),
                (2, 'ايهاب', 'ehab', 'pbkdf2:hash2', 'salt2', 'officer', NULL),
                (3, 'سلطان', 'sultan', 'pbkdf2:hash3', 'salt3', 'officer', NULL),
                (4, 'ابوالزيت', 'abualzait', 'pbkdf2:hash4', 'salt4', 'officer', NULL),
                (5, 'رعد', 'raad', 'pbkdf2:hash5', 'salt5', 'caller', NULL);
            INSERT INTO mat_complaints (id, complaint_number, subject, assigned_officer_id, created_by_id)
            VALUES (10, 'C-10', 'شكوى قديمة', 2, 1);
            INSERT INTO mat_sessions (token, user_id, username, role, name, accessible_tools)
            VALUES ('tok-1', 1, 'orwa', 'admin', 'عروة', 'dashboard,mat_complaints');
            INSERT INTO mat_chat_messages (user_id, message) VALUES (1, 'مرحبا');
        """)
        conn.commit()
        conn.close()

        server.init_db()

        conn = server.get_db()
        try:
            # Verify all 5 original officers retain exact credentials & fcm_token
            officers = {
                r["username"]: dict(r)
                for r in conn.execute("SELECT * FROM mat_officers").fetchall()
            }
            self.assertEqual(officers["orwa"]["password_hash"], "pbkdf2:hash1")
            self.assertEqual(officers["orwa"]["salt"], "salt1")
            self.assertEqual(officers["orwa"]["fcm_token"], "fcm-orwa")
            self.assertEqual(officers["ehab"]["password_hash"], "pbkdf2:hash2")
            self.assertEqual(officers["sultan"]["role"], "officer")
            self.assertEqual(officers["abualzait"]["role"], "officer")
            self.assertEqual(officers["raad"]["role"], "caller")
            self.assertIn("police_complaints", officers["ehab"]["accessible_tools"])
            self.assertNotIn("police_complaints", officers["raad"]["accessible_tools"])

            # Verify FK-linked rows remain intact and FK check passes
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM mat_sessions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM mat_chat_messages").fetchone()[0], 1)
            legacy_c = conn.execute("SELECT subject, last_followup_at FROM mat_complaints WHERE id = 10").fetchone()
            self.assertEqual(legacy_c["subject"], "شكوى قديمة")
            self.assertIsNotNone(legacy_c["last_followup_at"])
            fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
            self.assertEqual(fk_errors, [])

            # Verify mat_parties extended column and all new indexes
            party_cols = {r[1] for r in conn.execute("PRAGMA table_info(mat_parties)").fetchall()}
            self.assertIn("party_category", party_cols)

            indexes = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
            }
            self.assertTrue(
                {
                    "idx_mat_complaints_stage",
                    "idx_mat_complaints_followup",
                    "idx_mat_complaint_scans_cid",
                    "idx_mat_complaint_log_cid",
                }.issubset(indexes)
            )
        finally:
            conn.close()

    def test_init_db_fresh_database_seeds_governor_and_all_defaults(self):
        server.init_db()
        conn = server.get_db()
        try:
            officers = {
                r["username"]: dict(r)
                for r in conn.execute("SELECT * FROM mat_officers").fetchall()
            }
            for uname in ("orwa", "ehab", "sultan", "abualzait", "raad", "governor"):
                self.assertIn(uname, officers)
            gov = officers["governor"]
            self.assertEqual(gov["name"], "عطوفة المتصرف")
            self.assertEqual(gov["role"], "governor")
            self.assertEqual(gov["accessible_tools"], "dashboard,police_complaints,finder,chat")

            # Verify governor password '12345' hashes correctly
            expected_hash = "pbkdf2:" + hashlib.pbkdf2_hmac(
                "sha256", b"12345", gov["salt"].encode(), 100000
            ).hex()
            self.assertEqual(gov["password_hash"], expected_hash)
            self.assertIn("police_complaints", officers["orwa"]["accessible_tools"])
            self.assertIn("police_complaints", officers["ehab"]["accessible_tools"])
        finally:
            conn.close()

    def test_backup_and_restore_excludes_api_key_and_preserves_extended_columns(self):
        server.init_db()
        conn = server.get_db()
        try:
            gov_id = conn.execute("SELECT id FROM mat_officers WHERE username='governor'").fetchone()["id"]
            admin_id = conn.execute("SELECT id FROM mat_officers WHERE username='orwa'").fetchone()["id"]
            officer_id = conn.execute("SELECT id FROM mat_officers WHERE username='ehab'").fetchone()["id"]

            conn.execute(
                """
                INSERT INTO mat_complaints (
                    id, complaint_number, subject, complaint_type, status, priority, notes,
                    assigned_officer_id, created_by_id,
                    paper_date, complainant_category, respondent_category, summary,
                    has_signature, no_pending_lawsuit_declared, workflow_stage,
                    is_minor_police_complaint, ai_provider, ai_model, ai_extracted_json,
                    ai_analysis, ai_solution_recommendation, ai_recommended_action, ai_confidence,
                    officer_action, officer_notes, officer_reviewed_by_id, officer_reviewed_at,
                    section_head_notes, section_recommended_action, section_head_id, section_head_at,
                    governor_decision, governor_final_action, governor_notes, governor_id, governor_decided_at,
                    nearest_station, police_directorate, liwa_name, station_lat, station_lon,
                    linked_appointment_id, linked_file_number, last_followup_at
                ) VALUES (
                    101, 'PC-20261110-0101', 'موضوع شكوى', 'عام', 'معتمدة', 'عاجل', 'ملاحظة عامة',
                    ?, ?,
                    '2026-11-10', 'مؤسسة تجارية', 'منشأة', 'موجز تفصيلي للشكوى',
                    1, 1, 'governor_approved',
                    1, 'gemini', 'gemini-2.5-flash', '{"raw":true}',
                    'تحليل ذكي', 'توصية حل', 'توديع عن طريق مركز أمني', 0.91,
                    'توديع عن طريق مركز أمني', 'ملاحظة الضابط', ?, '2026-11-10 09:00:00',
                    'مشروحات القسم', 'توديع عن طريق مركز أمني', ?, '2026-11-10 09:30:00',
                    'موافقة', 'توديع عن طريق مركز أمني', 'قرار المتصرف', ?, '2026-11-10 10:00:00',
                    'مركز أمن تلاع العلي', 'مديرية شرطة شمال عمان', 'لواء الجامعة', 31.99, 35.87,
                    77, 'PC-20261110-0101', '2026-11-10 10:00:00'
                )
                """,
                (officer_id, officer_id, officer_id, admin_id, gov_id),
            )
            conn.execute(
                """
                INSERT INTO mat_parties (id, complaint_id, party_type, party_category, name, phone, address)
                VALUES (201, 101, 'شاكي', 'مؤسسة تجارية', 'شركة الأفق', '0791234567', 'الشميساني')
                """
            )
            conn.execute(
                """
                INSERT INTO mat_complaint_scans (
                    id, complaint_id, stored_filename, original_filename, mime_type,
                    file_size, page_order, ocr_raw_text, uploaded_by_id
                ) VALUES (301, 101, 'abc123.png', 'scan1.png', 'image/png', 1024, 1, 'نص مستخرج', ?)
                """,
                (officer_id,),
            )
            conn.execute(
                """
                INSERT INTO mat_complaint_workflow_log (
                    id, complaint_id, actor_id, actor_role, stage_from, stage_to, action_taken, notes
                ) VALUES (401, 101, ?, 'governor', 'pending_governor', 'governor_approved', 'موافقة', 'تم الاعتماد')
                """,
                (gov_id,),
            )
            conn.execute(
                """
                INSERT INTO mat_llm_settings (id, provider, model_name, api_base_url, api_key, is_enabled, updated_by_id)
                VALUES (1, 'gemini', 'gemini-2.5-pro', 'https://example.invalid', 'SUPER_SECRET_API_KEY_98765', 1, ?)
                """,
                (admin_id,),
            )
            conn.commit()

            server.backup_db_to_json(conn)
        finally:
            conn.close()

        # Verify backup JSON excludes api_key and contains new tables
        with open(self.backup_path, "r", encoding="utf-8") as f:
            backup_raw = f.read()
        self.assertNotIn("SUPER_SECRET_API_KEY_98765", backup_raw)
        backup_data = json.loads(backup_raw)
        self.assertEqual(len(backup_data["complaint_scans"]), 1)
        self.assertEqual(len(backup_data["complaint_workflow_log"]), 1)
        self.assertEqual(len(backup_data["llm_settings"]), 1)
        self.assertNotIn("api_key", backup_data["llm_settings"][0])
        self.assertEqual(backup_data["complaints"][0]["governor_decision"], "موافقة")

        # Restore into a brand new empty DB (without running backup_db_to_json overwrite first)
        os.remove(self.db_path)
        server.init_db()
        conn = server.get_db()
        try:
            restored_c = dict(conn.execute("SELECT * FROM mat_complaints WHERE id = 101").fetchone())
            self.assertEqual(restored_c["paper_date"], "2026-11-10")
            self.assertEqual(restored_c["complainant_category"], "مؤسسة تجارية")
            self.assertEqual(restored_c["respondent_category"], "منشأة")
            self.assertEqual(restored_c["workflow_stage"], "governor_approved")
            self.assertEqual(restored_c["officer_notes"], "ملاحظة الضابط")
            self.assertEqual(restored_c["section_head_notes"], "مشروحات القسم")
            self.assertEqual(restored_c["governor_decision"], "موافقة")
            self.assertEqual(restored_c["nearest_station"], "مركز أمن تلاع العلي")
            self.assertAlmostEqual(restored_c["station_lat"], 31.99)
            self.assertEqual(restored_c["linked_appointment_id"], 77)
            self.assertEqual(restored_c["linked_file_number"], "PC-20261110-0101")

            restored_p = conn.execute("SELECT party_category FROM mat_parties WHERE id = 201").fetchone()
            self.assertEqual(restored_p["party_category"], "مؤسسة تجارية")
            restored_s = conn.execute("SELECT stored_filename FROM mat_complaint_scans WHERE id = 301").fetchone()
            self.assertEqual(restored_s["stored_filename"], "abc123.png")
            restored_l = conn.execute("SELECT action_taken FROM mat_complaint_workflow_log WHERE id = 401").fetchone()
            self.assertEqual(restored_l["action_taken"], "موافقة")

            # Now set an api_key in DB and restore again from backup (which lacks api_key):
            # existing api_key MUST NOT be overwritten with empty string
            conn.execute("UPDATE mat_llm_settings SET api_key = 'LIVE_SECRET_KEY_111' WHERE id = 1")
            conn.commit()
            server.restore_db_from_json(conn)
            live_row = conn.execute("SELECT api_key, model_name FROM mat_llm_settings WHERE id = 1").fetchone()
            self.assertEqual(live_row["api_key"], "LIVE_SECRET_KEY_111")
            self.assertEqual(live_row["model_name"], "gemini-2.5-pro")
        finally:
            conn.close()

    def test_api_login_httponly_cookie_and_governor_default_names_fallback(self):
        server.init_db()
        # Delete governor from DB so api_login exercises default_names fallback as well
        conn = server.get_db()
        conn.execute("DELETE FROM mat_officers WHERE username = 'governor'")
        conn.commit()
        conn.close()

        httpd = server.ThreadedHTTPServer(("127.0.0.1", 0), server.MatServerHandler)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/v1/mat/login",
                data=json.dumps({"username": "governor"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                cookies = resp.headers.get_all("Set-Cookie") or []
                body = json.loads(resp.read().decode("utf-8"))

            session_cookies = [c for c in cookies if c.startswith("session=")]
            csrf_cookies = [c for c in cookies if c.startswith("csrf_token=")]
            self.assertEqual(len(session_cookies), 1)
            self.assertEqual(len(csrf_cookies), 1)
            self.assertIn("HttpOnly", session_cookies[0])
            self.assertIn("SameSite=Lax", session_cookies[0])
            self.assertNotIn("HttpOnly", csrf_cookies[0])
            self.assertIn("SameSite=Lax", csrf_cookies[0])

            self.assertEqual(body["user"]["role"], "governor")
            self.assertEqual(body["user"]["name"], "عطوفة المتصرف")
            self.assertIn("police_complaints", body["user"]["accessible_tools"])
        finally:
            httpd.shutdown()
            httpd.server_close()



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
        called_req = m_open.call_args[0][0]
        self.assertNotIn("fake-key", called_req.full_url)
        self.assertEqual(called_req.get_header("X-goog-api-key"), "fake-key")

    def test_extract_returns_manual_fallback_when_api_key_missing(self):
        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "", "api_base_url": "", "is_enabled": 1}
        res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", settings)
        self.assertEqual(res["status"], "manual_fallback")
        self.assertIn("API key", res["message"])

    def test_extract_returns_manual_fallback_when_disabled(self):
        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "key", "api_base_url": "", "is_enabled": 0}
        res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", settings)
        self.assertEqual(res["status"], "manual_fallback")
        self.assertIn("disabled", res["message"])

    def test_openai_payload_construction_and_parsing(self):
        fake_llm_json = {
            "subject": "شكوى اعتداء صوتي",
            "summary": "إزعاج من ورشة مجاورة",
            "ai_recommended_action": "اتصال هاتفي",
            "is_minor_police_complaint": True
        }
        fake_resp_body = json.dumps({
            "choices": [{"message": {"content": json.dumps(fake_llm_json)}}]
        }).encode("utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = fake_resp_body
        mock_resp.__enter__.return_value = mock_resp

        settings = {
            "provider": "openai",
            "model_name": "gpt-4o",
            "api_key": "sk-proj-test12345",
            "api_base_url": "https://api.openai.com/v1",
            "is_enabled": 1
        }
        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as m_open:
            res = mat_llm_engine.extract_and_analyze_complaint(b"fakeimagebytes", "image/jpeg", settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["extracted"]["subject"], "شكوى اعتداء صوتي")
        self.assertEqual(res["analysis"]["ai_recommended_action"], "اتصال هاتفي")
        req = m_open.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/chat/completions"))
        self.assertEqual(req.get_header("Authorization"), "Bearer sk-proj-test12345")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "gpt-4o")
        self.assertIn("data:image/jpeg;base64,", payload["messages"][0]["content"][1]["image_url"]["url"])

    def test_openai_rejects_pdf_with_manual_fallback(self):
        settings = {"provider": "openai", "model_name": "gpt-4o", "api_key": "sk-test", "api_base_url": "", "is_enabled": 1}
        res = mat_llm_engine.extract_and_analyze_complaint(b"%PDF-1.4", "application/pdf", settings)
        self.assertEqual(res["status"], "manual_fallback")
        self.assertIn("PDF", res["message"])

    def test_ollama_payload_construction_and_parsing(self):
        fake_llm_json = {
            "subject": "شكوى تسرب مياه",
            "summary": "تسرب مياه في منور عمارة",
            "ai_recommended_action": "توديع مغفور",
            "is_minor_police_complaint": True
        }
        fake_resp_body = json.dumps({
            "message": {"content": json.dumps(fake_llm_json)}
        }).encode("utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = fake_resp_body
        mock_resp.__enter__.return_value = mock_resp

        settings = {
            "provider": "ollama",
            "model_name": "llama3.2-vision",
            "api_key": "",
            "api_base_url": "http://127.0.0.1:11434",
            "is_enabled": 1
        }
        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as m_open:
            res = mat_llm_engine.extract_and_analyze_complaint(b"imagebytes", "image/png", settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["extracted"]["subject"], "شكوى تسرب مياه")
        self.assertEqual(res["analysis"]["ai_recommended_action"], "توديع مغفور")
        req = m_open.call_args[0][0]
        self.assertTrue(req.full_url.endswith("/api/chat"))
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "llama3.2-vision")
        self.assertEqual(payload["format"], "json")
        self.assertEqual(len(payload["messages"][0]["images"]), 1)

    def test_malformed_json_fence_cleanup(self):
        parsed1 = mat_llm_engine._parse_llm_json("```json\n{\"subject\": \"تست 1\"}\n```")
        self.assertEqual(parsed1["subject"], "تست 1")

        parsed2 = mat_llm_engine._parse_llm_json("Here is the output:\n```\n{\"subject\": \"تست 2\", \"has_signature\": true}\n```\nHope this helps!")
        self.assertEqual(parsed2["subject"], "تست 2")
        self.assertTrue(parsed2["has_signature"])

        parsed3 = mat_llm_engine._parse_llm_json("{\"subject\": \"تست 3\"}")
        self.assertEqual(parsed3["subject"], "تست 3")

        parsed4 = mat_llm_engine._parse_llm_json("This is not JSON at all")
        self.assertEqual(parsed4, {})

    def test_extract_unparseable_llm_output_returns_manual_fallback(self):
        conversational_refusal = "عذراً، لا يمكنني قراءة هذه الصورة بسبب عدم وضوح الخط."
        fake_resp_body = json.dumps({
            "candidates": [{"content": {"parts": [{"text": conversational_refusal}]}}]
        }).encode("utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = fake_resp_body
        mock_resp.__enter__.return_value = mock_resp

        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "fake-key", "api_base_url": "", "is_enabled": 1}
        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            res = mat_llm_engine.extract_and_analyze_complaint(b"imagebytes", "image/png", settings)

        self.assertEqual(res["status"], "manual_fallback")
        self.assertEqual(res["raw_text"], conversational_refusal)
        self.assertIn("could not be parsed as structured JSON", res["message"])
        self.assertEqual(res["extracted"], {})
        self.assertEqual(res["analysis"], {})

    def test_llm_connection_success_and_failure(self):
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps({"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        settings = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "SECRET_KEY_1234", "api_base_url": "", "is_enabled": 1}
        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            res = mat_llm_engine.test_llm_connection(settings)
        self.assertTrue(res["ok"])
        self.assertEqual(res["provider"], "gemini")

        settings_nokey = {"provider": "gemini", "model_name": "gemini-2.5-flash", "api_key": "", "api_base_url": "", "is_enabled": 1}
        res_nokey = mat_llm_engine.test_llm_connection(settings_nokey)
        self.assertFalse(res_nokey["ok"])
        self.assertIn("API key", res_nokey["message"])

        with mock.patch("urllib.request.urlopen", side_effect=Exception("HTTP 403 Forbidden with key SECRET_KEY_1234")):
            res_err = mat_llm_engine.test_llm_connection(settings)
        self.assertFalse(res_err["ok"])
        self.assertNotIn("SECRET_KEY_1234", res_err["message"])
        self.assertIn("[REDACTED]", res_err["message"])

        # HTTPError body extraction + AQ.* key redaction
        import io as _io
        import urllib.error as _uerr
        http_err = _uerr.HTTPError(
            url="https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
            code=402,
            msg="Payment Required",
            hdrs=None,
            fp=_io.BytesIO(json.dumps({
                "error": {
                    "code": 402,
                    "message": "Your prepayment credits are depleted for AQ.Ab8RN6JY-bZOOfGOxgr3-TestFakeKey123."
                }
            }).encode("utf-8")),
        )
        with mock.patch("urllib.request.urlopen", side_effect=http_err):
            res_402 = mat_llm_engine.test_llm_connection(settings)
        self.assertFalse(res_402["ok"])
        self.assertIn("402", res_402["message"])
        self.assertIn("prepayment credits are depleted", res_402["message"])
        self.assertNotIn("AQ.Ab8RN6JY", res_402["message"])
        self.assertIn("[REDACTED]", res_402["message"])

        # Non-JSON plain "OK\r\n" 200 stub (e.g. retired endpoints) must fail connection test
        plain_ok_resp = mock.MagicMock()
        plain_ok_resp.status = 200
        plain_ok_resp.read.return_value = b"OK\r\n"
        plain_ok_resp.__enter__.return_value = plain_ok_resp
        oai_settings = {"provider": "openai", "model_name": "google/gemma-4-31b-it:free", "api_base_url": "https://openrouter.ai/api/v1", "api_key": "github_pat_FakeToken1234567890", "is_enabled": 1}
        with mock.patch("urllib.request.urlopen", return_value=plain_ok_resp):
            res_stub = mat_llm_engine.test_llm_connection(oai_settings)
        self.assertFalse(res_stub["ok"])
        self.assertIn("valid AI completion JSON", res_stub["message"])

        # _call_openai falls back cleanly without response_format if HTTP 400 rejects response_format
        rf_err = _uerr.HTTPError(
            url="https://openrouter.ai/api/v1/chat/completions",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=_io.BytesIO(b'{"error":{"message":"response_format json_object is not supported for this model"}}'),
        )
        ok_oai_resp = mock.MagicMock()
        ok_oai_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": json.dumps({"subject": "شكوى اختبار", "summary": "ملخص", "ai_recommended_action": "اتصال هاتفي"}, ensure_ascii=False)}}]
        }).encode("utf-8")
        ok_oai_resp.__enter__.return_value = ok_oai_resp
        sent_payloads = []

        def fake_urlopen(req, timeout=60):
            sent_payloads.append(json.loads(req.data.decode("utf-8")))
            if len(sent_payloads) == 1:
                raise rf_err
            return ok_oai_resp

        with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
            res_rf = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", oai_settings)
        self.assertEqual(res_rf["status"], "ok")
        self.assertEqual(res_rf["extracted"]["subject"], "شكوى اختبار")
        self.assertIn("response_format", sent_payloads[0])
        self.assertNotIn("response_format", sent_payloads[1])
        self.assertEqual(sent_payloads[0]["temperature"], 0.1)
        self.assertEqual(sent_payloads[0]["frequency_penalty"], 0.2)
        self.assertEqual(sent_payloads[0]["messages"][0]["content"][1]["image_url"]["detail"], "high")
        self.assertIn("google/gemma-4-31b-it:free", sent_payloads[0]["models"])

    def test_openrouter_free_routing_and_mixed_script_repair_digit_lock(self):
        # Known-weak nemotron-3.5-super-vl:free gets routed via reliable vision fallback chain
        candidates = mat_llm_engine._resolve_openrouter_vision_models("nvidia/nemotron-3.5-super-vl:free")
        self.assertEqual(candidates[0], "google/gemma-4-31b-it:free")
        self.assertIn("dots-studio/dots-3-note-preview:free", candidates)

        # Normalize converts Eastern Arabic numerals and clears unreadable placeholders
        ext, _ana = mat_llm_engine._normalize_complaint_result(
            {
                "raw_transcription": "سطر أول",
                "paper_date": "٢٠٢٦/١١/١٠",
                "complainants": [
                    {"party_category": "مواطن", "name": "سالم", "national_id": "٩٨٥١٠٤٢٨١٧", "phone": "٠٧٩٥٤١٢٨٩٠", "address": "عمان"},
                    {"party_category": "مواطن", "name": "[غير واضح]", "national_id": "", "phone": "", "address": "غير واضح"},
                ],
                "respondents": [],
                "subject": "إغلاق كراج",
                "summary": "شكوى",
            }
        )
        self.assertEqual(ext["raw_transcription"], "سطر أول")
        self.assertEqual(ext["paper_date"], "2026/11/10")
        self.assertEqual(len(ext["complainants"]), 1)
        self.assertEqual(ext["complainants"][0]["national_id"], "9851042817")
        self.assertEqual(ext["complainants"][0]["phone"], "0795412890")

        # Two-stage OCR mixed-script repair cleans foreign noise while locking extracted digits
        dirty_stage1 = {
            "raw_transcription": "سالم 9851042817",
            "paper_date": "2026/11/10",
            "complainants": [{"party_category": "مواطن", "name": "سالم", "national_id": "9851042817", "phone": "0795412890", "address": "ضاحية الياسمين"}],
            "respondents": [{"party_category": "مواطن", "name": "إبراهيم", "national_id": "9901037419", "phone": "0788123456", "address": "ضاحية الياسمين"}],
            "subject": "إغلاق كراج Buildings",
            "summary": "يقوم بإغلاق مدخل البناء والREFUSE المكرر",
            "has_signature": True,
            "no_pending_lawsuit_declared": False,
        }
        repaired_stage2_corrupted_digits = {
            **dirty_stage1,
            "subject": "إغلاق مدخل الكراج",
            "summary": "يقوم بإغلاق مدخل البناء والرفض المكرر",
            "no_pending_lawsuit_declared": True,
            "respondents": [{"party_category": "مواطن", "name": "إبراهيم خليل", "national_id": "1111111111", "phone": "0700000000", "address": "ضاحية الياسمين"}],
            "ai_recommended_action": "توديع عن طريق مركز أمني",
        }
        calls = []

        def fake_post(req, timeout=60):
            calls.append(json.loads(req.data.decode("utf-8")))
            resp = mock.MagicMock()
            body = dirty_stage1 if len(calls) == 1 else repaired_stage2_corrupted_digits
            routed = "dots-studio/dots-3-note-preview:free" if len(calls) == 1 else "nvidia/nemotron-3-ultra-550b-a55b:free"
            resp.read.return_value = json.dumps(
                {"model": routed, "choices": [{"message": {"content": json.dumps(body, ensure_ascii=False)}}]}
            ).encode("utf-8")
            resp.__enter__.return_value = resp
            return resp

        or_settings = {
            "provider": "openai",
            "model_name": "dots-studio/dots-3-note-preview:free",
            "api_base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-test-key",
            "is_enabled": 1,
        }
        with mock.patch("urllib.request.urlopen", side_effect=fake_post):
            res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", or_settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(len(calls), 2)
        self.assertEqual(res["extracted"]["subject"], "إغلاق مدخل الكراج")
        self.assertEqual(res["extracted"]["summary"], "يقوم بإغلاق مدخل البناء والرفض المكرر")
        self.assertTrue(res["extracted"]["no_pending_lawsuit_declared"])
        # Digit lock must keep Stage 1 IDs/phones even if Stage 2 altered them
        self.assertEqual(res["extracted"]["respondents"][0]["national_id"], "9901037419")
        self.assertEqual(res["extracted"]["respondents"][0]["phone"], "0788123456")
        self.assertEqual(res["extracted"]["respondents"][0]["name"], "إبراهيم خليل")

    def test_nvidia_nim_payload_auto_url_and_redaction(self):
        # nvapi-* keys automatically resolve to integrate.api.nvidia.com/v1 when base_url is blank
        # and omit response_format / image_url.detail so NVIDIA NIM Gemma 4 does not hang
        fake_nim_json = {
            "raw_transcription": "شكوى اختبار",
            "paper_date": "2026/11/10",
            "complainants": [{"party_category": "مواطن", "name": "سالم", "national_id": "9851042817", "phone": "0795412890", "address": "ضاحية الياسمين"}],
            "respondents": [],
            "subject": "موضوع اختباري",
            "summary": "ملخص واضح",
            "has_signature": True,
            "no_pending_lawsuit_declared": True,
            "ai_recommended_action": "اتصال هاتفي",
        }
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"model": "google/gemma-4-31b-it", "choices": [{"message": {"content": json.dumps(fake_nim_json, ensure_ascii=False)}}]}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        nim_settings = {
            "provider": "openai",
            "model_name": "google/gemma-4-31b-it",
            "api_base_url": "",
            "api_key": "nvapi-FakeTestKey1234567890ABCD",
            "is_enabled": 1,
        }
        with mock.patch("urllib.request.urlopen", return_value=mock_resp) as m_open:
            res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", nim_settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["model"], "google/gemma-4-31b-it")
        req = m_open.call_args[0][0]
        self.assertEqual(req.full_url, "https://integrate.api.nvidia.com/v1/chat/completions")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertNotIn("response_format", payload)
        self.assertNotIn("detail", payload["messages"][0]["content"][1]["image_url"])

        # Redaction scrubs nvapi-* keys in error messages
        redacted = mat_llm_engine._redact_secret("Auth failed for nvapi-FakeTestKey1234567890ABCD")
        self.assertNotIn("FakeTestKey", redacted)
        self.assertIn("[REDACTED]", redacted)

        # Groq gsk_ keys resolve cleanly to api.groq.com/openai/v1
        self.assertEqual(
            mat_llm_engine._resolve_openai_base_url("", "gsk_FakeGroqKey123456"),
            "https://api.groq.com/openai/v1",
        )

    def test_cross_provider_fallback_and_rfc7807_error_formatting(self):
        # RFC 7807 NVIDIA 404 body formats cleanly without duplicated "HTTP Error 404: HTTP 404:"
        rfc_err = urllib.error.HTTPError(
            url="https://integrate.api.nvidia.com/v1/chat/completions",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=io.BytesIO(b'{"status":404,"title":"Not Found","detail":"Function id missing"}'),
        )
        fb_ok_resp = mock.MagicMock()
        fb_ok_resp.read.return_value = json.dumps(
            {
                "model": "dots-studio/dots-3-note-preview:free",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "raw_transcription": "شكوى اختبار",
                                    "subject": "موضوع بديل",
                                    "summary": "تفاصيل واضحة",
                                    "ai_recommended_action": "اتصال هاتفي",
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ],
            }
        ).encode("utf-8")
        fb_ok_resp.__enter__.return_value = fb_ok_resp

        nim_settings = {
            "provider": "openai",
            "model_name": "google/gemma-4-31b-it",
            "api_base_url": "https://integrate.api.nvidia.com/v1",
            "api_key": "nvapi-PrimaryDeadKey1234567890",
            "is_enabled": 1,
        }

        called_urls = []

        def fake_failover(req, timeout=60):
            called_urls.append(req.full_url)
            if "integrate.api.nvidia.com" in req.full_url:
                raise rfc_err
            return fb_ok_resp

        # 1) Without fallback configured, returns clean single HTTP 404 message
        err_only = mat_llm_engine._format_http_error(
            urllib.error.HTTPError(
                url="https://integrate.api.nvidia.com/v1/chat/completions",
                code=404,
                msg="HTTP 404: Not Found: Function id missing",
                hdrs=None,
                fp=None,
            )
        )
        self.assertEqual(err_only, "HTTP 404: Not Found: Function id missing")

        # 2) With MAT_FALLBACK_OPENAI_API_KEY configured, fails over cleanly to OpenRouter
        with mock.patch.dict(
            os.environ,
            {
                "MAT_FALLBACK_OPENAI_API_KEY": "sk-or-v1-FallbackKey1234567890",
                "MAT_FALLBACK_OPENAI_BASE_URL": "https://openrouter.ai/api/v1",
                "MAT_FALLBACK_LLM_MODEL": "google/gemma-4-31b-it:free",
            },
            clear=False,
        ):
            with mock.patch("urllib.request.urlopen", side_effect=fake_failover):
                res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", nim_settings)

        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["model"], "dots-studio/dots-3-note-preview:free")
        self.assertEqual(len(called_urls), 2)
        self.assertIn("integrate.api.nvidia.com", called_urls[0])
        self.assertIn("openrouter.ai", called_urls[1])

    def test_anti_hallucination_rejects_dummy_digits_and_garbled_ocr(self):
        # 1) Reject fabricated repeating IDs/phones (e.g. 1111111111) instead of filling official form
        hallucinated = {
            "raw_transcription": "متصرفية لواء قصبة عمان - محافظة 首都\nعطلة مشakra",
            "paper_date": "11/11/2023",
            "complainants": [{"party_category": "مواطن", "name": "دينا", "national_id": "1111111111", "phone": "0797771111", "address": "عمان - حي المonical"}],
            "respondents": [],
            "subject": "اختبار",
            "summary": "نص غير واضح",
            "ai_recommended_action": "اتصال هاتفي",
        }
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = json.dumps(
            {"model": "dots-studio/dots-3-note-preview:free", "choices": [{"message": {"content": json.dumps(hallucinated, ensure_ascii=False)}}]}
        ).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        settings = {
            "provider": "openai",
            "model_name": "gpt-4o",
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "sk-proj-testkey",
            "is_enabled": 1,
        }
        with mock.patch("urllib.request.urlopen", return_value=mock_resp):
            res = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", settings)

        self.assertEqual(res["status"], "manual_fallback")
        self.assertEqual(res["extracted"], {})
        self.assertIn("غير موثوقة", res["message"])

        # 2) Reject mixed Arabic-Latin splice or CJK even when digits look normal
        ext_splice, ana_splice = mat_llm_engine._normalize_complaint_result(
            {
                "raw_transcription": "حي المonical",
                "complainants": [{"party_category": "مواطن", "name": "سالم", "national_id": "9851042817", "phone": "0795412890", "address": "عمان - حي المonical"}],
                "respondents": [],
                "subject": "موضوع",
                "summary": "تفاصيل واضحة",
                "ai_confidence": 0.9,
            }
        )
        reason = mat_llm_engine._detect_unreliable_extraction(ext_splice, ana_splice)
        self.assertIn("تعذرت قراءة الخط اليدوي", reason)

        # 3) Groq gsk_ caps max_tokens=900 for 1000 OTPM budget, redacts gsk_, and rejects low-confidence blurry scans
        self.assertNotIn("SecretValue", mat_llm_engine._redact_secret("Error gsk_SecretValue1234567890ABCD"))
        blurry_json = {
            "raw_transcription": "[غير واضح]",
            "complainants": [],
            "respondents": [],
            "subject": "شكوى غير مقروءة",
            "summary": "تعذر القراءة",
            "ai_confidence": 0.1,
        }
        mock_groq = mock.MagicMock()
        mock_groq.read.return_value = json.dumps(
            {"model": "qwen/qwen3.8-27b", "choices": [{"message": {"content": json.dumps(blurry_json, ensure_ascii=False)}}]}
        ).encode("utf-8")
        mock_groq.__enter__.return_value = mock_groq
        groq_settings = {
            "provider": "openai",
            "model_name": "qwen/qwen3.8-27b",
            "api_base_url": "",
            "api_key": "gsk_FakeGroqKey1234567890ABCD",
            "is_enabled": 1,
        }
        with mock.patch("urllib.request.urlopen", return_value=mock_groq) as m_groq:
            res_blurry = mat_llm_engine.extract_and_analyze_complaint(b"\x89PNG\r\n\x1a\nfake", "image/png", groq_settings)

        req_groq = m_groq.call_args[0][0]
        self.assertEqual(req_groq.full_url, "https://api.groq.com/openai/v1/chat/completions")
        sent_groq = json.loads(req_groq.data.decode("utf-8"))
        self.assertEqual(sent_groq["max_tokens"], 900)
        self.assertEqual(res_blurry["status"], "manual_fallback")
        self.assertIn("تعذر استخراج نص واضح", res_blurry["message"])


class TestComplaintsUtilities(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scans_dir = os.path.join(self.tmpdir.name, "complaint_scans")
        os.makedirs(self.scans_dir, exist_ok=True)
        self.base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_normalize_arabic(self):
        raw = "أحمد إبراهيم آمنة مُحَمَّد، هبة ومصطفى؛ شارع 14؟"
        norm = mat_complaints_service.normalize_arabic(raw)
        self.assertEqual(norm, "احمد ابراهيم امنه محمد هبه ومصطفي شارع 14")

    def test_validate_and_store_scan_rejects_spoofed_and_oversized_files(self):
        # Spoofed .jpg containing HTML script
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(b"<script>alert(1)</script>", "evil.jpg", self.scans_dir)

        # Path traversal attempt in resolve_scan_path
        with self.assertRaises(ValueError):
            mat_complaints_service.resolve_scan_path("../server.py", self.scans_dir)

        with self.assertRaises(ValueError):
            mat_complaints_service.resolve_scan_path("..\\server.py", self.scans_dir)

        # Empty file
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(b"", "empty.png", self.scans_dir)

        # Oversized file (> 10MB)
        oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (10 * 1024 * 1024 + 1)
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(oversized, "huge.png", self.scans_dir)

        # Valid PNG magic bytes
        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
        meta_png = mat_complaints_service.validate_and_store_scan(png_bytes, "../../scan 01.png", self.scans_dir)
        self.assertTrue(meta_png["stored_filename"].endswith(".png"))
        self.assertNotIn("..", meta_png["stored_filename"])
        self.assertEqual(meta_png["mime_type"], "image/png")
        resolved_png = mat_complaints_service.resolve_scan_path(meta_png["stored_filename"], self.scans_dir)
        self.assertTrue(os.path.isfile(resolved_png))

        # Valid JPEG magic bytes
        jpeg_bytes = b"\xff\xd8\xff\xe0" + b"\x00" * 64
        meta_jpg = mat_complaints_service.validate_and_store_scan(jpeg_bytes, "doc.jpg", self.scans_dir)
        self.assertTrue(meta_jpg["stored_filename"].endswith(".jpg"))
        self.assertEqual(meta_jpg["mime_type"], "image/jpeg")

        # Valid WEBP magic bytes
        webp_bytes = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 32
        meta_webp = mat_complaints_service.validate_and_store_scan(webp_bytes, "doc.webp", self.scans_dir)
        self.assertTrue(meta_webp["stored_filename"].endswith(".webp"))
        self.assertEqual(meta_webp["mime_type"], "image/webp")

        # Valid PDF magic bytes
        pdf_bytes = b"%PDF-1.5 test document"
        meta_pdf = mat_complaints_service.validate_and_store_scan(pdf_bytes, "complaint.pdf", self.scans_dir)
        self.assertTrue(meta_pdf["stored_filename"].endswith(".pdf"))
        self.assertEqual(meta_pdf["mime_type"], "application/pdf")

        # Disallowed extension with valid PNG magic bytes
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(png_bytes, "malware.exe", self.scans_dir)

        # Mismatched extension (.pdf with PNG magic bytes)
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(png_bytes, "document.pdf", self.scans_dir)

        # Mismatched extension (.png with PDF magic bytes)
        with self.assertRaises(ValueError):
            mat_complaints_service.validate_and_store_scan(pdf_bytes, "document.png", self.scans_dir)

    def test_atomic_file_storage_and_no_leftover_tmp_files(self):
        png_data = b"\x89PNG\r\n\x1a\n" + b"TEST_PAYLOAD_ATOMIC_12345"
        meta = mat_complaints_service.validate_and_store_scan(png_data, "upload.png", self.scans_dir)
        self.assertTrue(os.path.isfile(meta["abs_path"]))
        with open(meta["abs_path"], "rb") as f:
            self.assertEqual(f.read(), png_data)

        # Verify no .tmp files exist in scans_dir
        tmp_files = [f for f in os.listdir(self.scans_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [])

    def test_match_nearest_police_station_from_amman_areas(self):
        res = mat_complaints_service.match_nearest_police_station("عمان - تلاع العلي قرب الدوار", self.base_dir)
        self.assertTrue(res["matched"])
        self.assertIn("تلاع العلي", res["nearest_station"])
        self.assertTrue(res["police_directorate"])
        self.assertTrue(res["liwa_name"])
        self.assertGreater(len(res["candidates"]), 0)

        # Empty or unknown location
        res_empty = mat_complaints_service.match_nearest_police_station("", self.base_dir)
        self.assertFalse(res_empty["matched"])
        self.assertEqual(res_empty["nearest_station"], "")

    def test_compute_90_day_status(self):
        # 92 days ago -> expired / due for stop
        old_date = (datetime.now() - timedelta(days=92)).strftime("%Y-%m-%d %H:%M:%S")
        res = mat_complaints_service.compute_90_day_status(old_date, "governor_approved")
        self.assertTrue(res["is_due_for_stop"])
        self.assertEqual(res["days_remaining"], 0)
        self.assertEqual(res["warning_level"], "expired")

        # Fresh complaint (today) -> normal
        today_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        res_today = mat_complaints_service.compute_90_day_status(today_date, "under_review")
        self.assertFalse(res_today["is_due_for_stop"])
        self.assertGreaterEqual(res_today["days_remaining"], 89)
        self.assertEqual(res_today["warning_level"], "normal")

        # 80 days ago -> warning
        warn_date = (datetime.now() - timedelta(days=80)).strftime("%Y-%m-%d %H:%M:%S")
        res_warn = mat_complaints_service.compute_90_day_status(warn_date, "officer_reviewed")
        self.assertFalse(res_warn["is_due_for_stop"])
        self.assertEqual(res_warn["warning_level"], "warning")
        self.assertLessEqual(res_warn["days_remaining"], 15)

        # Already stopped or closed complaint
        res_closed = mat_complaints_service.compute_90_day_status(old_date, "closed")
        self.assertFalse(res_closed["is_due_for_stop"])
        self.assertEqual(res_closed["warning_level"], "closed")

        res_stopped = mat_complaints_service.compute_90_day_status(old_date, "stopped")
        self.assertFalse(res_stopped["is_due_for_stop"])
        self.assertEqual(res_stopped["warning_level"], "closed")

        # ISO 8601 with Z timezone 95 days ago -> expired / due for stop
        iso_z_date = (datetime.now(timezone.utc) - timedelta(days=95)).strftime("%Y-%m-%dT%H:%M:%SZ")
        res_iso_z = mat_complaints_service.compute_90_day_status(iso_z_date, "governor_approved")
        self.assertTrue(res_iso_z["is_due_for_stop"])
        self.assertEqual(res_iso_z["days_remaining"], 0)
        self.assertEqual(res_iso_z["warning_level"], "expired")

        # ISO 8601 with timezone offset (+03:00) 10 days ago -> normal
        iso_offset_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S+03:00")
        res_iso_offset = mat_complaints_service.compute_90_day_status(iso_offset_date, "governor_approved")
        self.assertFalse(res_iso_offset["is_due_for_stop"])
        self.assertEqual(res_iso_offset["warning_level"], "normal")

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
        self.caller = dict(conn.execute("SELECT id as user_id, name, username, role FROM mat_officers WHERE role='caller' LIMIT 1").fetchone())
        conn.close()

    def tearDown(self):
        server.DB_PATH = self.orig_db
        server.BACKUP_JSON_PATH = self.orig_backup
        self.tmpdir.cleanup()

    def test_full_workflow_officer_action_section_head_governor_modify_to_phone_call(self):
        conn = server.get_db()
        try:
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
            self.assertTrue(created["complaint_number"].startswith("PC-"))
            self.assertEqual(len(created["parties"]), 2)

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
            self.assertIsNotNone(gov_res["linked_appointment"])

            appt = conn.execute("SELECT * FROM mat_simple_appointments WHERE id = ?", (gov_res["linked_appointment_id"],)).fetchone()
            self.assertIsNotNone(appt)
            self.assertEqual(appt["case_number"], created["complaint_number"])
            self.assertEqual(appt["visitor_name"], "سامي عمر")

            # Re-invoking governor approval does not create duplicate appointment
            gov_res_repeat = mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
                "decision": "تغيير_الإجراء",
                "governor_final_action": "اتصال هاتفي",
                "governor_notes": "تأكيد الاتصال الهاتفي."
            })
            self.assertEqual(gov_res_repeat["linked_appointment_id"], gov_res["linked_appointment_id"])
            appt_count = conn.execute(
                "SELECT COUNT(*) FROM mat_simple_appointments WHERE case_number = ?",
                (created["complaint_number"],)
            ).fetchone()[0]
            self.assertEqual(appt_count, 1)

            # Officer performs post-approval execution action and notes
            exec_res = mat_complaints_service.record_officer_action(conn, self.officer, cid, {
                "officer_action": "اتصال هاتفي",
                "officer_notes": "تم الاتصال بالطرفين وتحديد موعد المراجعة.",
                "execution_status": "completed"
            })
            self.assertEqual(exec_res["workflow_stage"], "completed")
            self.assertGreaterEqual(len(exec_res["workflow_log"]), 4)
        finally:
            conn.close()

    def test_governor_approval_station_referral_reserves_file(self):
        conn = server.get_db()
        try:
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
            self.assertIsNotNone(gov_res["linked_file"])
            res_file = conn.execute("SELECT * FROM mat_reserved_files WHERE file_number = ?", (created["complaint_number"],)).fetchone()
            self.assertIsNotNone(res_file)
            custody_log = conn.execute(
                "SELECT * FROM mat_file_custody_log WHERE reserved_file_id = ?",
                (res_file["id"],)
            ).fetchone()
            self.assertIsNotNone(custody_log)
            self.assertEqual(custody_log["status"], "accepted")
        finally:
            conn.close()

    def test_rbac_validation_and_invalid_stage_transitions(self):
        conn = server.get_db()
        try:
            # Caller cannot create complaint intake
            with self.assertRaises(PermissionError):
                mat_complaints_service.create_complaint_intake(conn, self.caller, {
                    "subject": "محاولة غير مصرح بها"
                }, self.base_dir)

            created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "subject": "اختبار صلاحيات ومراحل",
                "summary": "تفاصيل الاختبار",
                "submit_stage": "draft_scan"
            }, self.base_dir)
            cid = created["id"]

            # Blank officer notes or action rejected
            with self.assertRaises(ValueError):
                mat_complaints_service.record_officer_action(conn, self.officer, cid, {
                    "officer_action": "اتصال هاتفي",
                    "officer_notes": "   "
                })
            with self.assertRaises(ValueError):
                mat_complaints_service.record_officer_action(conn, self.officer, cid, {
                    "officer_action": "",
                    "officer_notes": "ملاحظة"
                })

            # Officer cannot recommend as section head
            with self.assertRaises(PermissionError):
                mat_complaints_service.record_section_head_recommendation(conn, self.officer, cid, {
                    "section_head_notes": "مشروحات",
                    "section_recommended_action": "اتصال هاتفي"
                })

            # Advance to pending_governor
            mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
                "section_head_notes": "يرفع للحاكم الإداري",
                "section_recommended_action": "توديع مغفور"
            })

            # Officer cannot act while pending_governor
            with self.assertRaises(ValueError):
                mat_complaints_service.record_officer_action(conn, self.officer, cid, {
                    "officer_action": "اتصال هاتفي",
                    "officer_notes": "محاولة تعديل أثناء انتظار القرار"
                })

            # Admin cannot issue governor decision
            with self.assertRaises(PermissionError):
                mat_complaints_service.record_governor_decision(conn, self.admin, cid, {"decision": "موافقة"})

            # Missing governor_final_action when تغيير_الإجراء
            with self.assertRaises(ValueError):
                mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
                    "decision": "تغيير_الإجراء",
                    "governor_final_action": ""
                })

            # Missing complaint raises LookupError
            with self.assertRaises(LookupError):
                mat_complaints_service.record_officer_action(conn, self.officer, 999999, {
                    "officer_action": "اتصال هاتفي",
                    "officer_notes": "ملاحظة"
                })
            self.assertIsNone(mat_complaints_service.get_complaint_detail(conn, 999999))
        finally:
            conn.close()

    def test_governor_reject_resubmit_and_urgent_tawdi_maghfour_with_preexisting_file(self):
        conn = server.get_db()
        try:
            created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "complaint_number": "PC-20261110-7777",
                "subject": "مشاجرة متكررة",
                "summary": "تهديد مباشر يتطلب توديع مغفور",
                "submit_stage": "pending_section_head"
            }, self.base_dir)
            cid = created["id"]

            # Pre-reserve file manually to verify idempotent handling without IntegrityError crash
            conn.execute(
                "INSERT INTO mat_reserved_files (file_number, officer_id, notes) VALUES (?, ?, ?)",
                ("PC-20261110-7777", self.officer["user_id"], "حجز مسبق")
            )
            conn.commit()

            mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
                "section_head_notes": "مقترح حفظ مبدئياً",
                "section_recommended_action": "حفظ / توجيه للقضاء المختص"
            })

            # Governor rejects
            rej = mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
                "decision": "رفض",
                "governor_notes": "يعاد للدراسة والتوديع المغفور"
            })
            self.assertEqual(rej["workflow_stage"], "governor_rejected")
            self.assertIsNone(rej["linked_appointment_id"])

            # Officer re-evaluates rejected complaint and sends back to section head
            re_off = mat_complaints_service.record_officer_action(conn, self.officer, cid, {
                "officer_action": "توديع مغفور",
                "officer_notes": "تمت إعادة الدراسة والتوصية بالتوديع المغفور",
                "send_to_section_head": True
            })
            self.assertEqual(re_off["workflow_stage"], "pending_section_head")

            mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
                "section_head_notes": "ينسب بالتوديع المغفور",
                "section_recommended_action": "توديع مغفور"
            })
            app_res = mat_complaints_service.record_governor_decision(conn, self.governor, cid, {
                "decision": "موافقة",
                "governor_notes": "موافق على التوديع المغفور"
            })
            self.assertEqual(app_res["workflow_stage"], "governor_approved")
            self.assertEqual(app_res["priority"], "عاجل")
            self.assertEqual(app_res["linked_file_number"], "PC-20261110-7777")
        finally:
            conn.close()

    def test_scan_linking_followup_90_days_update_list_and_docx_export(self):
        conn = server.get_db()
        try:
            # Insert an unlinked scan and an already-linked scan
            c1 = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "subject": "شكوى أولى",
                "summary": "ملخص أول",
                "submit_stage": "draft_scan"
            }, self.base_dir)
            cur = conn.execute(
                """
                INSERT INTO mat_complaint_scans (complaint_id, stored_filename, original_filename, mime_type, file_size, uploaded_by_id)
                VALUES (NULL, 'scan_free.png', 'free.png', 'image/png', 512, ?)
                """,
                (self.officer["user_id"],)
            )
            free_scan_id = cur.lastrowid
            cur2 = conn.execute(
                """
                INSERT INTO mat_complaint_scans (complaint_id, stored_filename, original_filename, mime_type, file_size, uploaded_by_id)
                VALUES (?, 'scan_taken.png', 'taken.png', 'image/png', 512, ?)
                """,
                (c1["id"], self.officer["user_id"])
            )
            taken_scan_id = cur2.lastrowid
            conn.commit()

            c2 = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "subject": "شكوى تعدي على رصيف",
                "summary": "تفاصيل الشكوى الثانية",
                "scan_ids": [free_scan_id, taken_scan_id],
                "parties": [
                    {"party_type": "شاكي", "name": "خالد سليم", "phone": "0795550000", "address": "صويلح"},
                    {"party_type": "مشتكى_عليه", "name": "متجر السعادة", "phone": "0796660000", "address": "الشميساني"}
                ]
            }, self.base_dir)
            # Only free scan should be linked to c2; taken scan stays on c1
            self.assertEqual([s["id"] for s in c2["scans"]], [free_scan_id])
            c1_detail = mat_complaints_service.get_complaint_detail(conn, c1["id"])
            self.assertEqual([s["id"] for s in c1_detail["scans"]], [taken_scan_id])

            # Update complaint details & rematch station
            updated = mat_complaints_service.update_complaint_details(conn, self.officer, c2["id"], {
                "subject": "شكوى تعدي وإغلاق مدخل",
                "rematch_station": True,
                "parties": [
                    {"party_type": "شاكي", "name": "خالد سليم", "phone": "0795550000", "address": "صويلح"},
                    {"party_type": "مشتكى_عليه", "name": "متجر السعادة", "phone": "0796660000", "address": "تلاع العلي"}
                ]
            }, self.base_dir)
            self.assertEqual(updated["subject"], "شكوى تعدي وإغلاق مدخل")
            self.assertIn("تلاع العلي", updated["nearest_station"])

            # Direct DOCX export from get_complaint_detail result
            template = os.path.join(self.base_dir, "complaint_form_editable.docx")
            docx_bytes = mat_complaints_service.export_complaint_docx(updated, template)
            with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
                xml_text = zf.read("word/document.xml").decode("utf-8")
            self.assertIn("شكوى تعدي وإغلاق مدخل", xml_text)
            self.assertIn("متجر السعادة", xml_text)

            # Stop 90 days rejected before 90 days for officer
            with self.assertRaises(ValueError):
                mat_complaints_service.register_followup(conn, self.officer, c2["id"], "stop_90_days", "")

            # Backdate c1 by 95 days -> appears in overdue_90 filter & can be stopped
            old_ts = (datetime.now() - timedelta(days=95)).strftime("%Y-%m-%d %H:%M:%S")
            conn.execute("UPDATE mat_complaints SET last_followup_at = ? WHERE id = ?", (old_ts, c1["id"]))
            conn.commit()

            listed_overdue = mat_complaints_service.list_complaints(conn, self.officer, {"overdue_90": True})
            self.assertEqual([item["id"] for item in listed_overdue["complaints"]], [c1["id"]])
            self.assertEqual(listed_overdue["stats"]["overdue_90"], 1)

            stopped = mat_complaints_service.register_followup(conn, self.officer, c1["id"], "stop_90_days", "مرور 95 يوماً")
            self.assertEqual(stopped["workflow_stage"], "stopped_90_days")
            self.assertEqual(stopped["ninety_day_status"]["warning_level"], "closed")

            # Follow-up resets timer on c2
            conn.execute("UPDATE mat_complaints SET last_followup_at = ? WHERE id = ?", (old_ts, c2["id"]))
            conn.commit()
            followed = mat_complaints_service.register_followup(conn, self.officer, c2["id"], "followup", "راجع الشاكي القسم")
            self.assertEqual(followed["ninety_day_status"]["warning_level"], "normal")
            self.assertFalse(followed["ninety_day_status"]["is_due_for_stop"])

            # Search filter by party name
            search_res = mat_complaints_service.list_complaints(conn, self.admin, {"q": "متجر السعادة"})
            self.assertEqual(len(search_res["complaints"]), 1)
            self.assertEqual(search_res["complaints"][0]["id"], c2["id"])
        finally:
            conn.close()

    def test_partial_update_null_parties_and_invalid_party_types(self):
        conn = server.get_db()
        try:
            created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "subject": "موضوع أولي",
                "parties": [
                    {"party_type": "شاكي", "name": "سامر ناصر", "phone": "0791110000", "address": "الشميساني"},
                    {"party_type": "مشتكى_عليه", "name": "طارق عادل", "phone": "0792220000", "address": "تلاع العلي"}
                ]
            }, self.base_dir)
            cid = created["id"]
            self.assertEqual(len(created["parties"]), 2)

            # Partial update with parties=None / complainants=None / respondents=None MUST preserve existing parties
            updated = mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "subject": "موضوع محدث جزئياً",
                "parties": None,
                "complainants": None,
                "respondents": None
            }, self.base_dir)
            self.assertEqual(updated["subject"], "موضوع محدث جزئياً")
            self.assertEqual(len(updated["parties"]), 2)
            self.assertEqual({p["name"] for p in updated["parties"]}, {"سامر ناصر", "طارق عادل"})

            # Non-list non-None party collections raise ValueError
            with self.assertRaises(ValueError):
                mat_complaints_service.update_complaint_details(conn, self.officer, cid, {"parties": "not-a-list"}, self.base_dir)
            with self.assertRaises(ValueError):
                mat_complaints_service.update_complaint_details(conn, self.officer, cid, {"complainants": {"name": "خطأ"}}, self.base_dir)
            with self.assertRaises(ValueError):
                mat_complaints_service.create_complaint_intake(conn, self.officer, {
                    "subject": "اختبار أطراف غير صالحة",
                    "respondents": "invalid"
                }, self.base_dir)
        finally:
            conn.close()

    def test_station_override_failed_rematch_and_explicit_clear_prevent_stale_metadata(self):
        conn = server.get_db()
        try:
            created = mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "subject": "شكوى اختبار المركز الأمني",
                "parties": [
                    {"party_type": "مشتكى_عليه", "name": "محل الروابي", "address": "تلاع العلي"}
                ]
            }, self.base_dir)
            cid = created["id"]
            self.assertIn("تلاع العلي", created["nearest_station"])
            self.assertTrue(created["police_directorate"])
            self.assertTrue(created["liwa_name"])
            self.assertIsNotNone(created["station_lat"])
            self.assertIsNotNone(created["station_lon"])

            # 1. Explicit coordinate clearing in update_complaint_details
            cleared_coords = mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "station_lat": None,
                "station_lon": "",
                "police_directorate": ""
            }, self.base_dir)
            self.assertIn("تلاع العلي", cleared_coords["nearest_station"])
            self.assertEqual(cleared_coords["police_directorate"], "")
            self.assertIsNone(cleared_coords["station_lat"])
            self.assertIsNone(cleared_coords["station_lon"])

            # Restore via rematch to تلاع العلي
            rematched = mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "rematch_station": True
            }, self.base_dir)
            self.assertTrue(rematched["police_directorate"])
            self.assertIsNotNone(rematched["station_lat"])

            # 2. Failed rematch_station=True with unknown address clears ALL 5 station fields
            failed_rematch = mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "rematch_station": True,
                "parties": [
                    {"party_type": "مشتكى_عليه", "name": "محل الروابي", "address": "منطقة_وهمية_غير_موجودة_xyz"}
                ]
            }, self.base_dir)
            self.assertEqual(failed_rematch["nearest_station"], "")
            self.assertEqual(failed_rematch["police_directorate"], "")
            self.assertEqual(failed_rematch["liwa_name"], "")
            self.assertIsNone(failed_rematch["station_lat"])
            self.assertIsNone(failed_rematch["station_lon"])

            # Restore via matching address then manually override nearest_station alone -> clears stale metadata
            mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "rematch_station": True,
                "parties": [
                    {"party_type": "مشتكى_عليه", "name": "محل الروابي", "address": "تلاع العلي"}
                ]
            }, self.base_dir)
            overridden = mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "nearest_station": "مركز أمن مخصص"
            }, self.base_dir)
            self.assertEqual(overridden["nearest_station"], "مركز أمن مخصص")
            self.assertEqual(overridden["police_directorate"], "")
            self.assertEqual(overridden["liwa_name"], "")
            self.assertIsNone(overridden["station_lat"])
            self.assertIsNone(overridden["station_lon"])

            # Section head overriding to another station with explicit directorate also clears stale coords/liwa
            mat_complaints_service.update_complaint_details(conn, self.officer, cid, {
                "rematch_station": True,
                "parties": [
                    {"party_type": "مشتكى_عليه", "name": "محل الروابي", "address": "تلاع العلي"}
                ]
            }, self.base_dir)
            sec_overridden = mat_complaints_service.record_section_head_recommendation(conn, self.admin, cid, {
                "section_head_notes": "تحويل لمركز أمن البيادر",
                "section_recommended_action": "توديع عن طريق مركز أمني",
                "nearest_station": "مركز أمن البيادر"
            })
            self.assertEqual(sec_overridden["nearest_station"], "مركز أمن البيادر")
            self.assertEqual(sec_overridden["police_directorate"], "")
            self.assertEqual(sec_overridden["liwa_name"], "")
            self.assertIsNone(sec_overridden["station_lat"])
            self.assertIsNone(sec_overridden["station_lon"])
        finally:
            conn.close()

    def test_duplicate_complaint_number_raises_value_error_and_unrelated_integrity_not_swallowed(self):
        conn = server.get_db()
        try:
            mat_complaints_service.create_complaint_intake(conn, self.officer, {
                "complaint_number": "PC-20261110-9901",
                "subject": "شكوى أصلية"
            }, self.base_dir)

            # Duplicate explicit complaint_number raises ValueError (not IntegrityError)
            with self.assertRaises(ValueError):
                mat_complaints_service.create_complaint_intake(conn, self.officer, {
                    "complaint_number": "PC-20261110-9901",
                    "subject": "شكوى مكررة"
                }, self.base_dir)

            # Even if UNIQUE index exists at DB level and check is bypassed, IntegrityError maps to ValueError
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_test_unique_cn ON mat_complaints(complaint_number)")
            conn.commit()
            with self.assertRaises(ValueError):
                mat_complaints_service.create_complaint_intake(conn, self.officer, {
                    "complaint_number": "PC-20261110-9901",
                    "subject": "شكوى مكررة ثانية"
                }, self.base_dir)

            # Unrelated IntegrityError in _auto_reserve_complaint_file (nonexistent officer_id FK) must not be swallowed
            with self.assertRaises(sqlite3.IntegrityError):
                mat_complaints_service._auto_reserve_complaint_file(
                    conn,
                    {"id": 999, "complaint_number": "PC-20261110-9999", "subject": "تست", "assigned_officer_id": 999999},
                    999999,
                )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
