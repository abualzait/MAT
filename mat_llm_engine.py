"""Multi-Provider LLM Vision Extraction & Analysis Engine for Police Complaints.

Pure Python standard library implementation: os, json, re, base64, urllib.request, urllib.error, ssl.
No external dependencies.
"""

import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

ALLOWED_RECOMMENDED_ACTIONS = [
    "توديع عن طريق مركز أمني",
    "اتصال هاتفي",
    "توديع مغفور",
    "حفظ / توجيه للقضاء المختص",
]

OPENROUTER_FREE_VISION_FALLBACKS = [
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "dots-studio/dots-3-note-preview:free",
]

OPENROUTER_FREE_TEXT_CLEANUP_MODELS = [
    "nvidia/nemotron-3.5-lightning:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
]

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "ollama": "llama3.2-vision",
}

COMPLAINT_EXTRACTION_PROMPT = """أنت خبير قانوني ومحرر وثائق رسمي في وزارة الداخلية الأردنية - محافظة العاصمة (متصرفية لواء قصبة عمان).
أمامك صورة أو مستند لاستدعاء / نموذج شكوى رسمي (عنوانه غالباً: عطوفة متصرف لواء قصبة عمان المحترم - نموذج شكوى).
المطلوب منك تفريغ محتويات الشكوى من الصورة بدقة حرفية متناهية وإجراء التحليل الإداري والقانوني للشكوى وتحديد مدى الحاجة لمتابعة المراكز الأمنية.

تعليمات الدقة الصارمة (إلزامية):
- ابدأ بتعبئة حقل `raw_transcription` بنسخ كل سطر مقروء في الورقة من الأعلى إلى الأسفل باللغة العربية السليمة حرفياً قبل تعبئة باقي الحقول.
- اقرأ الجداول بعناية من اليمين إلى اليسار: جدول (بيانات المشتكين / المدعين) يذهب إلى `complainants`، وجدول (بيانات المشتكى عليهم) يذهب إلى `respondents`.
- انقل الأسماء والرقم الوطني (غالباً 10 أرقام) ورقم الهاتف (يبدأ غالباً بـ 07) والعناوين والتاريخ (`paper_date` أعلى الورقة) ونص الشكوى (`summary`) حرفاً بحرف ورقماً برقم كما هي في الصورة تماماً.
- لا تخمّن أو تؤلف أي اسم أو رقم غير مقروء؛ إذا كانت خانة فارغة أو غير مقروءة تماماً اتركها نصاً فارغاً "" (أو اكتب [غير واضح] فقط داخل `raw_transcription`).
- إذا ورد إقرار مثل "أقر بعدم وجود قضية منظورة أمام المحاكم بخصوص هذه الشكوى" مع إشارة (✓ / نعم) فإن `no_pending_lawsuit_declared` تكون `true`، وإذا ذُكر وجود قضية قائمة أو وضع علامة لا تكون `false`.
- إذا ظهر توقيع خطي أو اسم في خانة توقيع المشتكي أسفل الورقة فإن `has_signature` تكون `true`.
- اكتب جميع النصوص المستخرجة والتحليل والتوصية باللغة العربية السليمة فقط دون إدخال كلمات إنجليزية أو أجنبية.

قم بإرجاع النتيجة حصراً بصيغة JSON صالحة ونظيفة وبدون أي مقدمات أو شروحات خارج كائن الـ JSON بالهيكل التالي:
{
  "raw_transcription": "التفريغ الحرفي الكامل لجميع أسطر الورقة من الأعلى للأسفل باللغة العربية",
  "paper_date": "تاريخ تقديم الشكوى المكتوب في الورقة إن وجد أو فارغ",
  "complainants": [
    {
      "party_category": "أحد الخيارات: مواطن أو مؤسسة تجارية أو مؤسسة حكومية",
      "name": "الاسم الكامل للمشتكي كما هو مكتوب",
      "national_id": "الرقم الوطني أو الرقم التجاري بالأرقام فقط",
      "phone": "رقم الهاتف بالأرقام فقط",
      "address": "العنوان بالتفصيل كما هو مكتوب"
    }
  ],
  "respondents": [
    {
      "party_category": "أحد الخيارات: مواطن أو منشأة",
      "name": "اسم المشتكى عليه أو اسم المحل/المنشأة كما هو مكتوب",
      "national_id": "الرقم الوطني إن وجد أو فارغ",
      "phone": "رقم الهاتف إن وجد أو فارغ",
      "address": "العنوان بالتفصيل كما هو مكتوب"
    }
  ],
  "subject": "موضوع الشكوى بدقة واختصار بالعربية",
  "summary": "موجز وتفاصيل وقائع الشكوى كما سردها المشتكي حرفياً بالعربية",
  "has_signature": true,
  "no_pending_lawsuit_declared": true,
  "is_minor_police_complaint": true,
  "police_necessity_reason": "سبب توجيه الشكوى للمركز الأمني أو حفظها باختصار بالعربية (جملة إلى جملتين)",
  "ai_analysis": "تحليل وقائع الشكوى والتكييف الإداري والقانوني باختصار ووضوح بالعربية (جملتان إلى ثلاث جمل)",
  "ai_solution_recommendation": "التوصية الإدارية والحل المقترح باختصار ووضوح بالعربية (جملتان إلى ثلاث جمل)",
  "ai_recommended_action": "توديع عن طريق مركز أمني",
  "ai_confidence": 0.92
}
الخيارات المسموحة لحقل ai_recommended_action هي حصراً:
1) 'توديع عن طريق مركز أمني'
2) 'اتصال هاتفي'
3) 'توديع مغفور'
4) 'حفظ / توجيه للقضاء المختص'"""


