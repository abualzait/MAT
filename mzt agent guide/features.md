# Project Features & Roadmap — MAT (Amman Police Stations)

## Current Features (Version 1.45.7)

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
   - **Dynamic 9-Liwa Boundary Shading:** Color-coded shaded polygons for each of Amman's 9 official administrative Liwas.
   - **Search Target Isolation:** The Liwa resulting from search is kept completely unshaded (0% fill opacity) with a crisp border highlight, while all other surrounding Liwas are tinted with distinct shading colors.
   - **Camera Pan & Close Zoom:** Smooth `flyTo` animation moving the map camera and zooming in (zoom level 16) directly to the resulting place and nearest station with automatic popup display.
   - **Accurate Station Coordinates:** Verified and corrected coordinates for police stations, including Dahiet Al-Rasheed Police Station (`31.9966, 35.8883` on Al-Wefaq Street).

5. **Internal Meeting Room & FCM Push Notifications:**
   - Real-time team messaging with unread notification badge.
   - Firebase Cloud Messaging (FCM v1) background & lock screen push notifications for browser & mobile devices via `/firebase-messaging-sw.js` and `/api/v1/mat/save-fcm-token`.

6. **Role-Based Access Control & Secret Key Support:**
   - Multi-role permissions (`admin`, `officer`, `caller`).
   - Emergency secret key override for admin privileges.

7. **Dashboard Quick Shortcuts:**
   - Direct header action shortcuts for "حجز موعد جديد", "مواعيد اليوم", and "دليل المراكز الأمنية".
