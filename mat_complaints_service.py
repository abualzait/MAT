"""
mat_complaints_service.py
Service layer for Amman Police Stations complaints system:
- Secure Scan Storage (JPEG, PNG, WEBP, PDF validation & path traversal protection)
- GIS Nearest Police Station Matcher (cached amman_areas.json + Arabic normalization)
- 90-Day Calculator & Warning Levels
- Official .docx Complaint Exporter (pure Python standard library: zipfile + xml.etree.ElementTree)
"""

import copy
import io
import json
import os
import re
import sqlite3
import tempfile
import textwrap
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone


# ── CONFIGURATION & CONSTANTS ────────────────────────────────────────────────

MAX_SCAN_SIZE = 10 * 1024 * 1024  # 10 MB

INTAKE_ALLOWED_STAGES = ("draft_scan", "officer_reviewed", "pending_section_head")
PRE_APPROVAL_STAGES = ("draft_scan", "officer_reviewed", "governor_rejected")
POST_APPROVAL_STAGES = ("governor_approved", "governor_modified", "in_execution")
SECTION_HEAD_ALLOWED_STAGES = (
    "draft_scan",
    "officer_reviewed",
    "pending_section_head",
    "governor_rejected",
    "pending_governor",
)
GOVERNOR_ALLOWED_STAGES = (
    "pending_governor",
    "governor_approved",
    "governor_modified",
    "governor_rejected",
)
GOVERNOR_DECISIONS = ("موافقة", "رفض", "تغيير_الإجراء")

STAGE_TO_STATUS = {
    "draft_scan": "جديد",
    "officer_reviewed": "قيد المراجعة",
    "pending_section_head": "بانتظار رئيس القسم",
    "pending_governor": "بانتظار الحاكم الإداري",
    "governor_approved": "معتمدة",
    "governor_modified": "معتمدة (معدلة)",
    "governor_rejected": "مرفوضة",
    "in_execution": "قيد التنفيذ",
    "completed": "منجزة",
    "stopped_90_days": "كف طلب (90 يوماً)",
}

UPDATABLE_COMPLAINT_FIELDS = (
    "paper_date",
    "subject",
    "summary",
    "complaint_type",
    "priority",
    "notes",
    "complainant_category",
    "respondent_category",
    "has_signature",
    "no_pending_lawsuit_declared",
    "is_minor_police_complaint",
    "assigned_officer_id",
    "nearest_station",
    "police_directorate",
    "liwa_name",
    "station_lat",
    "station_lon",
    "ai_provider",
    "ai_model",
    "ai_extracted_json",
    "ai_analysis",
    "ai_solution_recommendation",
    "ai_recommended_action",
    "ai_confidence",
)

ALLOWED_MAGIC = [
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"%PDF-", "application/pdf", ".pdf"),
]

ALLOWED_EXT_TO_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"

_AREAS_CACHE = None
_AREAS_CACHE_PATH = None


# ── ARABIC NORMALIZATION ─────────────────────────────────────────────────────

def normalize_arabic(text: str) -> str:
    """Normalize Arabic text by unifying letters, stripping diacritics and punctuation."""
    if not text:
        return ""
    s = str(text)
    # Unify Alef variations
    s = re.sub(r"[إأآٱ]", "ا", s)
    # Unify Ta Marbuta -> Ha
    s = re.sub(r"ة", "ه", s)
    # Unify Alef Maksura -> Ya
    s = re.sub(r"ى", "ي", s)
    # Strip Tashkeel / Diacritics
    s = re.sub(r"[\u064B-\u065F\u0670]", "", s)
    # Strip Tatweel
    s = re.sub(r"\u0640", "", s)
    # Strip common punctuation and symbols
    s = re.sub(r"[،؛؟ـ!\"#$%&\'()*+,\-./:;<=>?@\[\\\]^_`{|}~]", " ", s)
    # Collapse multiple whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ── SECURE SCAN STORAGE ──────────────────────────────────────────────────────

def _detect_file_type(raw_bytes: bytes) -> tuple[str, str]:
    """Detect MIME type and file extension based on magic bytes."""
    for magic, mime, ext in ALLOWED_MAGIC:
        if raw_bytes.startswith(magic):
            return mime, ext
    # Special check for WEBP (RIFF....WEBP)
    if len(raw_bytes) >= 12 and raw_bytes[:4] == b"RIFF" and raw_bytes[8:12] == b"WEBP":
        return "image/webp", ".webp"
    raise ValueError("نوع الملف غير مدعوم أو غير صالح (يسمح فقط بـ JPG, PNG, WEBP, PDF)")


