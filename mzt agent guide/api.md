# MAT API Contracts & Integration

All core API endpoints are prefixed with `/api/v1/mat/`.
Authentication is handled via session cookies (`token=...`), which are verified using the `mat_sessions` database table.

## Core API Routes

### Authentication
- **`POST /api/v1/mat/login`**
  - **Payload:** `{ "username": "...", "password": "..." }`
  - **Response:** `{ "status": "success", "token": "..." }` or error.

- **`POST /api/v1/mat/logout`**
  - Logs out current session cookie.

### Complaints & Cases
- **`GET /api/v1/mat/complaints`**
  - Fetch list of complaints.
- **`POST /api/v1/mat/complaints`**
  - Create a new complaint.

### Simple Appointments
- **`GET /api/v1/mat/simple-appointments`**
  - **Query Params:** `?start=...&end=...&status=...`
  - **Response:** JSON list of appointments.
- **`POST /api/v1/mat/simple-appointments`**
  - Create a new appointment for a case/visitor.

### File Reservations (Custody Tracking)
- **`GET /api/v1/mat/reservations`**
  - Fetch active physical file custody reservations.
- **`POST /api/v1/mat/reservations/transfer`**
  - Transfer a file to another officer.

### Internal Chat & Push Notifications
- **`GET /api/v1/mat/chat/messages`**
  - Fetch internal meeting room messages.
- **`POST /api/v1/mat/chat/messages`**
  - **Payload:** `{ "message": "..." }`
  - Sends message and triggers FCM push notification.
- **`POST /api/v1/mat/save-fcm-token`**
  - **Payload:** `{ "fcm_token": "..." }`
  - Saves the device FCM token for web/mobile push notifications to `mat_officers`.

## Security
- Emergency Admin overrides are supported via `MAT_SECRET_KEY` logic built into the server handlers.
