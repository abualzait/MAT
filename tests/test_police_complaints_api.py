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
        cls.orig_llm_env = {
            k: os.environ.get(k)
            for k in (
                "MAT_LLM_PROVIDER",
                "MAT_LLM_MODEL",
                "MAT_GEMINI_API_KEY",
                "MAT_OPENAI_API_KEY",
                "MAT_OPENAI_BASE_URL",
                "MAT_OLLAMA_URL",
                "MAT_FALLBACK_OPENAI_API_KEY",
                "MAT_FALLBACK_OPENAI_BASE_URL",
                "MAT_FALLBACK_LLM_MODEL",
            )
        }
        for k in cls.orig_llm_env:
            os.environ.pop(k, None)

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
        for k, val in cls.orig_llm_env.items():
            if val is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = val
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
        # Unauthenticated static access to sensitive paths MUST be strictly blocked (403)
        anon_op, anon_jar = self._new_client()
        blocked_paths = [
            "/data/complaint_scans/nonexistent.png",
            "/data/complaint_scans/",
            "//data/complaint_scans/nonexistent.png",
            "//.superpowers/sdd/2026-11-10-police-complaints-intake/progress.md",
            "/data/",
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
                self.assertEqual(resp.status, 403, f"Expected 403 for {path}, got {resp.status}")
                self.assertEqual(resp.getheader("X-Content-Type-Options"), "nosniff")
                self.assertEqual(resp.getheader("X-Frame-Options"), "SAMEORIGIN")
            finally:
                conn.close()

        # Public login page (serve_file) and static fallback asset (super().do_GET) must have security headers
        for pub_path in ("/complaints/login.html", "/leaflet.css"):
            st, hdrs, _ = self._req(anon_op, anon_jar, "GET", pub_path)
            self.assertEqual(st, 200)
            self.assertEqual(hdrs.get_all("X-Content-Type-Options"), ["nosniff"])
            self.assertEqual(hdrs.get_all("X-Frame-Options"), ["SAMEORIGIN"])

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

        # Unauthenticated scan download is rejected (401), and direct static paths (including // bypass) return 403
        anon_op, anon_jar = self._new_client()
        self.assertEqual(
            self._req(anon_op, anon_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan_res['scan_id']}")[0],
            401,
        )
        stored_files = os.listdir(server.SCANS_DIR)
        self.assertTrue(stored_files)
        for direct_path in (
            f"/data/complaint_scans/{stored_files[0]}",
            f"//data/complaint_scans/{stored_files[0]}",
        ):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            try:
                conn.request("GET", direct_path)
                resp = conn.getresponse()
                resp.read()
                self.assertEqual(resp.status, 403, f"Expected 403 for {direct_path}, got {resp.status}")
            finally:
                conn.close()

        # Unauthenticated PUT with malformed JSON body must return 401 (auth BEFORE body parse), not 400
        # Include CSRF cookie/header so CSRF passes and we exercise api_update_police_complaint auth order
        anon_csrf = "testcsrf123"
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(
                "PUT",
                f"/api/v1/mat/police-complaints/{cid}",
                body=b"{malformed-json",
                headers={
                    "Content-Type": "application/json",
                    "Cookie": f"csrf_token={anon_csrf}",
                    "X-CSRF-Token": anon_csrf,
                },
            )
            resp = conn.getresponse()
            resp.read()
            self.assertEqual(resp.status, 401)
        finally:
            conn.close()

        # Governor attempting non-followup PUT edit must return 403
        self.assertEqual(
            self._req(gov_op, gov_jar, "PUT", f"/api/v1/mat/police-complaints/{cid}", {"notes": "تعديل غير مصرح"})[0],
            403,
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

        # Oversized Content-Length > MAX_REQUEST_BYTES -> strictly 413
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
            self.assertEqual(resp.status, 413)
        finally:
            conn.close()

        # Non-existent complaint -> 404 (LookupError)
        self.assertEqual(self._req(off_op, off_jar, "GET", "/api/v1/mat/police-complaints/999999")[0], 404)

        # Missing subject on create -> 400 (ValueError)
        self.assertEqual(self._req(off_op, off_jar, "POST", "/api/v1/mat/police-complaints", {"subject": ""})[0], 400)

        # Internal KeyError / IndexError must map to 500 (not 404 via LookupError!)
        with mock.patch.object(
            server.mat_complaints_service,
            "list_complaints",
            side_effect=KeyError("missing_internal_field"),
        ):
            st, _, raw = self._req(off_op, off_jar, "GET", "/api/v1/mat/police-complaints")
        self.assertEqual(st, 500)
        self.assertIn("خطأ داخلي في الخادم", raw.decode("utf-8"))

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

        # Updating settings with masked placeholder "****1234" must preserve the real stored API key
        st, _, raw = self._req(
            adm_op,
            adm_jar,
            "PUT",
            "/api/v1/mat/llm-settings",
            {
                "provider": "gemini",
                "model_name": "gemini-2.5-flash",
                "api_key": "****1234",
                "is_enabled": 1,
            },
        )
        self.assertEqual(st, 200)
        resaved = json.loads(raw.decode("utf-8"))
        self.assertEqual(resaved["api_key_masked"], "****8877")
        conn_check = server.get_db()
        try:
            unmasked = mat_llm_engine.get_llm_settings(conn_check, mask_secret=False)
            self.assertEqual(unmasked["api_key"], "AIzaSySecretApiKeyForTesting998877")
        finally:
            conn_check.close()

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

    def test_07_simple_dashboard_police_summary_permissions_and_actions(self):
        off_op, off_jar = self._login("ehab")
        adm_op, adm_jar = self._login("orwa")
        gov_op, gov_jar = self._login("governor")
        cal_op, cal_jar = self._login("raad")

        # 1. Officer registers a draft complaint (action needed for officer, and forwarded to section head for admin)
        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints",
            {
                "subject": "شكوى اختبار لوحة التحكم",
                "summary": "اختبار إحصائيات وإشعارات الشكاوى",
                "submit_stage": "draft_scan",
                "complainants": [{"name": "أحمد علي", "phone": "0791234567"}],
            },
        )
        self.assertEqual(st, 201)
        draft_id = json.loads(raw.decode("utf-8"))["id"]

        st, _, raw = self._req(
            off_op,
            off_jar,
            "POST",
            "/api/v1/mat/police-complaints",
            {
                "subject": "شكوى بانتظار رئيس القسم",
                "summary": "مرفوعة للرئيس",
                "submit_stage": "pending_section_head",
                "complainants": [{"name": "سالم حسن", "phone": "0781112233"}],
            },
        )
        self.assertEqual(st, 201)
        sec_id = json.loads(raw.decode("utf-8"))["id"]

        # Officer dashboard: enabled=True, can_register=True, draft_id needs action
        st, _, raw = self._req(off_op, off_jar, "GET", "/api/v1/mat/simple-dashboard?filter=today")
        self.assertEqual(st, 200)
        off_dash = json.loads(raw.decode("utf-8"))["police_complaints_summary"]
        self.assertTrue(off_dash["enabled"])
        self.assertTrue(off_dash["can_register"])
        self.assertGreaterEqual(off_dash["action_required_count"], 1)
        off_ids = {item["id"] for item in off_dash["action_items"]}
        self.assertIn(draft_id, off_ids)
        self.assertNotIn(sec_id, off_ids)

        # Admin dashboard: enabled=True, can_register=True, sec_id needs action
        st, _, raw = self._req(adm_op, adm_jar, "GET", "/api/v1/mat/simple-dashboard?filter=today")
        self.assertEqual(st, 200)
        adm_dash = json.loads(raw.decode("utf-8"))["police_complaints_summary"]
        self.assertTrue(adm_dash["enabled"])
        self.assertTrue(adm_dash["can_register"])
        self.assertIn(sec_id, {item["id"] for item in adm_dash["action_items"]})

        # Governor dashboard: enabled=True, can_register=False (no intake permission)
        st, _, raw = self._req(gov_op, gov_jar, "GET", "/api/v1/mat/simple-dashboard?filter=today")
        self.assertEqual(st, 200)
        gov_dash = json.loads(raw.decode("utf-8"))["police_complaints_summary"]
        self.assertTrue(gov_dash["enabled"])
        self.assertFalse(gov_dash["can_register"])

        # Caller (raad, no police_complaints tool) dashboard: strictly disabled & empty
        st, _, raw = self._req(cal_op, cal_jar, "GET", "/api/v1/mat/simple-dashboard?filter=today")
        self.assertEqual(st, 200)
        cal_dash = json.loads(raw.decode("utf-8"))["police_complaints_summary"]
        self.assertFalse(cal_dash["enabled"])
        self.assertFalse(cal_dash["can_register"])
        self.assertEqual(cal_dash["action_required_count"], 0)
        self.assertEqual(cal_dash["action_items"], [])

        # Verify UI page contains renamed button and dashboard elements
        st, _, html_raw = self._req(off_op, off_jar, "GET", "/complaints/app.html")
        self.assertEqual(st, 200)
        html_txt = html_raw.decode("utf-8")
        self.assertIn('id="dashboardPoliceComplaintsCard"', html_txt)
        self.assertIn('id="dashboardRegisterComplaintBtn"', html_txt)
        self.assertIn("تسجيل شكوى جديدة", html_txt)
        self.assertNotIn("مسح شكوى جديدة", html_txt)

    def test_08_scan_extract_replace_scan_id_and_rotation_field(self):
        off_op, off_jar = self._login("ehab")
        png_b64 = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")

        fake_sideways = {
            "status": "ok",
            "provider": "openai",
            "model": "qwen/qwen3.8-27b",
            "detected_rotation_cw": 270,
            "extracted": {"subject": "اختبار مائل", "complainants": [], "respondents": []},
            "analysis": {"ai_confidence": 0.65, "ai_recommended_action": "توديع عن طريق مركز أمني"},
            "raw_text": "{}",
            "message": "ok",
        }
        fake_upright = {
            "status": "ok",
            "provider": "openai",
            "model": "qwen/qwen3.8-27b",
            "detected_rotation_cw": 0,
            "extracted": {"subject": "اختبار معتدل", "complainants": [], "respondents": []},
            "analysis": {"ai_confidence": 0.95, "ai_recommended_action": "توديع عن طريق مركز أمني"},
            "raw_text": "{}",
            "message": "ok",
        }

        with mock.patch.object(
            mat_llm_engine,
            "extract_and_analyze_complaint",
            side_effect=[fake_sideways, fake_upright],
        ):
            st, _, raw1 = self._req(
                off_op,
                off_jar,
                "POST",
                "/api/v1/mat/police-complaints/scan-extract",
                {"filename": "sideways.png", "file_base64": png_b64, "page_order": 1},
            )
            self.assertEqual(st, 200)
            res1 = json.loads(raw1.decode("utf-8"))
            scan1_id = res1["scan_id"]
            self.assertEqual(res1["detected_rotation_cw"], 270)
            self.assertEqual(self._req(off_op, off_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan1_id}")[0], 200)

            st, _, raw2 = self._req(
                off_op,
                off_jar,
                "POST",
                "/api/v1/mat/police-complaints/scan-extract",
                {
                    "filename": "upright.png",
                    "file_base64": png_b64,
                    "page_order": 1,
                    "replace_scan_id": scan1_id,
                },
            )
            self.assertEqual(st, 200)
            res2 = json.loads(raw2.decode("utf-8"))
            scan2_id = res2["scan_id"]
            self.assertEqual(res2["detected_rotation_cw"], 0)
            self.assertNotEqual(scan2_id, scan1_id)
            # Old replaced scan must be removed from DB & disk, new upright scan remains accessible
            self.assertEqual(self._req(off_op, off_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan1_id}")[0], 404)
            self.assertEqual(self._req(off_op, off_jar, "GET", f"/api/v1/mat/police-complaints/scans/{scan2_id}")[0], 200)


if __name__ == "__main__":
    unittest.main()
