# MAT API Contracts & Integration

All core API endpoints are prefixed with `/api/v1/mat/` (legacy `/api/...` paths are normalized to `/api/v1/mat/...` inside `server.py`).

## Authentication, CSRF & Security Headers
- **Session Cookie:** `POST /api/v1/mat/login` sets:
  - `session=<token>; HttpOnly; Path=/; SameSite=Lax` (verified against `mat_sessions`)
  - `csrf_token=<token>; Path=/; SameSite=Lax`
- **CSRF Protection:** All `POST`, `PUT`, and `DELETE` requests (except `/api/v1/mat/login`) must include header `X-CSRF-Token` matching the `csrf_token` cookie (`hmac.compare_digest`), otherwise `403 {"error": "طلب غير صالح (CSRF)"}`.
- **Payload Caps:** Maximum JSON/multipart HTTP body is `16 MB` (`413`). Maximum uploaded scan binary size is `10 MB` (`400`).
- **Response Security Headers:** Every HTTP response includes `X-Content-Type-Options: nosniff` and `X-Frame-Options: SAMEORIGIN`. Sensitive scan downloads and `.docx` exports additionally send `Cache-Control: no-store`.

---

## Core API Routes

### Authentication & Users
- **`POST /api/v1/mat/login`** — `{ "username": "...", "password": "...", "secret_code": "..." }` -> sets session & CSRF cookies, returns `{ "status": "success", "user": {...} }`.
- **`POST /api/v1/mat/logout`** — Invalidates session token.
- **`GET /api/v1/mat/me`** — Returns authenticated user info (`id`, `user_id`, `username`, `name`, `role`, `accessible_tools`).
- **`GET /api/v1/mat/officers` / `POST /api/v1/mat/officers` / `PUT /api/v1/mat/officers/{id}`** — Officer & governor account management (`admin` for mutations; valid roles: `admin`, `officer`, `caller`, `governor`).
- **`GET /api/v1/mat/simple-dashboard?filter=today|week|month|all`** — Returns appointment stats (`stats`), scheduled appointments, reserved files, searched areas, plus permission-gated `police_complaints_summary` (`{ "enabled": bool, "can_register": bool, "stats": {...}, "action_required_count": int, "action_items": [...] }` when role is `admin`/`governor` or `police_complaints` tool is enabled).

---

### Smart Police Complaints & Governor Workflow (`v1.46.0`)

#### 1. List Complaints & KPIs
- **`GET /api/v1/mat/police-complaints`**
  - **Roles:** `officer`, `admin`, `governor`, `caller` *(for `caller`, results are strictly filtered to `governor_final_action = 'اتصال هاتفي'` or `linked_appointment_id IS NOT NULL`)*.
  - **Query Params:**
    - `workflow_stage` or `stage` (supports comma-separated values or aliases: `all`, `draft`, `approved_in_execution` / `active_execution`, `pending_section_head`, `pending_governor`, `governor_rejected`, `completed`, `stopped_90_days`)
    - `q` or `search` (matches complaint number, subject, summary, station, directorate, notes, or party name/phone/national_id)
    - `mine=1`, `assigned_officer_id`, `nearest_station`, `overdue_90=1` / `due_for_stop=1`, `page` (default `1`), `limit` (default `50`, max `200`)
  - **Response (`200`):** `{ "complaints": [...], "total": int, "page": int, "limit": int, "stats": { "total", "draft_scan", "officer_reviewed", "pending_section_head", "pending_governor", "approved_in_execution", "governor_rejected", "completed", "stopped_90_days", "overdue_90", "warning_90" } }`.

#### 2. Get Single Complaint Detail
- **`GET /api/v1/mat/police-complaints/{id}`**
  - **Roles:** `officer`, `admin`, `governor`, `caller` *(403 if `caller` and complaint has neither `اتصال هاتفي` nor `linked_appointment_id`)*.
  - **Response (`200`):** Full complaint object including `parties`, `scans`, `workflow_log`, `ninety_day_status`, `linked_appointment`, and `linked_file`.