def _default_model_for_provider(provider: str) -> str:
    prov = (provider or "gemini").lower()
    return DEFAULT_MODELS.get(prov, "gemini-2.5-flash")


def _mask_api_key(key: Optional[str]) -> str:
    if not key:
        return ""
    clean = key.strip()
    if not clean:
        return ""
    if len(clean) <= 4:
        return "****"
    return "****" + clean[-4:]


def _redact_secret(text: str, secret: Optional[str] = None) -> str:
    if not text:
        return ""
    res = text
    if secret and len(secret) >= 4 and secret in res:
        res = res.replace(secret, "[REDACTED]")
    res = re.sub(r"AIzaSy[A-Za-z0-9_-]{15,}", "[REDACTED]", res)
    res = re.sub(r"AQ\.[A-Za-z0-9_.-]{15,}", "[REDACTED]", res)
    res = re.sub(r"nvapi-[A-Za-z0-9_-]{15,}", "[REDACTED]", res)
    res = re.sub(r"sk-[A-Za-z0-9_-]{15,}", "[REDACTED]", res)
    res = re.sub(r"(?:github_pat|ghp)_[A-Za-z0-9_]{15,}", "[REDACTED]", res)
    return res


def _format_http_error(exc: urllib.error.HTTPError, api_key: str = "") -> str:
    """Extract concise provider error details from an HTTPError without exposing secrets or duplicate prefixes."""
    detail = ""
    try:
        raw = exc.read()
        if isinstance(raw, (bytes, bytearray)):
            raw_text = raw.decode("utf-8", errors="replace").strip()
            if raw_text:
                try:
                    parsed = json.loads(raw_text)
                    err_obj = parsed.get("error") if isinstance(parsed, dict) else None
                    if isinstance(err_obj, dict) and err_obj.get("message"):
                        detail = str(err_obj["message"]).strip()
                    elif isinstance(parsed, dict) and parsed.get("detail"):
                        title = str(parsed.get("title") or "").strip()
                        det = str(parsed["detail"]).strip()
                        detail = f"{title}: {det}" if title else det
                    elif isinstance(parsed, dict) and parsed.get("message"):
                        detail = str(parsed["message"]).strip()
                    else:
                        detail = raw_text[:280]
                except Exception:
                    detail = raw_text[:280]
    except Exception:
        detail = ""
    if not detail:
        raw_msg = str(getattr(exc, "msg", "") or "").strip()
        if raw_msg and raw_msg.lower() not in ("bad request", "not found", "payment required", "too many requests"):
            return _redact_secret(raw_msg, api_key)
    base_msg = f"HTTP {exc.code}: {detail}" if detail else str(exc)
    return _redact_secret(base_msg, api_key)


def get_llm_settings(conn: Any = None, mask_secret: bool = True) -> Dict[str, Any]:
    """Retrieve LLM settings from database row id=1 or fall back to environment variables."""
    row = None
    if conn is not None:
        try:
            cur = conn.execute(
                "SELECT id, provider, model_name, api_base_url, api_key, is_enabled FROM mat_llm_settings WHERE id = 1"
            )
            row = cur.fetchone()
        except Exception:
            row = None

    if row:
        if hasattr(row, "keys"):
            provider = row["provider"] or "gemini"
            model_name = row["model_name"] or ""
            api_base_url = row["api_base_url"] or ""
            api_key = row["api_key"] or ""
            is_enabled = int(row["is_enabled"]) if row["is_enabled"] is not None else 1
        else:
            provider = row[1] or "gemini"
            model_name = row[2] or ""
            api_base_url = row[3] or ""
            api_key = row[4] or ""
            is_enabled = int(row[5]) if row[5] is not None else 1
        source = "db"

        # If DB key is empty, fall back to environment variable if set
        if not api_key:
            if provider == "gemini" and os.environ.get("MAT_GEMINI_API_KEY"):
                api_key = os.environ.get("MAT_GEMINI_API_KEY", "")
            elif provider == "openai" and os.environ.get("MAT_OPENAI_API_KEY"):
                api_key = os.environ.get("MAT_OPENAI_API_KEY", "")
    else:
        provider = os.environ.get("MAT_LLM_PROVIDER", "gemini")
        model_name = os.environ.get("MAT_LLM_MODEL", "")
        api_base_url = ""
        api_key = ""
        is_enabled = 1
        has_env = bool(
            os.environ.get("MAT_LLM_PROVIDER")
            or os.environ.get("MAT_GEMINI_API_KEY")
            or os.environ.get("MAT_OPENAI_API_KEY")
            or os.environ.get("MAT_OLLAMA_URL")
        )
        source = "env" if has_env else "default"

        if provider == "gemini":
            api_key = os.environ.get("MAT_GEMINI_API_KEY", "")
        elif provider == "openai":
            api_key = os.environ.get("MAT_OPENAI_API_KEY", "")
            api_base_url = os.environ.get("MAT_OPENAI_BASE_URL", "")
        elif provider == "ollama":
            api_base_url = os.environ.get("MAT_OLLAMA_URL", "http://localhost:11434")

    if not model_name:
        model_name = _default_model_for_provider(provider)

    api_key_configured = bool(api_key and api_key.strip())
    masked_key = _mask_api_key(api_key)

    result: Dict[str, Any] = {
        "provider": provider,
        "model_name": model_name,
        "api_base_url": api_base_url,
        "is_enabled": is_enabled,
        "api_key_configured": api_key_configured,
        "api_key_masked": masked_key,
        "source": source,
    }
    if not mask_secret:
        result["api_key"] = api_key

    return result


