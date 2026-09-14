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

1. **`mat_officers`**: User accounts and administrative roles (`admin`, `officer`, `caller`).
2. **`mat_complaints`**: Citizen complaint records, status tracking, and case files.
3. **`mat_parties`**: Complainants, respondents, and associated party details.
4. **`mat_appointments` / `mat_simple_appointments`**: Call logs, visitor meetings, dates, times, and status.
5. **`mat_reserved_files`**: Physical file reservations, current custody owner, and custody history logs (`mat_file_custody_log`).
6. **`mat_chat_messages`**: Real-time internal team messaging records.
7. **`mat_search_logs`**: Metrics and search queries logged from the GIS Police Station Finder.
8. **`mat_sessions`**: Active authentication tokens and user sessions.
