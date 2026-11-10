# Project Dictionary & Architectural Schema — MAT (Amman Police Stations)

## System Terminology

| Term / Abbreviation | Arabic Term | Definition & Purpose |
| :--- | :--- | :--- |
| **MAT** | حقيبة الأدوات المساعدة | Modular Assistant Toolkit — Core internal web application for Amman Governorate support staff. |
| **Smart Police Complaints** | الشكاوى الأمنية الذكية | End-to-end digital intake, AI Vision OCR, officer review, section referral, Governor approval, 90-day tracking, and `.docx` export workspace (`police_complaints` tool / `#tab-police-complaints`). |
| **Administrative Governor** | الحاكم الإداري (عطوفة المتصرف) | Exclusive decision-making authority (`governor` role, user `governor`) who approves, modifies, or rejects section head referrals and triggers automated downstream execution. |
| **Section Head Referral** | تنسيب رئيس القسم | Administrative recommendation step performed exclusively by `admin` (`section_head_notes` + `section_recommended_action`), advancing a complaint to `pending_governor`. |
| **Officer Review / Action** | نظر الضابط | Pre-approval assessment or post-approval execution action recorded by an `officer` or `admin` with mandatory `officer_notes` (`officer_action`). |
| **90-Day Stop Rule** | قاعدة 90 يوماً — كف الطلب | Regulatory lifecycle counter from `last_followup_at`: normal `<75` days, warning `75–89` days, due for stop `>=90` days (`is_due_for_stop=true`, stage `stopped_90_days` / `كف طلب (90 يوماً)`). Reset on complainant follow-up. |
| **Station Referral** | توديع عن طريق مركز أمني | Official action referring the complaint to the matched/designated police station; upon Governor approval, automatically reserves the complaint file in `mat_reserved_files`. |
| **Escorted / Urgent Referral** | توديع مغفور | High-priority police escort referral; upon Governor approval, automatically reserves the complaint file in `mat_reserved_files` AND escalates complaint `priority` to `'عاجل'`. |
| **Phone Call Referral** | اتصال هاتفي | Resolution via telephone contact; upon Governor approval, automatically creates a scheduled record in `mat_simple_appointments`, exposes the complaint to `caller` staff, and sends an FCM alert to callers. |
| **Police Station Finder** | دليل المراكز الأمنية | GIS-based interactive finder mapping areas, directorates, and nearest police stations in Amman (`Police_Station_Finder.html`). |
| **File Custody Tracking** | نظام تتبع الملفات | Tool tracking physical file ownership and transfer between officers (`mat_reserved_files`, `mat_file_custody_log`). |
| **Simple Appointments** | نظام المواعيد والاتصالات | Appointment scheduling and visitor logs for governorate departments (`mat_simple_appointments`). |
| **Meeting Room** | غرفة الاجتماعات | Live internal messaging and discussion channel between officers (`mat_chat_messages`). |

## Database Schema Overview (`mat_complaints.db` / `complaints.db`)