def save_llm_settings(conn: Any, user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Save or update LLM settings in mat_llm_settings row id=1."""
    existing_key = ""
    try:
        cur = conn.execute("SELECT api_key FROM mat_llm_settings WHERE id = 1")
        row = cur.fetchone()
        if row:
            existing_key = row["api_key"] if hasattr(row, "keys") else row[0]
    except Exception:
        existing_key = ""

    raw_new_key = payload.get("api_key")
    if raw_new_key is None or (isinstance(raw_new_key, str) and not raw_new_key.strip()):
        final_key = existing_key or ""
    else:
        final_key = str(raw_new_key).strip()

    provider = str(payload.get("provider") or "gemini").strip().lower()
    model_name = str(payload.get("model_name") or "").strip()
    if not model_name:
        model_name = _default_model_for_provider(provider)
    api_base_url = str(payload.get("api_base_url") or "").strip()
    is_enabled_raw = payload.get("is_enabled", 1)
    is_enabled = 1 if is_enabled_raw in (1, "1", True) else 0

    conn.execute(
        """
        INSERT INTO mat_llm_settings (id, provider, model_name, api_base_url, api_key, is_enabled, updated_by_id, updated_at)
        VALUES (1, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
        ON CONFLICT(id) DO UPDATE SET
            provider = excluded.provider,
            model_name = excluded.model_name,
            api_base_url = excluded.api_base_url,
            api_key = excluded.api_key,
            is_enabled = excluded.is_enabled,
            updated_by_id = excluded.updated_by_id,
            updated_at = datetime('now', 'localtime')
        """,
        (provider, model_name, api_base_url, final_key, is_enabled, user_id),
    )
    conn.commit()
    return get_llm_settings(conn, mask_secret=True)


def _parse_llm_json(raw_text: str) -> Dict[str, Any]:
    """Clean markdown fences and extract structured JSON safely."""
    if not raw_text or not isinstance(raw_text, str):
        return {}

    text = raw_text.strip()

    # Match ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try direct parse
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    # Try finding outer braces { ... }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = text[first_brace : last_brace + 1]
        try:
            data = json.loads(snippet)
            if isinstance(data, dict):
                return data
        except Exception:
            # Clean trailing commas
            cleaned = re.sub(r",\s*([}\]])", r"\1", snippet)
            try:
                data = json.loads(cleaned)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass

    return {}


_UNREADABLE_PLACEHOLDERS = {
    "[غير واضح]",
    "غير واضح",
    "[غير مقروء]",
    "غير مقروء",
    "غير متوفر",
    "لا يوجد",
    "فارغ",
    "n/a",
    "unknown",
    "unclear",
}


def _clean_extracted_text(val: Any, clear_placeholder: bool = False) -> str:
    """Trim whitespace and optionally clear placeholder tokens from OCR fields."""
    text = str(val or "").strip()
    if clear_placeholder and text.lower() in _UNREADABLE_PLACEHOLDERS:
        return ""
    return text


def _normalize_arabic_digits(val: Any) -> str:
    """Convert Eastern Arabic numerals to Western digits inside IDs and phone numbers."""
    text = _clean_extracted_text(val, clear_placeholder=True)
    if not text:
        return ""
    trans = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
    return text.translate(trans)


def _normalize_complaint_result(data: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Partition extracted form data and AI analysis fields with verified defaults."""
    ext_src = data.get("extracted") if isinstance(data.get("extracted"), dict) else data

    complainants_raw = ext_src.get("complainants")
    complainants = []
    if isinstance(complainants_raw, list):
        for c in complainants_raw:
            if isinstance(c, dict):
                cat = str(c.get("party_category") or "مواطن").strip()
                if cat not in ("مواطن", "مؤسسة تجارية", "مؤسسة حكومية"):
                    cat = "مواطن"
                row = {
                    "party_category": cat,
                    "name": _clean_extracted_text(c.get("name"), clear_placeholder=True),
                    "national_id": _normalize_arabic_digits(c.get("national_id")),
                    "phone": _normalize_arabic_digits(c.get("phone")),
                    "address": _clean_extracted_text(c.get("address"), clear_placeholder=True),
                }
                if any(row[k] for k in ("name", "national_id", "phone", "address")):
                    complainants.append(row)

    respondents_raw = ext_src.get("respondents")
    respondents = []
    if isinstance(respondents_raw, list):
        for r in respondents_raw:
            if isinstance(r, dict):
                cat = str(r.get("party_category") or "مواطن").strip()
                if cat not in ("مواطن", "منشأة"):
                    cat = "مواطن"
                row = {
                    "party_category": cat,
                    "name": _clean_extracted_text(r.get("name"), clear_placeholder=True),
                    "national_id": _normalize_arabic_digits(r.get("national_id")),
                    "phone": _normalize_arabic_digits(r.get("phone")),
                    "address": _clean_extracted_text(r.get("address"), clear_placeholder=True),
                }
                if any(row[k] for k in ("name", "national_id", "phone", "address")):
                    respondents.append(row)

    extracted = {
        "raw_transcription": _clean_extracted_text(ext_src.get("raw_transcription")),
        "paper_date": _normalize_arabic_digits(ext_src.get("paper_date")),
        "complainants": complainants,
        "respondents": respondents,
        "subject": _clean_extracted_text(ext_src.get("subject"), clear_placeholder=True),
        "summary": _clean_extracted_text(ext_src.get("summary"), clear_placeholder=True),
        "has_signature": bool(ext_src.get("has_signature")),
        "no_pending_lawsuit_declared": bool(ext_src.get("no_pending_lawsuit_declared")),
    }

    ana_src = data.get("analysis") if isinstance(data.get("analysis"), dict) else data

    action_raw = str(ana_src.get("ai_recommended_action") or "").strip()
    if action_raw in ALLOWED_RECOMMENDED_ACTIONS:
        recommended_action = action_raw
    elif "مركز" in action_raw or "أمني" in action_raw or "امني" in action_raw:
        recommended_action = "توديع عن طريق مركز أمني"
    elif "هاتف" in action_raw or "اتصال" in action_raw:
        recommended_action = "اتصال هاتفي"
    elif "مغفور" in action_raw:
        recommended_action = "توديع مغفور"
    elif "قضاء" in action_raw or "حفظ" in action_raw or "محكمة" in action_raw:
        recommended_action = "حفظ / توجيه للقضاء المختص"
    else:
        recommended_action = "توديع عن طريق مركز أمني"

    try:
        conf_val = float(ana_src.get("ai_confidence") or 0.8)
        conf_val = max(0.0, min(1.0, conf_val))
    except (ValueError, TypeError):
        conf_val = 0.8

    analysis = {
        "is_minor_police_complaint": bool(ana_src.get("is_minor_police_complaint", True)),
        "police_necessity_reason": str(ana_src.get("police_necessity_reason") or "").strip(),
        "ai_analysis": str(ana_src.get("ai_analysis") or "").strip(),
        "ai_solution_recommendation": str(ana_src.get("ai_solution_recommendation") or "").strip(),
        "ai_recommended_action": recommended_action,
        "ai_confidence": conf_val,
    }

    return extracted, analysis


def _call_gemini(file_bytes: bytes, mime_type: str, settings: Dict[str, Any], prompt: str) -> str:
    """Invoke Google Gemini Vision via REST API with x-goog-api-key header."""
    model = settings.get("model_name") or _default_model_for_provider("gemini")
    api_key = settings.get("api_key", "").strip()
    if not api_key:
        raise ValueError("Gemini API key is required")

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    b64_data = base64.b64encode(file_bytes).decode("ascii")

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": b64_data,
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "response_mime_type": "application/json",
        },
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")

    resp_json = json.loads(body)
    candidates = resp_json.get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini API returned no candidates")

    parts = candidates[0].get("content", {}).get("parts", [])
    if not parts:
        raise RuntimeError("Gemini candidate content has no parts")

    return parts[0].get("text", "")


def _is_openrouter_endpoint(base_url: str) -> bool:
    """Return True when targeting OpenRouter's unified API gateway."""
    return "openrouter.ai" in (base_url or "").lower()


def _is_nvidia_nim_endpoint(base_url: str) -> bool:
    """Return True when targeting NVIDIA NIM / integrate.api.nvidia.com."""
    return "integrate.api.nvidia.com" in (base_url or "").lower()


def _resolve_openai_base_url(raw_base_url: Any, api_key: str) -> str:
    """Resolve explicit base URL or infer NVIDIA NIM, Groq, or OpenRouter from key prefix when blank."""
    cleaned = str(raw_base_url or "").strip().rstrip("/")
    if cleaned:
        return cleaned
    if api_key.startswith("nvapi-"):
        return "https://integrate.api.nvidia.com/v1"
    if api_key.startswith("gsk_"):
        return "https://api.groq.com/openai/v1"
    if api_key.startswith("sk-or-"):
        return "https://openrouter.ai/api/v1"
    return "https://api.openai.com/v1"


def _resolve_openrouter_vision_models(configured_model: str) -> List[str]:
    """Order reliable OpenRouter free vision candidates without keeping known-weak Arabic models first."""
    model = (configured_model or "").strip()
    if not model or model == "nvidia/nemotron-3.5-super-vl:free":
        return list(OPENROUTER_FREE_VISION_FALLBACKS)
    return [model] + [m for m in OPENROUTER_FREE_VISION_FALLBACKS if m != model]


def _extract_openai_message_text(choice: Dict[str, Any]) -> str:
    """Extract text content cleanly, falling back to reasoning JSON if content is empty."""
    msg = choice.get("message") or {}
    content = msg.get("content", "")
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    text = str(content or "").strip()
    if text:
        return text
    reasoning = str(msg.get("reasoning") or msg.get("reasoning_content") or "").strip()
    if "{" in reasoning and "}" in reasoning:
        return reasoning
    return ""


def _post_openai_chat(url: str, api_key: str, payload: Dict[str, Any], timeout: int = 75) -> Dict[str, Any]:
    """POST to OpenAI-compatible /chat/completions endpoint and parse JSON envelope."""
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "MAT-Toolkit/1.46",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def _call_openai_with_meta(
    file_bytes: bytes, mime_type: str, settings: Dict[str, Any], prompt: str
) -> Tuple[str, str]:
    """Invoke OpenAI/OpenRouter Vision endpoint with high detail, temperature 0.0, and fallback retries."""
    if mime_type.lower() == "application/pdf":
        raise ValueError(
            "OpenAI vision does not support direct PDF files. Please upload PNG/JPG images or switch to Gemini."
        )

    model = settings.get("model_name") or _default_model_for_provider("openai")
    api_key = settings.get("api_key", "").strip()
    if not api_key:
        raise ValueError("OpenAI API key is required")

    base_url = _resolve_openai_base_url(settings.get("api_base_url"), api_key)
    url = f"{base_url}/chat/completions"
    is_openrouter = _is_openrouter_endpoint(base_url)
    is_nvidia_nim = _is_nvidia_nim_endpoint(base_url)
    is_free_openrouter = is_openrouter and (
        model.endswith(":free") or model == "openrouter/free"
    )

    b64_data = base64.b64encode(file_bytes).decode("ascii")

    def _build_payload(
        use_response_format: bool,
        use_high_detail: bool,
        use_openrouter_routing: bool,
        use_reasoning_disable: bool,
        use_freq_penalty: bool,
    ) -> Dict[str, Any]:
        image_obj: Dict[str, Any] = {"url": f"data:{mime_type};base64,{b64_data}"}
        if use_high_detail:
            image_obj["detail"] = "high"

        payload: Dict[str, Any] = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": image_obj},
                    ],
                }
            ],
            "temperature": 0.1 if is_free_openrouter else 0.0,
            "max_tokens": 4096,
        }
        if use_openrouter_routing:
            candidates = _resolve_openrouter_vision_models(model)
            payload["model"] = candidates[0]
            payload["models"] = candidates
        if use_reasoning_disable:
            payload["reasoning"] = {"enabled": False}
        if use_freq_penalty:
            payload["frequency_penalty"] = 0.2
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        return payload

    # NVIDIA NIM Gemma 4 stalls when response_format=json_object or image_url.detail=high is sent
    use_rf = not is_nvidia_nim
    use_detail = not is_nvidia_nim
    use_or_models = is_free_openrouter
    use_no_reason = is_free_openrouter
    use_freq_penalty = is_free_openrouter
    req_timeout = 95 if is_nvidia_nim else 75

    resp_json: Dict[str, Any] = {}
    for _attempt in range(6):
        try:
            payload = _build_payload(use_rf, use_detail, use_or_models, use_no_reason, use_freq_penalty)
            resp_json = _post_openai_chat(url, api_key, payload, timeout=req_timeout)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):
                err_detail = _format_http_error(exc, api_key)
                low = err_detail.lower()
                changed = False
                if use_rf and (
                    exc.code == 404
                    or "response_format" in low
                    or "json_object" in low
                    or "structured" in low
                ):
                    use_rf = False
                    changed = True
                if use_detail and "detail" in low:
                    use_detail = False
                    changed = True
                if use_no_reason and "reasoning" in low:
                    use_no_reason = False
                    changed = True
                if use_freq_penalty and "frequency_penalty" in low:
                    use_freq_penalty = False
                    changed = True
                if use_or_models and "models" in low:
                    use_or_models = False
                    changed = True
                if changed:
                    continue
                raise urllib.error.HTTPError(exc.url, exc.code, err_detail, exc.headers, None) from None
            raise

    choices = resp_json.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI API returned no choices")

    routed_model = str(resp_json.get("model") or model).strip() or model
    return _extract_openai_message_text(choices[0]), routed_model


