# Project Dictionary & Architectural Schema — MAT (Amman Police Stations)

## System Terminology

| Term / Abbreviation | Arabic Term | Definition & Purpose |
| :--- | :--- | :--- |
| **MAT** | حقيبة الأدوات المساعدة | Modular Assistant Toolkit — Core internal web application for Amman Governorate support staff. |
| **Police Station Finder** | دليل المراكز الأمنية | GIS-based interactive finder mapping areas, directorates, and nearest police stations in Amman. |
| **File Custody Tracking** | نظام تتبع الملفات | Tool tracking physical file ownership and transfer between officers (`mat_reserved_files`). |
| **Simple Appointments** | نظام المواعيد والاتصالات | Appointment scheduling and visitor logs for governorate departments (`mat_simple_appointments`). |
| **Meeting Room** | غرفة الاجتماعات | Live internal messaging and discussion channel between officers (`mat_chat_messages`). |

## Database Schema Overview (`complaints.db`)

1. **`mat_officers`**: User accounts, administrative roles (`admin`, `officer`, `caller`), accessible tools list, and device FCM tokens (`fcm_token`) for push notifications.
2. **`mat_complaints`**: Citizen complaint records, status tracking, and case files.
3. **`mat_parties`**: Complainants, respondents, and associated party details.
4. **`mat_appointments` / `mat_simple_appointments`**: Call logs, visitor meetings, dates, times, and status.
5. **`mat_reserved_files`**: Physical file reservations, current custody owner, and custody history logs (`mat_file_custody_log`).
6. **`mat_chat_messages`**: Real-time internal team messaging records with instant FCM push dispatch.
7. **`mat_search_logs`**: Metrics and search queries logged from the GIS Police Station Finder.
8. **`mat_sessions`**: Active authentication tokens and user sessions.

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