#### 3. Upload Scan & Execute Vision AI Extraction
- **`POST /api/v1/mat/police-complaints/scan-extract`**
  - **Roles:** `officer`, `admin` (403 for `caller`, `governor`).
  - **Accepted Content-Types:**
    - `multipart/form-data` (`file`/`scan`/`document`/`image` field + optional `complaint_id`, `page_order`)
    - `application/json` (`{ "filename": "...", "file_base64": "...", "complaint_id": null, "page_order": 1 }`)
  - **Validation:** Magic bytes & extension allow-list restricted to `.jpg`/`.jpeg`, `.png`, `.webp`, `.pdf` (max `10 MB`).
  - **Response (`200`):**
    ```json
    {
      "success": true,
      "scan_id": 12,
      "scan": { "id": 12, "original_filename": "...", "mime_type": "image/jpeg", "file_size": 12345, "page_order": 1, "url": "/api/v1/mat/police-complaints/scans/12" },
      "status": "ok | manual_fallback",
      "provider": "gemini | openai | ollama",
      "model": "...",
      "detected_rotation_cw": 0,
      "extracted": { "raw_transcription": "...", "paper_date": "...", "complainants": [], "respondents": [], "subject": "...", "summary": "...", "has_signature": true, "no_pending_lawsuit_declared": true },
      "analysis": { "is_minor_police_complaint": true, "police_necessity_reason": "...", "ai_analysis": "...", "ai_solution_recommendation": "...", "ai_recommended_action": "...", "ai_confidence": 0.92 },
      "raw_text": "...",
      "message": "...",
      "station_match": { "matched": true, "nearest_station": "...", "police_directorate": "...", "liwa_name": "...", "lat": 31.99, "lon": 35.88, "candidates": [] }
    }
    ```

#### 4. Download / View Stored Scan Document
- **`GET /api/v1/mat/police-complaints/scans/{scan_id}`**
  - **Roles:** `officer`, `admin`, `governor` (403 for `caller`).
  - **Query Params:** `?download=1` sets `Content-Disposition: attachment`; default is `inline`.
  - **Headers:** `Cache-Control: no-store`, validated MIME (`image/jpeg`, `image/png`, `image/webp`, `application/pdf`).

#### 5. Create Complaint Intake Record
- **`POST /api/v1/mat/police-complaints`**
  - **Roles:** `officer`, `admin`.
  - **Payload:** `{ "subject": "...", "summary": "...", "paper_date": "YYYY-MM-DD", "complaint_number": "(optional)", "submit_stage": "draft_scan | officer_reviewed | pending_section_head", "complainants": [...], "respondents": [...], "has_signature": true, "no_pending_lawsuit_declared": true, "scan_ids": [12], "nearest_station": "(optional override)", "assigned_officer_id": null, "officer_action": "...", "officer_notes": "...", "ai_provider": "...", "ai_model": "...", "ai_extracted_json": {}, "ai_analysis": "...", "ai_solution_recommendation": "...", "ai_recommended_action": "...", "ai_confidence": 0.9 }`
  - **Response (`201`):** Full complaint detail object (auto-generates unique `PC-YYYYMMDD-NNNN` if omitted, auto-matches nearest police station from first respondent address if not overridden, triggers FCM push if `submit_stage = "pending_section_head"`).

#### 6. Update Complaint Details
- **`PUT /api/v1/mat/police-complaints/{id}`**
  - **Roles:** `officer`, `admin` for general edits (blocked if `workflow_stage` is `completed` or `stopped_90_days`).
  - **Follow-up Shorthand:** If payload contains `followup_action` (within `{followup_action, action_type, notes}`), `officer`, `admin`, and `governor` are all permitted and routed to `register_followup()`.

#### 7. Officer Action & Mandatory Notes
- **`POST /api/v1/mat/police-complaints/{id}/officer-action`**
  - **Roles:** `officer`, `admin`.
  - **Payload:** `{ "officer_action": "...", "officer_notes": "(mandatory)", "send_to_section_head": true|false, "execution_status": "in_execution | completed" }`
  - **Behavior:** Pre-approval stages transition to `pending_section_head` or `officer_reviewed`; post-approval stages (`governor_approved`, `governor_modified`, `in_execution`) transition to `in_execution` or `completed`. Updates `last_followup_at`.

#### 8. Section Head Referral (`تنسيب رئيس القسم`)
- **`POST /api/v1/mat/police-complaints/{id}/section-recommend`**
  - **Roles:** `admin` ONLY.
  - **Payload:** `{ "section_recommended_action": "(mandatory)", "section_head_notes": "(mandatory)", "nearest_station": "(optional)", "police_directorate": "(optional)", "liwa_name": "(optional)", "station_lat": null, "station_lon": null }`
  - **Behavior:** Transitions stage to `pending_governor` and sends FCM push to `governor` users.

