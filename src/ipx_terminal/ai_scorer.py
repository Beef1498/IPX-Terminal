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


def _fallback_brief_template(
    signal: Dict[str, Any],
    target_platform: str,
    project: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Deterministic anti-slop editable draft brief when no AI API key is configured."""
    ent = (signal.get("entities_mentioned") or [signal["ticker"]])[0]
    sample = (signal.get("samples") or [signal["title"]])[0].strip("'\"")
    if project:
        from ipx_terminal.projects import rank_catalog_tracks_for_signal

        ranked = rank_catalog_tracks_for_signal(project, signal, limit=1)
        track = ranked[0] if ranked else None
        proj_name = str(project.get("name") or project.get("id") or "Client Project")
        if track:
            artist = track.get("artist") or proj_name
            title = track.get("title") or "Priority Track"
            clip_ts = track.get("clip_timestamp") or "chorus drop"
            sound_cue = track.get("sound_cue") or f"Drop {artist} — '{title}' at {clip_ts}."
            faceless = str(project.get("production_mode") or "") == "faceless_at_scale"
            prod_fmt = "clip_flip_meme" if faceless else "standard_short"
            asset_recipe = (
                f"Source existing viral {ent} / anime / street-car clip or WhatsApp POV screenshot (zero IRL filming); "
                f"drop into CapCut beat-sync template and cut hard on '{title}' ({clip_ts})."
                if faceless
                else ""
            )
            return {
                "model_used": "template_draft",
                "target_platform": target_platform,
                "project_id": project.get("id"),
                "matched_track": f"{artist} — {title}",
                "production_format": prod_fmt,
                "asset_recipe": asset_recipe,
                "angle": f"[{proj_name} · {prod_fmt}] Faceless audio-flip '{title}' ({artist}) onto the {ent} format"
                if faceless
                else f"[{proj_name}] Audio-flip '{title}' ({artist}) onto the {ent} format",
                "hook_2s": (
                    f"Faceless cold open on viral {ent} clip / screenshot (0.0-1.5s) cutting straight into '{title}' at {clip_ts}."
                    if faceless
                    else f"Cold open on relatable {ent} POV setup (0.0-1.5s) cutting straight into '{title}' at {clip_ts}."
                ),
                "on_screen_text": f"POV: cuando pasa esto y suena {title}...",
                "caption": f"{sample[:95]} — {artist} '{title}' ({proj_name})",
                "edit_beats": [
                    f"0.0-1.8s: [{prod_fmt}] Found-clip / AI-visual scroll-stop + Spanish/Spanglish POV text lock",
                    f"1.8-5.0s: Build tension with rapid 0.8s cuts right before '{title}' ({clip_ts}) hits",
                    f"5.0-9.0s: Beat-drop punchline synced to {artist} — '{title}' for 'Use This Sound' remakes",
                    "9.0-11.0s: Clean seamless loop back into frame 1 (no filming, 100% replicable at scale)",
                ],
                "audio_cue": f"{artist} — '{title}' [{clip_ts}]: {sound_cue}",
            }
    return {
        "model_used": "template_draft",
        "target_platform": target_platform,
        "angle": f"Fast-turnaround cultural reaction to {ent} ({signal['sector']})",
        "hook_2s": f"Cold open directly on the visual contrast / punchline for {ent} (zero intro, first cut at 1.2s).",
        "on_screen_text": f"Nobody is talking about what just happened with {ent}...",
        "caption": f"{sample[:110]} — are we early or is this already everywhere?",
        "edit_beats": [
            "0.0-1.8s: Visual pattern-interrupt + on-screen text lock",
            "1.8-5.5s: Core cultural reference / receipt frame (fast 1.2s cuts)",
            "5.5-9.5s: Punchline or unexpected twist that triggers re-watch/shares",
            "9.5-11.0s: Seamless loop back into frame 1 (no 'like and follow' outro)",
        ],
        "audio_cue": f"Match native {target_platform} trending sound or clean deadpan voiceover.",
    }


def generate_creative_brief(
    signal: Dict[str, Any],
    target_platform: str = "TikTok",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    timeout: int = 45,
    project: Optional[Dict[str, Any]] = None,
    timeline_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a native, anti-slop Creative Brief from a t_0 signal (falls back to draft template if no key)."""
    creds = resolve_ai_credentials(api_key=api_key, base_url=base_url, model=model)
    if not creds["api_key"] and "generativelanguage.googleapis.com" in creds["base_url"]:
        return _fallback_brief_template(signal, target_platform, project=project)

    project_block = ""
    top_track_label = ""
    if project:
        from ipx_terminal.projects import rank_catalog_tracks_for_signal

        candidates = rank_catalog_tracks_for_signal(project, signal, limit=3)
        if candidates:
            top_track_label = f"{candidates[0].get('artist', '')} — {candidates[0].get('title', '')}".strip(" —")
        compact_tracks = [
            {
                "artist": t.get("artist"),
                "title": t.get("title"),
                "status": t.get("status"),
                "clip_timestamp": t.get("clip_timestamp"),
                "hook_lyric": t.get("hook_lyric"),
                "vibe_tags": t.get("vibe_tags"),
                "sound_cue": t.get("sound_cue"),
            }
            for t in candidates
        ]
        prod_constraints = project.get("production_constraints") or {}
        faceless_rules = ""
        if str(project.get("production_mode") or "") == "faceless_at_scale" or prod_constraints:
            faceless_rules = (
                f"PRODUCTION CONSTRAINT (STRICT — FACELESS AT SCALE): We run faceless accounts at scale with NO physical "
                f"on-camera person or IRL filming crew. Allowed formats ONLY: {prod_constraints.get('allowed_formats')}. "
                f"BANNED: {prod_constraints.get('banned_formats')} (never suggest filming a person, GRWM camera shoot, or IRL actors). "
                f"Visual sources: {prod_constraints.get('visual_sources')}\n"
                "Also return two extra JSON keys: 'production_format' (one of the allowed_formats) and "
                "'asset_recipe' (exact online clip/meme search query, WhatsApp/carousel layout, OR ready-to-paste AI video/image prompt "
                "so an editor can produce 10 variations in minutes).\n"
            )
        project_block = (
            f"\nClient Project: {project.get('name')} (Label: {project.get('label_name')})\n"
            f"Languages / Voice: {project.get('languages')} | {project.get('brand_voice')}\n"
            f"Target US/MX Geos: {project.get('target_geos')}\n"
            f"{faceless_rules}"
            f"Best-Fit Client Catalog Tracks to Seed:\n{json.dumps(compact_tracks, ensure_ascii=False)}\n"
            "IMPORTANT: Pick the single strongest matching track from the Client Catalog above, localize/adapt "
            "the trend format natively into the client's voice (Spanish or natural Spanglish), and put the exact "
            "track title, artist, and clip_timestamp inside 'audio_cue' so creators can immediately replicate it.\n"
        )

    system_prompt = (
        "You are an elite viral short-form creative director & music trend strategist for TikTok, Instagram Reels, "
        "YouTube Shorts, and X. Our core goal for music clients is SONG-SEEDING & TREND CREATION: designing "
        "replicable POV, meme, CapCut-template, or reaction formats that put a client's song behind the video "
        "so viewers tap 'Use This Sound' and make their own versions. Never write corporate/AI-sounding hooks, "
        "cringe emojis, or generic 'Wait until the end!' clickbait. Return STRICT JSON with keys: "
        "'angle' (string: replicable trend/POV format concept), "
        "'hook_2s' (string: 0.0-2.0s visual/audio scroll-stop), "
        "'on_screen_text' (string, <=12 words, relatable template text viewers can copy), "
        "'caption' (string, native & share-triggering), "
        "'edit_beats' (list of 3-4 concise timed beat strings including exact beat-drop/chorus hit), and "
        "'audio_cue' (string: exact song placement, beat-drop timing, and why viewers will click 'Use This Sound')."
    )
    timeline_block = ""
    if timeline_context:
        season = timeline_context.get("current_season") or {}
        waves = timeline_context.get("seed_now_waves") or []
        cities = timeline_context.get("priority_spotify_cities_now") or []
        timeline_block = (
            f"\nActive Cultural Seeding Window ({timeline_context.get('reference_date', '')}):\n"
            f"- Seasonal Mood / Weather: {season.get('label', '')} ({season.get('collective_mood', '')})\n"
            f"- Priority Spotify/Billboard Cities Now: {', '.join(cities)}\n"
            f"- Upcoming Pre-Wave Anchors: {json.dumps(waves[:3], ensure_ascii=False)}\n"
            "If relevant, tie the video angle/hook subtly into the active seasonal mood or upcoming holiday/event wave.\n"
        )

    user_prompt = (
        f"Target Platform: {target_platform}\n"
        f"IP Ticker: {signal['ticker']} ({signal['sector']})\n"
        f"Signal Title: {signal['title']}\n"
        f"t_0 Summary: {signal['summary']}\n"
        f"Verbatim Samples: {json.dumps(signal.get('samples', []), ensure_ascii=False)}\n"
        f"Metrics: {json.dumps(signal.get('metrics', {}), ensure_ascii=False)}\n"
        f"{timeline_block}"
        f"{project_block}\n"
        "Create a sharp, native creative brief that could realistically break out on this platform."
    )
    payload = {
        "model": creds["model"],
        "temperature": 0.65,
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
        parsed = _extract_json_object(raw_resp["choices"][0]["message"]["content"])
        beats = parsed.get("edit_beats") or []
        if not isinstance(beats, list):
            beats = [str(beats)]
        out = {
            "model_used": creds["model"],
            "target_platform": target_platform,
            "angle": str(parsed.get("angle", "")).strip(),
            "hook_2s": str(parsed.get("hook_2s", "")).strip(),
            "on_screen_text": str(parsed.get("on_screen_text", "")).strip(),
            "caption": str(parsed.get("caption", "")).strip(),
            "edit_beats": [str(b).strip() for b in beats[:5] if str(b).strip()],
            "audio_cue": str(parsed.get("audio_cue", "")).strip(),
        }
        if project:
            out["project_id"] = project.get("id")
            if top_track_label:
                out["matched_track"] = top_track_label
            if parsed.get("production_format"):
                out["production_format"] = str(parsed.get("production_format")).strip()
            if parsed.get("asset_recipe"):
                out["asset_recipe"] = str(parsed.get("asset_recipe")).strip()
        return out
    except Exception:
        return _fallback_brief_template(signal, target_platform, project=project)