def _call_openai(file_bytes: bytes, mime_type: str, settings: Dict[str, Any], prompt: str) -> str:
    """Invoke OpenAI Vision endpoint with Bearer auth and base64 image data URI."""
    content, _routed = _call_openai_with_meta(file_bytes, mime_type, settings, prompt)
    return content


def _call_ollama(file_bytes: bytes, mime_type: str, settings: Dict[str, Any], prompt: str) -> str:
    """Invoke local or remote Ollama vision API (/api/chat)."""
    model = settings.get("model_name") or _default_model_for_provider("ollama")
    base_url = (settings.get("api_base_url") or "http://localhost:11434").rstrip("/")
    url = f"{base_url}/api/chat"

    b64_data = base64.b64encode(file_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [b64_data],
            }
        ],
        "format": "json",
        "stream": False,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=90) as resp:
        body = resp.read().decode("utf-8")

    resp_json = json.loads(body)
    message = resp_json.get("message") or {}
    return message.get("content", "")


_FOREIGN_SCRIPT_RE = re.compile(
    r"[\u4e00-\u9fff\u3040-\u30ff\u0400-\u04ff\uac00-\ud7af]|[A-Za-z]{2,}"
)


def _has_foreign_script_noise(parsed: Dict[str, Any]) -> bool:
    """Detect leaked English, CJK, Kana, or Cyrillic tokens inside Arabic extracted fields."""
    if not isinstance(parsed, dict):
        return False
    texts: List[str] = []
    for key in (
        "subject",
        "summary",
        "police_necessity_reason",
        "ai_analysis",
        "ai_solution_recommendation",
    ):
        val = parsed.get(key)
        if isinstance(val, str) and val.strip():
            texts.append(val)
    for list_key in ("complainants", "respondents"):
        rows = parsed.get(list_key)
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    for fkey in ("name", "address"):
                        v = row.get(fkey)
                        if isinstance(v, str) and v.strip():
                            texts.append(v)
    combined = "\n".join(texts)
    return bool(_FOREIGN_SCRIPT_RE.search(combined))


