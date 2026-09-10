#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║  MAT (Modular Assistant Toolkit) — حقيبة الأدوات المساعدة (1.23.0)  ║
║                                                              ║
║  يعمل بدون إنترنت على الشبكة المحلية                        ║
║  لا يحتاج تثبيت أي مكتبات إضافية                           ║
║                                                              ║
║  التشغيل: python server.py                                   ║
║  الوصول: http://عنوان-الجهاز:5000                            ║
╚══════════════════════════════════════════════════════════════╝
"""

import http.server
import socketserver
import sqlite3
import json
import hashlib
import uuid
import os
import re
import urllib.parse
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
import socket
import threading
import sys
import mimetypes

# Ensure UTF-8 stdout encoding for Windows console
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# ─── Environment & Configuration ───────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_env():
    env_file = os.path.join(BASE_DIR, '.env')
    if os.path.isfile(env_file):
        with open(env_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())

load_env()

MAT_ENV = os.environ.get('MAT_ENV', 'production')
MAT_PORT = int(os.environ.get('PORT', os.environ.get('MAT_PORT', 5001)))
MAT_HOST = os.environ.get('MAT_HOST', '0.0.0.0')
_data_dir = '/data'
if not os.path.exists(_data_dir):
    try:
        os.makedirs(_data_dir, exist_ok=True)
    except Exception:
        _data_dir = BASE_DIR

_default_db = os.path.join(_data_dir, 'mat_complaints.db')
MAT_DB_PATH = os.environ.get('MAT_DB_PATH', _default_db)
MAT_API_PREFIX = os.environ.get('MAT_API_PREFIX', '/api/v1/mat')
MAT_SECRET_KEY = os.environ.get('MAT_SECRET_KEY', 'mat_secret_key_2026')

matConfig = {
    'env': MAT_ENV,
    'port': MAT_PORT,
    'host': MAT_HOST,
    'db_path': MAT_DB_PATH,
    'api_prefix': MAT_API_PREFIX,
    'name': 'MAT',
    'arabic_name': 'حقيبة الأدوات المساعدة',
    'full_name': 'Modular Assistant Toolkit',
    'description': 'A highly scalable, modular digital workspace designed for governorate departments and official administrative support'
}

DB_PATH = MAT_DB_PATH
PORT = MAT_PORT
HOST = MAT_HOST


# ─── Global State ─────────────────────────────────────────────
chat_event = threading.Event()

# ══════════════════════════════════════════════════════════════
#  DATABASE
# ══════════════════════════════════════════════════════════════

def get_db():
    """Get a new database connection (thread-safe)."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def dict_from_row(row):
    """Convert sqlite3.Row to dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert list of sqlite3.Row to list of dicts."""
    return [dict(r) for r in rows]


def sync_postponed_appointments(conn):
    """Auto-update status of parent or superseded mat_appointments to 'مُؤجل'."""
    try:
        # 1. Explicit parent mat_appointments
        conn.execute("""
            UPDATE mat_simple_appointments 
            SET status = 'مُؤجل', updated_at = datetime('now', 'localtime')
            WHERE id IN (
                SELECT DISTINCT parent_appointment_id 
                FROM mat_simple_appointments 
                WHERE parent_appointment_id IS NOT NULL AND parent_appointment_id != ''
            ) AND status = 'مُجدول'
        """)
        # 2. Older mat_appointments for same visitor or case number where a newer appointment was created
        conn.execute("""
            UPDATE mat_simple_appointments 
            SET status = 'مُؤجل', updated_at = datetime('now', 'localtime')
            WHERE status = 'مُجدول' AND id IN (
                SELECT a1.id
                FROM mat_simple_appointments a1
                JOIN mat_simple_appointments a2 
                  ON (
                       (a1.case_number = a2.case_number AND a1.case_number IS NOT NULL AND a1.case_number != '') 
                       OR 
                       (a1.visitor_name = a2.visitor_name AND a1.visitor_name IS NOT NULL AND a1.visitor_name != '')
                     )
                 AND a2.id > a1.id
                 AND (
                       a2.appointment_date > a1.appointment_date 
                       OR 
                       (a2.appointment_date = a1.appointment_date AND a2.appointment_time > a1.appointment_time)
                     )
                WHERE a1.status = 'مُجدول'
            )
        """)
        conn.commit()
    except Exception as e:
        print(f"Error syncing postponed mat_appointments: {e}")



def init_db():
    """Initialize database tables and default data."""
    conn = get_db()
    c = conn.cursor()

    # ── Auto-Migration: Rename legacy tables to mat_ prefix BEFORE table creation ────────
    legacy_tables = [
        ('officers', 'mat_officers'),
        ('complaints', 'mat_complaints'),
        ('parties', 'mat_parties'),
        ('appointments', 'mat_appointments'),
        ('appointment_parties', 'mat_appointment_parties'),
        ('activity_log', 'mat_activity_log'),
        ('simple_appointments', 'mat_simple_appointments'),
        ('search_logs', 'mat_search_logs'),
        ('chat_messages', 'mat_chat_messages'),
        ('reserved_files', 'mat_reserved_files'),
        ('file_custody_log', 'mat_file_custody_log'),
        ('sessions', 'mat_sessions'),
        ('audit_logs', 'mat_audit_logs')
    ]
    for old_t, new_t in legacy_tables:
        try:
            res_old = c.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{old_t}'").fetchone()[0]
            res_new = c.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{new_t}'").fetchone()[0]
            if res_old > 0 and res_new == 0:
                c.execute(f"ALTER TABLE {old_t} RENAME TO {new_t}")
        except Exception as e:
            print(f"Migration rename error for {old_t} -> {new_t}: {e}")
    conn.commit()
    # ── Auto-Migration: Rename legacy tables to mat_ prefix ────────
    legacy_tables = [
        ('mat_officers', 'mat_officers'),
        ('mat_complaints', 'mat_complaints'),
        ('mat_parties', 'mat_parties'),
        ('mat_appointments', 'mat_appointments'),
        ('mat_appointment_parties', 'mat_appointment_parties'),
        ('mat_activity_log', 'mat_activity_log'),
        ('mat_simple_appointments', 'mat_simple_appointments'),
        ('mat_search_logs', 'mat_search_logs'),
        ('mat_chat_messages', 'mat_chat_messages'),
        ('mat_reserved_files', 'mat_reserved_files'),
        ('mat_file_custody_log', 'mat_file_custody_log'),
        ('mat_sessions', 'mat_sessions'),
        ('mat_audit_logs', 'mat_audit_logs')
    ]
    for old_t, new_t in legacy_tables:
        try:
            res_old = c.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{old_t}'").fetchone()[0]
            res_new = c.execute(f"SELECT count(*) FROM sqlite_master WHERE type='table' AND name='{new_t}'").fetchone()[0]
            if res_old > 0 and res_new == 0:
                c.execute(f"ALTER TABLE {old_t} RENAME TO {new_t}")
        except Exception as e:
            print(f"Migration rename error for {old_t} -> {new_t}: {e}")
    conn.commit()


    c.executescript('''
        CREATE TABLE IF NOT EXISTS mat_officers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'officer', 'caller')),
            accessible_tools TEXT DEFAULT 'mat_complaints,finder',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_number TEXT,
            subject TEXT NOT NULL,
            complaint_type TEXT DEFAULT 'عام',
            status TEXT DEFAULT 'جديد',
            priority TEXT DEFAULT 'عادي',
            notes TEXT,
            assigned_officer_id INTEGER REFERENCES mat_officers(id),
            created_by_id INTEGER REFERENCES mat_officers(id),
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
            party_type TEXT NOT NULL CHECK(party_type IN ('شاكي', 'مشتكى_عليه')),
            name TEXT NOT NULL,
            phone TEXT,
            national_id TEXT,
            address TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id INTEGER NOT NULL REFERENCES mat_complaints(id) ON DELETE CASCADE,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            appointment_type TEXT DEFAULT 'فردي' CHECK(appointment_type IN ('فردي', 'مشترك')),
            status TEXT DEFAULT 'مُجدول',
            location TEXT DEFAULT 'مكتب قسم الشكاوي',
            notes TEXT,
            requested_by_id INTEGER REFERENCES mat_officers(id),
            parent_appointment_id INTEGER REFERENCES mat_appointments(id),
            created_by_id INTEGER REFERENCES mat_officers(id),
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_appointment_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL REFERENCES mat_appointments(id) ON DELETE CASCADE,
            party_id INTEGER NOT NULL REFERENCES mat_parties(id) ON DELETE CASCADE,
            call_status TEXT DEFAULT 'لم_يُتصل',
            called_at TEXT,
            called_by_id INTEGER REFERENCES mat_officers(id),
            attendance TEXT DEFAULT 'منتظر',
            notes TEXT,
            UNIQUE(appointment_id, party_id)
        );

        CREATE TABLE IF NOT EXISTS mat_activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES mat_officers(id),
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id INTEGER,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_simple_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_number TEXT NOT NULL,
            visitor_name TEXT NOT NULL,
            phone TEXT,
            national_id TEXT,
            station_name TEXT,
            appointment_date TEXT NOT NULL,
            appointment_time TEXT NOT NULL,
            status TEXT DEFAULT 'مُجدول',
            notes TEXT,
            requested_by_id INTEGER REFERENCES mat_officers(id),
            parent_appointment_id INTEGER REFERENCES mat_simple_appointments(id),
            created_by_id INTEGER REFERENCES mat_officers(id),
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            updated_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_search_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            area_name TEXT NOT NULL UNIQUE,
            closest_station TEXT NOT NULL,
            directorate TEXT NOT NULL,
            search_count INTEGER DEFAULT 1,
            last_searched_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS mat_chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES mat_officers(id),
            message TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );

        CREATE INDEX IF NOT EXISTS idx_parties_phone ON mat_parties(phone);
        CREATE INDEX IF NOT EXISTS idx_parties_name ON mat_parties(name);
        CREATE INDEX IF NOT EXISTS idx_complaints_status ON mat_complaints(status);
        CREATE INDEX IF NOT EXISTS idx_appointments_date ON mat_appointments(appointment_date);
        CREATE INDEX IF NOT EXISTS idx_simple_appts_date ON mat_simple_appointments(appointment_date);
        CREATE INDEX IF NOT EXISTS idx_simple_appts_case ON mat_simple_appointments(case_number);
        CREATE INDEX IF NOT EXISTS idx_simple_appts_name ON mat_simple_appointments(visitor_name);
        CREATE INDEX IF NOT EXISTS idx_search_logs_count ON mat_search_logs(search_count);
        CREATE TABLE IF NOT EXISTS mat_reserved_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_number TEXT NOT NULL UNIQUE,
            officer_id INTEGER NOT NULL REFERENCES mat_officers(id),
            notes TEXT,
            reserved_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS mat_file_custody_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reserved_file_id INTEGER NOT NULL REFERENCES mat_reserved_files(id) ON DELETE CASCADE,
            from_officer_id INTEGER REFERENCES mat_officers(id),
            to_officer_id INTEGER NOT NULL REFERENCES mat_officers(id),
            status TEXT DEFAULT 'accepted',
            notes TEXT,
            transferred_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS mat_sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES mat_officers(id),
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            accessible_tools TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            last_seen TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS mat_audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            resource_id TEXT NOT NULL,
            actor_id INTEGER REFERENCES mat_officers(id),
            timestamp TEXT DEFAULT (datetime('now', 'localtime')),
            details TEXT
        );
    ''')

    # Run DB Migrations for existing databases
    try:
        # Check if mat_audit_logs exists
        c.execute("CREATE TABLE IF NOT EXISTS mat_audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL, resource_id TEXT NOT NULL, actor_id INTEGER REFERENCES mat_officers(id), timestamp TEXT DEFAULT (datetime('now', 'localtime')), details TEXT)")

        # Check if mat_file_custody_log exists and has status column
        c.execute("CREATE TABLE IF NOT EXISTS mat_file_custody_log (id INTEGER PRIMARY KEY AUTOINCREMENT, reserved_file_id INTEGER NOT NULL REFERENCES mat_reserved_files(id) ON DELETE CASCADE, from_officer_id INTEGER REFERENCES mat_officers(id), to_officer_id INTEGER NOT NULL REFERENCES mat_officers(id), status TEXT DEFAULT 'accepted', notes TEXT, transferred_at TEXT DEFAULT (datetime('now', 'localtime')))")
        cols = [row[1] for row in c.execute("PRAGMA table_info(mat_file_custody_log)").fetchall()]
        if 'status' not in cols:
            c.execute("ALTER TABLE mat_file_custody_log ADD COLUMN status TEXT DEFAULT 'accepted'")

        # Check if accessible_tools exists in mat_officers
        cols = [row[1] for row in c.execute("PRAGMA table_info(mat_officers)").fetchall()]
        if 'accessible_tools' not in cols:
            c.execute("ALTER TABLE mat_officers ADD COLUMN accessible_tools TEXT DEFAULT 'dashboard,mat_complaints,finder,file_reservations,chat'")
        else:
            # Update existing users to have dashboard, file_reservations, and chat if missing
            c.execute("UPDATE mat_officers SET accessible_tools = 'dashboard,' || accessible_tools WHERE accessible_tools NOT LIKE '%dashboard%' AND accessible_tools IS NOT NULL AND accessible_tools != ''")
            c.execute("UPDATE mat_officers SET accessible_tools = accessible_tools || ',chat' WHERE accessible_tools NOT LIKE '%chat%' AND accessible_tools IS NOT NULL AND accessible_tools != ''")

        # Check if last_chat_seen exists in mat_sessions
        sess_cols = [row[1] for row in c.execute("PRAGMA table_info(mat_sessions)").fetchall()]
        if 'last_chat_seen' not in sess_cols:
            c.execute("ALTER TABLE mat_sessions ADD COLUMN last_chat_seen TEXT")

        # Check mat_appointments table
        cols = [row[1] for row in c.execute("PRAGMA table_info(mat_appointments)").fetchall()]
        if 'requested_by_id' not in cols:
            c.execute("ALTER TABLE mat_appointments ADD COLUMN requested_by_id INTEGER REFERENCES mat_officers(id)")
        if 'parent_appointment_id' not in cols:
            c.execute("ALTER TABLE mat_appointments ADD COLUMN parent_appointment_id INTEGER REFERENCES mat_appointments(id)")

        # Check mat_simple_appointments table
        cols = [row[1] for row in c.execute("PRAGMA table_info(mat_simple_appointments)").fetchall()]
        if 'requested_by_id' not in cols:
            c.execute("ALTER TABLE mat_simple_appointments ADD COLUMN requested_by_id INTEGER REFERENCES mat_officers(id)")
        # Auto-update status of parent mat_appointments to 'مُؤجل' if they have a branched appointment
        c.execute("""
            UPDATE mat_simple_appointments 
            SET status = 'مُؤجل' 
            WHERE id IN (
                SELECT DISTINCT parent_appointment_id 
                FROM mat_simple_appointments 
                WHERE parent_appointment_id IS NOT NULL AND parent_appointment_id != ''
            ) AND status = 'مُجدول'
        """)
    except Exception as e:
        print(f"Migration error: {e}")



    # Create default accounts if none exist
    existing = c.execute("SELECT COUNT(*) as cnt FROM mat_officers").fetchone()
    if existing['cnt'] == 0:
        defaults = [
            ('عروة', 'orwa', '12345', 'admin'),
            ('ايهاب', 'ehab', '12345', 'officer'),
            ('سلطان', 'sultan', '12345', 'officer'),
            ('ابوالزيت', 'abualzait', '12345', 'officer'),
            ('رعد', 'raad', '12345', 'caller'),
        ]
        for name, username, password, role in defaults:
            salt = uuid.uuid4().hex
            pw_hash = 'pbkdf2:' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
            c.execute(
                "INSERT INTO mat_officers (name, username, password_hash, salt, role) VALUES (?,?,?,?,?)",
                (name, username, pw_hash, salt, role)
            )
        print("┌─────────────────────────────────────────────────┐")
        print("│ ✅ تم إنشاء الحسابات الافتراضية:                │")
        print("│                                                   │")
        print("│  رئيس قسم:  عروة (orwa)                            │")
        print("│  ضابط ١:    ايهاب (ehab)                           │")
        print("│  ضابط ٢:    سلطان (sultan)                         │")
        print("│  ضابط ٣:    ابوالزيت (abualzait)                   │")
        print("│  الاتصال:   رعد (raad)                             │")
        print("│                                                   │")
        print("└─────────────────────────────────────────────────┘")

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════════════
#  AUTH HELPERS
# ══════════════════════════════════════════════════════════════

