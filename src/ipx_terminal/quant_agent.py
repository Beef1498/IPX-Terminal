"""Autonomous Gemini Quant Agent for IPX Terminal (Morning Routine + Intraday Scout)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request

from ipx_terminal.ai_scorer import DEFAULT_AI_BASE_URL, _extract_json_object, resolve_ai_credentials
from ipx_terminal.config import CATEGORY_LABELS, DEFAULT_QUESTIONS, VALID_CATEGORIES, VALID_SECTORS
from ipx_terminal.db import TerminalDB, utc_now_iso
from ipx_terminal.ingest import fetch_prediction_markets, fetch_us_contagion_map, recheck_overdue_predictions
from ipx_terminal.quant import build_quant_workspace

DEFAULT_MORNING_MODEL = "gemini-2.5-pro"
DEFAULT_INTRADAY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_MEMOS_DIR = Path(__file__).resolve().parents[2] / "data" / "quant_memos"


def _resolve_quant_api_key(api_key: Optional[str] = None) -> str:
    """Resolve Gemini/AI API key from args, env, or sibling IPX-Eval/.env."""
    creds = resolve_ai_credentials(api_key=api_key)
    if creds["api_key"]:
        return creds["api_key"]
    sibling_env = Path(__file__).resolve().parents[3] / "IPX-Eval" / ".env"
    if sibling_env.exists():
        for raw_line in sibling_env.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() in ("GEMINI_API_KEY", "IPX_AI_API_KEY", "OPENAI_API_KEY"):
                val = v.strip().strip('"').strip("'")
                if val:
                    return val
    return ""


def _call_gemini_quant_llm(
    system_prompt: str,
    user_prompt: str,
    model: str,
    api_key: str,
    base_url: str = DEFAULT_AI_BASE_URL,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Call Gemini OpenAI-compatible chat completions endpoint and parse strict JSON."""
    payload = {
        "model": model,
        "temperature": 0.15,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        err_txt = exc.read().decode("utf-8", errors="replace")[:350]
        raise RuntimeError(f"Gemini Quant HTTP {exc.code} ({model}): {err_txt}") from exc
    except Exception as exc:
        raise RuntimeError(f"Gemini Quant connection failed ({model}): {exc}") from exc

    choices = body.get("choices") or []
    if not choices:
        raise RuntimeError("Gemini Quant returned no choices")
    raw_content = str((choices[0].get("message") or {}).get("content") or "").strip()
    return _extract_json_object(raw_content)


def list_quant_memos(memos_dir: Optional[Path] = None, limit: int = 12) -> List[Dict[str, Any]]:
    """Return recent persisted Gemini Quant memos sorted newest-first."""
    mdir = memos_dir or DEFAULT_MEMOS_DIR
    if not mdir.exists():
        return []
    files = sorted(mdir.glob("*.json"), reverse=True)[: max(1, limit)]
    out: List[Dict[str, Any]] = []
    for path in files:
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def _render_memo_markdown(memo: Dict[str, Any]) -> str:
    lines = [
        f"# IPX Gemini Quant Memo — {memo['mode'].upper()} ({memo['created_at']})",
        f"**Model:** `{memo['model_used']}` | **Dry Run:** `{memo['dry_run']}`",
        "",
        f"## {memo.get('headline', 'Daily Quant Summary')}",
        memo.get("executive_summary", ""),
        "",
        "## Top Actionable Signals",
    ]
    for sig in memo.get("top_signals") or []:
        lines.append(
            f"- **{sig.get('ticker', '?')}** ({sig.get('signal_flag', 'WATCH')}): {sig.get('thesis', '')}"
        )
    if memo.get("actions_taken"):
        lines.extend(["", "## Autonomous Actions Executed"])
        for act in memo["actions_taken"]:
            lines.append(f"- {act}")
    if memo.get("vcrm_actions"):
        lines.extend(["", "## VCRM Gate Action Items"])
        for v in memo["vcrm_actions"]:
            lines.append(f"- {v}")
    return "\n".join(lines).strip() + "\n"


def run_gemini_quant(
    db: TerminalDB,
    mode: str = "morning",
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    dry_run: bool = False,
    fetch_live: bool = True,
    max_calls: int = 2,
    memos_dir: Optional[Path] = None,
    llm_caller: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Run the autonomous Gemini Quant routine (Morning Pro or Intraday Flash-Lite).

    Guardrail (Adam Taylor VCRM rule): Gemini may freeze t_0 signals and log t_0
    predictions, but NEVER fabricates 48-72h outcomes. Outcomes are only resolved
    from real-world metrics or human adjudication.
    """
    norm_mode = "intraday" if str(mode).strip().lower() == "intraday" else "morning"
    resolved_model = (
        (model or "").strip()
        or (os.environ.get("IPX_QUANT_FAST_MODEL", "").strip() if norm_mode == "intraday" else os.environ.get("IPX_QUANT_MODEL", "").strip())
        or (DEFAULT_INTRADAY_MODEL if norm_mode == "intraday" else DEFAULT_MORNING_MODEL)
    )
    creds = resolve_ai_credentials(api_key=api_key, base_url=base_url, model=resolved_model)
    resolved_key = _resolve_quant_api_key(api_key=api_key)
    resolved_url = creds["base_url"]

    if llm_caller is None and not resolved_key and "generativelanguage.googleapis.com" in resolved_url:
        raise ValueError(
            "No GEMINI_API_KEY configured. Add GEMINI_API_KEY=... to IPX Terminal/.env (or set IPX_AI_API_KEY)."
        )

    actions_taken: List[str] = []
    recheck_summary: Dict[str, Any] = {"overdue_count": 0, "checked_count": 0}

    # 1. Clear/recheck overdue 48-72h calls first (deterministic real-world fetch)
    if fetch_live and not dry_run:
        try:
            recheck_summary = recheck_overdue_predictions(db=db)
            if recheck_summary.get("checked_count"):
                actions_taken.append(
                    f"Auto-rechecked {recheck_summary['checked_count']} overdue 48-72h call(s) via live metrics."
                )
        except Exception as exc:
            actions_taken.append(f"Overdue recheck skipped: {exc}")

    # 2. Build live workspace snapshot (Quant Screener + 8-Gate VCRM + Markets + US Map)
    quant_ws = build_quant_workspace(db, include_vcrm=True)
    markets_data: List[Dict[str, Any]] = []
    map_clusters: List[Dict[str, Any]] = []
    if fetch_live:
        try:
            mkts = fetch_prediction_markets(source="all", ip_only=True, live_odds_only=True, limit=12)
            markets_data = [
                {
                    "id": m.get("id"),
                    "source": m.get("source"),
                    "sector": m.get("sector"),
                    "title": m.get("title"),
                    "yes_pct": m.get("yes_pct"),
                    "volume_24h": m.get("volume_24h"),
                    "url": m.get("url"),
                }
                for m in (mkts.get("markets") or [])[:10]
            ]
        except Exception:
            markets_data = []
        try:
            cmap = fetch_us_contagion_map(hide_noise=True)
            map_clusters = [
                {
                    "topic": c.get("topic"),
                    "sector": c.get("sector"),
                    "state_count": c.get("state_count"),
                    "stage": c.get("stage"),
                    "origin_state": c.get("origin_state"),
                }
                for c in (cmap.get("clusters") or [])[:8]
            ]
        except Exception:
            map_clusters = []

    compact_snapshot = {
        "mode": norm_mode,
        "quant_summary": quant_ws.get("summary"),
        "screener_top": (quant_ws.get("screener") or [])[:12],
        "divergences": (quant_ws.get("divergences") or [])[:8],
        "vcrm_gates": [
            {"id": g["id"], "status": g["status"], "title": g["title"], "observed": g["observed"], "target": g["target"]}
            for g in (quant_ws.get("vcrm") or {}).get("gates") or []
        ],
        "live_prediction_markets": markets_data,
        "live_us_contagion_clusters": map_clusters,
        "valid_categories_and_labels": {k: list(v) for k, v in CATEGORY_LABELS.items()},
    }

    system_prompt = (
        "You are the Lead Quantitative Analyst on IPX Terminal (Content IP & Cultural Velocity Desk). "
        "Follow the strict IPX signal hierarchy: Derivative Remakes / US Geographic Breadth > "
        "Share-to-Like Ratio % > Views-to-Followers Breakout Ratio > Raw Solo Likes. "
        "NEVER fabricate metrics or 48-72h outcomes. Only reason from the t_0 snapshot provided.\n"
        "Return STRICT JSON with keys:\n"
        "- 'headline': string (crisp 1-line desk headline)\n"
        "- 'executive_summary': string (2-4 concise sentences on what matters right now)\n"
        "- 'top_signals': list of up to 4 objects {ticker, signal_flag, thesis}\n"
        "- 'markets_to_freeze': list of up to 2 objects from live_prediction_markets to freeze as t_0 signals "
        "{market_title, ticker, sector, yes_pct, source, url, rationale}\n"
        f"- 'calls_to_log': list of up to {max_calls} high-conviction t_0 calls against existing screener signal_id values "
        "{signal_id (int), category (one of valid_categories_and_labels keys), predicted_label (exact canonical label for that category), "
        "confidence (float 0.50-0.92, well-calibrated for Brier score), thesis (1-2 sentences)}\n"
        "- 'vcrm_actions': list of 1-4 concise strings describing how to clear any FAIL/PENDING VCRM gates."
    )
    user_prompt = (
        f"Run Mode: {norm_mode.upper()}\n"
        f"Live IPX Terminal Snapshot:\n{json.dumps(compact_snapshot, ensure_ascii=False, indent=2)}"
    )

    used_model = resolved_model
    if llm_caller is not None:
        decision = llm_caller(system_prompt, user_prompt, resolved_model)
    else:
        try:
            decision = _call_gemini_quant_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                model=resolved_model,
                api_key=resolved_key,
                base_url=resolved_url,
            )
        except RuntimeError:
            if resolved_model != DEFAULT_INTRADAY_MODEL:
                used_model = DEFAULT_INTRADAY_MODEL
                decision = _call_gemini_quant_llm(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    model=used_model,
                    api_key=resolved_key,
                    base_url=resolved_url,
                )
            else:
                raise

    # 3. Execute safe t_0 actions (freeze markets + log calibrated t_0 calls) unless dry_run
    frozen_signals: List[Dict[str, Any]] = []
    logged_predictions: List[Dict[str, Any]] = []

    if not dry_run:
        existing_pending_sig_ids = {
            p["signal_id"] for p in db.list_predictions(status="pending", limit=200)
        }

        for m in (decision.get("markets_to_freeze") or [])[:2]:
            title = str(m.get("market_title") or "").strip()
            ticker = str(m.get("ticker") or "").strip().upper()
            if not title or not ticker:
                continue
            sector = str(m.get("sector") or "POP").strip().upper()
            if sector not in VALID_SECTORS:
                sector = "POP"
            yes_pct = m.get("yes_pct")
            src = str(m.get("source") or "Polymarket").strip()
            try:
                sig = db.insert_signal(
                    ticker=ticker,
                    title=f"[{src}] {title}",
                    summary=str(m.get("rationale") or f"Frozen by Gemini Quant ({used_model}) at {yes_pct}% YES."),
                    platforms=[src],
                    metrics={
                        "yes_pct": float(yes_pct) if yes_pct is not None else None,
                        "market_source": src,
                        "frozen_by": f"gemini-quant:{used_model}",
                    },
                    source_type="prediction_market",
                    url=str(m.get("url") or ""),
                    sector=sector,
                    entity_name=title[:60],
                )
                frozen_signals.append({"signal_id": sig["id"], "ticker": sig["ticker"], "title": sig["title"]})
                actions_taken.append(f"Froze market t_0 signal #{sig['id']} ({sig['ticker']}) at {yes_pct}% YES.")
            except Exception:
                continue

        for c in (decision.get("calls_to_log") or [])[:max_calls]:
            try:
                sig_id = int(c.get("signal_id"))
            except (TypeError, ValueError):
                continue
            if sig_id in existing_pending_sig_ids:
                continue
            category = str(c.get("category") or "").strip()
            label = str(c.get("predicted_label") or "").strip()
            if category not in VALID_CATEGORIES or label not in CATEGORY_LABELS[category]:
                continue
            conf = max(0.50, min(0.92, float(c.get("confidence") or 0.65)))
            thesis = str(c.get("thesis") or "").strip()
            try:
                pred = db.create_prediction(
                    signal_id=sig_id,
                    category=category,
                    predicted_label=label,
                    confidence=round(conf, 2),
                    analyst_notes=f"[Gemini Quant · {used_model}] {thesis}",
                    outcome_window_hours=48,
                    question=DEFAULT_QUESTIONS[category],
                    ai_model=used_model,
                    ai_predicted_label=label,
                    ai_confidence=round(conf, 2),
                    ai_reasoning=thesis,
                )
                existing_pending_sig_ids.add(sig_id)
                logged_predictions.append(
                    {
                        "id": pred["id"],
                        "case_code": pred["case_code"],
                        "ticker": pred["ticker"],
                        "category": category,
                        "predicted_label": label,
                        "confidence": pred["confidence"],
                    }
                )
                actions_taken.append(
                    f"Logged t_0 call {pred['case_code']} on {pred['ticker']}: {label} ({int(round(pred['confidence'] * 100))}% conf)."
                )
            except Exception:
                continue

    created_at = utc_now_iso()
    memo: Dict[str, Any] = {
        "id": f"qmemo-{created_at.replace(':', '').replace('-', '')}",
        "created_at": created_at,
        "mode": norm_mode,
        "model_used": used_model,
        "dry_run": dry_run,
        "headline": str(decision.get("headline") or f"Gemini Quant {norm_mode.title()} Desk Update"),
        "executive_summary": str(decision.get("executive_summary") or ""),
        "top_signals": list(decision.get("top_signals") or [])[:5],
        "vcrm_actions": list(decision.get("vcrm_actions") or [])[:5],
        "actions_taken": actions_taken,
        "frozen_signals": frozen_signals,
        "logged_predictions": logged_predictions,
        "recheck_summary": {
            "overdue_count": recheck_summary.get("overdue_count", 0),
            "checked_count": recheck_summary.get("checked_count", 0),
        },
    }

    mdir = memos_dir or DEFAULT_MEMOS_DIR
    mdir.mkdir(parents=True, exist_ok=True)
    stem = f"{created_at.replace(':', '').replace('-', '')}_{norm_mode}"
    json_path = mdir / f"{stem}.json"
    md_path = mdir / f"{stem}.md"
    json_path.write_text(json.dumps(memo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path.write_text(_render_memo_markdown(memo), encoding="utf-8")
    memo["memo_path"] = str(md_path)
    return memo