def _lock_verified_digits(orig_parsed: Dict[str, Any], repaired_parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure Stage 2 text repair never mutates extracted numeric IDs, phones, or dates."""
    if not isinstance(orig_parsed, dict) or not isinstance(repaired_parsed, dict):
        return repaired_parsed

    merged = dict(repaired_parsed)
    orig_ext, _ = _normalize_complaint_result(orig_parsed)

    orig_date = orig_ext.get("paper_date") or ""
    if len(re.sub(r"\D", "", orig_date)) >= 4:
        merged["paper_date"] = orig_date

    for list_key in ("complainants", "respondents"):
        orig_rows = orig_ext.get(list_key) or []
        rep_rows = merged.get(list_key)
        if not isinstance(rep_rows, list) or not orig_rows:
            merged[list_key] = orig_rows
            continue
        locked_rows = []
        for idx, rep_row in enumerate(rep_rows):
            row_copy = dict(rep_row) if isinstance(rep_row, dict) else {}
            if idx < len(orig_rows):
                o_row = orig_rows[idx]
                for num_key in ("national_id", "phone"):
                    o_val = _normalize_arabic_digits(o_row.get(num_key))
                    if len(re.sub(r"\D", "", o_val)) >= 6:
                        row_copy[num_key] = o_val
            locked_rows.append(row_copy)
        merged[list_key] = locked_rows
    return merged


def _repair_mixed_script_ocr_json(
    parsed: Dict[str, Any], settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], str]:
    """Clean leaked non-Arabic OCR tokens via a pure-Arabic text LLM while locking numeric IDs."""
    base_url = (settings.get("api_base_url") or "").rstrip("/")
    api_key = str(settings.get("api_key") or "").strip()
    if not base_url or not api_key or not _is_openrouter_endpoint(base_url):
        return parsed, ""

    cleanup_prompt = (
        "أنت مدقق لغوي وقانوني أردني في متصرفية لواء قصبة عمان.\n"
        "البيانات التالية مُفرّغة آلياً (OCR) من نموذج شكوى وقد تحتوي على كلمات أجنبية أو رموز دخيلة تسللت مكان كلمات عربية قريبة من السياق:\n"
        f"{json.dumps(parsed, ensure_ascii=False)}\n\n"
        "التعليمات الإلزامية:\n"
        "1) صحّح فقط الكلمات الأجنبية أو المشوشة في الحقول النصية لتصبح عربية سليمة ومطابقة لسياق الشكوى تماماً دون اختراع وقائع غير موجودة.\n"
        "2) حافظ على جميع الأسماء والأرقام الوطنية وأرقام الهواتف والتواريخ كما هي حرفياً دون تغيير أي رقم.\n"
        "3) إذا ورد في النص إقرار مثل (أقر بعدم وجود قضية منظورة أمام المحاكم... نعم / ✓) اجعل `no_pending_lawsuit_declared` قيمتها `true`.\n"
        "4) اكتب `police_necessity_reason` و`ai_analysis` و`ai_solution_recommendation` باللغة العربية الفصحى الرسمية فقط.\n"
        "5) التزم في `ai_recommended_action` بأحد الخيارات الأربعة فقط: "
        "'توديع عن طريق مركز أمني' أو 'اتصال هاتفي' أو 'توديع مغفور' أو 'حفظ / توجيه للقضاء المختص'.\n"
        "6) أعد كائن JSON صالحاً فقط بنفس المفاتيح بدون أي نص خارجه."
    )

    payload = {
        "model": OPENROUTER_FREE_TEXT_CLEANUP_MODELS[0],
        "models": list(OPENROUTER_FREE_TEXT_CLEANUP_MODELS),
        "reasoning": {"enabled": False},
        "messages": [{"role": "user", "content": cleanup_prompt}],
        "temperature": 0.0,
        "max_tokens": 3072,
    }
    try:
        resp_json = _post_openai_chat(f"{base_url}/chat/completions", api_key, payload, timeout=45)
        choices = resp_json.get("choices") or []
        if not choices:
            return parsed, ""
        text = _extract_openai_message_text(choices[0])
        repaired = _parse_llm_json(text)
        if not repaired or not isinstance(repaired, dict):
            return parsed, ""
        return _lock_verified_digits(parsed, repaired), text
    except Exception:
        return parsed, ""


def _get_fallback_openai_settings(primary_settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build secondary OpenAI-compatible settings from MAT_FALLBACK_* env vars if configured."""
    fb_key = os.environ.get("MAT_FALLBACK_OPENAI_API_KEY", "").strip()
    if not fb_key:
        return None
    primary_key = str(primary_settings.get("api_key") or "").strip()
    fb_base = os.environ.get("MAT_FALLBACK_OPENAI_BASE_URL", "").strip()
    fb_model = os.environ.get("MAT_FALLBACK_LLM_MODEL", "").strip()
    if not fb_model:
        resolved_base = _resolve_openai_base_url(fb_base, fb_key)
        if _is_openrouter_endpoint(resolved_base):
            fb_model = OPENROUTER_FREE_VISION_FALLBACKS[0]
        elif _is_nvidia_nim_endpoint(resolved_base):
            fb_model = "google/gemma-4-31b-it"
        elif "api.groq.com" in resolved_base.lower():
            fb_model = "meta-llama/llama-4-scout-17b-16e-instruct"
        else:
            fb_model = _default_model_for_provider("openai")
    if fb_key == primary_key and fb_model == str(primary_settings.get("model_name") or "").strip():
        return None
    return {
        "provider": "openai",
        "model_name": fb_model,
        "api_base_url": fb_base,
        "api_key": fb_key,
        "is_enabled": 1,
    }


def _extract_with_single_provider(
    file_bytes: bytes, mime_type: str, settings: Dict[str, Any]
) -> Tuple[Dict[str, Any], bool]:
    """Execute one provider attempt and return (result_dict, is_retriable_failure)."""
    provider = str(settings.get("provider") or "gemini").lower()
    model = settings.get("model_name") or _default_model_for_provider(provider)
    api_key = str(settings.get("api_key") or "").strip()

    raw_text = ""
    effective_model = model
    try:
        if provider == "gemini":
            raw_text = _call_gemini(file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT)
        elif provider == "openai":
            raw_text, effective_model = _call_openai_with_meta(
                file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT
            )
        elif provider == "ollama":
            raw_text = _call_ollama(file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT)
        else:
            return (
                {
                    "status": "manual_fallback",
                    "provider": provider,
                    "model": model,
                    "extracted": {},
                    "analysis": {},
                    "raw_text": "",
                    "message": f"Unsupported LLM provider: '{provider}'",
                },
                False,
            )

        parsed = _parse_llm_json(raw_text)
        if not parsed:
            return (
                {
                    "status": "manual_fallback",
                    "provider": provider,
                    "model": effective_model,
                    "extracted": {},
                    "analysis": {},
                    "raw_text": raw_text,
                    "message": "LLM output could not be parsed as structured JSON",
                },
                True,
            )

        if provider == "openai" and _has_foreign_script_noise(parsed):
            repaired_parsed, repaired_raw = _repair_mixed_script_ocr_json(parsed, settings)
            if repaired_raw:
                parsed = repaired_parsed
                raw_text = repaired_raw

        extracted, analysis = _normalize_complaint_result(parsed)

        return (
            {
                "status": "ok",
                "provider": provider,
                "model": effective_model,
                "extracted": extracted,
                "analysis": analysis,
                "raw_text": raw_text,
                "message": "Extraction and analysis completed successfully",
            },
            False,
        )
    except urllib.error.HTTPError as e:
        err_msg = _format_http_error(e, api_key)
        return (
            {
                "status": "manual_fallback",
                "provider": provider,
                "model": effective_model,
                "extracted": {},
                "analysis": {},
                "raw_text": raw_text,
                "message": f"Extraction error: {err_msg}",
            },
            True,
        )
    except Exception as e:
        err_msg = _redact_secret(str(e), api_key)
        return (
            {
                "status": "manual_fallback",
                "provider": provider,
                "model": effective_model,
                "extracted": {},
                "analysis": {},
                "raw_text": raw_text,
                "message": f"Extraction error: {err_msg}",
            },
            True,
        )


def extract_and_analyze_complaint(
    file_bytes: bytes, mime_type: str, settings: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute LLM Vision extraction & legal-administrative analysis with graceful fallback."""
    provider = str(settings.get("provider") or "gemini").lower()
    model = settings.get("model_name") or _default_model_for_provider(provider)
    is_enabled = settings.get("is_enabled", 1)

    if not is_enabled:
        return {
            "status": "manual_fallback",
            "provider": provider,
            "model": model,
            "extracted": {},
            "analysis": {},
            "raw_text": "",
            "message": "LLM engine is disabled",
        }

    api_key = str(settings.get("api_key") or "").strip()
    if provider in ("gemini", "openai") and not api_key:
        fb_settings = _get_fallback_openai_settings(settings)
        if fb_settings:
            fb_res, _ = _extract_with_single_provider(file_bytes, mime_type, fb_settings)
            return fb_res
        return {
            "status": "manual_fallback",
            "provider": provider,
            "model": model,
            "extracted": {},
            "analysis": {},
            "raw_text": "",
            "message": f"API key not configured for provider '{provider}'",
        }

    result, retriable = _extract_with_single_provider(file_bytes, mime_type, settings)
    if retriable:
        fb_settings = _get_fallback_openai_settings(settings)
        if fb_settings:
            fb_res, _ = _extract_with_single_provider(file_bytes, mime_type, fb_settings)
            if fb_res.get("status") == "ok":
                return fb_res
    return result


def test_llm_connection(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Test connectivity and credentials for the specified provider."""
    is_enabled = settings.get("is_enabled", 1)
    if not is_enabled:
        return {"ok": False, "message": "LLM engine is currently disabled"}

    provider = str(settings.get("provider") or "gemini").lower()
    model = settings.get("model_name") or _default_model_for_provider(provider)
    api_key = str(settings.get("api_key") or "").strip()

    if provider in ("gemini", "openai") and not api_key:
        return {"ok": False, "message": f"API key not configured for provider '{provider}'"}

    try:
        if provider == "gemini":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            payload = {
                "contents": [{"parts": [{"text": "ping"}]}],
                "generationConfig": {"maxOutputTokens": 5},
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "x-goog-api-key": api_key,
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                if isinstance(status, int) and not (200 <= status < 300):
                    return {"ok": False, "message": f"Unexpected status {status}", "provider": provider}
                raw_body = resp.read()
                try:
                    parsed_body = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else {}
                except Exception:
                    parsed_body = {}
                if not isinstance(parsed_body, dict) or not parsed_body.get("candidates"):
                    return {
                        "ok": False,
                        "message": "Endpoint did not return valid Gemini candidates JSON",
                        "provider": provider,
                    }
                return {
                    "ok": True,
                    "message": "اتصال مزود Gemini ناجح",
                    "provider": provider,
                    "model": model,
                }
        elif provider == "openai":
            base_url = _resolve_openai_base_url(settings.get("api_base_url"), api_key)
            url = f"{base_url}/chat/completions"
            is_openrouter = _is_openrouter_endpoint(base_url)
            is_nvidia_nim = _is_nvidia_nim_endpoint(base_url)
            is_free_or = is_openrouter and (model.endswith(":free") or model == "openrouter/free")
            payload: Dict[str, Any] = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 16 if is_free_or else 5,
            }
            if is_free_or:
                candidates = _resolve_openrouter_vision_models(model)
                payload["model"] = candidates[0]
                payload["models"] = candidates
                payload["reasoning"] = {"enabled": False}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    "User-Agent": "MAT-Toolkit/1.46",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15 if (is_free_or or is_nvidia_nim) else 10) as resp:
                status = getattr(resp, "status", 200)
                if isinstance(status, int) and not (200 <= status < 300):
                    return {"ok": False, "message": f"Unexpected status {status}", "provider": provider}
                raw_body = resp.read()
                try:
                    parsed_body = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else {}
                except Exception:
                    parsed_body = {}
                if not isinstance(parsed_body, dict) or not parsed_body.get("choices"):
                    return {
                        "ok": False,
                        "message": "Endpoint did not return valid AI completion JSON (check Base URL / model / retired endpoint)",
                        "provider": provider,
                    }
                resolved_model = str(parsed_body.get("model") or model).strip() or model
                return {
                    "ok": True,
                    "message": "اتصال مزود OpenAI ناجح",
                    "provider": provider,
                    "model": resolved_model,
                }
        elif provider == "ollama":
            base_url = (settings.get("api_base_url") or "http://localhost:11434").rstrip("/")
            url = f"{base_url}/api/tags"
            req = urllib.request.Request(
                url,
                headers={"Content-Type": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                if isinstance(status, int) and not (200 <= status < 300):
                    return {"ok": False, "message": f"Unexpected status {status}", "provider": provider}
                raw_body = resp.read()
                try:
                    parsed_body = json.loads(raw_body.decode("utf-8", errors="replace")) if raw_body else {}
                except Exception:
                    parsed_body = {}
                if not isinstance(parsed_body, dict) or "models" not in parsed_body:
                    return {
                        "ok": False,
                        "message": "Endpoint did not return valid Ollama /api/tags JSON",
                        "provider": provider,
                    }
                return {
                    "ok": True,
                    "message": "اتصال مزود Ollama ناجح",
                    "provider": provider,
                    "model": model,
                }
        else:
            return {"ok": False, "message": f"Unsupported provider: '{provider}'"}

        return {"ok": False, "message": f"Unexpected response from provider '{provider}'"}
    except urllib.error.HTTPError as e:
        err_msg = _format_http_error(e, api_key)
        return {
            "ok": False,
            "message": f"Connection error: {err_msg}",
            "provider": provider,
        }
    except Exception as e:
        err_msg = _redact_secret(str(e), api_key)
        return {
            "ok": False,
            "message": f"Connection error: {err_msg}",
            "provider": provider,
        }