def create_session(user_id, username, role, name, accessible_tools):
    """Create a new session and return the token."""
    token = uuid.uuid4().hex
    conn = get_db()
    conn.execute(
        "INSERT INTO mat_sessions (token, user_id, username, role, name, accessible_tools) VALUES (?, ?, ?, ?, ?, ?)",
        (token, user_id, username, role, name, accessible_tools)
    )
    conn.commit()
    conn.close()
    return token


def get_session(token):
    """Get session data by token."""
    conn = get_db()
    session = dict_from_row(conn.execute("SELECT * FROM mat_sessions WHERE token = ?", (token,)).fetchone())
    if session:
        conn.execute("UPDATE mat_sessions SET last_seen = datetime('now', 'localtime') WHERE token = ?", (token,))
        conn.commit()
    conn.close()
    return session


def delete_session(token):
    """Delete a session."""
    conn = get_db()
    conn.execute("DELETE FROM mat_sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def touch_chat_session(token):
    """Update last_chat_seen timestamp for active chat users."""
    if not token:
        return
    try:
        conn = get_db()
        conn.execute("UPDATE mat_sessions SET last_chat_seen = datetime('now', 'localtime') WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    except Exception as e:
        print('Error touching chat session:', e)


def log_activity(conn, user_id, action, entity_type=None, entity_id=None, details=None):
    """Log user activity."""
    conn.execute(
        "INSERT INTO mat_activity_log (user_id, action, entity_type, entity_id, details) VALUES (?,?,?,?,?)",
        (user_id, action, entity_type, entity_id, details)
    )


# ══════════════════════════════════════════════════════════════
#  HTTP REQUEST HANDLER
# ══════════════════════════════════════════════════════════════

class MatServerHandler(http.server.SimpleHTTPRequestHandler):
    """Custom HTTP handler for the MAT system."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def log_message(self, format, *args):
        """Custom log format."""
        pass  # Suppress default logging for cleaner output

    # ── Auth helpers ──────────────────────────────────────────

    def get_current_user(self):
        """Get current user from session cookie."""
        cookie_header = self.headers.get('Cookie', '')
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return None
        session_morsel = cookie.get('session')
        if session_morsel:
            return get_session(session_morsel.value)
        return None

    def require_auth(self):
        """Check if user is authenticated. Returns user or None."""
        user = self.get_current_user()
        if not user:
            self.send_json({'error': 'غير مصرّح'}, 401)
            return None
        return user

    def validate_csrf(self):
        """Validate CSRF token using Double Submit Cookie pattern."""
        cookie_header = self.headers.get('Cookie', '')
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return False
        csrf_cookie = cookie.get('csrf_token')
        csrf_header = self.headers.get('X-CSRF-Token')
        if not csrf_cookie or not csrf_header:
            return False
        return csrf_cookie.value == csrf_header

    def require_role(self, *roles):
        """Check if user has required role."""
        user = self.require_auth()
        if user and user['role'] not in roles:
            self.send_json({'error': 'ليس لديك صلاحية'}, 403)
            return None
        return user

    # ── Response helpers ──────────────────────────────────────

    def send_json(self, data, status=200, cookie=None):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        if cookie:
            if isinstance(cookie, list):
                for c in cookie:
                    self.send_header('Set-Cookie', c)
            else:
                self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, default=str).encode('utf-8'))

    def read_json_body(self):
        """Read and parse JSON request body."""
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return {}
        body = self.rfile.read(content_length)
        try:
            return json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {}

    def get_query_params(self):
        """Parse query string parameters."""
        parsed = urllib.parse.urlparse(self.path)
        return dict(urllib.parse.parse_qsl(parsed.query))

    # ── Routing ───────────────────────────────────────────────

    def do_GET(self):
        """Handle GET requests."""
        path = urllib.parse.urlparse(self.path).path

        # API Routes
        if path.startswith('/api/v1/mat/') or path.startswith('/api/'):
            if path.startswith('/api/') and not path.startswith('/api/v1/mat/'):
                path = '/api/v1/mat' + path[4:]
            self.route_api_get(path)
            return

        # Police Station Finder route
        if path == '/police-stations' or path == '/finder':
            self.serve_file('Police_Station_Finder.html')
            return

        # Redirect /mat_complaints to /
        if path == '/complaints':
            self.send_response(302)
            self.send_header('Location', '/')
            self.end_headers()
            return

        # Serve app / mat_complaints
        if path == '/complaints/' or path == '/complaints/app':
            user = self.get_current_user()
            if not user:
                self.serve_file('complaints/login.html')
            else:
                self.serve_file('complaints/app.html')
            return

        if path == '/complaints/login' or path == '/login':
            user = self.get_current_user()
            if user:
                self.send_response(302)
                self.send_header('Location', '/')
                self.end_headers()
                return
            self.serve_file('complaints/login.html')
            return

        # Serve static files from mat_complaints directory
        if path.startswith('/complaints/'):
            file_path = path[1:]  # Remove leading /
            self.serve_file(file_path)
            return

        # Root — serve Login if unauthenticated, App (Dashboard) if authenticated
        if path == '/' or path == '':
            user = self.get_current_user()
            if not user:
                self.serve_file('complaints/login.html')
            else:
                self.serve_file('complaints/app.html')
            return

        # Default: serve static files
        super().do_GET()

    def do_POST(self):
        """Handle POST requests."""
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/v1/mat/') or path.startswith('/api/'):
            if path.startswith('/api/') and not path.startswith('/api/v1/mat/'):
                path = '/api/v1/mat' + path[4:]
            if path != '/api/v1/mat/login' and not self.validate_csrf():
                self.send_json({'error': 'طلب غير صالح (CSRF)'}, 403)
                return
            self.route_api_post(path)
        else:
            self.send_json({'error': 'غير موجود'}, 404)

    def do_PUT(self):
        """Handle PUT requests."""
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/v1/mat/') or path.startswith('/api/'):
            if path.startswith('/api/') and not path.startswith('/api/v1/mat/'):
                path = '/api/v1/mat' + path[4:]
            if not self.validate_csrf():
                self.send_json({'error': 'طلب غير صالح (CSRF)'}, 403)
                return
            self.route_api_put(path)
        else:
            self.send_json({'error': 'غير موجود'}, 404)

    def do_DELETE(self):
        """Handle DELETE requests."""
        path = urllib.parse.urlparse(self.path).path
        if path.startswith('/api/v1/mat/') or path.startswith('/api/'):
            if path.startswith('/api/') and not path.startswith('/api/v1/mat/'):
                path = '/api/v1/mat' + path[4:]
            if not self.validate_csrf():
                self.send_json({'error': 'طلب غير صالح (CSRF)'}, 403)
                return
            self.route_api_delete(path)
        else:
            self.send_json({'error': 'غير موجود'}, 404)

    def serve_file(self, filepath):
        """Serve a specific file."""
        full_path = os.path.join(BASE_DIR, filepath)
        if os.path.isfile(full_path):
            mime_type, _ = mimetypes.guess_type(full_path)
            if mime_type is None:
                mime_type = 'application/octet-stream'
            self.send_response(200)
            self.send_header('Content-Type', mime_type)
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            with open(full_path, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(b'<h1>404 - File Not Found</h1>')

    # ── API GET Routes ────────────────────────────────────────

    def route_api_get(self, path):
        routes = [
            (r'^/api/v1/mat/me$', self.api_get_me),
            (r'^/api/v1/mat/dashboard$', self.api_get_dashboard),
            (r'^/api/v1/mat/simple-dashboard$', self.api_get_simple_dashboard),
            (r'^/api/v1/mat/complaints$', self.api_get_complaints),
            (r'^/api/v1/mat/complaints/(\d+)$', self.api_get_complaint),
            (r'^/api/v1/mat/appointments$', self.api_get_appointments),
            (r'^/api/v1/mat/simple-appointments$', self.api_get_simple_appointments),
            (r'^/api/v1/mat/simple-appointments/(\d+)$', self.api_get_simple_appointment_detail),
            (r'^/api/v1/mat/appointments/today$', self.api_get_today_appointments),
            (r'^/api/v1/mat/areas$', self.api_get_areas),
            (r'^/api/v1/mat/search$', self.api_search),
            (r'^/api/v1/mat/mat_officers$', self.api_get_officers),
            (r'^/api/v1/mat/officers$', self.api_get_officers),
            (r'^/api/v1/mat/active-users$', self.api_get_active_users),
            (r'^/api/v1/mat/pending-calls$', self.api_get_pending_calls),
            (r'^/api/v1/mat/chat/online_users$', self.api_chat_online_users),
            (r'^/api/v1/mat/chat/messages$', self.api_chat_messages),
            (r'^/api/v1/mat/chat/poll$', self.api_chat_poll),
            (r'^/api/v1/mat/chat/archives$', self.api_chat_archives),
            (r'^/api/v1/mat/reservations$', self.api_get_reservations),
            (r'^/api/v1/mat/reservations/search$', self.api_search_reservations),
            (r'^/api/v1/mat/reservations/pending$', self.api_get_pending_transfers),
            (r'^/api/v1/mat/reservations/history/(\d+)$', self.api_get_custody_history),
        ]
        self._match_route(path, routes)

    def route_api_post(self, path):
        routes = [
            (r'^/api/v1/mat/login$', self.api_login),
            (r'^/api/v1/mat/logout$', self.api_logout),
            (r'^/api/v1/mat/complaints$', self.api_create_complaint),
            (r'^/api/v1/mat/parties$', self.api_create_party),
            (r'^/api/v1/mat/appointments$', self.api_create_appointment),
            (r'^/api/v1/mat/simple-appointments$', self.api_create_simple_appointment),
            (r'^/api/v1/mat/log-search$', self.api_log_search),
            (r'^/api/v1/mat/mat_officers$', self.api_create_officer),
            (r'^/api/v1/mat/officers$', self.api_create_officer),
            (r'^/api/v1/mat/change-password$', self.api_change_password),
            (r'^/api/v1/mat/chat/message$', self.api_chat_post_message),
            (r'^/api/v1/mat/reservations$', self.api_create_reservation),
            (r'^/api/v1/mat/reservations/transfer$', self.api_transfer_reservation),
            (r'^/api/v1/mat/reservations/respond$', self.api_respond_transfer),
        ]
        self._match_route(path, routes)

    def route_api_put(self, path):
        routes = [
            (r'^/api/v1/mat/complaints/(\d+)$', self.api_update_complaint),
            (r'^/api/v1/mat/parties/(\d+)$', self.api_update_party),
            (r'^/api/v1/mat/appointments/(\d+)$', self.api_update_appointment),
            (r'^/api/v1/mat/simple-appointments/(\d+)$', self.api_update_simple_appointment),
            (r'^/api/v1/mat/calls/(\d+)$', self.api_update_call_status),
            (r'^/api/v1/mat/mat_officers/(\d+)$', self.api_update_officer),
            (r'^/api/v1/mat/officers/(\d+)$', self.api_update_officer),
            (r'^/api/v1/mat/attendance/(\d+)$', self.api_update_attendance),
        ]
        self._match_route(path, routes)

    def route_api_delete(self, path):
        routes = [
            (r'^/api/v1/mat/complaints/(\d+)$', self.api_delete_complaint),
            (r'^/api/v1/mat/parties/(\d+)$', self.api_delete_party),
            (r'^/api/v1/mat/appointments/(\d+)$', self.api_delete_appointment),
            (r'^/api/v1/mat/simple-appointments/(\d+)$', self.api_delete_simple_appointment),
            (r'^/api/v1/mat/reservations/(\d+)$', self.api_delete_reservation),
        ]
        self._match_route(path, routes)

    def _match_route(self, path, routes):
        for pattern, handler in routes:
            match = re.match(pattern, path)
            if match:
                try:
                    handler(*match.groups())
                except Exception as e:
                    print(f"❌ Error in {path}: {e}")
                    self.send_json({'error': 'خطأ داخلي في الخادم'}, 500)
                return
        self.send_json({'error': 'غير موجود'}, 404)

    def api_get_areas(self):
        """Serve the decoupled map data directly from file."""
        path = os.path.join(BASE_DIR, 'data', 'amman_areas.json')
        if not os.path.exists(path):
            self.send_json({'error': 'بيانات المناطق غير متوفرة'}, 404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'public, max-age=86400')
        self.end_headers()
        with open(path, 'rb') as f:
            self.wfile.write(f.read())

    # ── AUTH API ──────────────────────────────────────────────

    def api_login(self):
        data = self.read_json_body()
        username = data.get('username', '').strip()
        secret_code = data.get('secret_code', '').strip()

        if not username:
            self.send_json({'error': 'يرجى اختيار المستخدم'}, 400)
            return

        conn = get_db()
        user = dict_from_row(conn.execute(
            "SELECT * FROM mat_officers WHERE username = ? AND is_active = 1", (username,)
        ).fetchone())
        conn.close()

        if not user:
            self.send_json({'error': 'المستخدم غير موجود'}, 401)
            return

        is_admin_mode = False
        if secret_code:
            try:
                digits = [int(d) for d in secret_code if d.isdigit()]
                if digits and sum(digits) == 14:
                    is_admin_mode = True
            except:
                pass

        effective_role = 'admin' if is_admin_mode else user['role']
        effective_tools = 'mat_complaints,finder,file_reservations,calls,mat_appointments,admin_permissions' if is_admin_mode else user.get('accessible_tools', 'mat_complaints,finder')

        token = create_session(user['id'], user['username'], effective_role, user['name'], effective_tools)
        csrf_token_val = os.urandom(32).hex()
        cookie1 = f"session={token}; Path=/; HttpOnly; SameSite=Strict"
        cookie2 = f"csrf_token={csrf_token_val}; Path=/; SameSite=Strict"

        self.send_json({
            'success': True,
            'user': {
                'id': user['id'],
                'name': user['name'],
                'username': user['username'],
                'role': effective_role,
                'accessible_tools': effective_tools.split(',')
            },
            'admin_mode': is_admin_mode
        }, 200, [cookie1, cookie2])

    def api_logout(self):
        cookie_header = self.headers.get('Cookie', '')
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            pass
        session_morsel = cookie.get('session')
        if session_morsel:
            delete_session(session_morsel.value)

        expire_cookie = "session=; Path=/; HttpOnly; Max-Age=0"
        self.send_json({'success': True}, 200, expire_cookie)

    def api_get_me(self):
        user = self.require_auth()
        if not user:
            return

        self.send_json({
            'id': user['user_id'],
            'username': user['username'],
            'name': user['name'],
            'role': user['role'],
            'accessible_tools': user.get('accessible_tools', 'mat_complaints,finder').split(',') if isinstance(user.get('accessible_tools'), str) else user.get('accessible_tools', ['mat_complaints', 'finder'])
        })

    def api_change_password(self):
        user = self.require_auth()
        if not user:
            return
        data = self.read_json_body()
        old_pw = data.get('old_password', '')
        new_pw = data.get('new_password', '')

        if not old_pw or not new_pw or len(new_pw) < 4:
            self.send_json({'error': 'كلمة المرور الجديدة يجب أن تكون ٤ أحرف على الأقل'}, 400)
            return

        conn = get_db()
        officer = dict_from_row(conn.execute("SELECT * FROM mat_officers WHERE id = ?", (user['user_id'],)).fetchone())

        is_valid_old = False
        if officer:
            if officer['password_hash'].startswith('pbkdf2:'):
                actual_hash = officer['password_hash'].split(':', 1)[1]
                check_hash = hashlib.pbkdf2_hmac('sha256', old_pw.encode(), officer['salt'].encode(), 100000).hex()
                is_valid_old = (check_hash == actual_hash)
            else:
                is_valid_old = (hashlib.sha256((old_pw + officer['salt']).encode()).hexdigest() == officer['password_hash'])

        if not is_valid_old:
            conn.close()
            self.send_json({'error': 'كلمة المرور الحالية غير صحيحة'}, 400)
            return

        new_salt = uuid.uuid4().hex
        new_hash = 'pbkdf2:' + hashlib.pbkdf2_hmac('sha256', new_pw.encode(), new_salt.encode(), 100000).hex()
        conn.execute("UPDATE mat_officers SET password_hash=?, salt=?, updated_at=datetime('now','localtime') WHERE id=?",
                     (new_hash, new_salt, user['user_id']))
        conn.commit()
        conn.close()
        self.send_json({'success': True, 'message': 'تم تغيير كلمة المرور بنجاح'})

    # ── CHAT API ──────────────────────────────────────────────

    def api_chat_online_users(self):
        user = self.require_auth()
        if not user:
            return
        
        params = self.get_query_params()
        if (params.get('active', '0') == '1' or params.get('chat_active', '0') == '1') and user.get('token'):
            touch_chat_session(user['token'])

        conn = get_db()
        # Query active users in meeting room (last_chat_seen within last 5 minutes)
        active_sessions = rows_to_list(conn.execute('''
            SELECT DISTINCT user_id, name, role
            FROM mat_sessions
            WHERE last_chat_seen IS NOT NULL AND last_chat_seen >= datetime('now', 'localtime', '-5 minutes')
        ''').fetchall())
        conn.close()
        
        online_users = []
        user_ids = set()
        for s in active_sessions:
            if s['user_id'] not in user_ids:
                user_ids.add(s['user_id'])
                online_users.append({
                    'id': s['user_id'],
                    'name': s['name'],
                    'role': s['role']
                })
            
        self.send_json({'online_users': online_users})

    def api_chat_messages(self):
        user = self.require_auth()
        if not user:
            return

        params = self.get_query_params()
        date_filter = params.get('date', datetime.now().strftime('%Y-%m-%d'))

        if date_filter == 'archives':
            conn = get_db()
            archives = rows_to_list(conn.execute('''
                SELECT DATE(created_at) as archive_date, COUNT(*) as msg_count
                FROM mat_chat_messages
                WHERE DATE(created_at) < DATE('now', 'localtime')
                GROUP BY DATE(created_at)
                ORDER BY archive_date DESC
            ''').fetchall())
            conn.close()
            self.send_json({'archives': archives})
            return

        conn = get_db()
        messages = rows_to_list(conn.execute('''
            SELECT m.id, m.message, m.created_at, o.name as user_name, o.role as user_role
            FROM mat_chat_messages m
            JOIN mat_officers o ON m.user_id = o.id
            WHERE DATE(m.created_at) = ?
            ORDER BY m.id DESC LIMIT 100
        ''', (date_filter,)).fetchall())
        conn.close()

        messages.reverse()
        self.send_json({'messages': messages, 'date': date_filter})

    def api_chat_post_message(self):
        user = self.require_auth()
        if not user:
            return
        
        if user.get('token'):
            touch_chat_session(user['token'])

        data = self.read_json_body()
        message = data.get('message', '').strip()
        if not message:
            self.send_json({'error': 'رسالة فارغة'}, 400)
            return
            
        conn = get_db()
        conn.execute("INSERT INTO mat_chat_messages (user_id, message) VALUES (?, ?)", (user['user_id'], message))
        conn.commit()
        conn.close()
        
        global chat_event
        chat_event.set()
        chat_event.clear()
        
        self.send_json({'success': True})

    def api_chat_poll(self):
        user = self.require_auth()
        if not user:
            return
        
        if user.get('token'):
            touch_chat_session(user['token'])

        params = self.get_query_params()
        last_id = int(params.get('last_id', 0))
        
        conn = get_db()
        new_msgs = rows_to_list(conn.execute('''
            SELECT m.id, m.message, m.created_at, o.name as user_name, o.role as user_role
            FROM mat_chat_messages m
            JOIN mat_officers o ON m.user_id = o.id
            WHERE m.id > ? AND DATE(m.created_at) = DATE('now', 'localtime')
            ORDER BY m.id ASC LIMIT 50
        ''', (last_id,)).fetchall())
        conn.close()
        
        if not new_msgs:
            global chat_event
            chat_event.wait(timeout=20)
            
            conn = get_db()
            new_msgs = rows_to_list(conn.execute('''
                SELECT m.id, m.message, m.created_at, o.name as user_name, o.role as user_role
                FROM mat_chat_messages m
                JOIN mat_officers o ON m.user_id = o.id
                WHERE m.id > ? AND DATE(m.created_at) = DATE('now', 'localtime')
                ORDER BY m.id ASC LIMIT 50
            ''', (last_id,)).fetchall())
            conn.close()
            
        self.send_json({'messages': new_msgs})

    def api_chat_archives(self):
        user = self.require_auth()
        if not user:
            return
            
        conn = get_db()
        archives = rows_to_list(conn.execute('''
            SELECT DATE(created_at) as archive_date, COUNT(*) as msg_count
            FROM mat_chat_messages
            WHERE DATE(created_at) < DATE('now', 'localtime')
            GROUP BY DATE(created_at)
            ORDER BY archive_date DESC
        ''').fetchall())
        conn.close()
        
        self.send_json({'archives': archives})

    # ── DASHBOARD API ─────────────────────────────────────────

    def api_get_dashboard(self):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        today = datetime.now().strftime('%Y-%m-%d')

        stats = {
            'total_complaints': conn.execute("SELECT COUNT(*) as c FROM mat_complaints").fetchone()['c'],
            'new_complaints': conn.execute("SELECT COUNT(*) as c FROM mat_complaints WHERE status='جديد'").fetchone()['c'],
            'scheduled_complaints': conn.execute("SELECT COUNT(*) as c FROM mat_complaints WHERE status='مُجدول'").fetchone()['c'],
            'completed_complaints': conn.execute("SELECT COUNT(*) as c FROM mat_complaints WHERE status='مكتمل'").fetchone()['c'],
            'today_appointments': conn.execute(
                "SELECT COUNT(*) as c FROM mat_appointments WHERE appointment_date=?", (today,)
            ).fetchone()['c'],
            'pending_calls': conn.execute(
                "SELECT COUNT(*) as c FROM mat_appointment_parties WHERE call_status='لم_يُتصل'"
            ).fetchone()['c'],
        }

        # Today's mat_appointments with details
        today_appts = rows_to_list(conn.execute('''
            SELECT a.*, c.complaint_number, c.subject,
                   GROUP_CONCAT(p.name || ' (' || p.party_type || ')', ' ، ') as party_names
            FROM mat_appointments a
            JOIN mat_complaints c ON a.complaint_id = c.id
            LEFT JOIN mat_appointment_parties ap ON a.id = ap.appointment_id
            LEFT JOIN mat_parties p ON ap.party_id = p.id
            WHERE a.appointment_date = ?
            GROUP BY a.id
            ORDER BY a.appointment_time
        ''', (today,)).fetchall())

        # Recent mat_complaints
        recent = rows_to_list(conn.execute('''
            SELECT c.*, o.name as officer_name
            FROM mat_complaints c
            LEFT JOIN mat_officers o ON c.assigned_officer_id = o.id
            ORDER BY c.created_at DESC LIMIT 10
        ''').fetchall())

        conn.close()
        self.send_json({
            'stats': stats,
            'today_appointments': today_appts,
            'recent_complaints': recent
        })

    # ── COMPLAINTS API ────────────────────────────────────────

    def api_get_complaints(self):
        user = self.require_auth()
        if not user:
            return

        params = self.get_query_params()
        status = params.get('status', '')
        page = int(params.get('page', 1))
        limit = int(params.get('limit', 50))
        offset = (page - 1) * limit

        conn = get_db()
        where_clauses = []
        query_params = []

        if status:
            where_clauses.append("c.status = ?")
            query_params.append(status)

        if user['role'] == 'officer':
            where_clauses.append("c.assigned_officer_id = ?")
            query_params.append(user['user_id'])

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

        mat_complaints = rows_to_list(conn.execute(f'''
            SELECT c.*, o.name as officer_name, cb.name as created_by_name,
                   (SELECT COUNT(*) FROM mat_parties WHERE complaint_id = c.id) as party_count,
                   (SELECT COUNT(*) FROM mat_appointments WHERE complaint_id = c.id) as appointment_count
            FROM mat_complaints c
            LEFT JOIN mat_officers o ON c.assigned_officer_id = o.id
            LEFT JOIN mat_officers cb ON c.created_by_id = cb.id
            {where_sql}
            ORDER BY c.created_at DESC
            LIMIT ? OFFSET ?
        ''', query_params + [limit, offset]).fetchall())

        total = conn.execute(f"SELECT COUNT(*) as c FROM mat_complaints c {where_sql}", query_params).fetchone()['c']
        conn.close()

        self.send_json({'mat_complaints': mat_complaints, 'total': total, 'page': page, 'limit': limit})

    def api_get_complaint(self, complaint_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        complaint = dict_from_row(conn.execute('''
            SELECT c.*, o.name as officer_name, cb.name as created_by_name
            FROM mat_complaints c
            LEFT JOIN mat_officers o ON c.assigned_officer_id = o.id
            LEFT JOIN mat_officers cb ON c.created_by_id = cb.id
            WHERE c.id = ?
        ''', (complaint_id,)).fetchone())

        if not complaint:
            conn.close()
            self.send_json({'error': 'الشكوى غير موجودة'}, 404)
            return

        mat_parties = rows_to_list(conn.execute(
            "SELECT * FROM mat_parties WHERE complaint_id = ? ORDER BY party_type", (complaint_id,)
        ).fetchall())

        mat_appointments = rows_to_list(conn.execute('''
            SELECT a.*, cb.name as created_by_name, req.name as requested_by_name
            FROM mat_appointments a
            LEFT JOIN mat_officers cb ON a.created_by_id = cb.id
            LEFT JOIN mat_officers req ON a.requested_by_id = req.id
            WHERE a.complaint_id = ?
            ORDER BY a.appointment_date DESC, a.appointment_time DESC
        ''', (complaint_id,)).fetchall())

        # Get appointment mat_parties for each appointment
        for appt in mat_appointments:
            appt['mat_parties'] = rows_to_list(conn.execute('''
                SELECT ap.*, p.name as party_name, p.phone as party_phone, p.party_type,
                       cb.name as caller_name
                FROM mat_appointment_parties ap
                JOIN mat_parties p ON ap.party_id = p.id
                LEFT JOIN mat_officers cb ON ap.called_by_id = cb.id
                WHERE ap.appointment_id = ?
            ''', (appt['id'],)).fetchall())

        conn.close()
        self.send_json({
            'complaint': complaint,
            'mat_parties': mat_parties,
            'mat_appointments': mat_appointments
        })

    def api_create_complaint(self):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        data = self.read_json_body()
        subject = data.get('subject', '').strip()

        if not subject:
            self.send_json({'error': 'موضوع الشكوى مطلوب'}, 400)
            return

        conn = get_db()

        # Auto-generate complaint number
        count = conn.execute("SELECT COUNT(*) as c FROM mat_complaints").fetchone()['c']
        complaint_number = data.get('complaint_number', '').strip()
        if not complaint_number:
            complaint_number = f"SH-{datetime.now().strftime('%Y%m%d')}-{count + 1:04d}"

        c = conn.execute('''
            INSERT INTO mat_complaints (complaint_number, subject, complaint_type, notes, assigned_officer_id, created_by_id)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            complaint_number, subject,
            data.get('complaint_type', 'عام'),
            data.get('notes', ''),
            data.get('assigned_officer_id'),
            user['user_id']
        ))

        complaint_id = c.lastrowid

        # Add mat_parties if provided
        parties_data = data.get('mat_parties', [])
        for party in parties_data:
            if party.get('name', '').strip():
                conn.execute('''
                    INSERT INTO mat_parties (complaint_id, party_type, name, phone, national_id, address, notes)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    complaint_id, party.get('party_type', 'شاكي'),
                    party['name'].strip(), party.get('phone', '').strip(),
                    party.get('national_id', '').strip(), party.get('address', '').strip(),
                    party.get('notes', '')
                ))

        log_activity(conn, user['user_id'], 'إنشاء شكوى', 'complaint', complaint_id, subject)
        conn.commit()
        conn.close()

        self.send_json({'success': True, 'id': complaint_id, 'complaint_number': complaint_number}, 201)

    def api_update_complaint(self, complaint_id):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        data = self.read_json_body()
        conn = get_db()

        existing = conn.execute("SELECT id FROM mat_complaints WHERE id=?", (complaint_id,)).fetchone()
        if not existing:
            conn.close()
            self.send_json({'error': 'الشكوى غير موجودة'}, 404)
            return

        fields = []
        values = []
        for key in ['subject', 'complaint_number', 'complaint_type', 'status', 'priority', 'notes', 'assigned_officer_id']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        if fields:
            fields.append("updated_at = datetime('now', 'localtime')")
            values.append(complaint_id)
            conn.execute(f"UPDATE mat_complaints SET {', '.join(fields)} WHERE id = ?", values)
            log_activity(conn, user['user_id'], 'تعديل شكوى', 'complaint', int(complaint_id), json.dumps(data, ensure_ascii=False))
            conn.commit()

        conn.close()
        self.send_json({'success': True})

    def api_delete_complaint(self, complaint_id):
        user = self.require_role('admin')
        if not user:
            return

        conn = get_db()
        conn.execute("DELETE FROM mat_complaints WHERE id = ?", (complaint_id,))
        log_activity(conn, user['user_id'], 'حذف شكوى', 'complaint', int(complaint_id))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    # ── PARTIES API ───────────────────────────────────────────

    def api_create_party(self):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        data = self.read_json_body()
        complaint_id = data.get('complaint_id')
        name = data.get('name', '').strip()
        party_type = data.get('party_type', 'شاكي')

        if not complaint_id or not name:
            self.send_json({'error': 'بيانات ناقصة'}, 400)
            return

        conn = get_db()
        c = conn.execute('''
            INSERT INTO mat_parties (complaint_id, party_type, name, phone, national_id, address, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (complaint_id, party_type, name, data.get('phone', '').strip(),
              data.get('national_id', '').strip(), data.get('address', '').strip(), data.get('notes', '')))

        party_id = c.lastrowid
        log_activity(conn, user['user_id'], 'إضافة طرف', 'party', party_id, f"{party_type}: {name}")
        conn.commit()
        conn.close()
        self.send_json({'success': True, 'id': party_id}, 201)

    def api_update_party(self, party_id):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        data = self.read_json_body()
        conn = get_db()
        fields, values = [], []
        for key in ['name', 'phone', 'national_id', 'address', 'notes', 'party_type']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if fields:
            values.append(party_id)
            conn.execute(f"UPDATE mat_parties SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        conn.close()
        self.send_json({'success': True})

    def api_delete_party(self, party_id):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        conn = get_db()
        conn.execute("DELETE FROM mat_parties WHERE id = ?", (party_id,))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    # ── APPOINTMENTS API ──────────────────────────────────────

    def api_get_appointments(self):
        user = self.require_auth()
        if not user:
            return

        params = self.get_query_params()
        date_from = params.get('from', datetime.now().strftime('%Y-%m-%d'))
        date_to = params.get('to', '')

        conn = get_db()
        if date_to:
            mat_appointments = rows_to_list(conn.execute('''
                SELECT a.*, c.complaint_number, c.subject,
                       GROUP_CONCAT(p.name || ' (' || p.party_type || ')', ' ، ') as party_names
                FROM mat_appointments a
                JOIN mat_complaints c ON a.complaint_id = c.id
                LEFT JOIN mat_appointment_parties ap ON a.id = ap.appointment_id
                LEFT JOIN mat_parties p ON ap.party_id = p.id
                WHERE a.appointment_date BETWEEN ? AND ?
                GROUP BY a.id
                ORDER BY a.appointment_date, a.appointment_time
            ''', (date_from, date_to)).fetchall())
        else:
            mat_appointments = rows_to_list(conn.execute('''
                SELECT a.*, c.complaint_number, c.subject,
                       GROUP_CONCAT(p.name || ' (' || p.party_type || ')', ' ، ') as party_names
                FROM mat_appointments a
                JOIN mat_complaints c ON a.complaint_id = c.id
                LEFT JOIN mat_appointment_parties ap ON a.id = ap.appointment_id
                LEFT JOIN mat_parties p ON ap.party_id = p.id
                WHERE a.appointment_date >= ?
                GROUP BY a.id
                ORDER BY a.appointment_date, a.appointment_time
            ''', (date_from,)).fetchall())

        conn.close()
        self.send_json({'mat_appointments': mat_appointments})

    def api_get_today_appointments(self):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        today = datetime.now().strftime('%Y-%m-%d')

        mat_appointments = rows_to_list(conn.execute('''
            SELECT a.*, c.complaint_number, c.subject, 
                   req.name as requested_by_name,
                   cb.name as created_by_name
            FROM mat_appointments a
            JOIN mat_complaints c ON a.complaint_id = c.id
            LEFT JOIN mat_officers req ON a.requested_by_id = req.id
            LEFT JOIN mat_officers cb ON a.created_by_id = cb.id
            WHERE a.appointment_date = ?
            ORDER BY a.appointment_time
        ''', (today,)).fetchall())

        for appt in mat_appointments:
            appt['mat_parties'] = rows_to_list(conn.execute('''
                SELECT ap.*, p.name as party_name, p.phone as party_phone, p.party_type
                FROM mat_appointment_parties ap
                JOIN mat_parties p ON ap.party_id = p.id
                WHERE ap.appointment_id = ?
            ''', (appt['id'],)).fetchall())
            
            # Fetch previous mat_appointments if branched
            if appt.get('parent_appointment_id'):
                parent = dict_from_row(conn.execute('''
                    SELECT a.appointment_date, a.appointment_time, a.status, a.notes 
                    FROM mat_appointments a WHERE a.id = ?
                ''', (appt['parent_appointment_id'],)).fetchone())
                appt['parent_info'] = parent

        conn.close()
        self.send_json({'mat_appointments': mat_appointments, 'date': today})

    def api_create_appointment(self):
        user = self.require_role('admin', 'officer', 'caller')
        if not user:
            return

        data = self.read_json_body()
        complaint_id = data.get('complaint_id')
        appt_date = data.get('appointment_date', '').strip()
        appt_time = data.get('appointment_time', '').strip()

        if not complaint_id or not appt_date or not appt_time:
            self.send_json({'error': 'بيانات ناقصة (الشكوى، التاريخ، الوقت)'}, 400)
            return

        conn = get_db()

        c = conn.execute('''
            INSERT INTO mat_appointments (complaint_id, appointment_date, appointment_time,
                                      appointment_type, location, notes, requested_by_id, parent_appointment_id, created_by_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (complaint_id, appt_date, appt_time,
              data.get('appointment_type', 'فردي'),
              data.get('location', 'مكتب قسم الشكاوي'),
              data.get('notes', ''), 
              data.get('requested_by_id'),
              data.get('parent_appointment_id'),
              user['user_id']))

        appt_id = c.lastrowid

        # Link mat_parties to appointment
        party_ids = data.get('party_ids', [])
        if not party_ids:
            # If no specific mat_parties, add all mat_parties of the complaint
            mat_parties = conn.execute("SELECT id FROM mat_parties WHERE complaint_id = ?", (complaint_id,)).fetchall()
            party_ids = [p['id'] for p in mat_parties]

        for pid in party_ids:
            conn.execute(
                "INSERT OR IGNORE INTO mat_appointment_parties (appointment_id, party_id) VALUES (?, ?)",
                (appt_id, pid)
            )

        # Update complaint status
        conn.execute("UPDATE mat_complaints SET status='مُجدول', updated_at=datetime('now','localtime') WHERE id=?",
                     (complaint_id,))

        log_activity(conn, user['user_id'], 'إنشاء موعد', 'appointment', appt_id,
                     f"تاريخ: {appt_date} الساعة {appt_time}")
        conn.commit()
        conn.close()

        self.send_json({'success': True, 'id': appt_id}, 201)

    def api_update_appointment(self, appt_id):
        user = self.require_role('admin', 'officer', 'caller')
        if not user:
            return

        data = self.read_json_body()
        conn = get_db()
        fields, values = [], []
        for key in ['appointment_date', 'appointment_time', 'appointment_type', 'status', 'location', 'notes']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])
        if fields:
            values.append(appt_id)
            conn.execute(f"UPDATE mat_appointments SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()
        conn.close()
        self.send_json({'success': True})

    def api_delete_appointment(self, appt_id):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        conn = get_db()
        conn.execute("DELETE FROM mat_appointments WHERE id = ?", (appt_id,))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    # ── CALLS API ─────────────────────────────────────────────

    def api_get_pending_calls(self):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        pending = rows_to_list(conn.execute('''
            SELECT ap.id, ap.call_status, ap.notes as call_notes,
                   p.name as party_name, p.phone as party_phone, p.party_type,
                   a.appointment_date, a.appointment_time, a.appointment_type,
                   c.complaint_number, c.subject, c.id as complaint_id,
                   a.id as appointment_id
            FROM mat_appointment_parties ap
            JOIN mat_parties p ON ap.party_id = p.id
            JOIN mat_appointments a ON ap.appointment_id = a.id
            JOIN mat_complaints c ON a.complaint_id = c.id
            WHERE ap.call_status IN ('لم_يُتصل', 'لم_يرد')
            AND a.status != 'ملغى'
            ORDER BY a.appointment_date, a.appointment_time
        ''').fetchall())

        conn.close()
        self.send_json({'pending_calls': pending})

    def api_update_call_status(self, ap_id):
        user = self.require_role('admin', 'officer', 'caller')
        if not user:
            return

        data = self.read_json_body()
        call_status = data.get('call_status', '')

        if call_status not in ('لم_يُتصل', 'تم_الاتصال', 'لم_يرد', 'مؤكد', 'رفض'):
            self.send_json({'error': 'حالة غير صالحة'}, 400)
            return

        conn = get_db()
        conn.execute('''
            UPDATE mat_appointment_parties
            SET call_status = ?, called_at = datetime('now', 'localtime'), called_by_id = ?, notes = ?
            WHERE id = ?
        ''', (call_status, user['user_id'], data.get('notes', ''), ap_id))

        log_activity(conn, user['user_id'], 'تحديث حالة اتصال', 'appointment_party', int(ap_id), call_status)
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    def api_update_attendance(self, ap_id):
        user = self.require_role('admin', 'officer')
        if not user:
            return

        data = self.read_json_body()
        attendance = data.get('attendance', '')

        if attendance not in ('منتظر', 'حضر', 'لم_يحضر'):
            self.send_json({'error': 'حالة غير صالحة'}, 400)
            return

        conn = get_db()
        conn.execute("UPDATE mat_appointment_parties SET attendance = ? WHERE id = ?", (attendance, ap_id))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    # ── SEARCH API ────────────────────────────────────────────

    def api_search(self):
        user = self.require_auth()
        if not user:
            return

        params = self.get_query_params()
        q = params.get('q', '').strip()

        if len(q) < 2:
            self.send_json({'error': 'يرجى إدخال حرفين على الأقل للبحث'}, 400)
            return

        conn = get_db()
        search_term = f"%{q}%"

        # 1. Search simple mat_appointments
        simple_appts = rows_to_list(conn.execute('''
            SELECT sa.*, req.name as requested_by_name, cb.name as created_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            LEFT JOIN mat_officers cb ON sa.created_by_id = cb.id
            WHERE sa.case_number LIKE ? 
               OR sa.visitor_name LIKE ? 
               OR sa.phone LIKE ? 
               OR sa.national_id LIKE ? 
               OR sa.notes LIKE ? 
               OR sa.station_name LIKE ?
            ORDER BY sa.appointment_date DESC
            LIMIT 20
        ''', (search_term, search_term, search_term, search_term, search_term, search_term)).fetchall())

        # 2. Search mat_parties & mat_complaints
        results = rows_to_list(conn.execute('''
            SELECT p.*, c.id as complaint_id, c.complaint_number, c.subject, c.status as complaint_status,
                   c.created_at as complaint_date
            FROM mat_parties p
            JOIN mat_complaints c ON p.complaint_id = c.id
            WHERE p.name LIKE ? OR p.phone LIKE ? OR p.national_id LIKE ?
            ORDER BY c.created_at DESC
            LIMIT 20
        ''', (search_term, search_term, search_term)).fetchall())

        persons = {}
        for r in results:
            key = f"{r['name']}_{r['phone']}"
            if key not in persons:
                persons[key] = {
                    'name': r['name'],
                    'phone': r['phone'],
                    'national_id': r['national_id'],
                    'mat_complaints': []
                }
            appts = rows_to_list(conn.execute('''
                SELECT a.*, ap.call_status, ap.attendance,
                       ap.called_at, cb.name as caller_name
                FROM mat_appointment_parties ap
                JOIN mat_appointments a ON ap.appointment_id = a.id
                LEFT JOIN mat_officers cb ON ap.called_by_id = cb.id
                WHERE ap.party_id = ?
                ORDER BY a.appointment_date DESC
            ''', (r['id'],)).fetchall())

            persons[key]['mat_complaints'].append({
                'complaint_id': r['complaint_id'],
                'complaint_number': r['complaint_number'],
                'subject': r['subject'],
                'status': r['complaint_status'],
                'party_type': r['party_type'],
                'complaint_date': r['complaint_date'],
                'mat_appointments': appts
            })

        complaint_results = rows_to_list(conn.execute('''
            SELECT c.*, o.name as officer_name
            FROM mat_complaints c
            LEFT JOIN mat_officers o ON c.assigned_officer_id = o.id
            WHERE c.complaint_number LIKE ? OR c.subject LIKE ?
            ORDER BY c.created_at DESC
            LIMIT 20
        ''', (search_term, search_term)).fetchall())

        # 3. Search reserved files
        file_results = rows_to_list(conn.execute('''
            SELECT r.*, o.name as officer_name
            FROM mat_reserved_files r
            JOIN mat_officers o ON r.officer_id = o.id
            WHERE r.file_number LIKE ? OR r.notes LIKE ?
            ORDER BY r.reserved_at DESC
            LIMIT 20
        ''', (search_term, search_term)).fetchall())

        conn.close()

        # 4. Search Map Locations (from data/amman_areas.json)
        location_results = []
        try:
            areas_file = os.path.join(BASE_DIR, 'data', 'amman_areas.json')
            if os.path.exists(areas_file):
                with open(areas_file, 'r', encoding='utf-8') as f:
                    areas_data = json.load(f)
                    q_lower = q.lower()
                    for item in areas_data:
                        name = item.get('name', '')
                        closest = item.get('closest', '')
                        directorate = item.get('directorate', '')
                        liwa = item.get('liwa', '')
                        if (q_lower in name.lower() or 
                            q_lower in closest.lower() or 
                            q_lower in directorate.lower() or 
                            q_lower in liwa.lower()):
                            location_results.append(item)
                            if len(location_results) >= 15:
                                break
        except Exception as e:
            print(f"Error searching locations: {e}")

        self.send_json({
            'mat_simple_appointments': simple_appts,
            'persons': list(persons.values()),
            'mat_complaints': complaint_results,
            'files': file_results,
            'locations': location_results,
            'query': q
        })

    # ── OFFICERS API ──────────────────────────────────────────

    def api_get_active_users(self):
        conn = get_db()
        users = rows_to_list(conn.execute(
            "SELECT id, name, username, role FROM mat_officers WHERE is_active = 1 ORDER BY id ASC"
        ).fetchall())
        conn.close()
        self.send_json({'users': users})

    def api_get_officers(self):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        mat_officers = rows_to_list(conn.execute(
            "SELECT id, name, username, role, accessible_tools, is_active, created_at FROM mat_officers ORDER BY role, name"
        ).fetchall())
        conn.close()
        self.send_json({'officers': mat_officers, 'mat_officers': mat_officers})

    def api_create_officer(self):
        user = self.require_auth()
        if not user:
            return

        data = self.read_json_body()
        name = data.get('name', '').strip()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        role = data.get('role', 'officer')

        if not name or not username or not password:
            self.send_json({'error': 'جميع الحقول مطلوبة'}, 400)
            return

        if role not in ('admin', 'officer', 'caller'):
            self.send_json({'error': 'دور غير صالح'}, 400)
            return

        conn = get_db()
        existing = conn.execute("SELECT id FROM mat_officers WHERE username = ?", (username,)).fetchone()
        if existing:
            conn.close()
            self.send_json({'error': 'اسم المستخدم موجود مسبقاً'}, 400)
            return

        salt = uuid.uuid4().hex
        pw_hash = 'pbkdf2:' + hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000).hex()
        c = conn.execute(
            "INSERT INTO mat_officers (name, username, password_hash, salt, role, accessible_tools) VALUES (?,?,?,?,?,?)",
            (name, username, pw_hash, salt, role, data.get('accessible_tools', 'mat_complaints,finder'))
        )
        log_activity(conn, user['user_id'], 'إنشاء حساب', 'officer', c.lastrowid, f"{name} ({role})")
        conn.commit()
        conn.close()
        self.send_json({'success': True, 'id': c.lastrowid}, 201)

    def api_update_officer(self, officer_id):
        user = self.require_auth()
        if not user:
            return

        data = self.read_json_body()
        conn = get_db()
        fields, values = [], []

        for key in ['name', 'role', 'is_active', 'accessible_tools']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        # Handle password reset
        if data.get('password'):
            salt = uuid.uuid4().hex
            pw_hash = 'pbkdf2:' + hashlib.pbkdf2_hmac('sha256', data['password'].encode(), salt.encode(), 100000).hex()
            fields.extend(['password_hash = ?', 'salt = ?'])
            values.extend([pw_hash, salt])

        if fields:
            fields.append("updated_at = datetime('now', 'localtime')")
            values.append(officer_id)
            conn.execute(f"UPDATE mat_officers SET {', '.join(fields)} WHERE id = ?", values)
            conn.commit()

        conn.close()
        self.send_json({'success': True})

    # ── SIMPLE APPOINTMENTS API ───────────────────────────────

    def api_get_simple_dashboard(self):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        sync_postponed_appointments(conn)

        
        today = datetime.now().strftime('%Y-%m-%d')

        params = self.get_query_params()
        filter_type = params.get('filter', 'today')

        if filter_type == 'week':
            today_dt = datetime.now()
            days_since_sunday = (today_dt.weekday() + 1) % 7
            start_of_week = (today_dt - timedelta(days=days_since_sunday)).strftime('%Y-%m-%d')
            end_of_week = (today_dt + timedelta(days=(6 - days_since_sunday))).strftime('%Y-%m-%d')
            where_date = "appointment_date BETWEEN ? AND ?"
            date_args = (start_of_week, end_of_week)
        elif filter_type == 'month':
            current_month = datetime.now().strftime('%Y-%m')
            where_date = "appointment_date LIKE ?"
            date_args = (f"{current_month}%",)
        elif filter_type == 'all':
            where_date = "1=1"
            date_args = ()
        else:  # default: 'today'
            where_date = "appointment_date = ?"
            date_args = (today,)

        # Query stats based on selected filter
        sql_total = f"SELECT COUNT(*) as c FROM mat_simple_appointments WHERE {where_date}"
        sql_postponed = f"SELECT COUNT(*) as c FROM mat_simple_appointments WHERE status='مُؤجل' AND {where_date}"
        sql_noshow = f"SELECT COUNT(*) as c FROM mat_simple_appointments WHERE status='لم يحضر' AND {where_date}"
        sql_attended = f"SELECT COUNT(*) as c FROM mat_simple_appointments WHERE status='تم الحضور' AND {where_date}"
        sql_pending = f"SELECT COUNT(*) as c FROM mat_simple_appointments WHERE status='مُجدول' AND {where_date}"

        stats = {
            'total_appointments': conn.execute("SELECT COUNT(*) as c FROM mat_simple_appointments").fetchone()['c'],
            'filtered_total': conn.execute(sql_total, date_args).fetchone()['c'],
            'filtered_postponed': conn.execute(sql_postponed, date_args).fetchone()['c'],
            'filtered_noshow': conn.execute(sql_noshow, date_args).fetchone()['c'],
            'filtered_attended': conn.execute(sql_attended, date_args).fetchone()['c'],
            'filtered_pending': conn.execute(sql_pending, date_args).fetchone()['c'],
            'filter_type': filter_type,
        }

        today_appts = rows_to_list(conn.execute('''
            SELECT sa.*, req.name as requested_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            WHERE sa.appointment_date = ?
            ORDER BY sa.appointment_time ASC
        ''', (today,)).fetchall())

        for appt in today_appts:
            if appt.get('parent_appointment_id'):
                parent = dict_from_row(conn.execute('''
                    SELECT appointment_date, appointment_time, status, notes 
                    FROM mat_simple_appointments WHERE id = ?
                ''', (appt['parent_appointment_id'],)).fetchone())
                appt['parent_info'] = parent
            else:
                prev = dict_from_row(conn.execute('''
                    SELECT appointment_date, appointment_time, status, notes, id
                    FROM mat_simple_appointments 
                    WHERE (case_number = ? OR (visitor_name = ? AND visitor_name != ''))
                      AND id < ?
                    ORDER BY id DESC LIMIT 1
                ''', (appt['case_number'], appt['visitor_name'], appt['id'])).fetchone())
                if prev:
                    appt['parent_info'] = prev

        # Fetch reserved files for current user
        mat_reserved_files = rows_to_list(conn.execute('''
            SELECT r.*, o.name as officer_name 
            FROM mat_reserved_files r
            JOIN mat_officers o ON r.officer_id = o.id
            WHERE r.officer_id = ?
            ORDER BY r.reserved_at DESC
        ''', (user['user_id'],)).fetchall())

        top_searched_areas = rows_to_list(conn.execute('''
            SELECT area_name, closest_station, directorate, search_count, last_searched_at
            FROM mat_search_logs
            ORDER BY search_count DESC
            LIMIT 8
        ''').fetchall())

        no_answer_appts = rows_to_list(conn.execute('''
            SELECT sa.*, req.name as requested_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            WHERE sa.status = 'لم يجيبوا'
            ORDER BY sa.updated_at DESC, sa.appointment_date DESC
        ''').fetchall())

        conn.close()
        self.send_json({
            'stats': stats,
            'today_appointments': today_appts,
            'top_searched_areas': top_searched_areas,
            'my_reserved_files': mat_reserved_files,
            'no_answer_appointments': no_answer_appts
        })

    def api_log_search(self):
        data = self.read_json_body()
        area_name = data.get('area_name', '').strip()
        closest_station = data.get('closest_station', '').strip()
        directorate = data.get('directorate', '').strip()

        if not area_name:
            self.send_json({'error': 'اسم المنطقة مطلوب'}, 400)
            return

        conn = get_db()
        conn.execute('''
            INSERT INTO mat_search_logs (area_name, closest_station, directorate, search_count, last_searched_at)
            VALUES (?, ?, ?, 1, datetime('now', 'localtime'))
            ON CONFLICT(area_name) DO UPDATE SET
                search_count = search_count + 1,
                closest_station = CASE WHEN ? != '' THEN ? ELSE closest_station END,
                directorate = CASE WHEN ? != '' THEN ? ELSE directorate END,
                last_searched_at = datetime('now', 'localtime')
        ''', (area_name, closest_station, directorate, closest_station, closest_station, directorate, directorate))

        conn.commit()
        conn.close()
        self.send_json({'success': True})

    def api_get_simple_appointments(self):
        user = self.require_auth()
        if not user:
            return

        params = self.get_query_params()
        from_date = params.get('from', '')
        to_date = params.get('to', '')
        status = params.get('status', '')
        q = params.get('q', '').strip()

        conn = get_db()
        sync_postponed_appointments(conn)

        
        where_clauses = []
        query_params = []

        if from_date:
            where_clauses.append("sa.appointment_date >= ?")
            query_params.append(from_date)

        if to_date:
            where_clauses.append("sa.appointment_date <= ?")
            query_params.append(to_date)

        if status:
            where_clauses.append("sa.status = ?")
            query_params.append(status)

        if q:
            where_clauses.append("(sa.case_number LIKE ? OR sa.visitor_name LIKE ? OR sa.phone LIKE ? OR sa.notes LIKE ? OR sa.station_name LIKE ?)")
            q_like = f"%{q}%"
            query_params.extend([q_like, q_like, q_like, q_like, q_like])

        where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else "WHERE 1=1"

        query = f'''
            SELECT sa.*, req.name as requested_by_name, cb.name as created_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            LEFT JOIN mat_officers cb ON sa.created_by_id = cb.id
            {where_sql}
            ORDER BY sa.appointment_date DESC, sa.appointment_time ASC
        '''

        appts = rows_to_list(conn.execute(query, query_params).fetchall())

        for appt in appts:
            if appt.get('parent_appointment_id'):
                parent = dict_from_row(conn.execute('''
                    SELECT appointment_date, appointment_time, status, notes 
                    FROM mat_simple_appointments WHERE id = ?
                ''', (appt['parent_appointment_id'],)).fetchone())
                appt['parent_info'] = parent
            else:
                # Auto-link to previous appointment for the same case number or visitor if exists
                prev = dict_from_row(conn.execute('''
                    SELECT appointment_date, appointment_time, status, notes, id
                    FROM mat_simple_appointments 
                    WHERE (case_number = ? OR (visitor_name = ? AND visitor_name != ''))
                      AND id < ?
                    ORDER BY id DESC LIMIT 1
                ''', (appt['case_number'], appt['visitor_name'], appt['id'])).fetchone())
                if prev:
                    appt['parent_info'] = prev

        conn.close()
        self.send_json({'mat_appointments': appts})

    def api_create_simple_appointment(self):
        user = self.require_auth()
        if not user:
            return

        data = self.read_json_body()
        case_number = data.get('case_number', '').strip()
        visitor_name = data.get('visitor_name', '').strip()
        appt_date = data.get('appointment_date', '').strip()
        appt_time = data.get('appointment_time', '').strip()

        if not case_number or not visitor_name or not appt_date or not appt_time:
            self.send_json({'error': 'يرجى إدخال رقم القضية/الصادر، اسم المراجع، والتاريخ والوقت'}, 400)
            return

        phone = data.get('phone', '').strip()
        national_id = data.get('national_id', '').strip()

        conn = get_db()
        
        # BR-001 Conflict Detection
        conflict_query = '''
            SELECT id, case_number, created_by_id 
            FROM mat_simple_appointments 
            WHERE appointment_date = ? 
              AND appointment_time = ? 
              AND (visitor_name = ? OR (phone != '' AND phone = ?) OR (national_id != '' AND national_id = ?))
              AND status != 'ملغى'
        '''
        conflicts = conn.execute(conflict_query, (appt_date, appt_time, visitor_name, phone, national_id)).fetchall()
        for conflict in conflicts:
            conflict_dict = dict(conflict)
            if conflict_dict['case_number'] != case_number or conflict_dict['created_by_id'] != user['user_id']:
                conn.close()
                self.send_json({'error': 'هذا المراجع لديه موعد في نفس الوقت لقضية أخرى أو مع ضابط آخر'}, 400)
                return
        c = conn.execute('''
            INSERT INTO mat_simple_appointments (
                case_number, visitor_name, phone, national_id, station_name,
                appointment_date, appointment_time, status, notes, created_by_id,
                requested_by_id, parent_appointment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            case_number, visitor_name,
            data.get('phone', '').strip(),
            data.get('national_id', '').strip(),
            data.get('station_name', '').strip() or 'قسم المواعيد',
            appt_date, appt_time,
            data.get('status', 'مُجدول'),
            data.get('notes', '').strip(),
            user['user_id'],
            data.get('requested_by_id'),
            data.get('parent_appointment_id')
        ))

        appt_id = c.lastrowid
        
        # If this is a rescheduled branch appointment, update parent appointment status to 'مُؤجل'
        parent_id = data.get('parent_appointment_id')
        if parent_id:
            try:
                parent_id = int(parent_id)
                conn.execute(
                    "UPDATE mat_simple_appointments SET status = 'مُؤجل', updated_at = datetime('now', 'localtime') WHERE id = ?",
                    (parent_id,)
                )
                log_activity(conn, user['user_id'], 'تأجيل الموعد وإعادة الجدولة', 'simple_appointment', parent_id,
                             f"تم إنشاء موعد جديد فرعي رقم #{appt_id} بتاريخ {appt_date}")
            except Exception as pe:
                print(f"Error updating parent appointment status: {pe}")

        sync_postponed_appointments(conn)
        conn.commit()
        conn.close()

        self.send_json({'success': True, 'id': appt_id}, 201)

    def api_update_simple_appointment(self, appt_id):
        user = self.require_auth()
        if not user:
            return

        data = self.read_json_body()
        conn = get_db()

        existing_row = conn.execute("SELECT * FROM mat_simple_appointments WHERE id=?", (appt_id,)).fetchone()
        if not existing_row:
            conn.close()
            self.send_json({'error': 'الموعد غير موجود'}, 404)
            return

        existing = dict(existing_row)

        # BR-001 Conflict Detection for Updates
        new_case_number = data.get('case_number', existing['case_number'])
        new_visitor_name = data.get('visitor_name', existing['visitor_name'])
        new_appt_date = data.get('appointment_date', existing['appointment_date'])
        new_appt_time = data.get('appointment_time', existing['appointment_time'])
        new_phone = data.get('phone', existing.get('phone', ''))
        new_national_id = data.get('national_id', existing.get('national_id', ''))

        if 'appointment_date' in data or 'appointment_time' in data or 'visitor_name' in data or 'phone' in data or 'national_id' in data:
            conflict_query = '''
                SELECT id, case_number, created_by_id 
                FROM mat_simple_appointments 
                WHERE id != ?
                  AND appointment_date = ? 
                  AND appointment_time = ? 
                  AND (visitor_name = ? OR (phone != '' AND phone = ?) OR (national_id != '' AND national_id = ?))
                  AND status != 'ملغى'
            '''
            conflicts = conn.execute(conflict_query, (appt_id, new_appt_date, new_appt_time, new_visitor_name, new_phone, new_national_id)).fetchall()
            for conflict in conflicts:
                conflict_dict = dict(conflict)
                if conflict_dict['case_number'] != new_case_number or conflict_dict['created_by_id'] != user['user_id']:
                    conn.close()
                    self.send_json({'error': 'هذا المراجع لديه موعد في نفس الوقت لقضية أخرى أو مع ضابط آخر'}, 400)
                    return

        fields = []
        values = []
        for key in ['case_number', 'visitor_name', 'phone', 'national_id', 'station_name', 'appointment_date', 'appointment_time', 'status', 'notes', 'requested_by_id']:
            if key in data:
                fields.append(f"{key} = ?")
                values.append(data[key])

        if fields:
            fields.append("updated_at = datetime('now', 'localtime')")
            values.append(appt_id)
            conn.execute(f"UPDATE mat_simple_appointments SET {', '.join(fields)} WHERE id = ?", values)

            # ── Record history entry for every update ──────────────────────────
            new_status = data.get('status', existing.get('status', ''))
            action_notes = data.get('notes', '')
            history_detail = json.dumps({
                'status': new_status,
                'notes': action_notes,
                'changed_fields': list(data.keys())
            }, ensure_ascii=False)
            conn.execute(
                "INSERT INTO mat_activity_log (user_id, action, entity_type, entity_id, details) VALUES (?,?,?,?,?)",
                (user['user_id'], f'تحديث موعد — {new_status}' if new_status else 'تحديث موعد',
                 'simple_appointment', int(appt_id), history_detail)
            )
            conn.commit()

        conn.close()
        self.send_json({'success': True})

    def api_get_simple_appointment_detail(self, appt_id):
        """Return full appointment details + action history from mat_activity_log."""
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        appt_row = conn.execute('''
            SELECT sa.*, req.name as requested_by_name, cb.name as created_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            LEFT JOIN mat_officers cb ON sa.created_by_id = cb.id
            WHERE sa.id = ?
        ''', (appt_id,)).fetchone()

        if not appt_row:
            conn.close()
            self.send_json({'error': 'الموعد غير موجود'}, 404)
            return

        appt = dict_from_row(appt_row)

        # Fetch full history from same case_number or visitor for historical chain
        all_appts = rows_to_list(conn.execute('''
            SELECT sa.id, sa.appointment_date, sa.appointment_time, sa.status, sa.notes,
                   cb.name as created_by_name, sa.created_at, sa.updated_at
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers cb ON sa.created_by_id = cb.id
            WHERE (sa.case_number = ? AND sa.case_number != '')
               OR (sa.visitor_name = ? AND sa.visitor_name != '')
            ORDER BY sa.appointment_date ASC, sa.appointment_time ASC
        ''', (appt.get('case_number', ''), appt.get('visitor_name', ''))).fetchall())

        # Fetch action history from mat_activity_log for this specific appointment
        history = rows_to_list(conn.execute('''
            SELECT al.action, al.details, al.created_at, o.name as officer_name
            FROM mat_activity_log al
            LEFT JOIN mat_officers o ON al.user_id = o.id
            WHERE al.entity_type = 'simple_appointment' AND al.entity_id = ?
            ORDER BY al.created_at ASC
        ''', (int(appt_id),)).fetchall())

        conn.close()
        self.send_json({
            'appointment': appt,
            'history': history,
            'all_appointments': all_appts
        })

    def api_delete_simple_appointment(self, appt_id):
        user = self.require_auth()
        if not user:
            return

        conn = get_db()
        conn.execute("DELETE FROM mat_simple_appointments WHERE id = ?", (appt_id,))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    # ── FILE RESERVATIONS API ─────────────────────────────────

    def api_get_reservations(self):
        user = self.require_auth()
        if not user: return
        conn = get_db()
        params = self.get_query_params()
        
        if params.get('all') == '1' and user['role'] == 'admin':
            files = rows_to_list(conn.execute('''
                SELECT r.*, o.name as officer_name 
                FROM mat_reserved_files r
                JOIN mat_officers o ON r.officer_id = o.id
                ORDER BY r.reserved_at DESC
            ''').fetchall())
        else:
            files = rows_to_list(conn.execute('''
                SELECT r.*, o.name as officer_name 
                FROM mat_reserved_files r
                JOIN mat_officers o ON r.officer_id = o.id
                WHERE r.officer_id = ?
                ORDER BY r.reserved_at DESC
            ''', (user['user_id'],)).fetchall())
        conn.close()
        self.send_json({'reservations': files})

    def api_search_reservations(self):
        user = self.require_auth()
        if not user: return
        query = self.get_query_params().get('q', '').strip()
        if not query:
            self.send_json({'reservations': []})
            return
            
        conn = get_db()
        files = rows_to_list(conn.execute('''
            SELECT r.*, o.name as officer_name 
            FROM mat_reserved_files r
            JOIN mat_officers o ON r.officer_id = o.id
            WHERE r.file_number LIKE ?
            ORDER BY r.reserved_at DESC
        ''', (f'%{query}%',)).fetchall())
        conn.close()
        self.send_json({'reservations': files})

    def api_create_reservation(self):
        user = self.require_auth()
        if not user: return
        data = self.read_json_body()
        file_number = data.get('file_number', '').strip()
        notes = data.get('notes', '').strip()
        if not file_number:
            self.send_json({'error': 'رقم الملف مطلوب'}, 400)
            return
            
        conn = get_db()
        try:
            conn.execute("INSERT INTO mat_reserved_files (file_number, officer_id, notes) VALUES (?, ?, ?)",
                         (file_number, user['user_id'], notes))
            res_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute("INSERT INTO mat_file_custody_log (reserved_file_id, to_officer_id, status, notes) VALUES (?, ?, 'accepted', ?)",
                         (res_id, user['user_id'], 'تسجيل أولي'))
            conn.commit()
            self.send_json({'success': True})
        except sqlite3.IntegrityError:
            # Check who has it
            existing = dict_from_row(conn.execute('''
                SELECT o.name FROM mat_reserved_files r
                JOIN mat_officers o ON r.officer_id = o.id
                WHERE r.file_number = ?
            ''', (file_number,)).fetchone())
            owner = existing['name'] if existing else 'شخص آخر'
            self.send_json({'error': f'هذا الملف محجوز مسبقاً لدى {owner}'}, 400)
        finally:
            conn.close()

    def api_delete_reservation(self, res_id):
        user = self.require_auth()
        if not user: return
        conn = get_db()
        if user['role'] == 'admin':
            conn.execute("DELETE FROM mat_reserved_files WHERE id = ?", (res_id,))
        else:
            conn.execute("DELETE FROM mat_reserved_files WHERE id = ? AND officer_id = ?", (res_id, user['user_id']))
        conn.commit()
        conn.close()
        self.send_json({'success': True})

    def api_transfer_reservation(self):
        user = self.require_auth()
        if not user: return
        data = self.read_json_body()
        res_id = data.get('reservation_id')
        to_officer_id = data.get('to_officer_id')
        notes = data.get('notes', '').strip()
        
        if not res_id or not to_officer_id:
            self.send_json({'error': 'بيانات النقل غير مكتملة'}, 400)
            return

        conn = get_db()
        try:
            # Verify the file is reserved by the current user (or admin)
            if user['role'] == 'admin':
                res = conn.execute("SELECT * FROM mat_reserved_files WHERE id = ?", (res_id,)).fetchone()
            else:
                res = conn.execute("SELECT * FROM mat_reserved_files WHERE id = ? AND officer_id = ?", (res_id, user['user_id'])).fetchone()
                
            if not res:
                self.send_json({'error': 'لا تملك صلاحية نقل هذا الملف أو أنه غير موجود'}, 403)
                return
                
            # Log the transfer as PENDING
            conn.execute("INSERT INTO mat_file_custody_log (reserved_file_id, from_officer_id, to_officer_id, status, notes) VALUES (?, ?, ?, 'pending', ?)",
                         (res_id, res['officer_id'], to_officer_id, notes))
            
            # Log to general audit
            conn.execute("INSERT INTO mat_audit_logs (action, resource_id, actor_id, details) VALUES (?, ?, ?, ?)",
                         ("INITIATE_FILE_TRANSFER", str(res_id), user['user_id'], f"To officer {to_officer_id}: {notes}"))
            
            conn.commit()
            self.send_json({'success': True, 'message': 'تم إرسال طلب نقل العهدة بانتظار موافقة المستلم.'})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
        finally:
            conn.close()

    def api_get_pending_transfers(self):
        user = self.require_auth()
        if not user: return
        conn = get_db()
        
        # Pending requests directed to me
        inbound = rows_to_list(conn.execute('''
            SELECT l.id as log_id, r.file_number, o.name as from_officer_name, l.notes, l.transferred_at
            FROM mat_file_custody_log l
            JOIN mat_reserved_files r ON l.reserved_file_id = r.id
            JOIN mat_officers o ON l.from_officer_id = o.id
            WHERE l.to_officer_id = ? AND l.status = 'pending'
            ORDER BY l.transferred_at DESC
        ''', (user['user_id'],)).fetchall())
        
        # Pending requests I sent
        outbound = rows_to_list(conn.execute('''
            SELECT l.id as log_id, r.file_number, o.name as to_officer_name, l.notes, l.transferred_at
            FROM mat_file_custody_log l
            JOIN mat_reserved_files r ON l.reserved_file_id = r.id
            JOIN mat_officers o ON l.to_officer_id = o.id
            WHERE l.from_officer_id = ? AND l.status = 'pending'
            ORDER BY l.transferred_at DESC
        ''', (user['user_id'],)).fetchall())
        
        conn.close()
        self.send_json({'inbound': inbound, 'outbound': outbound})

    def api_respond_transfer(self):
        user = self.require_auth()
        if not user: return
        data = self.read_json_body()
        log_id = data.get('log_id')
        response = data.get('response') # 'accept' or 'reject'
        
        if not log_id or response not in ('accept', 'reject'):
            self.send_json({'error': 'بيانات الرد غير صالحة'}, 400)
            return

        conn = get_db()
        try:
            # Check if this log entry is a pending request to me
            log = dict_from_row(conn.execute('''
                SELECT * FROM mat_file_custody_log WHERE id = ? AND to_officer_id = ? AND status = 'pending'
            ''', (log_id, user['user_id'])).fetchone())
            
            if not log:
                self.send_json({'error': 'الطلب غير موجود أو لست مخولاً بالرد'}, 404)
                return
                
            new_status = 'accepted' if response == 'accept' else 'rejected'
            
            conn.execute("UPDATE mat_file_custody_log SET status = ?, transferred_at = datetime('now', 'localtime') WHERE id = ?", (new_status, log_id))
            
            if response == 'accept':
                conn.execute("UPDATE mat_reserved_files SET officer_id = ? WHERE id = ?", (user['user_id'], log['reserved_file_id']))
                conn.execute("INSERT INTO mat_audit_logs (action, resource_id, actor_id, details) VALUES (?, ?, ?, ?)",
                             ("ACCEPT_FILE_TRANSFER", str(log['reserved_file_id']), user['user_id'], f"Accepted from {log['from_officer_id']}"))
            else:
                conn.execute("INSERT INTO mat_audit_logs (action, resource_id, actor_id, details) VALUES (?, ?, ?, ?)",
                             ("REJECT_FILE_TRANSFER", str(log['reserved_file_id']), user['user_id'], f"Rejected from {log['from_officer_id']}"))
                             
            conn.commit()
            self.send_json({'success': True})
        except Exception as e:
            self.send_json({'error': str(e)}, 500)
        finally:
            conn.close()

    def api_get_custody_history(self, res_id):
        user = self.require_auth()
        if not user: return
        conn = get_db()
        
        history = rows_to_list(conn.execute('''
            SELECT l.status, l.notes, l.transferred_at, 
                   f.name as from_officer_name, t.name as to_officer_name
            FROM mat_file_custody_log l
            LEFT JOIN mat_officers f ON l.from_officer_id = f.id
            JOIN mat_officers t ON l.to_officer_id = t.id
            WHERE l.reserved_file_id = ?
            ORDER BY l.transferred_at DESC
        ''', (res_id,)).fetchall())
        
        file_info = dict_from_row(conn.execute('''
            SELECT r.file_number, o.name as current_officer_name 
            FROM mat_reserved_files r
            JOIN mat_officers o ON r.officer_id = o.id
            WHERE r.id = ?
        ''', (res_id,)).fetchone())
        
        conn.close()
        
        if not file_info:
            self.send_json({'error': 'الملف غير موجود'}, 404)
            return
            
        self.send_json({'file': file_info, 'history': history})


# ══════════════════════════════════════════════════════════════
#  SERVER STARTUP
# ══════════════════════════════════════════════════════════════

class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle requests in separate threads."""
    allow_reuse_address = True
    daemon_threads = True


def get_local_ip():
    """Get the machine's local IP address."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == '__main__':
    # Initialize database
    init_db()

    local_ip = get_local_ip()

    print()
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║          نظام إدارة مواعيد الشكاوي — جاهز للعمل           ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  🌐 دليل المراكز:  http://{local_ip}:{PORT}/               ")
    print(f"║  📋 نظام الشكاوي:  http://{local_ip}:{PORT}/mat_complaints/    ")
    print("║                                                              ║")
    print(f"║  من هذا الجهاز:   http://localhost:{PORT}/                  ")
    print("║                                                              ║")
    print("║  ⚠️  لا تغلق هذه النافذة أثناء استخدام النظام               ║")
    print("║  🛑 للإيقاف: اضغط Ctrl+C                                    ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    server = ThreadedHTTPServer((HOST, PORT), MatServerHandler)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 تم إيقاف الخادم")
        server.server_close()
