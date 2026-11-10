import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from unittest import mock

import mat_llm_engine
import server


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class TestPoliceComplaintsApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.orig_db = server.DB_PATH
        cls.orig_backup = server.BACKUP_JSON_PATH
        cls.orig_scans = getattr(server, "SCANS_DIR", None)

        server.DB_PATH = os.path.join(cls.tmpdir.name, "api_test.db")
        server.BACKUP_JSON_PATH = os.path.join(cls.tmpdir.name, "api_backup.json")
        server.SCANS_DIR = os.path.join(cls.tmpdir.name, "complaint_scans")
        server.init_db()

        cls.httpd = server.ThreadedHTTPServer(("127.0.0.1", 0), server.MatServerHandler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        server.DB_PATH = cls.orig_db
        server.BACKUP_JSON_PATH = cls.orig_backup
        if cls.orig_scans is not None:
            server.SCANS_DIR = cls.orig_scans
        elif hasattr(server, "SCANS_DIR"):
            delattr(server, "SCANS_DIR")
        cls.tmpdir.cleanup()

    def _new_client(self):
        jar = CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        return opener, jar

    def _req(self, opener, jar, method, path, body=None, include_csrf=True, headers=None):
        url = f"http://127.0.0.1:{self.port}{path}"
        if isinstance(body, (bytes, bytearray)):
            data = bytes(body)
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
        else:
            data = None

        req_headers = {}
        if data is not None and not (headers and "Content-Type" in headers):
            req_headers["Content-Type"] = "application/json"
        if include_csrf:
            for c in jar:
                if c.name == "csrf_token":
                    req_headers["X-CSRF-Token"] = c.value
        if headers:
            req_headers.update(headers)

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with opener.open(req, timeout=10) as resp:
                return resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as err:
            return err.code, err.headers, err.read()

    def _login(self, username):
        op, jar = self._new_client()
        st, _, _ = self._req(op, jar, "POST", "/api/v1/mat/login", {"username": username})
        self.assertEqual(st, 200, f"Login failed for {username}")
        return op, jar

    def test_01_static_file_protection_and_security_headers(self):
        # Unauthenticated static access to sensitive paths MUST be blocked (403 or 404)
        anon_op, anon_jar = self._new_client()
        blocked_paths = [
            "/data/complaint_scans/nonexistent.png",
            "/data/complaint_scans/",
            "/.env",
            "/key.json",
            "/data_backup.json",
            "/mat_complaints.db",
            "/complaints.db",
            "/.superpowers/sdd/2026-11-10-police-complaints-intake/progress.md",
            "/complaints/../.env",
        ]
        for path in blocked_paths:
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                conn.request("GET", path)
                resp = conn.getresponse()
                resp.read()
                self.assertIn(resp.status, (403, 404), f"Expected 403/404 for {path}, got {resp.status}")
            finally:
                conn.close()

        # Public login page must have security headers
        st, hdrs, _ = self._req(anon_op, anon_jar, "GET", "/complaints/login.html")
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(hdrs.get("X-Frame-Options"), "SAMEORIGIN")

        # Unauthenticated API access -> 401 with security headers
        st, hdrs, _ = self._req(anon_op, anon_jar, "GET", "/api/v1/mat/police-complaints")
        self.assertEqual(st, 401)
        self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(hdrs.get("X-Frame-Options"), "SAMEORIGIN")

    def test_02_rbac_csrf_and_end_to_end_http_flow(self):
        off_op, off_jar = self._login("ehab")
        adm_op, adm_jar = self._login("orwa")
        gov_op, gov_jar = self._login("governor")

        # Missing X-CSRF-Token returns 403 on state-changing endpoint
        st, _, _ = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints",
            {"subject": "محاولة بدون CSRF"},
            include_csrf=False,
        )
        self.assertEqual(st, 403)

        # Officer uploads scan via base64 JSON (with data URI prefix) -> manual_fallback
        png_b64 = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints/scan-extract",
            {"filename": "handwritten.png", "file_base64": png_b64},
        )
        self.assertEqual(st, 200)
        scan_res = json.loads(raw.decode("utf-8"))
        self.assertIn("scan_id", scan_res)
        self.assertEqual(scan_res["status"], "manual_fallback")

        # Verify scan file was written in isolated test SCANS_DIR
        self.assertTrue(len(os.listdir(server.SCANS_DIR)) >= 1)

        # Match nearest police station endpoint
        q_addr = urllib.parse.quote("تلاع العلي")
        st, _, raw = self._req(
            off_op,
            off_jar,
            "GET",
            f"/api/v1/mat/police-complaints/match-station?address={q_addr}",
        )
        self.assertEqual(st, 200)
        match_res = json.loads(raw.decode("utf-8"))
        self.assertTrue(match_res["matched"])
        self.assertTrue(match_res["nearest_station"])

        # Create complaint linked to scan
        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints",
            {
                "scan_ids": [scan_res["scan_id"]],
                "subject": "خلاف جوار خفيف",
                "summary": "نزاع على مواقف العمارة في الشميساني",
                "parties": [
                    {"party_type": "شاكي", "name": "سالم", "phone": "0791234567", "address": "الشميساني"},
                    {"party_type": "مشتكى_عليه", "name": "رامي", "phone": "0797654321", "address": "تلاع العلي"},
                ],
            },
        )
        self.assertEqual(st, 201)
        created = json.loads(raw.decode("utf-8"))
        cid = created["id"]

        # Update complaint details via PUT
        st, _, raw = self._req(
            off_op,
            off_jar,
            "PUT",
            f"/api/v1/mat/police-complaints/{cid}",
            {"notes": "تم تدقيق العنوان"},
        )
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["notes"], "تم تدقيق العنوان")

        # Officer records action & notes and submits to Section Head
        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            f"/api/v1/mat/police-complaints/{cid}/officer-action",
            {
                "officer_action": "توديع عن طريق مركز أمني",
                "officer_notes": "نوصي بالتوديع لمركز أمن تلاع العلي.",
                "send_to_section_head": True,
            },
        )
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["workflow_stage"], "pending_section_head")

        # Officer cannot access LLM settings or section head recommendation (admin only)
        self.assertEqual(self._req(off_op, off_jar, "GET", "/api/v1/mat/llm-settings")[0], 403)
        self.assertEqual(
            self._req(
                off_op,
                off_jar,
                "POST",
                f"/api/v1/mat/police-complaints/{cid}/section-recommend",
                {"section_head_notes": "ملاحظة", "section_recommended_action": "اتصال هاتفي"},
            )[0],
            403,
        )

        # Admin (Section Head) recommends action
        st, _, raw = self._req(
            adm_op,
            adm_jar,
            "POST",
            f"/api/v1/mat/police-complaints/{cid}/section-recommend",
            {
                "section_head_notes": "توديع رسمي",
                "section_recommended_action": "توديع عن طريق مركز أمني",
                "nearest_station": "مركز أمن تلاع العلي",
            },
        )
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["workflow_stage"], "pending_governor")

        # Admin cannot issue Governor decision (governor only)
        st, _, _ = self._req(
            adm_op,
            adm_jar,
            "POST",
            f"/api/v1/mat/police-complaints/{cid}/governor-decision",
            {"decision": "موافقة"},
        )
        self.assertEqual(st, 403)

        # Governor approves
        st, _, raw = self._req(
            gov_op,
            gov_jar,
            "POST",
            f"/api/v1/mat/police-complaints/{cid}/governor-decision",
            {"decision": "موافقة", "governor_notes": "يعتمد التوديع"},
        )
        self.assertEqual(st, 200)
        gov_detail = json.loads(raw.decode("utf-8"))
        self.assertEqual(gov_detail["workflow_stage"], "governor_approved")
        self.assertTrue(gov_detail["linked_file_number"])

        # Follow-up endpoint works
        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            f"/api/v1/mat/police-complaints/{cid}/followup",
            {"action_type": "followup", "notes": "راجع المشتكي القسم لمتابعة التوديع"},
        )
        self.assertEqual(st, 200)
        fu_detail = json.loads(raw.decode("utf-8"))
        self.assertTrue(
            any("متابعة" in (entry.get("action_taken") or "") for entry in fu_detail["workflow_log"])
        )

        # GET list & detail endpoints
        st, _, raw = self._req(adm_op, adm_jar, "GET", "/api/v1/mat/police-complaints?workflow_stage=governor_approved")
        self.assertEqual(st, 200)
        list_res = json.loads(raw.decode("utf-8"))
        self.assertTrue(any(c["id"] == cid for c in list_res["complaints"]))

        st, _, raw = self._req(gov_op, gov_jar, "GET", f"/api/v1/mat/police-complaints/{cid}")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(raw.decode("utf-8"))["id"], cid)

        # Protected scan download has nosniff & X-Frame-Options headers and exact bytes
        st, hdrs, dl_bytes = self._req(
            gov_op, gov_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan_res['scan_id']}"
        )
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(hdrs.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertEqual(dl_bytes, PNG_BYTES)

        # Unauthenticated scan download is rejected (401), and direct static path is blocked (403)
        anon_op, anon_jar = self._new_client()
        self.assertEqual(
            self._req(anon_op, anon_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan_res['scan_id']}")[0],
            401,
        )
        stored_files = os.listdir(server.SCANS_DIR)
        self.assertTrue(stored_files)
        self.assertIn(
            self._req(anon_op, anon_jar, "GET", f"/data/complaint_scans/{stored_files[0]}")[0],
            (403, 404),
        )

        # Export filled DOCX
        st, hdrs, doc_bytes = self._req(
            adm_op, adm_jar, "GET", f"/api/v1/mat/police-complaints/{cid}/export-docx"
        )
        self.assertEqual(st, 200)
        self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(hdrs.get("X-Frame-Options"), "SAMEORIGIN")
        self.assertTrue(doc_bytes.startswith(b"PK"))

        # Global search includes police_complaints matching subject, station, and party phone
        for term in ("خلاف جوار", "تلاع العلي", "0797654321"):
            st, _, raw = self._req(
                adm_op,
                adm_jar,
                "GET",
                f"/api/v1/mat/search?q={urllib.parse.quote(term)}",
            )
            self.assertEqual(st, 200)
            sres = json.loads(raw.decode("utf-8"))
            self.assertIn("police_complaints", sres)
            self.assertTrue(
                any(item["id"] == cid for item in sres["police_complaints"]),
                f"Expected complaint {cid} in global search for {term!r}",
            )

    def test_03_multipart_upload_oversized_rejection_and_error_mapping(self):
        off_op, off_jar = self._login("ehab")

        # Multipart/form-data upload with mocked Gemini extraction
        boundary = "----MatScanBoundary98765"
        mp_body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="شكوى_مسح.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode("utf-8") + PNG_BYTES + f"\r\n--{boundary}--\r\n".encode("utf-8")

        mock_llm_out = {
            "status": "ok",
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "extracted": {
                "paper_date": "2026-11-10",
                "complainants": [{"party_category": "مواطن", "name": "خالد", "phone": "0790001111", "address": "العبدلي"}],
                "respondents": [{"party_category": "منشأة", "name": "محل النور", "phone": "0792223333", "address": "ماركا الشمالية"}],
                "subject": "إزعاج ليلي",
                "summary": "ضوضاء مستمرة ليلاً",
                "has_signature": True,
                "no_pending_lawsuit_declared": True,
            },
            "analysis": {
                "is_minor_police_complaint": True,
                "police_necessity_reason": "إزعاج عام بسيط",
                "ai_analysis": "تحتاج لتنبيه",
                "ai_solution_recommendation": "استدعاء أو توديع",
                "ai_recommended_action": "اتصال هاتفي",
                "ai_confidence": 0.9,
            },
            "raw_text": "{\"subject\":\"إزعاج ليلي\"}",
            "message": "ok",
        }
        with mock.patch.object(mat_llm_engine, "extract_and_analyze_complaint", return_value=mock_llm_out):
            st, _, raw = self._req(
                off_op,
                off_jar,
                "POST",
                "/api/v1/mat/police-complaints/scan-extract",
                body=mp_body,
                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            )
        self.assertEqual(st, 200)
        res = json.loads(raw.decode("utf-8"))
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["extracted"]["subject"], "إزعاج ليلي")
        self.assertTrue(res["station_match"]["matched"])

        # Invalid file magic bytes -> 400 (ValueError)
        bad_b64 = base64.b64encode(b"MZ_NOT_AN_IMAGE").decode("ascii")
        st, _, _ = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints/scan-extract",
            {"filename": "bad.exe", "file_base64": bad_b64},
        )
        self.assertEqual(st, 400)

        # Oversized Content-Length > MAX_REQUEST_BYTES -> 413
        csrf_val = next(c.value for c in off_jar if c.name == "csrf_token")
        sess_val = next(c.value for c in off_jar if c.name == "session")
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.putrequest("POST", "/api/v1/mat/police-complaints")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(server.MAX_REQUEST_BYTES + 1024))
            conn.putheader("Cookie", f"session={sess_val}; csrf_token={csrf_val}")
            conn.putheader("X-CSRF-Token", csrf_val)
            conn.endheaders()
            resp = conn.getresponse()
            resp.read()
            self.assertIn(resp.status, (400, 413))
        finally:
            conn.close()

        # Non-existent complaint -> 404 (LookupError)
        self.assertEqual(self._req(off_op, off_jar, "GET", "/api/v1/mat/police-complaints/999999")[0], 404)

        # Missing subject on create -> 400 (ValueError)
        self.assertEqual(self._req(off_op, off_jar, "POST", "/api/v1/mat/police-complaints", {"subject": ""})[0], 400)

        # Unexpected internal exception -> 500 generic Arabic message without leaking secrets or SQL details
        with mock.patch.object(
            server.mat_complaints_service,
            "list_complaints",
            side_effect=RuntimeError("SELECT * FROM mat_llm_settings failed AIzaSySecretKeyLeak123456"),
        ):
            st, _, raw = self._req(off_op, off_jar, "GET", "/api/v1/mat/police-complaints")
        self.assertEqual(st, 500)
        err_body = raw.decode("utf-8")
        self.assertNotIn("SELECT", err_body)
        self.assertNotIn("AIzaSy", err_body)
        self.assertIn("خطأ داخلي في الخادم", err_body)

    def test_04_llm_settings_masking_test_and_fcm_dispatch_and_create_governor(self):
        adm_op, adm_jar = self._login("orwa")
        off_op, off_jar = self._login("ehab")
        gov_op, gov_jar = self._login("governor")
        cal_op, cal_jar = self._login("raad")

        # Task 1 carry-forward: admin can create another governor account; non-admin blocked; invalid role -> 400
        self.assertEqual(
            self._req(
                off_op,
                off_jar,
                "POST",
                "/api/v1/mat/officers",
                {"name": "متسلل", "username": "unauth_off", "password": "pw", "role": "admin"},
            )[0],
            403,
        )
        self.assertEqual(
            self._req(
                adm_op,
                adm_jar,
                "POST",
                "/api/v1/mat/officers",
                {"name": "دور خاطئ", "username": "bad_role", "password": "pw", "role": "superadmin"},
            )[0],
            400,
        )
        st, _, raw = self._req(
            adm_op,
            adm_jar,
            "POST",
            "/api/v1/mat/officers",
            {
                "name": "مساعد المتصرف",
                "username": "gov_deputy",
                "password": "secret123",
                "role": "governor",
                "accessible_tools": "dashboard,police_complaints,finder,chat",
            },
        )
        self.assertEqual(st, 201)

        # Admin updates LLM settings; secret key is masked in response and excluded from backup JSON
        st, _, raw = self._req(
            adm_op,
            adm_jar,
            "PUT",
            "/api/v1/mat/llm-settings",
            {
                "provider": "gemini",
                "model_name": "gemini-2.5-flash",
                "api_key": "AIzaSySecretApiKeyForTesting998877",
                "is_enabled": 1,
            },
        )
        self.assertEqual(st, 200)
        saved = json.loads(raw.decode("utf-8"))
        self.assertNotIn("api_key", saved)
        self.assertTrue(saved["api_key_configured"])
        self.assertEqual(saved["api_key_masked"], "****8877")

        # Backup JSON must never expose api_key
        with open(server.BACKUP_JSON_PATH, "r", encoding="utf-8") as bf:
            self.assertNotIn("AIzaSySecretApiKeyForTesting998877", bf.read())

        # Admin GET settings masks key
        st, _, raw = self._req(adm_op, adm_jar, "GET", "/api/v1/mat/llm-settings")
        self.assertEqual(st, 200)
        fetched = json.loads(raw.decode("utf-8"))
        self.assertNotIn("api_key", fetched)
        self.assertEqual(fetched["api_key_masked"], "****8877")

        # Non-admin blocked from PUT/POST llm-settings
        self.assertEqual(
            self._req(off_op, off_jar, "PUT", "/api/v1/mat/llm-settings", {"provider": "ollama"})[0],
            403,
        )
        self.assertEqual(
            self._req(gov_op, gov_jar, "POST", "/api/v1/mat/llm-settings/test", {})[0],
            403,
        )

        # Admin tests connection (mocked HTTP)
        with mock.patch.object(
            mat_llm_engine,
            "test_llm_connection",
            return_value={"ok": True, "message": "اتصال ناجح", "provider": "gemini"},
        ):
            st, _, raw = self._req(adm_op, adm_jar, "POST", "/api/v1/mat/llm-settings/test", {})
        self.assertEqual(st, 200)
        self.assertTrue(json.loads(raw.decode("utf-8"))["ok"])

        # Register FCM tokens for admin, officer, governor, caller
        for op, jar, tok in (
            (adm_op, adm_jar, "fcm-tok-admin"),
            (off_op, off_jar, "fcm-tok-officer"),
            (gov_op, gov_jar, "fcm-tok-governor"),
            (cal_op, cal_jar, "fcm-tok-caller"),
        ):
            st, _, _ = self._req(op, jar, "POST", "/api/v1/mat/save-fcm-token", {"fcm_token": tok})
            self.assertEqual(st, 200)

        sent_notifications = []
        notify_cond = threading.Condition()

        def fake_fcm(target_token, title, body, data_payload=None):
            with notify_cond:
                sent_notifications.append((target_token, title, body, data_payload))
                notify_cond.notify_all()
            return True

        def wait_for_tokens(expected_tokens, timeout=2.0):
            deadline = time.monotonic() + timeout
            with notify_cond:
                while time.monotonic() < deadline:
                    current = {tok for tok, _, _, _ in sent_notifications}
                    if expected_tokens.issubset(current):
                        return current
                    notify_cond.wait(timeout=max(0.01, deadline - time.monotonic()))
                return {tok for tok, _, _, _ in sent_notifications}

        with mock.patch.object(server, "send_fcm_notification", side_effect=fake_fcm):
            # 1. Officer creates complaint & submits directly to Section Head -> notifies admin
            st, _, raw = self._req(
                off_op,
                off_jar,
                "POST",
                "/api/v1/mat/police-complaints",
                {
                    "subject": "شكوى إشعارات",
                    "submit_stage": "pending_section_head",
                    "parties": [{"party_type": "مشتكى_عليه", "name": "زيد", "address": "ماركا"}],
                },
            )
            self.assertEqual(st, 201)
            cid2 = json.loads(raw.decode("utf-8"))["id"]
            self.assertIn("fcm-tok-admin", wait_for_tokens({"fcm-tok-admin"}))

            # Caller should NOT be able to view non-phone-call complaint detail (403)
            self.assertEqual(self._req(cal_op, cal_jar, "GET", f"/api/v1/mat/police-complaints/{cid2}")[0], 403)

            # 2. Section Head recommends -> notifies governor
            with notify_cond:
                sent_notifications.clear()
            st, _, _ = self._req(
                adm_op,
                adm_jar,
                "POST",
                f"/api/v1/mat/police-complaints/{cid2}/section-recommend",
                {"section_head_notes": "رفع", "section_recommended_action": "توديع عن طريق مركز أمني"},
            )
            self.assertEqual(st, 200)
            self.assertIn("fcm-tok-governor", wait_for_tokens({"fcm-tok-governor"}))

            # 3. Governor modifies decision to 'اتصال هاتفي' -> notifies admin, officer, and caller
            with notify_cond:
                sent_notifications.clear()
            st, _, raw = self._req(
                gov_op,
                gov_jar,
                "POST",
                f"/api/v1/mat/police-complaints/{cid2}/governor-decision",
                {
                    "decision": "تغيير_الإجراء",
                    "governor_final_action": "اتصال هاتفي",
                    "governor_notes": "استدعاء هاتفي أولاً",
                },
            )
            self.assertEqual(st, 200)
            notified_tokens = wait_for_tokens({"fcm-tok-admin", "fcm-tok-officer", "fcm-tok-caller"})
            self.assertIn("fcm-tok-admin", notified_tokens)
            self.assertIn("fcm-tok-officer", notified_tokens)
            self.assertIn("fcm-tok-caller", notified_tokens)

        # Now caller CAN list and view the phone-call complaint, but cannot download scans (403)
        st, _, raw = self._req(cal_op, cal_jar, "GET", "/api/v1/mat/police-complaints")
        self.assertEqual(st, 200)
        caller_list = json.loads(raw.decode("utf-8"))["complaints"]
        self.assertTrue(any(c["id"] == cid2 for c in caller_list))
        self.assertEqual(self._req(cal_op, cal_jar, "GET", f"/api/v1/mat/police-complaints/{cid2}")[0], 200)
        self.assertEqual(self._req(cal_op, cal_jar, "GET", "/api/v1/mat/police-complaints/scans/1")[0], 403)


if __name__ == "__main__":
    unittest.main()