def validate_and_store_scan(raw_bytes: bytes, original_filename: str, scans_dir: str) -> dict:
    """Validate scan size and magic bytes, prevent traversal, and store with UUID filename."""
    if not raw_bytes or len(raw_bytes) == 0:
        raise ValueError("الملف فارغ")
    if len(raw_bytes) > MAX_SCAN_SIZE:
        raise ValueError("حجم الملف يتجاوز الحد الأقصى المسموح به (10 ميجابايت)")

    mime_type, ext = _detect_file_type(raw_bytes)

    # Sanitize original filename (remove paths and dangerous characters)
    clean_orig = str(original_filename or "").replace("\\", "/")
    clean_orig = os.path.basename(clean_orig)
    clean_orig = re.sub(r"[\r\n\t\x00]", "", clean_orig).strip()
    if not clean_orig:
        clean_orig = f"scan_{uuid.uuid4().hex[:8]}{ext}"

    # Extension allow-list and magic-type consistency check
    orig_ext = os.path.splitext(clean_orig)[1].lower()
    if orig_ext:
        if orig_ext not in ALLOWED_EXT_TO_MIME:
            raise ValueError(f"امتداد الملف غير مسموح به ({orig_ext})")
        if ALLOWED_EXT_TO_MIME[orig_ext] != mime_type:
            raise ValueError(f"امتداد الملف ({orig_ext}) لا يطابق محتوى الملف الحقيقي ({mime_type})")
    else:
        clean_orig = f"{clean_orig}{ext}"

    # Generate secure UUID filename
    stored_filename = f"{uuid.uuid4().hex}{ext}"

    os.makedirs(scans_dir, exist_ok=True)
    real_scans_dir = os.path.realpath(scans_dir)
    target_path = os.path.realpath(os.path.join(scans_dir, stored_filename))

    if not target_path.startswith(real_scans_dir + os.sep):
        raise ValueError("مسار حفظ غير آمن")

    # Atomic write via temporary file inside same directory
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=real_scans_dir, delete=False, suffix=".tmp") as tmp_f:
            tmp_path = tmp_f.name
            tmp_f.write(raw_bytes)
            tmp_f.flush()
            os.fsync(tmp_f.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise

    return {
        "stored_filename": stored_filename,
        "original_filename": clean_orig,
        "mime_type": mime_type,
        "file_size": len(raw_bytes),
        "abs_path": target_path,
    }


def resolve_scan_path(stored_filename: str, scans_dir: str) -> str:
    """Safely resolve an absolute scan file path and prevent directory traversal."""
    if not stored_filename or not isinstance(stored_filename, str):
        raise ValueError("اسم الملف غير صالح")
    if "/" in stored_filename or "\\" in stored_filename or ".." in stored_filename:
        raise ValueError("محاولة وصول غير مصرح بها للمسار")
    if os.path.basename(stored_filename) != stored_filename:
        raise ValueError("محاولة وصول غير مصرح بها للمسار")

    real_scans_dir = os.path.realpath(scans_dir)
    target_path = os.path.realpath(os.path.join(scans_dir, stored_filename))

    if not target_path.startswith(real_scans_dir + os.sep):
        raise ValueError("محاولة وصول غير مصرح بها للمسار")
    return target_path


# ── GIS NEAREST POLICE STATION MATCHER ────────────────────────────────────────

def _load_areas(base_dir: str) -> list[dict]:
    """Load and cache amman_areas.json."""
    global _AREAS_CACHE, _AREAS_CACHE_PATH
    areas_path = os.path.join(base_dir, "data", "amman_areas.json")
    if _AREAS_CACHE is not None and _AREAS_CACHE_PATH == areas_path:
        return _AREAS_CACHE

    if not os.path.exists(areas_path):
        return []

    with open(areas_path, "r", encoding="utf-8") as f:
        _AREAS_CACHE = json.load(f)
        _AREAS_CACHE_PATH = areas_path
    return _AREAS_CACHE


_AMMAN_STREET_STATION_RULES = [
    {
        "tokens": ("شارع المدينه المنوره", "طريق المدينه المنوره", "دوار المدينه المنوره", "المدينه المنوره شارع"),
        "avoid_if_tokens": ("ماركا", "اسكان ماركا"),
        "area_name": "شارع المدينة المنورة (تلاع العلي)",
        "nearest_station": "مركز أمن تلاع العلي",
        "police_directorate": "مديرية شرطة شمال عمان",
        "liwa_name": "لواء الجامعة",
        "lat": 31.9911,
        "lon": 35.8683,
    },
    {
        "tokens": ("شارع مكه المكرمه", "شارع مكه", "طريق مكه", "دوار الكيلو", "دوار الحرمين", "مجمع جبر"),
        "avoid_if_tokens": ("ماركا", "اسكان ماركا"),
        "area_name": "شارع مكة المكرمة (تلاع العلي / الكيلو)",
        "nearest_station": "مركز أمن تلاع العلي",
        "police_directorate": "مديرية شرطة شمال عمان",
        "liwa_name": "لواء الجامعة",
        "lat": 31.9766,
        "lon": 35.8620,
    },
    {
        "tokens": ("شارع عبدالله غوشه", "شارع عبد الله غوشه", "شارع غوشه", "عبدالله غوشه", "الصويفيه", "ام اذينه", "الدوار السابع", "الدوار الثامن"),
        "avoid_if_tokens": (),
        "area_name": "شارع عبدالله غوشة / الصويفية",
        "nearest_station": "مركز أمن البيادر",
        "police_directorate": "مديرية شرطة جنوب عمان",
        "liwa_name": "لواء وادي السير",
        "lat": 31.9530,
        "lon": 35.8560,
    },
    {
        "tokens": ("شارع وصفي التل", "الجاردنز", "شارع الملكه رانيا", "شارع الجامعه الاردنيه", "الجامعه الاردنيه"),
        "avoid_if_tokens": (),
        "area_name": "شارع وصفي التل / الجامعة",
        "nearest_station": "مركز أمن ضاحية الرشيد",
        "police_directorate": "مديرية شرطة شمال عمان",
        "liwa_name": "لواء الجامعة",
        "lat": 31.9853,
        "lon": 35.8807,
    },
    {
        "tokens": ("شارع خليل السالم", "خلدا"),
        "avoid_if_tokens": (),
        "area_name": "خلدا / شارع خليل السالم",
        "nearest_station": "مركز أمن تلاع العلي",
        "police_directorate": "مديرية شرطة شمال عمان",
        "liwa_name": "لواء الجامعة",
        "lat": 31.9950,
        "lon": 35.8450,
    },
    {
        "tokens": ("شارع زهران", "الدوار الثالث", "الدوار الرابع", "الدوار الخامس", "دوار عبدون", "عبدون"),
        "avoid_if_tokens": (),
        "area_name": "شارع زهران / جبل عمان",
        "nearest_station": "مركز أمن زهران",
        "police_directorate": "مديرية شرطة وسط عمان",
        "liwa_name": "لواء قصبة عمان",
        "lat": 31.9540,
        "lon": 35.9050,
    },
    {
        "tokens": ("شارع الملك حسين", "العبدلي", "دوار الداخليه"),
        "avoid_if_tokens": (),
        "area_name": "العبدلي / شارع الملك حسين",
        "nearest_station": "مركز أمن الشميساني",
        "police_directorate": "مديرية شرطة وسط عمان",
        "liwa_name": "لواء قصبة عمان",
        "lat": 31.9680,
        "lon": 35.9050,
    },
    {
        "tokens": ("الدوار الاول", "الدوار الثاني", "شارع الرينبو", "جبل اللويبده", "دوار باريس", "دوار الشابسوغ"),
        "avoid_if_tokens": (),
        "area_name": "وسط البلد / جبل عمان",
        "nearest_station": "مركز أمن المدينة",
        "police_directorate": "مديرية شرطة وسط عمان",
        "liwa_name": "لواء قصبة عمان",
        "lat": 31.9515,
        "lon": 35.9300,
    },
    {
        "tokens": ("شارع الاستقلال",),
        "avoid_if_tokens": (),
        "area_name": "شارع الاستقلال",
        "nearest_station": "مركز أمن النزهة",
        "police_directorate": "مديرية شرطة وسط عمان",
        "liwa_name": "لواء قصبة عمان",
        "lat": 31.9750,
        "lon": 35.9350,
    },
    {
        "tokens": ("شارع الحريه",),
        "avoid_if_tokens": (),
        "area_name": "شارع الحرية",
        "nearest_station": "مركز أمن المقابلين",
        "police_directorate": "مديرية شرطة جنوب عمان",
        "liwa_name": "لواء القويسمة",
        "lat": 31.9180,
        "lon": 35.9180,
    },
]


def _resolve_real_station_item(item: dict, real_station_areas: list) -> dict:
    """Resolve generic 'أقرب مركز أمني' placeholder rows to nearest real police station by coordinates."""
    closest = str(item.get("closest") or "").strip()
    if closest and closest != "أقرب مركز أمني":
        return {
            "area_name": item.get("name") or "",
            "nearest_station": closest,
            "police_directorate": item.get("directorate") or "",
            "liwa_name": item.get("liwa") or "",
            "lat": item.get("lat"),
            "lon": item.get("lon"),
        }

    lat = item.get("lat")
    lon = item.get("lon")
    if isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and real_station_areas:
        nearest = min(
            real_station_areas,
            key=lambda a: (float(a["lat"]) - float(lat)) ** 2 + (float(a["lon"]) - float(lon)) ** 2,
        )
        return {
            "area_name": item.get("name") or nearest.get("name") or "",
            "nearest_station": nearest.get("closest") or "",
            "police_directorate": nearest.get("directorate") or "",
            "liwa_name": nearest.get("liwa") or "",
            "lat": lat,
            "lon": lon,
        }
    return {}


def match_nearest_police_station(address: str, base_dir: str) -> dict:
    """
    Match an address string against famous Amman street aliases and data/amman_areas.json.
    Returns nearest station, directorate, liwa, lat, lon, and top candidates.
    """
    default_res = {
        "matched": False,
        "area_name": "",
        "nearest_station": "",
        "police_directorate": "",
        "liwa_name": "",
        "lat": None,
        "lon": None,
        "candidates": [],
    }

    if not address or not isinstance(address, str):
        return default_res

    areas = _load_areas(base_dir)
    if not areas:
        return default_res

    norm_addr = normalize_arabic(address)
    if not norm_addr:
        return default_res

    real_station_areas = [
        a for a in areas
        if str(a.get("closest") or "").strip() not in ("", "أقرب مركز أمني")
        and isinstance(a.get("lat"), (int, float))
        and isinstance(a.get("lon"), (int, float))
    ]

    # Check explicit Amman main street & landmark aliases before ambiguous neighborhood substrings
    street_override = None
    best_alias_len = 0
    for rule in _AMMAN_STREET_STATION_RULES:
        if rule["avoid_if_tokens"] and any(av in norm_addr for av in rule["avoid_if_tokens"]):
            continue
        for tok in rule["tokens"]:
            if tok in norm_addr and len(tok) > best_alias_len:
                best_alias_len = len(tok)
                street_override = {
                    "area_name": rule["area_name"],
                    "nearest_station": rule["nearest_station"],
                    "police_directorate": rule["police_directorate"],
                    "liwa_name": rule["liwa_name"],
                    "lat": rule["lat"],
                    "lon": rule["lon"],
                }

    addr_words = [w for w in norm_addr.split() if len(w) > 1]
    stopwords = {"عمان", "شارع", "قرب", "دوار", "منطقه", "حوض", "حي", "مقابل", "خلف", "بجانب", "مجمع", "عماره", "طابق", "شقه"}

    scored = []
    for area in areas:
        area_name = area.get("name") or ""
        closest = area.get("closest") or ""
        directorate = area.get("directorate") or ""
        liwa = area.get("liwa") or ""

        name_norm = normalize_arabic(area_name)
        closest_norm = normalize_arabic(closest)
        dir_norm = normalize_arabic(directorate)
        liwa_norm = normalize_arabic(liwa)

        score = 0
        # Exact substring matches
        if name_norm and name_norm in norm_addr:
            score += len(name_norm) * 50
        if closest_norm and closest != "أقرب مركز أمني" and closest_norm in norm_addr:
            score += len(closest_norm) * 40

        # Word overlap
        for w in name_norm.split():
            if len(w) > 1 and w in addr_words and w not in stopwords:
                score += len(w) * 15

        if closest != "أقرب مركز أمني":
            for w in closest_norm.split():
                if len(w) > 1 and w in addr_words and w not in stopwords:
                    score += len(w) * 10

        for w in liwa_norm.split():
            if len(w) > 1 and w in addr_words and w not in stopwords:
                score += len(w) * 3

        for w in dir_norm.split():
            if len(w) > 1 and w in addr_words and w not in stopwords:
                score += len(w) * 2

        if score > 0:
            scored.append((score, area))

    if not scored and not street_override:
        return default_res

    scored.sort(key=lambda x: x[0], reverse=True)

    candidates = []
    seen_stations = set()
    if street_override:
        seen_stations.add(street_override["nearest_station"])
        candidates.append(street_override)

    for _, raw_item in scored:
        resolved = _resolve_real_station_item(raw_item, real_station_areas)
        st = resolved.get("nearest_station") or ""
        if st and st != "أقرب مركز أمني" and st not in seen_stations:
            seen_stations.add(st)
            candidates.append(resolved)
            if len(candidates) >= 5:
                break

    if not candidates:
        return default_res

    best = candidates[0]
    return {
        "matched": True,
        "area_name": best["area_name"],
        "nearest_station": best["nearest_station"],
        "police_directorate": best["police_directorate"],
        "liwa_name": best["liwa_name"],
        "lat": best["lat"],
        "lon": best["lon"],
        "candidates": candidates,
    }


# ── 90-DAY CALCULATOR ────────────────────────────────────────────────────────

def compute_90_day_status(last_followup_at: str, workflow_stage: str) -> dict:
    """
    Calculate the elapsed days from the last follow-up date and determine the 90-day status.
    Supports ISO 8601 timestamps (including 'Z' and timezone offsets) and standard SQLite dates.
    Returns: days_elapsed, days_remaining, is_due_for_stop, warning_level
    """
    is_closed = str(workflow_stage or "").lower() in (
        "closed",
        "stopped",
        "archived",
        "governor_rejected",
        "stopped_90_days",
        "completed",
    )

    dt = None
    if last_followup_at:
        s = str(last_followup_at).strip()
        # Try ISO 8601 first (handles Z, offsets +HH:MM, and standard T format)
        try:
            iso_s = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(iso_s)
        except (ValueError, TypeError):
            # Fallback to standard formats
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
                try:
                    dt = datetime.strptime(s, fmt)
                    break
                except (ValueError, TypeError):
                    continue

    if dt:
        if dt.tzinfo is not None:
            now = datetime.now(timezone.utc)
            elapsed = max(0, (now - dt).days)
        else:
            now = datetime.now()
            elapsed = max(0, (now - dt).days)
    else:
        elapsed = 0

    days_remaining = max(0, 90 - elapsed)

    if is_closed:
        return {
            "days_elapsed": elapsed,
            "days_remaining": days_remaining,
            "is_due_for_stop": False,
            "warning_level": "closed",
        }

    if elapsed >= 90:
        return {
            "days_elapsed": elapsed,
            "days_remaining": 0,
            "is_due_for_stop": True,
            "warning_level": "expired",
        }
    elif elapsed >= 75:
        return {
            "days_elapsed": elapsed,
            "days_remaining": days_remaining,
            "is_due_for_stop": False,
            "warning_level": "warning",
        }
    else:
        return {
            "days_elapsed": elapsed,
            "days_remaining": days_remaining,
            "is_due_for_stop": False,
            "warning_level": "normal",
        }


# ── OFFICIAL .DOCX COMPLAINT EXPORTER ────────────────────────────────────────

def _qn(tag: str) -> str:
    """Return qualified XML tag for WordprocessingML."""
    return f"{{{W_NS}}}{tag}"


def _set_cell_text(tc_elem: ET.Element, text: str, bold: bool = False):
    """Set text in a table cell, preserving tcPr and setting Arabic RTL formatting."""
    tc_pr = tc_elem.find(_qn("tcPr"))
    tc_elem.clear()
    if tc_pr is not None:
        tc_elem.append(tc_pr)

    p = ET.SubElement(tc_elem, _qn("p"))
    p_pr = ET.SubElement(p, _qn("pPr"))
    ET.SubElement(p_pr, _qn("bidi"))
    jc = ET.SubElement(p_pr, _qn("jc"))
    jc.set(_qn("val"), "right")

    if text:
        r = ET.SubElement(p, _qn("r"))
        r_pr = ET.SubElement(r, _qn("rPr"))
        ET.SubElement(r_pr, _qn("rtl"))
        r_fonts = ET.SubElement(r_pr, _qn("rFonts"))
        r_fonts.set(_qn("hint"), "cs")
        if bold:
            ET.SubElement(r_pr, _qn("b"))
            ET.SubElement(r_pr, _qn("bCs"))
        t = ET.SubElement(r, _qn("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = str(text)


def _append_paragraph_to_cell(tc_elem: ET.Element, text: str, bold: bool = False):
    """Append a paragraph to an existing table cell."""
    p = ET.SubElement(tc_elem, _qn("p"))
    p_pr = ET.SubElement(p, _qn("pPr"))
    ET.SubElement(p_pr, _qn("bidi"))
    jc = ET.SubElement(p_pr, _qn("jc"))
    jc.set(_qn("val"), "right")

    if text:
        r = ET.SubElement(p, _qn("r"))
        r_pr = ET.SubElement(r, _qn("rPr"))
        ET.SubElement(r_pr, _qn("rtl"))
        r_fonts = ET.SubElement(r_pr, _qn("rFonts"))
        r_fonts.set(_qn("hint"), "cs")
        if bold:
            ET.SubElement(r_pr, _qn("b"))
            ET.SubElement(r_pr, _qn("bCs"))
        t = ET.SubElement(r, _qn("t"))
        t.set(f"{{{XML_NS}}}space", "preserve")
        t.text = str(text)


def export_complaint_docx(complaint_detail: dict, template_path: str) -> bytes:
    """
    Populate complaint_form_editable.docx template with complaint details.
    Uses pure standard library zipfile and xml.etree.ElementTree.
    Returns bytes of the populated .docx file.
    """
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"ملف نموذج الشكوى غير موجود: {template_path}")

    if not isinstance(complaint_detail, dict):
        raise ValueError("بيانات الشكوى غير صالحة")

    complaint = (
        complaint_detail.get("complaint")
        if isinstance(complaint_detail.get("complaint"), dict)
        else complaint_detail
    )
    parties = complaint_detail.get("parties") or []

    # Register XML namespaces so Word understands all tags properly
    ET.register_namespace("w", W_NS)
    ET.register_namespace("r", "http://schemas.openxmlformats.org/officeDocument/2006/relationships")
    ET.register_namespace("m", "http://schemas.openxmlformats.org/officeDocument/2006/math")
    ET.register_namespace("v", "urn:schemas-microsoft-com:vml")
    ET.register_namespace("wp", "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing")
    ET.register_namespace("w10", "urn:schemas-microsoft-com:office:word")
    ET.register_namespace("a", "http://schemas.openxmlformats.org/drawingml/2006/main")
    ET.register_namespace("pic", "http://schemas.openxmlformats.org/drawingml/2006/picture")
    ET.register_namespace("w14", "http://schemas.microsoft.com/office/word/2010/wordml")

    with open(template_path, "rb") as f:
        template_bytes = f.read()

    in_zip = zipfile.ZipFile(io.BytesIO(template_bytes), "r")
    doc_xml_bytes = in_zip.read("word/document.xml")
    root = ET.fromstring(doc_xml_bytes)

    body = root.find(_qn("body"))
    if body is None:
        raise ValueError("ملف Word غير صالح: عنصر body مفقود")

    # 1. Update Table 0 Cell 0 (Date & Complaint Number)
    tbl0 = body[0] if len(body) > 0 and body[0].tag == _qn("tbl") else None
    if tbl0 is not None:
        r0 = tbl0.find(_qn("tr"))
        if r0 is not None:
            cells = r0.findall(_qn("tc"))
            if cells:
                c0 = cells[0]
                paper_date = complaint.get("paper_date") or ""
                comp_num = complaint.get("complaint_number") or ""
                date_text = f"التاريخ: {paper_date} م" if paper_date else "التاريخ:    /    / 202 م"
                _set_cell_text(c0, date_text, bold=True)
                if comp_num:
                    _append_paragraph_to_cell(c0, f"رقم الشكوى: {comp_num}", bold=True)

    # 2. Update Table 1 (Complainants)
    complainants = [p for p in parties if p.get("party_type") == "شاكي"]
    tbl1 = body[3] if len(body) > 3 and body[3].tag == _qn("tbl") else None
    if tbl1 is not None:
        rows1 = tbl1.findall(_qn("tr"))
        for i, comp in enumerate(complainants):
            row_idx = i + 1
            if row_idx < len(rows1):
                row = rows1[row_idx]
            else:
                row = copy.deepcopy(rows1[1])
                tbl1.append(row)
            cells = row.findall(_qn("tc"))
            if len(cells) >= 5:
                _set_cell_text(cells[0], str(i + 1))
                _set_cell_text(cells[1], comp.get("name") or "")
                _set_cell_text(cells[2], comp.get("national_id") or "")
                _set_cell_text(cells[3], comp.get("phone") or "")
                _set_cell_text(cells[4], comp.get("address") or "")

    # 3. Update Table 2 (Respondents)
    respondents = [p for p in parties if p.get("party_type") == "مشتكى_عليه"]
    tbl2 = body[5] if len(body) > 5 and body[5].tag == _qn("tbl") else None
    if tbl2 is not None:
        rows2 = tbl2.findall(_qn("tr"))
        for i, resp in enumerate(respondents):
            row_idx = i + 1
            if row_idx < len(rows2):
                row = rows2[row_idx]
            else:
                row = copy.deepcopy(rows2[1])
                tbl2.append(row)
            cells = row.findall(_qn("tc"))
            if len(cells) >= 5:
                _set_cell_text(cells[0], str(i + 1))
                _set_cell_text(cells[1], resp.get("name") or "")
                _set_cell_text(cells[2], resp.get("national_id") or "")
                _set_cell_text(cells[3], resp.get("phone") or "")
                _set_cell_text(cells[4], resp.get("address") or "")

    # 4. Update Paragraph 7 (Subject)
    subject = str(complaint.get("subject") or "").strip()
    p7 = body[7] if len(body) > 7 and body[7].tag == _qn("p") else None
    if p7 is not None and subject:
        # Find runs inside p7 and inject subject text into the spacing run
        for r_elem in p7.findall(_qn("r")):
            t_elem = r_elem.find(_qn("t"))
            if t_elem is not None and t_elem.text and len(t_elem.text) > 10 and t_elem.text.strip() == "":
                t_elem.text = f"  {subject}    "
                break

    # 5. Update Table 3 (Summary rows 0..14 & Section Explanations row 16)
    summary = str(complaint.get("summary") or "").strip()
    tbl3 = body[8] if len(body) > 8 and body[8].tag == _qn("tbl") else None
    if tbl3 is not None:
        rows3 = tbl3.findall(_qn("tr"))
        # Rows 0..14: summary lines
        wrapped_lines = []
        if summary:
            for line in summary.splitlines():
                if not line.strip():
                    wrapped_lines.append("")
                else:
                    wrapped_lines.extend(textwrap.wrap(line, width=70) or [""])

        for r_idx in range(min(15, len(rows3))):
            line_text = wrapped_lines[r_idx] if r_idx < len(wrapped_lines) else ""
            cells = rows3[r_idx].findall(_qn("tc"))
            if cells:
                _set_cell_text(cells[0], line_text)

        # Row 16: Section explanations & official notes
        if len(rows3) > 16:
            r16_cells = rows3[16].findall(_qn("tc"))
            if r16_cells:
                c16 = r16_cells[0]
                _set_cell_text(c16, "مشروحات القسم:", bold=True)

                section_notes = complaint.get("section_head_notes") or ""
                if section_notes:
                    _append_paragraph_to_cell(c16, f"مشروحات القسم: {section_notes}")

                nearest_station = complaint.get("nearest_station") or ""
                police_dir = complaint.get("police_directorate") or ""
                if nearest_station:
                    station_desc = f"المركز الأمني المعني: {nearest_station}"
                    if police_dir:
                        station_desc += f" ({police_dir})"
                    _append_paragraph_to_cell(c16, station_desc)

                rec_action = complaint.get("section_recommended_action") or complaint.get("officer_action") or ""
                if rec_action:
                    _append_paragraph_to_cell(c16, f"الإجراء المنسب به: {rec_action}")

                officer_notes = complaint.get("officer_notes") or ""
                if officer_notes:
                    _append_paragraph_to_cell(c16, f"ملاحظات الضابط: {officer_notes}")

                gov_dec = complaint.get("governor_decision") or ""
                gov_action = complaint.get("governor_final_action") or ""
                gov_notes = complaint.get("governor_notes") or ""
                if gov_dec or gov_action or gov_notes:
                    gov_parts = [p for p in (gov_dec, gov_action, gov_notes) if p]
                    _append_paragraph_to_cell(c16, f"قرار الحاكم الإداري: {' - '.join(gov_parts)}")

    # 6. Repack into new DOCX
    out_io = io.BytesIO()
    with zipfile.ZipFile(out_io, "w", compression=zipfile.ZIP_DEFLATED) as out_zip:
        for item in in_zip.infolist():
            if item.filename == "word/document.xml":
                updated_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
                out_zip.writestr(item, updated_xml)
            else:
                out_zip.writestr(item, in_zip.read(item.filename))

    in_zip.close()
    return out_io.getvalue()


# ── WORKFLOW HELPERS & RBAC ──────────────────────────────────────────────────

def _now_str() -> str:
    """Return current local timestamp string formatted consistently with SQLite localtime."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _require_roles(user: dict, allowed_roles: tuple[str, ...]) -> tuple[int, str]:
    """Validate authenticated user dict and enforce role-based access control."""
    if not user or not isinstance(user, dict):
        raise PermissionError("المصادقة مطلوبة")
    actor_id = user.get("user_id") or user.get("id")
    if not actor_id:
        raise PermissionError("معرف المستخدم مفقود")
    try:
        actor_int = int(actor_id)
    except (ValueError, TypeError) as exc:
        raise PermissionError("معرف المستخدم غير صالح") from exc
    role = str(user.get("role") or "").strip()
    if role not in allowed_roles:
        raise PermissionError(f"غير مصرح للدور '{role}' بتنفيذ هذا الإجراء")
    return actor_int, role


def _clean_opt_int(value, field_name: str = "value"):
    """Parse optional integer identifier safely; return None for blank values."""
    if value is None or value == "":
        return None
    try:
        iv = int(value)
        return iv if iv > 0 else None
    except (ValueError, TypeError) as exc:
        raise ValueError(f"قيمة غير صالحة للحقل {field_name}") from exc


def _clean_opt_float(value, field_name: str = "value"):
    """Parse optional float coordinate safely; return None for blank values."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"قيمة رقمية غير صالحة للحقل {field_name}") from exc


def _is_truthy(val) -> bool:
    """Interpret boolean flags from JSON payloads or query parameters."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _get_complaint_or_raise(conn, complaint_id: int) -> dict:
    """Fetch raw complaint row by ID or raise LookupError."""
    cid = _clean_opt_int(complaint_id, "complaint_id")
    if cid is None:
        raise LookupError("رقم الشكوى غير صالح")
    row = conn.execute("SELECT * FROM mat_complaints WHERE id = ?", (cid,)).fetchone()
    if row is None:
        raise LookupError(f"الشكوى غير موجودة (#{cid})")
    return dict(row)


def _log_workflow_and_activity(
    conn,
    complaint_id: int,
    actor_id: int,
    actor_role: str,
    stage_from: str,
    stage_to: str,
    action_taken: str,
    notes: str = "",
    activity_action: str = None,
    activity_details: str = None,
) -> None:
    """Record workflow audit trail in mat_complaint_workflow_log and mat_activity_log."""
    conn.execute(
        """
        INSERT INTO mat_complaint_workflow_log
            (complaint_id, actor_id, actor_role, stage_from, stage_to, action_taken, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(complaint_id),
            int(actor_id),
            str(actor_role or ""),
            stage_from,
            stage_to,
            str(action_taken or "").strip(),
            str(notes or "").strip(),
            _now_str(),
        ),
    )
    conn.execute(
        """
        INSERT INTO mat_activity_log (user_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(actor_id),
            activity_action or str(action_taken or "").strip(),
            "police_complaint",
            int(complaint_id),
            activity_details if activity_details is not None else str(notes or "").strip(),
        ),
    )


def _has_party_update(payload: dict) -> bool:
    """Return True only when payload provides at least one non-None party collection."""
    return any(payload.get(k) is not None for k in ("parties", "complainants", "respondents"))


def _normalize_parties(payload: dict) -> list[dict]:
    """Normalize parties from payload['parties'] or separate complainants/respondents lists."""
    for key in ("parties", "complainants", "respondents"):
        val = payload.get(key)
        if val is not None and not isinstance(val, list):
            raise ValueError(f"الحقل {key} يجب أن يكون قائمة")

    raw_parties = payload.get("parties")
    combined = []
    if isinstance(raw_parties, list):
        combined = list(raw_parties)
    else:
        for comp in payload.get("complainants") or []:
            if isinstance(comp, dict):
                item = dict(comp)
                item.setdefault("party_type", "شاكي")
                combined.append(item)
        for resp in payload.get("respondents") or []:
            if isinstance(resp, dict):
                item = dict(resp)
                item.setdefault("party_type", "مشتكى_عليه")
                combined.append(item)

    normalized = []
    for p in combined:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if not name:
            continue
        party_type = str(p.get("party_type") or "شاكي").strip()
        if party_type not in ("شاكي", "مشتكى_عليه"):
            raise ValueError(f"نوع الطرف غير صالح: {party_type}")
        party_category = str(p.get("party_category") or "مواطن").strip() or "مواطن"
        normalized.append(
            {
                "party_type": party_type,
                "party_category": party_category,
                "name": name,
                "phone": str(p.get("phone") or "").strip(),
                "national_id": str(p.get("national_id") or "").strip(),
                "address": str(p.get("address") or "").strip(),
                "notes": str(p.get("notes") or "").strip(),
            }
        )
    return normalized


def _insert_parties(conn, complaint_id: int, parties: list[dict]) -> None:
    """Persist normalized parties for a complaint."""
    for party in parties:
        conn.execute(
            """
            INSERT INTO mat_parties
                (complaint_id, party_type, party_category, name, phone, national_id, address, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(complaint_id),
                party["party_type"],
                party["party_category"],
                party["name"],
                party["phone"],
                party["national_id"],
                party["address"],
                party["notes"],
            ),
        )


def _link_scan_ids(conn, complaint_id: int, scan_ids) -> None:
    """Safely attach unowned scan records to a complaint without hijacking scans owned elsewhere."""
    if not scan_ids or not isinstance(scan_ids, (list, tuple)):
        return
    for raw_sid in scan_ids:
        sid = _clean_opt_int(raw_sid, "scan_id")
        if sid is None:
            continue
        conn.execute(
            """
            UPDATE mat_complaint_scans
            SET complaint_id = ?
            WHERE id = ? AND (complaint_id IS NULL OR complaint_id = ?)
            """,
            (int(complaint_id), sid, int(complaint_id)),
        )


def _first_respondent_address(payload: dict, parties: list[dict]) -> str:
    """Pick first non-empty respondent address or explicit payload respondent_address."""
    for p in parties:
        if p.get("party_type") == "مشتكى_عليه" and p.get("address"):
            return str(p["address"]).strip()
    return str(payload.get("respondent_address") or "").strip()


def _resolve_station_fields(
    payload: dict,
    parties: list[dict],
    base_dir: str = None,
    existing: dict = None,
    allow_clear: bool = True,
) -> dict:
    """Resolve nearest police station metadata, clearing stale fields on override, failed rematch, or clear."""
    existing = existing or {}
    rematch = _is_truthy(payload.get("rematch_station"))

    def _present(key: str) -> bool:
        if key not in payload:
            return False
        if allow_clear:
            return True
        val = payload.get(key)
        return val is not None and str(val).strip() != ""

    has_station_key = _present("nearest_station")
    explicit_station = str(payload.get("nearest_station") or "").strip() if has_station_key else ""
    existing_station = str(existing.get("nearest_station") or "").strip()

    has_dir_key = _present("police_directorate")
    has_liwa_key = _present("liwa_name")
    has_lat_key = _present("station_lat")
    has_lon_key = _present("station_lon")

    explicit_dir = str(payload.get("police_directorate") or "").strip() if has_dir_key else None
    explicit_liwa = str(payload.get("liwa_name") or "").strip() if has_liwa_key else None
    explicit_lat = _clean_opt_float(payload.get("station_lat"), "station_lat") if has_lat_key else None
    explicit_lon = _clean_opt_float(payload.get("station_lon"), "station_lon") if has_lon_key else None

    station_cleared = allow_clear and has_station_key and not explicit_station and not rematch
    station_changed = has_station_key and bool(explicit_station) and (explicit_station != existing_station)

    matched = {}
    if not explicit_station and not station_cleared and (rematch or (not existing_station and base_dir)):
        resp_addr = _first_respondent_address(payload, parties)
        if resp_addr and base_dir:
            res = match_nearest_police_station(resp_addr, base_dir)
            if res.get("matched"):
                matched = res

    if station_cleared:
        nearest_station = ""
        stale_reset = True
    elif has_station_key and explicit_station:
        nearest_station = explicit_station
        stale_reset = station_changed
    elif rematch:
        nearest_station = matched.get("nearest_station") or ""
        stale_reset = True
    elif matched:
        nearest_station = matched.get("nearest_station") or ""
        stale_reset = True
    else:
        nearest_station = existing_station
        stale_reset = False

    def _pick_str(has_key: bool, explicit_val, matched_key: str, existing_key: str) -> str:
        if has_key:
            return explicit_val or ""
        if matched:
            return matched.get(matched_key) or ""
        if stale_reset:
            return ""
        return str(existing.get(existing_key) or "").strip()

    def _pick_coord(has_key: bool, explicit_val, matched_key: str, existing_key: str):
        if has_key:
            return explicit_val
        if matched:
            return matched.get(matched_key)
        if stale_reset:
            return None
        return existing.get(existing_key)

    return {
        "nearest_station": nearest_station,
        "police_directorate": _pick_str(has_dir_key, explicit_dir, "police_directorate", "police_directorate"),
        "liwa_name": _pick_str(has_liwa_key, explicit_liwa, "liwa_name", "liwa_name"),
        "station_lat": _pick_coord(has_lat_key, explicit_lat, "lat", "station_lat"),
        "station_lon": _pick_coord(has_lon_key, explicit_lon, "lon", "station_lon"),
    }


def _generate_unique_complaint_number(conn) -> str:
    """Generate a collision-free complaint number in PC-YYYYMMDD-NNNN format."""
    today_tag = datetime.now().strftime("%Y%m%d")
    prefix = f"PC-{today_tag}-"
    rows = conn.execute(
        "SELECT complaint_number FROM mat_complaints WHERE complaint_number LIKE ?",
        (f"{prefix}%",),
    ).fetchall()
    max_seq = 0
    for row in rows:
        cn = row["complaint_number"] if hasattr(row, "keys") else row[0]
        if cn and cn.startswith(prefix):
            tail = cn[len(prefix):]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    seq = max_seq + 1
    while True:
        candidate = f"{prefix}{seq:04d}"
        exists = conn.execute(
            "SELECT 1 FROM mat_complaints WHERE complaint_number = ?",
            (candidate,),
        ).fetchone()
        if not exists:
            return candidate
        seq += 1


# ── AUTOMATED MAT TOOLKIT INTEGRATIONS ───────────────────────────────────────

def _auto_create_phone_appointment(conn, complaint: dict, parties: list[dict], actor_id: int) -> int:
    """Create a mat_simple_appointments entry for 'اتصال هاتفي' if not already linked."""
    existing_appt_id = complaint.get("linked_appointment_id")
    if existing_appt_id:
        existing_row = conn.execute(
            "SELECT id FROM mat_simple_appointments WHERE id = ?",
            (int(existing_appt_id),),
        ).fetchone()
        if existing_row:
            return int(existing_row["id"])

    respondents = [p for p in parties if p.get("party_type") == "مشتكى_عليه"]
    complainants = [p for p in parties if p.get("party_type") == "شاكي"]
    primary_party = respondents[0] if respondents else (complainants[0] if complainants else None)

    case_number = (complaint.get("complaint_number") or f"PC-{complaint['id']}").strip()
    if primary_party:
        visitor_name = (primary_party.get("name") or "").strip() or complaint.get("subject") or case_number
        phone = (primary_party.get("phone") or "").strip()
        national_id = (primary_party.get("national_id") or "").strip()
    else:
        visitor_name = (complaint.get("subject") or "").strip() or case_number
        phone = ""
        national_id = ""

    now_dt = datetime.now()
    appt_dt = now_dt + timedelta(days=1) if now_dt.hour >= 15 else now_dt
    appointment_date = appt_dt.strftime("%Y-%m-%d")
    appointment_time = "10:00"
    station_name = (complaint.get("nearest_station") or "").strip() or "قسم الشكاوي"

    note_parts = [f"شكوى أمنية ({case_number}): {complaint.get('subject') or ''}"]
    if complaint.get("governor_decision"):
        note_parts.append(f"قرار الحاكم الإداري: {complaint['governor_decision']}")
    if complaint.get("governor_notes"):
        note_parts.append(str(complaint["governor_notes"]).strip())
    notes = " | ".join(p for p in note_parts if p)

    requested_by_id = (
        complaint.get("section_head_id")
        or complaint.get("assigned_officer_id")
        or complaint.get("created_by_id")
        or actor_id
    )

    cur = conn.execute(
        """
        INSERT INTO mat_simple_appointments (
            case_number, visitor_name, phone, national_id, station_name,
            appointment_date, appointment_time, status, notes, created_by_id,
            requested_by_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'مُجدول', ?, ?, ?)
        """,
        (
            case_number,
            visitor_name,
            phone,
            national_id,
            station_name,
            appointment_date,
            appointment_time,
            notes,
            int(actor_id),
            int(requested_by_id),
        ),
    )
    appt_id = int(cur.lastrowid)

    conn.execute(
        "UPDATE mat_complaints SET linked_appointment_id = ?, updated_at = ? WHERE id = ?",
        (appt_id, _now_str(), int(complaint["id"])),
    )
    conn.execute(
        """
        INSERT INTO mat_activity_log (user_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            int(actor_id),
            "إنشاء موعد اتصال هاتفي تلقائي",
            "simple_appointment",
            appt_id,
            f"تم جدولة اتصال تلقائي للشكوى {case_number} بتاريخ {appointment_date}",
        ),
    )
    return appt_id


def _auto_reserve_complaint_file(conn, complaint: dict, actor_id: int) -> str:
    """Reserve complaint_number in mat_reserved_files and record initial custody log idempotently."""
    file_number = (complaint.get("complaint_number") or f"PC-{complaint['id']}").strip()
    target_officer_id = int(
        complaint.get("assigned_officer_id")
        or complaint.get("section_head_id")
        or complaint.get("created_by_id")
        or actor_id
    )

    existing_res = conn.execute(
        "SELECT id FROM mat_reserved_files WHERE file_number = ?",
        (file_number,),
    ).fetchone()

    created_new = False
    if existing_res is None:
        station_info = (complaint.get("nearest_station") or "").strip()
        note_text = f"حجز تلقائي لشكوى: {complaint.get('subject') or ''}".strip()
        if station_info:
            note_text += f" ({station_info})"
        new_res_id = None
        try:
            cur = conn.execute(
                "INSERT INTO mat_reserved_files (file_number, officer_id, notes) VALUES (?, ?, ?)",
                (file_number, target_officer_id, note_text),
            )
            new_res_id = int(cur.lastrowid)
        except sqlite3.IntegrityError:
            existing_res = conn.execute(
                "SELECT id FROM mat_reserved_files WHERE file_number = ?",
                (file_number,),
            ).fetchone()
            if existing_res is None:
                raise
        if new_res_id is not None:
            conn.execute(
                """
                INSERT INTO mat_file_custody_log (reserved_file_id, to_officer_id, status, notes)
                VALUES (?, ?, 'accepted', ?)
                """,
                (new_res_id, target_officer_id, "تسجيل أولي تلقائي بعد قرار الحاكم الإداري"),
            )
            created_new = True

    conn.execute(
        "UPDATE mat_complaints SET linked_file_number = ?, updated_at = ? WHERE id = ?",
        (file_number, _now_str(), int(complaint["id"])),
    )
    if created_new:
        conn.execute(
            """
            INSERT INTO mat_activity_log (user_id, action, entity_type, entity_id, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(actor_id),
                "حجز ملف شكوى تلقائي",
                "police_complaint",
                int(complaint["id"]),
                f"تم حجز الملف رقم {file_number} تلقائياً للضابط #{target_officer_id}",
            ),
        )
    return file_number


def _ensure_officer_exists(conn, officer_id: int) -> None:
    """Verify an explicit officer ID exists in mat_officers."""
    row = conn.execute("SELECT id FROM mat_officers WHERE id = ?", (int(officer_id),)).fetchone()
    if row is None:
        raise ValueError(f"الضابط المحدد غير موجود (#{officer_id})")


def _apply_post_approval_integrations(conn, complaint_id: int, final_action: str, actor_id: int) -> None:
    """Execute automated MAT integrations based on the governor's approved final action."""
    complaint = _get_complaint_or_raise(conn, complaint_id)
    parties = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM mat_parties WHERE complaint_id = ? ORDER BY id ASC",
            (int(complaint_id),),
        ).fetchall()
    ]
    action_clean = str(final_action or "").strip()
    if action_clean == "اتصال هاتفي":
        _auto_create_phone_appointment(conn, complaint, parties, actor_id)
    elif action_clean in ("توديع عن طريق مركز أمني", "توديع مغفور"):
        _auto_reserve_complaint_file(conn, complaint, actor_id)
        if action_clean == "توديع مغفور":
            conn.execute(
                "UPDATE mat_complaints SET priority = 'عاجل', updated_at = ? WHERE id = ?",
                (_now_str(), int(complaint_id)),
            )


