"""OpenAI-compatible AI scorer for live Human vs. AI t_0 predictions (Gemini API & DGX Spark)."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional
import urllib.error
import urllib.request

from ipx_terminal.config import CATEGORY_LABELS, DEFAULT_QUESTIONS, VALID_CATEGORIES

DEFAULT_AI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_AI_MODEL = "gemini-3.5-flash-lite"


def _strip_thinking(text: str) -> str:
    cleaned = re.sub(r"<(think|thought)>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r"<\|thought\|>.*?<\|/thought\|>", "", cleaned, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def _extract_json_object(raw_text: str) -> Dict[str, Any]:
    cleaned = _strip_thinking(raw_text)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return json.loads(fence.group(1))
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])
    return json.loads(cleaned)


def resolve_ai_credentials(
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, str]:
    resolved_key = (
        (api_key or "").strip()
        or os.environ.get("IPX_AI_API_KEY", "").strip()
        or os.environ.get("GEMINI_API_KEY", "").strip()
        or os.environ.get("OPENAI_API_KEY", "").strip()
    )
    resolved_url = (
        (base_url or "").strip()
        or os.environ.get("IPX_AI_BASE_URL", "").strip()
        or DEFAULT_AI_BASE_URL
    ).rstrip("/")
    resolved_model = (
        (model or "").strip()
        or os.environ.get("IPX_AI_MODEL", "").strip()
        or DEFAULT_AI_MODEL
    )
    return {"api_key": resolved_key, "base_url": resolved_url, "model": resolved_model}


def score_signal_with_ai(
    signal: Dict[str, Any],
    category: str,
    question: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 45,
) -> Dict[str, Any]:
    """Call an OpenAI-compatible endpoint (Gemini API or DGX Spark vLLM/NIM/Ollama) for a t_0 call."""
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Invalid category '{category}'")

    creds = resolve_ai_credentials(api_key=api_key, base_url=base_url, model=model)
    if not creds["api_key"] and "generativelanguage.googleapis.com" in creds["base_url"]:
        raise ValueError(
            "No API key configured. Set GEMINI_API_KEY or IPX_AI_API_KEY (or point IPX_AI_BASE_URL to local DGX Spark)."
        )

    valid_labels = CATEGORY_LABELS[category]
    q_text = (question or DEFAULT_QUESTIONS[category]).strip()
    snapshot = {
        "ticker": signal["ticker"],
        "sector": signal["sector"],
        "title": signal["title"],
        "captured_at": signal["captured_at"],
        "summary": signal["summary"],
        "platforms": signal["platforms"],
        "metrics": signal["metrics"],
        "samples": signal["samples"],
        "entities_mentioned": signal["entities_mentioned"],
    }

    system_prompt = (
        "You are an institutional Content IP & social media intelligence analyst on IPX Terminal. "
        "Evaluate ONLY the t_0 signal snapshot provided. Return STRICT JSON with keys: "
        f"'label' (must be one of {list(valid_labels)}), 'confidence' (float 0.0-1.0), "
        "'key_signals' (list of 2-4 concise strings), and 'reasoning' (2-3 sentences)."
    )
    user_prompt = (
        f"Category: {category}\n"
        f"Allowed labels: {', '.join(valid_labels)}\n"
        f"Question: {q_text}\n\n"
        f"t_0 Signal Snapshot:\n{json.dumps(snapshot, ensure_ascii=False, indent=2)}"
    )

    payload = {
        "model": creds["model"],
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }

    headers = {"Content-Type": "application/json"}
    if creds["api_key"]:
        headers["Authorization"] = f"Bearer {creds['api_key']}"

    req = urllib.request.Request(
        f"{creds['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw_resp = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"AI endpoint HTTP {exc.code}: {detail}") from exc

    content = raw_resp["choices"][0]["message"]["content"]
    parsed = _extract_json_object(content)

    label = str(parsed.get("label", "")).strip()
    if label not in valid_labels:
        raise ValueError(f"Model returned invalid label '{label}' (expected one of {valid_labels})")

    conf_raw = parsed.get("confidence", 0.7)
    confidence = max(0.0, min(1.0, float(conf_raw)))
    reasoning = str(parsed.get("reasoning", "")).strip()
    key_signals = parsed.get("key_signals") or []
    if not isinstance(key_signals, list):
        key_signals = [str(key_signals)]

    return {
        "model": creds["model"],
        "category": category,
        "label": label,
        "confidence": round(confidence, 3),
        "key_signals": [str(x) for x in key_signals[:5]],
        "reasoning": reasoning,
    }
