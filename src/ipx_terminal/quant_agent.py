"""Autonomous Gemini Quant Agent for IPX Terminal (Morning Routine + Intraday Scout)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.error
import urllib.request

from ipx_terminal.ai_scorer import DEFAULT_AI_BASE_URL, _extract_json_object, generate_creative_brief, resolve_ai_credentials
from ipx_terminal.config import (
    CATEGORY_LABELS,
    DEFAULT_EXPORT_DIR,
    DEFAULT_QUESTIONS,
    VALID_CATEGORIES,
    VALID_SECTORS,
)
from ipx_terminal.db import TerminalDB, utc_now_iso
from ipx_terminal.exporter import export_resolved_to_jsonl
from ipx_terminal.ingest import (
    fetch_prediction_markets,
    fetch_scrapecreators_creator_posts,
    fetch_us_contagion_map,
    recheck_overdue_predictions,
)
from ipx_terminal.quant import build_quant_workspace

DEFAULT_MORNING_MODEL = "gemini-2.5-pro"
DEFAULT_INTRADAY_MODEL = "gemini-3.5-flash-lite"
DEFAULT_WATCHLIST_PATH = Path(__file__).resolve().parents[2] / "data" / "creator_watchlist.json"


def _default_memos_dir() -> Path:
    explicit = os.environ.get("IPX_QUANT_MEMOS_DIR", "").strip()
    if explicit:
        return Path(explicit)
    db_env = os.environ.get("IPX_DB_PATH", "").strip()
    if db_env:
        return Path(db_env).resolve().parent / "quant_memos"
    return Path(__file__).resolve().parents[2] / "data" / "quant_memos"


DEFAULT_MEMOS_DIR = _default_memos_dir()


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
    if memo.get("drafted_briefs"):
        lines.extend(["", "## Ready-to-Shoot Video Briefs Auto-Drafted"])
        for b in memo["drafted_briefs"]:
            lines.append(
                f"- **{b.get('ticker', '?')}** ({b.get('target_platform', 'TikTok')}): *{b.get('angle', '')}* — Hook: \"{b.get('hook_2s', '')}\""
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


def auto_resolve_clear_cut_outcomes(
    db: TerminalDB,
    recheck_result: Dict[str, Any],
    export_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Deterministically resolve clear-cut overdue 48-72h calls from real metrics (zero AI self-grading).

    Only resolves unambiguous breakout/noise outcomes based on verified ScrapeCreators / live
    metric deltas; ambiguous middle-ground calls remain pending for human adjudication.
    """
    resolved_items: List[Dict[str, Any]] = []
    skipped_ambiguous: List[str] = []

    for item in recheck_result.get("checked") or []:
        pred_id = item.get("prediction_id")
        if not pred_id:
            continue
        pred = db.get_prediction(int(pred_id))
        if not pred or pred.get("status") != "pending":
            continue
        cat = str(pred.get("category") or "")
        if cat not in ("breakout", "contagion"):
            continue

        deltas = item.get("deltas") or {}
        live = item.get("live_metrics") or {}
        views_delta = float(deltas.get("views_delta") or 0.0)
        views_ratio = float(deltas.get("views_ratio") or 0.0)
        cur_views = float(live.get("views") or 0.0)
        cur_likes = float(live.get("likes") or 0.0)
        cur_shares = float(live.get("shares") or 0.0)
        share_to_like = (cur_shares / cur_likes) if (cur_shares > 0 and cur_likes > 0) else 0.0

        label: Optional[str] = None
        if cat == "breakout":
            if views_ratio >= 2.0 or views_delta >= 250_000 or (cur_views >= 500_000 and share_to_like >= 0.15):
                label = "breakout"
            elif 0 < views_ratio <= 1.15 and views_delta < 25_000:
                label = "noise"
        elif cat == "contagion":
            if views_ratio >= 2.5 or views_delta >= 500_000:
                label = "mainstream_breakout"
            elif 0 < views_ratio <= 1.15 and views_delta < 25_000:
                label = "echo_chamber"

        if not label:
            skipped_ambiguous.append(str(pred.get("case_code") or pred_id))
            continue

        rationale = (
            f"Deterministic 48-72h metric adjudication ({item.get('provider', 'live')}): "
            f"views_ratio={views_ratio:.2f}x, views_delta={int(views_delta):+}, "
            f"current_views={int(cur_views):,}, share_to_like={share_to_like * 100:.1f}%."
        )
        resolved = db.resolve_prediction(
            prediction_id=int(pred_id),
            ground_truth_label=label,
            required_concepts=[pred["ticker"], label],
            rationale=rationale,
            outcome_metrics={
                "provider": item.get("provider", "live"),
                "views_ratio": round(views_ratio, 2),
                "views_delta": int(views_delta),
                "current_views": int(cur_views),
                "share_to_like_pct": round(share_to_like * 100.0, 1),
                "adjudication": "deterministic_numeric_threshold",
            },
        )
        resolved_items.append(
            {
                "prediction_id": int(pred_id),
                "case_code": resolved["case_code"],
                "ticker": resolved["ticker"],
                "ground_truth_label": label,
                "prediction_correct": bool((resolved.get("outcome") or {}).get("prediction_correct")),
            }
        )

    exported_count = 0
    if resolved_items:
        try:
            exp = export_resolved_to_jsonl(db=db, out_dir=export_dir or DEFAULT_EXPORT_DIR)
            exported_count = int(exp.get("total_exported") or 0)
        except Exception:
            exported_count = 0

    return {
        "resolved_count": len(resolved_items),
        "resolved": resolved_items,
        "skipped_ambiguous": skipped_ambiguous,
        "exported_count": exported_count,
    }