1. **`mat_officers`**: User accounts, administrative roles (`admin`, `officer`, `caller`, `governor`), accessible tools list (`dashboard,mat_complaints,finder,file_reservations,police_complaints,chat`), and device FCM tokens (`fcm_token`).
2. **`mat_complaints`**: Citizen & police complaint records, paper date, party categories, formal checkboxes (`has_signature`, `no_pending_lawsuit_declared`, `is_minor_police_complaint`), AI Vision extraction & recommendation fields, officer action, section head recommendation, governor decision, GIS station match (`nearest_station`, `police_directorate`, `liwa_name`, `station_lat`, `station_lon`), MAT links (`linked_appointment_id`, `linked_file_number`), workflow stage (`workflow_stage`), and 90-day counter (`last_followup_at`).
3. **`mat_parties`**: Complainants (`شاكي`) and respondents (`مشتكى_عليه`), including `party_category` (`مواطن`, `مؤسسة تجارية`, `مؤسسة حكومية`, `منشأة`), `phone`, `national_id`, and `address`.
4. **`mat_complaint_scans`**: Metadata for uploaded scan attachments (`stored_filename` UUID, `original_filename`, `mime_type`, `file_size`, `page_order`, `ocr_raw_text`, `uploaded_by_id`).
5. **`mat_complaint_workflow_log`**: Chronological audit log of every stage transition, actor role, action taken, and notes for each complaint.
6. **`mat_llm_settings`**: Single-row (`id = 1`) Vision AI configuration (`provider`, `model_name`, `api_base_url`, `api_key`, `is_enabled`, `updated_by_id`, `updated_at`).
7. **`mat_appointments` / `mat_simple_appointments`**: Call logs, visitor meetings, dates, times, and status (automatically populated for `اتصال هاتفي` Governor approvals).
8. **`mat_reserved_files` / `mat_file_custody_log`**: Physical file reservations and chain-of-custody transfers (automatically populated for `توديع عن طريق مركز أمني` and `توديع مغفور` approvals).
9. **`mat_chat_messages`**: Real-time internal team messaging records with instant FCM push dispatch.
10. **`mat_search_logs`**: Metrics and search queries logged from the GIS Police Station Finder.
11. **`mat_sessions`**: Active authentication tokens, user roles, accessible tools, and chat presence (`last_chat_seen`, `last_seen`).
12. **`mat_activity_log` / `mat_audit_logs`**: System-wide user activity and audit trail tables.

## Workflow Stage Glossary (`workflow_stage`)

| Stage Key | Arabic Display Status | Meaning |
| :--- | :--- | :--- |
| `draft_scan` | جديد / مسودة مسح | Newly scanned or entered draft awaiting officer action |
| `officer_reviewed` | قيد المراجعة / نظر الضابط | Reviewed by an officer with action & notes recorded |
| `pending_section_head` | بانتظار رئيس القسم | Submitted by officer for section head referral (`تنسيب`) |
| `pending_governor` | بانتظار الحاكم الإداري | Recommended by section head; awaiting Governor's decision |
| `governor_approved` | معتمدة | Approved by Administrative Governor as recommended |
| `governor_modified` | معتمدة (معدلة) | Approved by Governor with modified final action |
| `governor_rejected` | مرفوضة | Rejected by Governor; returned for officer/section re-review |
| `in_execution` | قيد التنفيذ | Post-approval execution underway by assigned officer |
| `completed` | منجزة | Complaint execution completed and closed |
| `stopped_90_days` | كف طلب (90 يوماً) | Formally stopped due to 90+ days without complainant follow-up |

## Administrative Districts of Amman Governorate (ألوية محافظة العاصمة)

| Liwa Name (اللواء) | English Name | Color Code | Center Coordinates | Curated Key Stations |
| :--- | :--- | :--- | :--- | :--- |
| **لواء قصبة عمان** | Amman Qasabah District | `#2563EB` | `31.9510, 35.9380` | مركز أمن المدينة، المهاجرين، زهران، الشميساني، الحسين، التاج |
| **لواء الجامعة** | Al-Jami'ah District | `#7C3AED` | `32.0120, 35.8730` | مركز أمن ضاحية الرشيد، أبو نصير، صويلح، تلاع العلي، شفا بدران |
| **لواء وادي السير** | Wadi Essier District | `#059669` | `31.9340, 35.8450` | مركز أمن البيادر، مركز أمن مرج الحمام |
| **لواء ماركا** | Marka District | `#D97706` | `31.9750, 35.9850` | مركز أمن ماركا، طارق، النصر، الهاشمي |
| **لواء القويسمة** | Quaismeh District | `#DB2777` | `31.9180, 35.9650` | مركز أمن القويسمة، المقابلين، الجويدة، المنارة، أحد، اليادودة |
| **لواء سحاب** | Sahab District | `#0891B2` | `31.8850, 36.0050` | مركز أمن سحاب |
| **لواء ناعور** | Na'oor District | `#0D9488` | `31.8650, 35.8250` | مركز أمن ناعور |
| **لواء الموقر** | Muaqqar District | `#EA580C` | `31.8175, 36.1039` | مركز أمن الموقر |
| **لواء الجيزة** | Jizah District | `#4F46E5` | `31.7000, 35.9500` | مركز أمن الجيزة |
