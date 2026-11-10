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
from typing import Any, Dict, Optional, Tuple

ALLOWED_RECOMMENDED_ACTIONS = [
    "توديع عن طريق مركز أمني",
    "اتصال هاتفي",
    "توديع مغفور",
    "حفظ / توجيه للقضاء المختص",
]

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "ollama": "llama3.2-vision",
}

COMPLAINT_EXTRACTION_PROMPT = """أنت خبير قانوني وإداري ومحلل وثائق رسمي تابع لوزارة الداخلية الأردنية - محافظة العاصمة (متصرفية لواء قصبة عمان).
أمامك صورة أو مستند لاستدعاء / نموذج شكوى خطي رسمي (استمارة الشكوى والمراكز الأمنية).
المطلوب منك تفريغ محتويات الشكوى بدقة متناهية وإجراء تحليل إداري وقانوني للشكوى وتحديد مدى الحاجة لمتابعة المراكز الأمنية.

قم بإرجاع النتيجة حصراً بصيغة JSON نظيفة وصحيحة وبدون أي مقدمات أو شروحات خارج كائن الـ JSON بالهيكل التالي:
{
  "paper_date": "تاريخ تقديم الشكوى المكتوب في الورقة إن وجد",
  "complainants": [
    {
      "party_category": "أحد الخيارات: مواطن أو مؤسسة تجارية أو مؤسسة حكومية",
      "name": "الاسم الكامل للمشتكي",
      "national_id": "الرقم الوطني أو الرقم التجاري",
      "phone": "رقم الهاتف",
      "address": "العنوان بالتفصيل"
    }
  ],
  "respondents": [
    {
      "party_category": "أحد الخيارات: مواطن أو منشأة",
      "name": "اسم المشتكى عليه أو اسم المحل/المنشأة",
      "national_id": "الرقم الوطني إن وجد أو فارغ",
      "phone": "رقم الهاتف",
      "address": "العنوان بالتفصيل"
    }
  ],
  "subject": "موضوع الشكوى بدقة واختصار",
  "summary": "موجز وتفاصيل وقائع الشكوى كما سردها المشتكي",
  "has_signature": true,
  "no_pending_lawsuit_declared": true,
  "is_minor_police_complaint": true,
  "police_necessity_reason": "سبب توجيه الشكوى للمركز الأمني أو سبب حفظها",
  "ai_analysis": "تحليل وقائع الشكوى والتكييف الإداري والقانوني لها",
  "ai_solution_recommendation": "التوصية الإدارية والحل المقترح لإنهاء النزاع وإصلاح ذات البين",
  "ai_recommended_action": "توديع عن طريق مركز أمني",
  "ai_confidence": 0.92
}
الخيارات المسموحة لحقل ai_recommended_action هي حصراً:
1) 'توديع عن طريق مركز أمني'
2) 'اتصال هاتفي'
3) 'توديع مغفور'
4) 'حفظ / توجيه للقضاء المختص'
تأكد من كتابة نصوص عربية سليمة وواضحة والالتزام التام بالخيارات المحددة."""


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
    res = re.sub(r"sk-[A-Za-z0-9_-]{15,}", "[REDACTED]", res)
    return res


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
                complainants.append(
                    {
                        "party_category": cat,
                        "name": str(c.get("name") or "").strip(),
                        "national_id": str(c.get("national_id") or "").strip(),
                        "phone": str(c.get("phone") or "").strip(),
                        "address": str(c.get("address") or "").strip(),
                    }
                )

    respondents_raw = ext_src.get("respondents")
    respondents = []
    if isinstance(respondents_raw, list):
        for r in respondents_raw:
            if isinstance(r, dict):
                cat = str(r.get("party_category") or "مواطن").strip()
                if cat not in ("مواطن", "منشأة"):
                    cat = "مواطن"
                respondents.append(
                    {
                        "party_category": cat,
                        "name": str(r.get("name") or "").strip(),
                        "national_id": str(r.get("national_id") or "").strip(),
                        "phone": str(r.get("phone") or "").strip(),
                        "address": str(r.get("address") or "").strip(),
                    }
                )

    extracted = {
        "paper_date": str(ext_src.get("paper_date") or "").strip(),
        "complainants": complainants,
        "respondents": respondents,
        "subject": str(ext_src.get("subject") or "").strip(),
        "summary": str(ext_src.get("summary") or "").strip(),
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
            "temperature": 0.2,
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


def _call_openai(file_bytes: bytes, mime_type: str, settings: Dict[str, Any], prompt: str) -> str:
    """Invoke OpenAI Vision endpoint with Bearer auth and base64 image data URI."""
    if mime_type.lower() == "application/pdf":
        raise ValueError(
            "OpenAI vision does not support direct PDF files. Please upload PNG/JPG images or switch to Gemini."
        )

    model = settings.get("model_name") or _default_model_for_provider("openai")
    api_key = settings.get("api_key", "").strip()
    if not api_key:
        raise ValueError("OpenAI API key is required")

    base_url = (settings.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
    url = f"{base_url}/chat/completions"

    b64_data = base64.b64encode(file_bytes).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{b64_data}"
                        },
                    },
                ],
            }
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
    }

    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode("utf-8")

    resp_json = json.loads(body)
    choices = resp_json.get("choices") or []
    if not choices:
        raise RuntimeError("OpenAI API returned no choices")

    return choices[0].get("message", {}).get("content", "")


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
        return {
            "status": "manual_fallback",
            "provider": provider,
            "model": model,
            "extracted": {},
            "analysis": {},
            "raw_text": "",
            "message": f"API key not configured for provider '{provider}'",
        }

    raw_text = ""
    try:
        if provider == "gemini":
            raw_text = _call_gemini(file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT)
        elif provider == "openai":
            raw_text = _call_openai(file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT)
        elif provider == "ollama":
            raw_text = _call_ollama(file_bytes, mime_type, settings, COMPLAINT_EXTRACTION_PROMPT)
        else:
            return {
                "status": "manual_fallback",
                "provider": provider,
                "model": model,
                "extracted": {},
                "analysis": {},
                "raw_text": "",
                "message": f"Unsupported LLM provider: '{provider}'",
            }

        parsed = _parse_llm_json(raw_text)
        if not parsed:
            return {
                "status": "manual_fallback",
                "provider": provider,
                "model": model,
                "extracted": {},
                "analysis": {},
                "raw_text": raw_text,
                "message": "LLM output could not be parsed as structured JSON",
            }

        extracted, analysis = _normalize_complaint_result(parsed)

        return {
            "status": "ok",
            "provider": provider,
            "model": model,
            "extracted": extracted,
            "analysis": analysis,
            "raw_text": raw_text,
            "message": "Extraction and analysis completed successfully",
        }
    except Exception as e:
        err_msg = _redact_secret(str(e), api_key)
        return {
            "status": "manual_fallback",
            "provider": provider,
            "model": model,
            "extracted": {},
            "analysis": {},
            "raw_text": raw_text,
            "message": f"Extraction error: {err_msg}",
        }


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
                return {
                    "ok": True,
                    "message": "اتصال مزود Gemini ناجح",
                    "provider": provider,
                    "model": model,
                }
        elif provider == "openai":
            base_url = (settings.get("api_base_url") or "https://api.openai.com/v1").rstrip("/")
            url = f"{base_url}/chat/completions"
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 5,
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = getattr(resp, "status", 200)
                if isinstance(status, int) and not (200 <= status < 300):
                    return {"ok": False, "message": f"Unexpected status {status}", "provider": provider}
                return {
                    "ok": True,
                    "message": "اتصال مزود OpenAI ناجح",
                    "provider": provider,
                    "model": model,
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
                return {
                    "ok": True,
                    "message": "اتصال مزود Ollama ناجح",
                    "provider": provider,
                    "model": model,
                }
        else:
            return {"ok": False, "message": f"Unsupported provider: '{provider}'"}

        return {"ok": False, "message": f"Unexpected response from provider '{provider}'"}
    except Exception as e:
        err_msg = _redact_secret(str(e), api_key)
        return {
            "ok": False,
            "message": f"Connection error: {err_msg}",
            "provider": provider,
        }