#### 9. Administrative Governor Decision (`قرار الحاكم الإداري`)
- **`POST /api/v1/mat/police-complaints/{id}/governor-decision`**
  - **Roles:** `governor` ONLY (`403` for `admin`, `officer`, `caller`).
  - **Payload:** `{ "decision": "موافقة | رفض | تغيير_الإجراء", "governor_final_action": "(required when تغيير_الإجراء)", "governor_notes": "...", "nearest_station": "(optional)", "police_directorate": "(optional)", "liwa_name": "(optional)", "station_lat": null, "station_lon": null }`
  - **Automated Integrations:**
    - `اتصال هاتفي` (approved/modified): Auto-creates `mat_simple_appointments` record (`linked_appointment_id`) and dispatches FCM to `caller` role.
    - `توديع عن طريق مركز أمني` / `توديع مغفور` (approved/modified): Auto-reserves file in `mat_reserved_files` + `mat_file_custody_log` (`linked_file_number`), and `توديع مغفور` escalates `priority` to `'عاجل'`.

#### 10. Follow-up & 90-Day Stop Rule
- **`POST /api/v1/mat/police-complaints/{id}/followup`**
  - **Roles:** `officer`, `admin`, `governor`.
  - **Payload:** `{ "action_type": "followup | stop_90_days", "notes": "..." }`
  - **Rules:** `followup` resets `last_followup_at` to now; `stop_90_days` requires `days_elapsed >= 90` OR explicit override by `admin`/`governor` with non-empty `notes`.

#### 11. Official `.docx` Export & GIS Match
- **`GET /api/v1/mat/police-complaints/{id}/export-docx`**
  - **Roles:** `officer`, `admin`, `governor`.
  - **Response (`200`):** Populated Word `.docx` bytes (`Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`, `Cache-Control: no-store`).
- **`GET /api/v1/mat/police-complaints/match-station?address=...`**
  - **Roles:** `officer`, `admin`, `governor`, `caller`.
  - **Response (`200`):** `{ "matched", "area_name", "nearest_station", "police_directorate", "liwa_name", "lat", "lon", "candidates" }`.

---

### Vision LLM Settings (Admin Only)
- **`GET /api/v1/mat/llm-settings`** (`admin` only) -> Returns `{ "provider", "model_name", "api_base_url", "is_enabled", "api_key_configured", "api_key_masked", "source" }` (raw `api_key` is NEVER returned).
- **`PUT /api/v1/mat/llm-settings`** (`admin` only) -> Payload: `{ "provider": "gemini|openai|ollama", "model_name": "...", "api_base_url": "http(s)://...", "api_key": "(optional; blank or **** preserves existing key)", "is_enabled": 1|0 }`.
- **`POST /api/v1/mat/llm-settings/test`** (`admin` only) -> Validates and tests provider connectivity without persisting temporary inputs (`{ "ok": true|false, "message": "...", "provider": "...", "model": "..." }`).

---

### Existing MAT Endpoints
- **Legacy Complaints & Parties:** `GET/POST /api/v1/mat/complaints`, `GET/PUT/DELETE /api/v1/mat/complaints/{id}`, `POST/PUT/DELETE /api/v1/mat/parties`
- **Simple Appointments:** `GET/POST /api/v1/mat/simple-appointments`, `GET/PUT/DELETE /api/v1/mat/simple-appointments/{id}`
- **File Reservations (Custody Tracking):** `GET/POST /api/v1/mat/reservations`, `GET /api/v1/mat/reservations/search`, `GET /api/v1/mat/reservations/pending`, `GET /api/v1/mat/reservations/history/{id}`, `POST /api/v1/mat/reservations/transfer`, `POST /api/v1/mat/reservations/respond`, `DELETE /api/v1/mat/reservations/{id}`
- **Internal Chat & Push Notifications:** `GET /api/v1/mat/chat/messages`, `POST /api/v1/mat/chat/message`, `GET /api/v1/mat/chat/poll`, `GET /api/v1/mat/chat/online_users`, `GET /api/v1/mat/chat/archives`, `POST /api/v1/mat/save-fcm-token`
- **GIS Data:** `GET /api/v1/mat/areas`, `GET /api/v1/mat/search`, `POST /api/v1/mat/log-search`

## Security Notes
- Emergency Admin overrides are supported via `MAT_SECRET_KEY` logic built into `/api/v1/mat/login`.
- Any unmasked API keys or internal exceptions are redacted via `mat_llm_engine._redact_secret()` before logging or returning safe HTTP `500` responses.
