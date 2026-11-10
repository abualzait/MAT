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
import tempfile
import textwrap
import uuid
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


# ── CONFIGURATION & CONSTANTS ────────────────────────────────────────────────

MAX_SCAN_SIZE = 10 * 1024 * 1024  # 10 MB

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


def match_nearest_police_station(address: str, base_dir: str) -> dict:
    """
    Match an address string against data/amman_areas.json.
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

    addr_words = [w for w in norm_addr.split() if len(w) > 1]
    stopwords = {"عمان", "شارع", "قرب", "دوار", "منطقه", "حوض", "حي", "مقابل", "خلف", "بجانب", "مجمع"}

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
        if closest_norm and closest_norm in norm_addr:
            score += len(closest_norm) * 40

        # Word overlap
        for w in name_norm.split():
            if len(w) > 1 and w in addr_words and w not in stopwords:
                score += len(w) * 15

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

    if not scored:
        return default_res

    scored.sort(key=lambda x: x[0], reverse=True)
    best = scored[0][1]

    # Collect top unique candidate stations
    candidates = []
    seen_stations = set()
    for _, item in scored:
        st = item.get("closest") or ""
        if st and st not in seen_stations:
            seen_stations.add(st)
            candidates.append({
                "area_name": item.get("name") or "",
                "nearest_station": st,
                "police_directorate": item.get("directorate") or "",
                "liwa_name": item.get("liwa") or "",
                "lat": item.get("lat"),
                "lon": item.get("lon"),
            })
            if len(candidates) >= 5:
                break

    return {
        "matched": True,
        "area_name": best.get("name") or "",
        "nearest_station": best.get("closest") or "",
        "police_directorate": best.get("directorate") or "",
        "liwa_name": best.get("liwa") or "",
        "lat": best.get("lat"),
        "lon": best.get("lon"),
        "candidates": candidates,
    }


# ── 90-DAY CALCULATOR ────────────────────────────────────────────────────────

def compute_90_day_status(last_followup_at: str, workflow_stage: str) -> dict:
    """
    Calculate the elapsed days from the last follow-up date and determine the 90-day status.
    Supports ISO 8601 timestamps (including 'Z' and timezone offsets) and standard SQLite dates.
    Returns: days_elapsed, days_remaining, is_due_for_stop, warning_level
    """
    is_closed = str(workflow_stage or "").lower() in ("closed", "stopped", "archived", "governor_rejected")

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

    complaint = complaint_detail.get("complaint") or {}
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