# ── PUBLIC WORKFLOW SERVICE FUNCTIONS ────────────────────────────────────────

def get_complaint_detail(conn, complaint_id: int) -> dict | None:
    """Return full complaint record with attached parties, scans, workflow log, 90-day status, and linked tools."""
    cid = _clean_opt_int(complaint_id, "complaint_id")
    if cid is None:
        return None

    row = conn.execute(
        """
        SELECT c.*,
               o_assigned.name AS assigned_officer_name,
               o_created.name AS created_by_name,
               o_off.name AS officer_reviewed_by_name,
               o_sec.name AS section_head_name,
               o_gov.name AS governor_name
        FROM mat_complaints c
        LEFT JOIN mat_officers o_assigned ON c.assigned_officer_id = o_assigned.id
        LEFT JOIN mat_officers o_created ON c.created_by_id = o_created.id
        LEFT JOIN mat_officers o_off ON c.officer_reviewed_by_id = o_off.id
        LEFT JOIN mat_officers o_sec ON c.section_head_id = o_sec.id
        LEFT JOIN mat_officers o_gov ON c.governor_id = o_gov.id
        WHERE c.id = ?
        """,
        (cid,),
    ).fetchone()
    if row is None:
        return None

    detail = dict(row)
    detail["parties"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT * FROM mat_parties
            WHERE complaint_id = ?
            ORDER BY CASE WHEN party_type = 'شاكي' THEN 0 ELSE 1 END, id ASC
            """,
            (cid,),
        ).fetchall()
    ]
    detail["scans"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT s.*, o.name AS uploaded_by_name
            FROM mat_complaint_scans s
            LEFT JOIN mat_officers o ON s.uploaded_by_id = o.id
            WHERE s.complaint_id = ?
            ORDER BY s.page_order ASC, s.id ASC
            """,
            (cid,),
        ).fetchall()
    ]
    detail["workflow_log"] = [
        dict(r)
        for r in conn.execute(
            """
            SELECT l.*, o.name AS actor_name
            FROM mat_complaint_workflow_log l
            LEFT JOIN mat_officers o ON l.actor_id = o.id
            WHERE l.complaint_id = ?
            ORDER BY l.created_at ASC, l.id ASC
            """,
            (cid,),
        ).fetchall()
    ]
    detail["ninety_day_status"] = compute_90_day_status(
        detail.get("last_followup_at"),
        detail.get("workflow_stage"),
    )

    linked_appt = None
    if detail.get("linked_appointment_id"):
        appt_row = conn.execute(
            """
            SELECT sa.*, req.name AS requested_by_name, cb.name AS created_by_name
            FROM mat_simple_appointments sa
            LEFT JOIN mat_officers req ON sa.requested_by_id = req.id
            LEFT JOIN mat_officers cb ON sa.created_by_id = cb.id
            WHERE sa.id = ?
            """,
            (int(detail["linked_appointment_id"]),),
        ).fetchone()
        if appt_row is not None:
            linked_appt = dict(appt_row)
    detail["linked_appointment"] = linked_appt

    linked_file = None
    if detail.get("linked_file_number"):
        file_row = conn.execute(
            """
            SELECT rf.*, o.name AS officer_name
            FROM mat_reserved_files rf
            LEFT JOIN mat_officers o ON rf.officer_id = o.id
            WHERE rf.file_number = ?
            """,
            (detail["linked_file_number"],),
        ).fetchone()
        if file_row is not None:
            linked_file = dict(file_row)
    detail["linked_file"] = linked_file

    return detail


