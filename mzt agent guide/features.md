# Project Features & Roadmap — MAT (Amman Police Stations)

## Current Features (Version 1.45.10)

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
   - **Floating Result Card Box on Map:** Direct on-map preview card displaying the three primary administrative fields: **المركز الأمني (Police Station)**, **الوحدة الإدارية (Administrative Unit)**, and **مديرية الشرطة (Police Directorate)**, alongside distance, phone contact, and Google Maps direction navigation.
   - **Interactive Map Fullscreen Maximize:** Toggle control to expand the map into true full-viewport view (`100vw × 100vh`) with automatic tile resizing and keyboard `Escape` shortcut support.

5. **Internal Meeting Room & FCM Push Notifications:**
   - Real-time team messaging with unread notification badge.
   - Firebase Cloud Messaging (FCM v1) background & lock screen push notifications for browser & mobile devices via `/firebase-messaging-sw.js` and `/api/v1/mat/save-fcm-token`.

6. **Role-Based Access Control & Secret Key Support:**
   - Multi-role permissions (`admin`, `officer`, `caller`).
   - Emergency secret key override for admin privileges.

7. **Dashboard Quick Shortcuts:**
   - Direct header action shortcuts for "حجز موعد جديد", "مواعيد اليوم", and "دليل المراكز الأمنية".


### التحديث v1.45.10 (مربع البحث في ملء الشاشة ورابط مباشر بالخريطة من صفحة الدخول)
1. **مربع البحث العائم عن المناطق عند عرض الخارطة ملء الشاشة (Fullscreen Map Area Search):**
   - تصميم شريط بحث زجاجي عائم (`map-area-search-box`) يظهر تلقائياً أعلى الخريطة في وضع ملء الشاشة دون حجب أزرار التحكم أو أدوات التكبير.
   - بحث فوري لحظي في كافة مناطق العاصمة (566 منطقة وحي ودوار)، مع قائمة إكمال تلقائي مقسمة إلى فئات مع أيقونات وشارات ملونة.
   - عرض اسم أقرب مركز أمني معتمد لكل حي أو منطقة سكنية ضمن قائمة الاقتراحات مباشرة.
   - انتقال كاميرا الخريطة فوراً بالتحليق (`flyTo`) مع التكبير المباشر وتظليل الألوية وعرض بطاقة النتيجة العائمة (`mapResultCardBox`).
   - دعم كامل للتنقل بأسهم لوحة المفاتيح وزر تفريغ سريع `✕` وزر تحديد الموقع الجغرافي المباشر `📍`.
   - مزامنة متبادلة وفورية بين حقل البحث الرئيسي في الصفحة وحقل البحث في ملء الشاشة.
2. **رابط وصول مباشر للخريطة بصفحة الدخول (Direct Fullscreen Link on Login Page):**
   - إضافة بطاقة تفاعلية مميزة بصفحة الدخول (`/login` / `complaints/login.html`) بلون الهوية المؤسسية لمحافظة العاصمة تنقل المستخدم مباشرة إلى `/finder?fullscreen=1`.
   - تفعيل وضع ملء الشاشة فور فتح الرابط مع إعادة ضبط أبعاد الخريطة (`forceMapResize`).
   - إضافة زر عودة سريع لصفحة الدخول (`🚪 تسجيل الدخول`) داخل أدوات وضع ملء الشاشة.

### التحديث v1.45.9 (تجاوز الكاش والمزامنة اللحظية وتحسين الاستجابة للشاشات المقسمة والأجهزة اللوحية)
1. **شريط تبديل العرض المتجاوب (Responsive View Switcher):**
   - إضافة شريط تبديل سريع يظهر تلقائياً عند تضييق الشاشة أو داخل النوافذ المقسمة وiframe (`<= 992px`):
     - `🗺️ الخريطة والبطاقة`: تظهر الخريطة التفاعلية بالكامل مع تظليل الألوية وبطاقة النتيجة العائمة دون الحاجة للتمرير لأسفل.
     - `👮 تفاصيل المركز`: بطاقة المركز الأمني وقائمة المراكز المحيطة مع زر سريع `🗺️ الخريطة`.
     - `📍 الأماكن المطابقة`: قائمة نتائج البحث للأماكن المطابقة والمعالم.
     - `📑 عرض متتابع`: تتابع تقليدي للأقسام الثلاثة.
2. **التركيز التلقائي على الخريطة عند البحث (Map-First Auto-Focus):**
   - عند إتمام أي عملية بحث أو اختيار موقع من القائمة، يتحول العرض تلقائياً إلى تبويب الخريطة (`view-map`) لضمان رؤية تظليل اللواء والمركز والبطاقة العائمة فوراً.
3. **منع التخزين المؤقت وحظر الكاش (Cache-Busting & Anti-Caching):**
   - تحديث `server.py` لإرسال ترويسات `Cache-Control: no-cache, no-store, must-revalidate` لجميع الملفات وملف `Police_Station_Finder.html`.
   - تنظيف السكربتات المزدوجة في `complaints/app.html` وتحديث وسوم الإصدار إلى `?v=1.45.9`.