def auto_draft_morning_briefs(
    db: TerminalDB,
    screener: List[Dict[str, Any]],
    api_key: str,
    model: str,
    base_url: str = DEFAULT_AI_BASE_URL,
    max_briefs: int = 2,
) -> List[Dict[str, Any]]:
    """Auto-draft ready-to-shoot short-form Video Briefs for top STRONG_SIGNAL / high-alpha tickers."""
    existing_sig_ids = {b["signal_id"] for b in db.list_briefs(limit=250)}
    drafted: List[Dict[str, Any]] = []

    candidates = [
        r for r in screener
        if r.get("signal_id") and r["signal_id"] not in existing_sig_ids
        and (r.get("signal_flag") == "STRONG_SIGNAL" or float(r.get("alpha_score") or 0.0) >= 30.0)
    ]
    for row in candidates[: max(0, max_briefs)]:
        sig = db.get_signal(int(row["signal_id"]))
        if not sig:
            continue
        platforms = sig.get("platforms") or []
        target_plat = "TikTok"
        for p in platforms:
            pl = str(p).lower()
            if "shorts" in pl or "youtube" in pl:
                target_plat = "YouTube Shorts"
                break
            if "reel" in pl or "instagram" in pl:
                target_plat = "Instagram Reels"
                break
            if "tiktok" in pl:
                target_plat = "TikTok"
                break
        gen = generate_creative_brief(
            signal=sig,
            target_platform=target_plat,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        saved = db.create_brief(
            signal_id=sig["id"],
            target_platform=target_plat,
            angle=gen["angle"],
            hook_2s=gen["hook_2s"],
            on_screen_text=gen["on_screen_text"],
            caption=gen["caption"],
            edit_beats=gen["edit_beats"],
            audio_cue=gen["audio_cue"],
            model_used=gen.get("model_used") or model,
        )
        drafted.append(
            {
                "brief_id": saved["id"],
                "signal_id": sig["id"],
                "ticker": saved["ticker"],
                "target_platform": saved["target_platform"],
                "angle": saved["angle"],
                "hook_2s": saved["hook_2s"],
            }
        )
    return drafted


def _make_creator_ticker(handle: str, sector: str) -> str:
    clean = "".join(ch for ch in handle.upper() if ch.isalnum())[:5] or "IPX"
    sec_tag = {
        "CREATORS": "CR",
        "MUSIC": "MU",
        "FILM_TV": "FT",
        "GAMING": "GM",
        "SPORTS": "SP",
        "POP": "PP",
        "DEALS": "DL",
    }.get(sector.upper(), "IP")
    return f"{clean}.{sec_tag}"


def ingest_daily_niche_creators(
    db: TerminalDB,
    watchlist_path: Optional[Path] = None,
    max_creators: int = 5,
    api_key: Optional[str] = None,
    fetcher: Optional[Callable[[str, str], List[Dict[str, Any]]]] = None,
) -> Dict[str, Any]:
    """Rotate 1 creator per distinct niche from creator_watchlist.json and ingest their top fresh post into Terminal."""
    wl_path = watchlist_path or DEFAULT_WATCHLIST_PATH
    if not wl_path.exists():
        return {"ingested_count": 0, "ingested": [], "errors": ["creator_watchlist.json not found"]}

    entries: List[Dict[str, Any]] = json.loads(wl_path.read_text(encoding="utf-8"))
    # Sort least-recently-ingested first, then pick at most 1 per distinct sector for daily niche diversity
    ranked = sorted(
        enumerate(entries),
        key=lambda pair: str(pair[1].get("last_terminal_ingest_at") or ""),
    )
    selected: List[tuple] = []
    seen_sectors = set()
    for idx, entry in ranked:
        sec = str(entry.get("sector") or "POP").upper()
        if sec in seen_sectors and len(seen_sectors) < 7:
            continue
        seen_sectors.add(sec)
        selected.append((idx, entry))
        if len(selected) >= max_creators:
            break

    existing_urls = {
        str(s.get("url") or "").strip().lower()
        for s in db.list_signals(limit=500)
        if s.get("url")
    }

    ingested: List[Dict[str, Any]] = []
    errors: List[str] = []
    now_iso = utc_now_iso()

    for idx, entry in selected:
        platform = str(entry.get("platform") or "YouTube Shorts")
        handle = str(entry.get("handle") or "").strip().lstrip("@")
        sector = str(entry.get("sector") or "CREATORS").upper()
        if sector not in VALID_SECTORS:
            sector = "CREATORS"
        if not handle:
            continue
        try:
            posts = (
                fetcher(platform, handle)
                if fetcher is not None
                else fetch_scrapecreators_creator_posts(platform=platform, handle=handle, api_key=api_key)
            )
            entries[idx]["last_terminal_ingest_at"] = now_iso
            if not posts:
                continue

            # Compute creator median views so we spot genuine breakout multiples vs. baseline
            view_vals = sorted(float(p.get("views") or 0) for p in posts if float(p.get("views") or 0) > 0)
            median_views = view_vals[len(view_vals) // 2] if view_vals else 0.0

            best_post = None
            best_score = -1.0
            for p in posts:
                url = str(p.get("url") or "").strip()
                if url and url.lower() in existing_urls:
                    continue
                views = float(p.get("views") or 0)
                likes = float(p.get("likes") or 0)
                shares = float(p.get("shares") or 0)
                if views <= 0 and likes <= 0:
                    continue
                rel_mult = (views / median_views) if (median_views > 0 and views > 0) else 1.0
                stl = (shares / likes) if (shares > 0 and likes > 0) else 0.0
                rank_score = (stl * 100.0 * 2.0) + (rel_mult * 10.0) + (views / 250_000.0)
                if rank_score > best_score:
                    best_score = rank_score
                    best_post = (p, rel_mult, stl)

            if not best_post:
                continue

            post, rel_mult, stl = best_post
            ticker = _make_creator_ticker(handle, sector)
            views = int(post.get("views") or 0)
            likes = int(post.get("likes") or 0)
            shares = int(post.get("shares") or 0)
            comments = int(post.get("comments") or 0)
            raw_title = str(post.get("title") or post.get("caption") or f"@{handle} {platform} post").strip()
            short_title = raw_title[:85]
            url = str(post.get("url") or "").strip()

            sig = db.insert_signal(
                ticker=ticker,
                title=f"{platform} @{handle}: {short_title}",
                summary=(
                    f"Daily niche rotation ({sector}) via ScrapeCreators on {platform} (@{handle}): "
                    f"{views:,} views ({rel_mult:.2f}x creator median), {likes:,} likes, {shares:,} shares "
                    f"({stl * 100:.1f}% share-to-like)."
                ),
                platforms=[platform],
                metrics={
                    "views": views,
                    "likes": likes,
                    "shares": shares,
                    "comments": comments,
                    "breakout_ratio_views_to_followers": round(rel_mult, 2),
                    "share_to_like_ratio": round(stl, 4),
                    "creator_handle": f"@{handle}",
                    "niche_rotation": True,
                },
                samples=[raw_title[:160]] if raw_title else [],
                entities_mentioned=[f"@{handle}", platform, sector],
                source_type="scrapecreators_rotation",
                url=url,
                sector=sector,
                entity_name=f"@{handle} ({sector})",
            )
            if url:
                existing_urls.add(url.lower())
            ingested.append(
                {
                    "signal_id": sig["id"],
                    "ticker": sig["ticker"],
                    "sector": sector,
                    "platform": platform,
                    "handle": f"@{handle}",
                    "views": views,
                    "breakout_ratio": round(rel_mult, 2),
                    "share_to_like_pct": round(stl * 100.0, 1),
                }
            )
        except Exception as exc:
            errors.append(f"@{handle} ({platform}): {exc}")

    try:
        wl_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except Exception:
        pass

    return {"ingested_count": len(ingested), "ingested": ingested, "errors": errors}


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
    auto_resolve_summary: Dict[str, Any] = {"resolved_count": 0, "resolved": [], "exported_count": 0}

    # 1. Clear/recheck overdue 48-72h calls first (deterministic real-world fetch + clear-cut auto-resolve)
    niche_ingest_summary: Dict[str, Any] = {"ingested_count": 0, "ingested": [], "errors": []}
    if fetch_live and not dry_run:
        if norm_mode == "morning":
            try:
                niche_ingest_summary = ingest_daily_niche_creators(db=db, max_creators=5)
                for item in niche_ingest_summary.get("ingested") or []:
                    actions_taken.append(
                        f"Ingested fresh {item['sector']} post ({item['ticker']} · {item['platform']} {item['handle']}): "
                        f"{item['views']:,} views ({item['breakout_ratio']}x median, {item['share_to_like_pct']}% share/like)."
                    )
            except Exception as exc:
                actions_taken.append(f"Daily niche creator rotation skipped: {exc}")
        try:
            recheck_summary = recheck_overdue_predictions(db=db)
            if recheck_summary.get("checked_count"):
                actions_taken.append(
                    f"Auto-rechecked {recheck_summary['checked_count']} overdue 48-72h call(s) via live metrics."
                )
                auto_resolve_summary = auto_resolve_clear_cut_outcomes(db=db, recheck_result=recheck_summary)
                for r in auto_resolve_summary.get("resolved") or []:
                    actions_taken.append(
                        f"Auto-resolved {r['case_code']} ({r['ticker']}) -> {r['ground_truth_label']} "
                        f"({'HIT' if r['prediction_correct'] else 'MISS'}) from live metrics."
                    )
                if auto_resolve_summary.get("exported_count"):
                    actions_taken.append(
                        f"Auto-exported {auto_resolve_summary['exported_count']} resolved case(s) to IPX-Eval JSONL."
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
        "{market_title, ticker (MUST be a fresh topic-specific ticker like AVNG.IP or NFL.DEN — NEVER reuse an unrelated existing ticker), "
        "sector, yes_pct, source, url, rationale}\n"
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
        recent_sigs = db.list_signals(limit=250)
        existing_market_urls = {
            str(s.get("url") or "").strip().lower()
            for s in recent_sigs
            if s.get("source_type") == "prediction_market" and s.get("url")
        }
        existing_market_titles = {
            str(s.get("title") or "").strip().lower()
            for s in recent_sigs
            if s.get("source_type") == "prediction_market" and s.get("title")
        }

        for m in (decision.get("markets_to_freeze") or [])[:2]:
            title = str(m.get("market_title") or "").strip()
            ticker = str(m.get("ticker") or "").strip().upper()
            if not title or not ticker:
                continue
            mkt_url = str(m.get("url") or "").strip()
            src = str(m.get("source") or "Polymarket").strip()
            full_title = f"[{src}] {title}"
            if (mkt_url and mkt_url.lower() in existing_market_urls) or full_title.lower() in existing_market_titles:
                continue
            sector = str(m.get("sector") or "POP").strip().upper()
            if sector not in VALID_SECTORS:
                sector = "POP"
            yes_pct = m.get("yes_pct")
            try:
                sig = db.insert_signal(
                    ticker=ticker,
                    title=full_title,
                    summary=str(m.get("rationale") or f"Frozen by Gemini Quant ({used_model}) at {yes_pct}% YES."),
                    platforms=[src],
                    metrics={
                        "yes_pct": float(yes_pct) if yes_pct is not None else None,
                        "market_source": src,
                        "frozen_by": f"gemini-quant:{used_model}",
                    },
                    source_type="prediction_market",
                    url=mkt_url,
                    sector=sector,
                    entity_name=title[:60],
                )
                if mkt_url:
                    existing_market_urls.add(mkt_url.lower())
                existing_market_titles.add(full_title.lower())
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

    # 4. In Morning Pass, auto-draft up to 2 ready-to-shoot Video Briefs for top STRONG_SIGNAL tickers
    drafted_briefs: List[Dict[str, Any]] = []
    if not dry_run and norm_mode == "morning":
        try:
            drafted_briefs = auto_draft_morning_briefs(
                db=db,
                screener=quant_ws.get("screener") or [],
                api_key=resolved_key,
                model=used_model,
                base_url=resolved_url,
                max_briefs=2,
            )
            for b in drafted_briefs:
                actions_taken.append(
                    f"Auto-drafted Video Brief #{b['brief_id']} for {b['ticker']} ({b['target_platform']}): {b['angle'][:65]}"
                )
        except Exception:
            drafted_briefs = []

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
        "drafted_briefs": drafted_briefs,
        "auto_resolved": auto_resolve_summary.get("resolved") or [],
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