def _expand_stage_filter(raw_stage: str) -> list[str]:
    """Expand stage filter alias or comma-separated stages into explicit stage names."""
    stage = str(raw_stage or "").strip()
    if not stage or stage == "all":
        return []
    if stage in ("approved_in_execution", "active_execution"):
        return ["governor_approved", "governor_modified", "in_execution"]
    if stage == "draft":
        return ["draft_scan", "officer_reviewed"]
    return [part.strip() for part in stage.split(",") if part.strip()]


def list_complaints(conn, user: dict, filters: dict = None) -> dict:
    """List police complaints with role visibility, search/stage/90-day filters, and KPI stats."""
    actor_id, role = _require_roles(user, ("officer", "admin", "governor", "caller"))
    filters = filters or {}

    base_clauses = []
    base_params = []
    if role == "caller":
        base_clauses.append("(c.governor_final_action = 'اتصال هاتفي' OR c.linked_appointment_id IS NOT NULL)")

    base_where = "WHERE " + " AND ".join(base_clauses) if base_clauses else ""

    # Compute KPI stats across all visible complaints
    stats = {
        "total": 0,
        "draft_scan": 0,
        "officer_reviewed": 0,
        "pending_section_head": 0,
        "pending_governor": 0,
        "approved_in_execution": 0,
        "governor_rejected": 0,
        "completed": 0,
        "stopped_90_days": 0,
        "overdue_90": 0,
        "warning_90": 0,
    }
    stat_rows = conn.execute(
        f"SELECT c.workflow_stage, c.last_followup_at FROM mat_complaints c {base_where}",
        base_params,
    ).fetchall()
    for sr in stat_rows:
        st = sr["workflow_stage"] or "draft_scan"
        stats["total"] += 1
        if st in ("draft_scan",):
            stats["draft_scan"] += 1
        elif st == "officer_reviewed":
            stats["officer_reviewed"] += 1
        elif st == "pending_section_head":
            stats["pending_section_head"] += 1
        elif st == "pending_governor":
            stats["pending_governor"] += 1
        elif st in ("governor_approved", "governor_modified", "in_execution"):
            stats["approved_in_execution"] += 1
        elif st == "governor_rejected":
            stats["governor_rejected"] += 1
        elif st == "completed":
            stats["completed"] += 1
        elif st == "stopped_90_days":
            stats["stopped_90_days"] += 1

        nd = compute_90_day_status(sr["last_followup_at"], st)
        if nd["is_due_for_stop"]:
            stats["overdue_90"] += 1
        elif nd["warning_level"] == "warning":
            stats["warning_90"] += 1

    # Apply query filters
    where_clauses = list(base_clauses)
    query_params = list(base_params)

    stage_list = _expand_stage_filter(filters.get("workflow_stage") or filters.get("stage") or "")
    if stage_list:
        placeholders = ", ".join("?" for _ in stage_list)
        where_clauses.append(f"c.workflow_stage IN ({placeholders})")
        query_params.extend(stage_list)

    if _is_truthy(filters.get("mine")):
        where_clauses.append("(c.assigned_officer_id = ? OR c.created_by_id = ?)")
        query_params.extend([actor_id, actor_id])

    assigned_filter = _clean_opt_int(filters.get("assigned_officer_id"), "assigned_officer_id") if filters.get("assigned_officer_id") else None
    if assigned_filter is not None:
        where_clauses.append("c.assigned_officer_id = ?")
        query_params.append(assigned_filter)

    station_filter = str(filters.get("nearest_station") or "").strip()
    if station_filter:
        where_clauses.append("c.nearest_station LIKE ?")
        query_params.append(f"%{station_filter}%")

    q = str(filters.get("q") or filters.get("search") or "").strip()
    if q:
        term = f"%{q}%"
        where_clauses.append(
            """
            (
                c.complaint_number LIKE ?
                OR c.subject LIKE ?
                OR c.summary LIKE ?
                OR c.nearest_station LIKE ?
                OR c.police_directorate LIKE ?
                OR c.officer_notes LIKE ?
                OR c.section_head_notes LIKE ?
                OR EXISTS (
                    SELECT 1 FROM mat_parties p
                    WHERE p.complaint_id = c.id
                      AND (p.name LIKE ? OR p.phone LIKE ? OR p.national_id LIKE ?)
                )
            )
            """
        )
        query_params.extend([term] * 10)

    where_sql = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    try:
        page = max(1, int(filters.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        limit = max(1, min(200, int(filters.get("limit") or 50)))
    except (ValueError, TypeError):
        limit = 50
    offset = (page - 1) * limit

    overdue_only = _is_truthy(filters.get("overdue_90") or filters.get("due_for_stop"))

    base_select = f"""
        SELECT c.*,
               o_assigned.name AS assigned_officer_name,
               o_created.name AS created_by_name,
               o_sec.name AS section_head_name,
               o_gov.name AS governor_name,
               (SELECT COUNT(*) FROM mat_complaint_scans s WHERE s.complaint_id = c.id) AS scan_count
        FROM mat_complaints c
        LEFT JOIN mat_officers o_assigned ON c.assigned_officer_id = o_assigned.id
        LEFT JOIN mat_officers o_created ON c.created_by_id = o_created.id
        LEFT JOIN mat_officers o_sec ON c.section_head_id = o_sec.id
        LEFT JOIN mat_officers o_gov ON c.governor_id = o_gov.id
        {where_sql}
        ORDER BY c.updated_at DESC, c.id DESC
    """

    if overdue_only:
        all_rows = [dict(r) for r in conn.execute(base_select, query_params).fetchall()]
        filtered_rows = []
        for item in all_rows:
            nd = compute_90_day_status(item.get("last_followup_at"), item.get("workflow_stage"))
            if nd["is_due_for_stop"]:
                item["ninety_day_status"] = nd
                filtered_rows.append(item)
        total = len(filtered_rows)
        paged_items = filtered_rows[offset : offset + limit]
    else:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM mat_complaints c {where_sql}",
            query_params,
        ).fetchone()["c"]
        paged_rows = conn.execute(
            f"{base_select} LIMIT ? OFFSET ?",
            query_params + [limit, offset],
        ).fetchall()
        paged_items = []
        for r in paged_rows:
            item = dict(r)
            item["ninety_day_status"] = compute_90_day_status(
                item.get("last_followup_at"),
                item.get("workflow_stage"),
            )
            paged_items.append(item)

    # Batch-attach parties for returned page
    if paged_items:
        ids = [item["id"] for item in paged_items]
        placeholders = ", ".join("?" for _ in ids)
        party_rows = conn.execute(
            f"""
            SELECT * FROM mat_parties
            WHERE complaint_id IN ({placeholders})
            ORDER BY CASE WHEN party_type = 'شاكي' THEN 0 ELSE 1 END, id ASC
            """,
            ids,
        ).fetchall()
        parties_by_cid = {}
        for pr in party_rows:
            pd = dict(pr)
            parties_by_cid.setdefault(pd["complaint_id"], []).append(pd)
        for item in paged_items:
            item["parties"] = parties_by_cid.get(item["id"], [])

    return {
        "complaints": paged_items,
        "total": total,
        "page": page,
        "limit": limit,
        "stats": stats,
    }


def create_complaint_intake(conn, user: dict, payload: dict, base_dir: str) -> dict:
    """Create a new police complaint intake record, link parties/scans, and auto-match nearest station."""
    actor_id, role = _require_roles(user, ("officer", "admin"))
    if not isinstance(payload, dict):
        raise ValueError("البيانات المرسلة غير صالحة")

    subject = str(payload.get("subject") or "").strip()
    if not subject:
        raise ValueError("موضوع الشكوى مطلوب")

    submit_stage = str(payload.get("submit_stage") or payload.get("workflow_stage") or "draft_scan").strip()
    if submit_stage not in INTAKE_ALLOWED_STAGES:
        raise ValueError(f"مرحلة الإدخال الأولي غير صالحة: {submit_stage}")

    parties = _normalize_parties(payload)
    first_comp = next((p for p in parties if p["party_type"] == "شاكي"), None)
    first_resp = next((p for p in parties if p["party_type"] == "مشتكى_عليه"), None)

    complainant_category = str(
        payload.get("complainant_category")
        or (first_comp["party_category"] if first_comp else "مواطن")
    ).strip() or "مواطن"
    respondent_category = str(
        payload.get("respondent_category")
        or (first_resp["party_category"] if first_resp else "مواطن")
    ).strip() or "مواطن"

    station_info = _resolve_station_fields(payload, parties, base_dir)

    complaint_number = str(payload.get("complaint_number") or "").strip()
    if not complaint_number:
        complaint_number = _generate_unique_complaint_number(conn)
    else:
        existing_num = conn.execute(
            "SELECT 1 FROM mat_complaints WHERE complaint_number = ?",
            (complaint_number,),
        ).fetchone()
        if existing_num is not None:
            raise ValueError(f"رقم الشكوى مسجل مسبقاً: {complaint_number}")

    assigned_officer_id = _clean_opt_int(payload.get("assigned_officer_id"), "assigned_officer_id")
    if assigned_officer_id is None:
        assigned_officer_id = actor_id
    else:
        _ensure_officer_exists(conn, assigned_officer_id)

    ai_extracted_raw = payload.get("ai_extracted_json")
    if isinstance(ai_extracted_raw, (dict, list)):
        ai_extracted_json = json.dumps(ai_extracted_raw, ensure_ascii=False)
    elif ai_extracted_raw is not None:
        ai_extracted_json = str(ai_extracted_raw)
    else:
        ai_extracted_json = None

    ai_confidence = _clean_opt_float(payload.get("ai_confidence"), "ai_confidence")

    officer_action = str(payload.get("officer_action") or "").strip() or None
    officer_notes = str(payload.get("officer_notes") or "").strip() or None
    now = _now_str()
    officer_reviewed_by_id = actor_id if (officer_action or officer_notes) else None
    officer_reviewed_at = now if (officer_action or officer_notes) else None

    last_followup_at = str(payload.get("last_followup_at") or "").strip() or now
    legacy_status = STAGE_TO_STATUS.get(submit_stage, "جديد")

    try:
        cur = conn.execute(
            """
            INSERT INTO mat_complaints (
                complaint_number, subject, complaint_type, status, priority, notes,
                assigned_officer_id, created_by_id, created_at, updated_at,
                paper_date, complainant_category, respondent_category, summary,
                has_signature, no_pending_lawsuit_declared, workflow_stage,
                is_minor_police_complaint,
                ai_provider, ai_model, ai_extracted_json, ai_analysis,
                ai_solution_recommendation, ai_recommended_action, ai_confidence,
                officer_action, officer_notes, officer_reviewed_by_id, officer_reviewed_at,
                nearest_station, police_directorate, liwa_name, station_lat, station_lon,
                last_followup_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?
            )
            """,
            (
                complaint_number,
                subject,
                str(payload.get("complaint_type") or "عام").strip() or "عام",
                legacy_status,
                str(payload.get("priority") or "عادي").strip() or "عادي",
                str(payload.get("notes") or "").strip(),
                assigned_officer_id,
                actor_id,
                now,
                now,
                str(payload.get("paper_date") or "").strip(),
                complainant_category,
                respondent_category,
                str(payload.get("summary") or "").strip(),
                1 if _is_truthy(payload.get("has_signature")) else 0,
                1 if _is_truthy(payload.get("no_pending_lawsuit_declared")) else 0,
                submit_stage,
                1 if _is_truthy(payload.get("is_minor_police_complaint", True)) else 0,
                str(payload.get("ai_provider") or "").strip() or None,
                str(payload.get("ai_model") or "").strip() or None,
                ai_extracted_json,
                str(payload.get("ai_analysis") or "").strip() or None,
                str(payload.get("ai_solution_recommendation") or "").strip() or None,
                str(payload.get("ai_recommended_action") or "").strip() or None,
                ai_confidence,
                officer_action,
                officer_notes,
                officer_reviewed_by_id,
                officer_reviewed_at,
                station_info["nearest_station"],
                station_info["police_directorate"],
                station_info["liwa_name"],
                station_info["station_lat"],
                station_info["station_lon"],
                last_followup_at,
            ),
        )
    except sqlite3.IntegrityError as exc:
        dup = conn.execute(
            "SELECT 1 FROM mat_complaints WHERE complaint_number = ?",
            (complaint_number,),
        ).fetchone()
        if dup is not None:
            raise ValueError(f"رقم الشكوى مسجل مسبقاً: {complaint_number}") from exc
        raise
    complaint_id = int(cur.lastrowid)

    _insert_parties(conn, complaint_id, parties)
    _link_scan_ids(conn, complaint_id, payload.get("scan_ids"))

    _log_workflow_and_activity(
        conn,
        complaint_id,
        actor_id,
        role,
        None,
        submit_stage,
        "إنشاء شكوى",
        notes=officer_notes or subject,
        activity_action="إنشاء شكوى أمنية",
        activity_details=f"{complaint_number} — {subject}",
    )

    conn.commit()
    return get_complaint_detail(conn, complaint_id)


def update_complaint_details(conn, user: dict, complaint_id: int, payload: dict, base_dir: str) -> dict:
    """Update editable complaint details, parties, scan links, and station match."""
    actor_id, role = _require_roles(user, ("officer", "admin"))
    if not isinstance(payload, dict):
        raise ValueError("البيانات المرسلة غير صالحة")

    existing = _get_complaint_or_raise(conn, complaint_id)
    current_stage = existing.get("workflow_stage") or "draft_scan"
    if current_stage in ("completed", "stopped_90_days"):
        raise ValueError(f"لا يمكن تعديل شكوى مغلقة أو موقوفة ({current_stage})")

    has_party_update = _has_party_update(payload)
    if has_party_update:
        parties = _normalize_parties(payload)
    else:
        # Validate types if explicit keys were passed as None (safe) vs invalid non-None already handled
        parties = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM mat_parties WHERE complaint_id = ? ORDER BY id ASC",
                (int(complaint_id),),
            ).fetchall()
        ]

    update_map = {}
    for field in UPDATABLE_COMPLAINT_FIELDS:
        if field not in payload:
            continue
        val = payload[field]
        if field == "subject":
            cleaned = str(val or "").strip()
            if not cleaned:
                raise ValueError("موضوع الشكوى لا يمكن أن يكون فارغاً")
            update_map[field] = cleaned
        elif field in ("has_signature", "no_pending_lawsuit_declared", "is_minor_police_complaint"):
            update_map[field] = 1 if _is_truthy(val) else 0
        elif field == "assigned_officer_id":
            off_id = _clean_opt_int(val, "assigned_officer_id")
            if off_id is not None:
                _ensure_officer_exists(conn, off_id)
            update_map[field] = off_id
        elif field in ("station_lat", "station_lon", "ai_confidence"):
            update_map[field] = _clean_opt_float(val, field)
        elif field == "ai_extracted_json" and isinstance(val, (dict, list)):
            update_map[field] = json.dumps(val, ensure_ascii=False)
        else:
            update_map[field] = str(val or "").strip()

    # Resolve/re-match station if explicitly requested or station fields passed or missing
    station_keys = {
        "nearest_station",
        "police_directorate",
        "liwa_name",
        "station_lat",
        "station_lon",
        "rematch_station",
        "respondent_address",
    }
    if station_keys.intersection(payload.keys()) or (has_party_update and not existing.get("nearest_station")):
        should_match_gis = _is_truthy(payload.get("rematch_station")) or (
            not existing.get("nearest_station") and (has_party_update or "respondent_address" in payload)
        )
        station_info = _resolve_station_fields(
            payload,
            parties,
            base_dir=base_dir if should_match_gis else None,
            existing=existing,
            allow_clear=True,
        )
        update_map.update(station_info)

    target_stage = current_stage
    if "submit_stage" in payload and payload["submit_stage"]:
        req_stage = str(payload["submit_stage"]).strip()
        if req_stage not in INTAKE_ALLOWED_STAGES:
            raise ValueError(f"لا يمكن الانتقال المباشر إلى المرحلة: {req_stage}")
        if current_stage not in PRE_APPROVAL_STAGES and req_stage != current_stage:
            raise ValueError(f"لا يمكن تغيير المرحلة من {current_stage} عبر التحديث العام")
        target_stage = req_stage
        update_map["workflow_stage"] = target_stage
        update_map["status"] = STAGE_TO_STATUS.get(target_stage, existing.get("status"))

    now = _now_str()
    if update_map or has_party_update or "scan_ids" in payload:
        update_map["updated_at"] = now
        set_clauses = [f"{col} = ?" for col in update_map.keys()]
        values = list(update_map.values()) + [int(complaint_id)]
        conn.execute(
            f"UPDATE mat_complaints SET {', '.join(set_clauses)} WHERE id = ?",
            values,
        )

    if has_party_update:
        conn.execute("DELETE FROM mat_parties WHERE complaint_id = ?", (int(complaint_id),))
        _insert_parties(conn, int(complaint_id), parties)

    if "scan_ids" in payload:
        _link_scan_ids(conn, int(complaint_id), payload.get("scan_ids"))

    _log_workflow_and_activity(
        conn,
        int(complaint_id),
        actor_id,
        role,
        current_stage,
        target_stage,
        "تحديث بيانات الشكوى",
        notes=str(payload.get("update_notes") or update_map.get("subject") or existing.get("subject") or ""),
    )

    conn.commit()
    return get_complaint_detail(conn, int(complaint_id))


