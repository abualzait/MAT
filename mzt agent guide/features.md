# Project Features & Roadmap — MAT (Amman Police Stations)

## Current Features (Version 1.44.0)

1. **Complaints & Cases Management (`/complaints/app`):**
   - Record, view, and process citizen complaints and administrative cases.
   - Global search by case number, complainant name, or visitor record.

2. **Appointments & Calls Scheduling:**
   - Manage daily schedules, postponed appointments, and no-shows.
   - Filter by date range and appointment status (`مُجدول`, `مُؤجل`, `تم الحضور`, `لم يحضر`, `لم يجيبوا`, `ملغى`).
   - Monthly calendar agenda view and printable daily schedule.

3. **Physical File Custody Tracking (`/api/v1/mat/reservations`):**
   - Reserve active physical files under officer custody.
   - Initiate and accept custody transfers between officers with complete audit logs.

4. **GIS Police Station Directory (`/finder` / `Police_Station_Finder.html`):**
   - Offline/Online Leaflet interactive map with custom tile caching.
   - Search by Amman area, neighborhood, street, or landmark.
   - Locate nearest police station and view contact numbers & administrative details.

5. **Internal Meeting Room & FCM Push Notifications:**
   - Real-time team messaging with unread notification badge.
   - Firebase Cloud Messaging (FCM v1) background & lock screen push notifications for browser & mobile devices via `/firebase-messaging-sw.js` and `/api/v1/mat/save-fcm-token`.

6. **Role-Based Access Control & Secret Key Support:**
   - Multi-role permissions (`admin`, `officer`, `caller`).
   - Emergency secret key override for admin privileges.

7. **Dashboard Quick Shortcuts:**
   - Direct header action shortcuts for "حجز موعد جديد", "مواعيد اليوم", and "دليل المراكز الأمنية".