def record_officer_action(conn, user: dict, complaint_id: int, payload: dict) -> dict:
    """Record officer's action and mandatory notes during pre-approval review or post-approval execution."""
    actor_id, role = _require_roles(user, ("officer", "admin"))
    if not isinstance(payload, dict):
        raise ValueError("البيانات المرسلة غير صالحة")

    existing = _get_complaint_or_raise(conn, complaint_id)
    current_stage = existing.get("workflow_stage") or "draft_scan"

    officer_action = str(payload.get("officer_action") or "").strip()
    officer_notes = str(payload.get("officer_notes") or "").strip()
    if not officer_action:
        raise ValueError("يجب تحديد إجراء الضابط")
    if not officer_notes:
        raise ValueError("ملاحظات الضابط إلزامية عند تسجيل الإجراء")

    if current_stage in PRE_APPROVAL_STAGES:
        new_stage = "pending_section_head" if _is_truthy(payload.get("send_to_section_head")) else "officer_reviewed"
    elif current_stage in POST_APPROVAL_STAGES:
        exec_status = str(payload.get("execution_status") or "").strip()
        new_stage = "completed" if exec_status == "completed" else "in_execution"
    else:
        raise ValueError(f"لا يمكن تسجيل إجراء الضابط في المرحلة الحالية: {current_stage}")

    now = _now_str()
    new_status = STAGE_TO_STATUS.get(new_stage, existing.get("status"))

    conn.execute(
        """
        UPDATE mat_complaints
        SET officer_action = ?,
            officer_notes = ?,
            officer_reviewed_by_id = ?,
            officer_reviewed_at = ?,
            workflow_stage = ?,
            status = ?,
            last_followup_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            officer_action,
            officer_notes,
            actor_id,
            now,
            new_stage,
            new_status,
            now,
            now,
            int(complaint_id),
        ),
    )

    _log_workflow_and_activity(
        conn,
        int(complaint_id),
        actor_id,
        role,
        current_stage,
        new_stage,
        f"إجراء الضابط: {officer_action}",
        notes=officer_notes,
    )

    conn.commit()
    return get_complaint_detail(conn, int(complaint_id))


def record_section_head_recommendation(conn, user: dict, complaint_id: int, payload: dict) -> dict:
    """Record section head notes and recommended action, routing complaint to Governor."""
    actor_id, role = _require_roles(user, ("admin",))
    if not isinstance(payload, dict):
        raise ValueError("البيانات المرسلة غير صالحة")

    existing = _get_complaint_or_raise(conn, complaint_id)
    current_stage = existing.get("workflow_stage") or "draft_scan"
    if current_stage not in SECTION_HEAD_ALLOWED_STAGES:
        raise ValueError(f"لا يمكن تنسيب رئيس القسم في المرحلة الحالية: {current_stage}")

    rec_action = str(payload.get("section_recommended_action") or "").strip()
    sec_notes = str(payload.get("section_head_notes") or "").strip()
    if not rec_action:
        raise ValueError("يجب تحديد الإجراء المنسب من رئيس القسم")
    if not sec_notes:
        raise ValueError("مشروحات القسم مطلوبة")

    station = _resolve_station_fields(payload, [], base_dir=None, existing=existing, allow_clear=False)

    now = _now_str()
    new_stage = "pending_governor"
    new_status = STAGE_TO_STATUS[new_stage]

    conn.execute(
        """
        UPDATE mat_complaints
        SET section_head_notes = ?,
            section_recommended_action = ?,
            section_head_id = ?,
            section_head_at = ?,
            nearest_station = ?,
            police_directorate = ?,
            liwa_name = ?,
            station_lat = ?,
            station_lon = ?,
            workflow_stage = ?,
            status = ?,
            last_followup_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            sec_notes,
            rec_action,
            actor_id,
            now,
            station["nearest_station"],
            station["police_directorate"],
            station["liwa_name"],
            station["station_lat"],
            station["station_lon"],
            new_stage,
            new_status,
            now,
            now,
            int(complaint_id),
        ),
    )

    _log_workflow_and_activity(
        conn,
        int(complaint_id),
        actor_id,
        role,
        current_stage,
        new_stage,
        f"تنسيب رئيس القسم: {rec_action}",
        notes=sec_notes,
    )

    conn.commit()
    return get_complaint_detail(conn, int(complaint_id))


def record_governor_decision(conn, user: dict, complaint_id: int, payload: dict) -> dict:
    """Record exclusive Governor decision and trigger automated MAT toolkit integrations."""
    actor_id, role = _require_roles(user, ("governor",))
    if not isinstance(payload, dict):
        raise ValueError("البيانات المرسلة غير صالحة")

    existing = _get_complaint_or_raise(conn, complaint_id)
    current_stage = existing.get("workflow_stage") or "draft_scan"
    if current_stage not in GOVERNOR_ALLOWED_STAGES:
        raise ValueError(f"لا يمكن إصدار قرار الحاكم الإداري في المرحلة الحالية: {current_stage}")

    decision = str(payload.get("decision") or "").strip()
    if decision not in GOVERNOR_DECISIONS:
        raise ValueError("قرار الحاكم الإداري يجب أن يكون: موافقة أو رفض أو تغيير_الإجراء")

    governor_notes = str(payload.get("governor_notes") or "").strip()

    if decision == "تغيير_الإجراء":
        final_action = str(payload.get("governor_final_action") or "").strip()
        if not final_action:
            raise ValueError("يجب تحديد الإجراء النهائي الجديد عند تغيير الإجراء المنسب")
        new_stage = "governor_modified"
    elif decision == "موافقة":
        final_action = (
            str(payload.get("governor_final_action") or "").strip()
            or str(existing.get("section_recommended_action") or "").strip()
            or str(existing.get("officer_action") or "").strip()
            or str(existing.get("ai_recommended_action") or "").strip()
        )
        new_stage = "governor_approved"
    else:
        final_action = str(payload.get("governor_final_action") or "رفض التنسيب").strip()
        new_stage = "governor_rejected"

    station = _resolve_station_fields(payload, [], base_dir=None, existing=existing, allow_clear=False)

    now = _now_str()
    new_status = STAGE_TO_STATUS[new_stage]

    conn.execute(
        """
        UPDATE mat_complaints
        SET governor_decision = ?,
            governor_final_action = ?,
            governor_notes = ?,
            governor_id = ?,
            governor_decided_at = ?,
            nearest_station = ?,
            police_directorate = ?,
            liwa_name = ?,
            station_lat = ?,
            station_lon = ?,
            workflow_stage = ?,
            status = ?,
            last_followup_at = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            decision,
            final_action,
            governor_notes,
            actor_id,
            now,
            station["nearest_station"],
            station["police_directorate"],
            station["liwa_name"],
            station["station_lat"],
            station["station_lon"],
            new_stage,
            new_status,
            now,
            now,
            int(complaint_id),
        ),
    )

    if new_stage in ("governor_approved", "governor_modified"):
        _apply_post_approval_integrations(conn, int(complaint_id), final_action, actor_id)

    _log_workflow_and_activity(
        conn,
        int(complaint_id),
        actor_id,
        role,
        current_stage,
        new_stage,
        f"قرار الحاكم الإداري ({decision}): {final_action}",
        notes=governor_notes,
    )

    conn.commit()
    return get_complaint_detail(conn, int(complaint_id))


def register_followup(conn, user: dict, complaint_id: int, action_type: str, notes: str = "") -> dict:
    """Register complainant follow-up (resetting 90-day counter) or invoke 90-day stop rule."""
    actor_id, role = _require_roles(user, ("officer", "admin", "governor"))
    existing = _get_complaint_or_raise(conn, complaint_id)
    current_stage = existing.get("workflow_stage") or "draft_scan"

    if current_stage in ("completed", "stopped_90_days"):
        raise ValueError(f"الشكوى مغلقة أو موقوفة مسبقاً ({current_stage})")

    act = str(action_type or "followup").strip().lower()
    clean_notes = str(notes or "").strip()
    now = _now_str()

    if act == "stop_90_days":
        status_90 = compute_90_day_status(existing.get("last_followup_at"), current_stage)
        can_override = role in ("admin", "governor") and bool(clean_notes)
        if status_90["days_elapsed"] < 90 and not can_override:
            raise ValueError(
                "لا يمكن تفعيل كف الطلب قبل مرور 90 يوماً على آخر متابعة إلا بملاحظة صريحة من رئيس القسم أو الحاكم الإداري"
            )
        new_stage = "stopped_90_days"
        new_status = STAGE_TO_STATUS[new_stage]
        conn.execute(
            """
            UPDATE mat_complaints
            SET workflow_stage = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_stage, new_status, now, int(complaint_id)),
        )
        _log_workflow_and_activity(
            conn,
            int(complaint_id),
            actor_id,
            role,
            current_stage,
            new_stage,
            "كف طلب (90 يوماً)",
            notes=clean_notes or "تم تفعيل كف الطلب لمرور 90 يوماً دون مراجعة",
        )
    elif act in ("followup", "complainant_followup", "reset_90_days"):
        if current_stage == "governor_rejected":
            raise ValueError("لا يمكن إعادة ضبط المتابعة لشكوى مرفوضة")
        conn.execute(
            """
            UPDATE mat_complaints
            SET last_followup_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (now, now, int(complaint_id)),
        )
        _log_workflow_and_activity(
            conn,
            int(complaint_id),
            actor_id,
            role,
            current_stage,
            current_stage,
            "متابعة الشاكي (إعادة ضبط 90 يوماً)",
            notes=clean_notes or "تم تسجيل متابعة الشاكي وإعادة ضبط عداد الـ 90 يوماً",
        )
    else:
        raise ValueError(f"نوع المتابعة غير صالح: {action_type}")

    conn.commit()
    return get_complaint_detail(conn, int(complaint_id))


def _parse_tools_set(raw_tools) -> set:
    if isinstance(raw_tools, (list, tuple, set)):
        return {str(t).strip() for t in raw_tools if str(t).strip()}
    return {t.strip() for t in str(raw_tools or "").split(",") if t.strip()}


def _determine_complaint_action_need(complaint: dict, role: str):
    """Return (rank, reason_text) if the complaint requires action by the given role, else None."""
    stage = str(complaint.get("workflow_stage") or "draft_scan").strip()
    if stage in ("completed", "stopped_90_days"):
        return None

    nd = complaint.get("ninety_day_status") or {}
    is_due_stop = bool(nd.get("is_due_for_stop"))
    base_rank = None
    reason = None

    if role == "admin":
        if stage == "pending_section_head":
            base_rank, reason = 1, "بانتظار تنسيب رئيس القسم"
        elif stage in ("draft_scan", "officer_reviewed"):
            base_rank, reason = 2, "بانتظار المراجعة والتنسيب"
        elif stage == "governor_rejected":
            base_rank, reason = 2, "مرفوضة من الحاكم — تحتاج إعادة تنسيب"
        elif stage in ("governor_approved", "governor_modified", "in_execution"):
            base_rank, reason = 3, "معتمدة — بانتظار متابعة التنفيذ"
    elif role == "officer":
        if stage in ("draft_scan", "officer_reviewed"):
            base_rank, reason = 1, "مسودة — تحتاج مراجعة ورفع"
        elif stage == "governor_rejected":
            base_rank, reason = 1, "مرفوضة من الحاكم — تحتاج تعديل وإعادة رفع"
        elif stage in ("governor_approved", "governor_modified", "in_execution"):
            base_rank, reason = 2, "معتمدة — بانتظار التنفيذ والمتابعة"
    elif role == "governor":
        if stage == "pending_governor":
            base_rank, reason = 1, "بانتظار قرار الحاكم الإداري"
    elif role == "caller":
        if stage in ("governor_approved", "governor_modified", "in_execution"):
            base_rank, reason = 1, "مطلوب إجراء اتصال هاتفي ومتابعة"

    if is_due_stop:
        if reason:
            reason = f"{reason} (تجاوزت 90 يوماً)"
            base_rank = min(base_rank, 1)
        else:
            base_rank = 1
            reason = "تجاوزت 90 يوماً — تستحق كف الطلب"

    if not reason:
        return None
    if complaint.get("priority") == "عاجل":
        base_rank = 0
    return base_rank, reason


def get_dashboard_police_summary(conn, user: dict) -> dict:
    """Return permission-gated police complaints stats and action-needed items for the dashboard."""
    if not isinstance(user, dict):
        return {"enabled": False, "can_register": False, "stats": {}, "action_required_count": 0, "action_items": []}

    role = str(user.get("role") or "").strip()
    tools_set = _parse_tools_set(user.get("accessible_tools"))

    user_id = user.get("user_id") or user.get("id")
    if user_id:
        row = conn.execute(
            "SELECT role, accessible_tools FROM mat_officers WHERE id = ?",
            (int(user_id),),
        ).fetchone()
        if row:
            role = str(row["role"] or role).strip()
            tools_set = _parse_tools_set(row["accessible_tools"])

    has_access = role in ("admin", "governor") or ("police_complaints" in tools_set)
    if not has_access or role not in ("officer", "admin", "governor", "caller"):
        return {"enabled": False, "can_register": False, "stats": {}, "action_required_count": 0, "action_items": []}

    effective_user = dict(user)
    effective_user["role"] = role
    if user_id and not effective_user.get("user_id"):
        effective_user["user_id"] = int(user_id)

    listed = list_complaints(conn, effective_user, {"limit": 200})
    action_entries = []
    for c in listed.get("complaints") or []:
        need = _determine_complaint_action_need(c, role)
        if not need:
            continue
        rank, reason = need
        nd = c.get("ninety_day_status") or {}
        action_entries.append((
            rank,
            -(int(c.get("id") or 0)),
            {
                "id": c.get("id"),
                "complaint_number": c.get("complaint_number") or f"#{c.get('id')}",
                "subject": c.get("subject") or "بدون موضوع",
                "workflow_stage": c.get("workflow_stage") or "draft_scan",
                "status": c.get("status") or "",
                "priority": c.get("priority") or "عادي",
                "nearest_station": c.get("nearest_station") or "",
                "is_due_for_stop": bool(nd.get("is_due_for_stop")),
                "days_elapsed": int(nd.get("days_elapsed") or 0),
                "action_reason": reason,
            },
        ))

    action_entries.sort(key=lambda item: (item[0], item[1]))
    action_items = [entry[2] for entry in action_entries]
    return {
        "enabled": True,
        "can_register": role in ("admin", "officer"),
        "stats": listed.get("stats") or {},
        "action_required_count": len(action_items),
        "action_items": action_items[:20],
    }
