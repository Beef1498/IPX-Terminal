"""Client Project & Music Catalog workspace loader for IPX Terminal (e.g. Street Mob / Fuerza Regida)."""

from __future__ import annotations

import html as html_lib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipx_terminal.config import PROJECT_ROOT
from ipx_terminal.db import TerminalDB

DEFAULT_PROJECTS_DIR = PROJECT_ROOT / "data" / "projects"


def list_projects(projects_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return all client project configs from data/projects/*.json sorted primary-first."""
    pdir = projects_dir or DEFAULT_PROJECTS_DIR
    if not pdir.exists():
        return []
    projects: List[Dict[str, Any]] = []
    for path in sorted(pdir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                data.setdefault("source_file", str(path))
                projects.append(data)
        except Exception:
            continue
    projects.sort(key=lambda p: (0 if p.get("primary") else 1, 0 if p.get("active", True) else 1, str(p.get("id", ""))))
    return projects


def get_project(project_id: str, projects_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Look up a single client project by its id (case-insensitive)."""
    needle = str(project_id or "").strip().lower()
    if not needle:
        return None
    for proj in list_projects(projects_dir=projects_dir):
        if str(proj.get("id") or "").strip().lower() == needle:
            return proj
    return None


def get_default_active_project(projects_dir: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Return the primary active client project, or None if none are active."""
    for proj in list_projects(projects_dir=projects_dir):
        if proj.get("active", True) and proj.get("primary", False):
            return proj
    for proj in list_projects(projects_dir=projects_dir):
        if proj.get("active", True):
            return proj
    return None


def rank_catalog_tracks_for_signal(
    project: Dict[str, Any],
    signal: Dict[str, Any],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """Rank tracks from a client project's catalog against a t_0 signal's text, tags, and sector."""
    tracks = list(project.get("catalog_tracks") or [])
    if not tracks:
        return []

    haystack_parts = [
        str(signal.get("ticker") or ""),
        str(signal.get("sector") or ""),
        str(signal.get("title") or ""),
        str(signal.get("summary") or ""),
        " ".join(str(s) for s in (signal.get("samples") or [])),
        " ".join(str(e) for e in (signal.get("entities_mentioned") or [])),
    ]
    haystack = " ".join(haystack_parts).lower()

    # Map common cultural/viral concepts to vibe keywords for cross-niche audio flipping
    keyword_bridges = {
        "roast": ["roast", "comedy", "pov", "relational_roast", "sarcasm", "meme"],
        "capcut": ["capcut_template", "high_energy_capcut", "pov", "meme"],
        "template": ["capcut_template", "relatable_pov", "meme"],
        "relationship": ["desamor", "toxic_pov", "relational_roast", "couple", "situationship"],
        "ex": ["desamor", "heartbreak", "toxic_pov", "moving_on"],
        "couple": ["couple", "romance", "desamor", "situationship"],
        "car": ["car", "trokiando", "late_night", "night_drive", "flex"],
        "truck": ["truck", "trokiando", "flex", "corrido_belico"],
        "gym": ["gym", "hustle", "sports", "grit", "win"],
        "sport": ["sports", "hype", "win", "hustle", "energy"],
        "nfl": ["sports", "hype", "win", "energy"],
        "nba": ["sports", "hype", "win", "energy"],
        "nhl": ["sports", "hype", "win", "energy"],
        "party": ["party", "antros", "club", "nightlife", "hype"],
        "club": ["party", "antros", "club", "nightlife"],
        "dance": ["dance", "party", "cumbia", "hype"],
        "grwm": ["grwm", "outfit", "lifestyle", "party"],
        "luxury": ["flex", "luxury", "lifestyle"],
        "night": ["late_night", "night_drive", "chill", "antros"],
        "heartbreak": ["desamor", "heartbreak", "toxic_pov"],
        "meme": ["meme", "comedy", "pov", "roast"],
    }
    expanded_terms = set()
    for trigger, mapped in keyword_bridges.items():
        if trigger in haystack:
            expanded_terms.update(mapped)

    scored: List[tuple] = []
    for idx, track in enumerate(tracks):
        score = 0.0
        if str(track.get("status") or "").lower() == "priority_push":
            score += 2.0
        tags = [str(t).lower() for t in (track.get("vibe_tags") or [])]
        archetypes = [str(a).lower() for a in (track.get("format_archetypes") or [])]
        for tag in tags:
            if tag in haystack or tag.replace("_", " ") in haystack:
                score += 4.0
            if tag in expanded_terms:
                score += 2.5
        for arch in archetypes:
            if arch in haystack or arch.replace("_", " ") in haystack:
                score += 3.0
            if arch in expanded_terms:
                score += 2.0
        artist_l = str(track.get("artist") or "").lower()
        title_l = str(track.get("title") or "").lower()
        if artist_l and artist_l in haystack:
            score += 6.0
        if title_l and title_l in haystack:
            score += 6.0
        scored.append((score, -idx, track))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[: max(1, limit)]]


def seed_project_entities(db: TerminalDB, project: Dict[str, Any]) -> Dict[str, Any]:
    """Upsert all roster/label entities from a client project into the IPX Terminal SQLite DB."""
    label_name = str(project.get("label_name") or project.get("name") or "Client Project")
    sector = str(project.get("sector") or "MUSIC").upper()
    seeded: List[Dict[str, Any]] = []
    for ent in project.get("roster_entities") or []:
        ticker = str(ent.get("ticker") or "").strip().upper()
        name = str(ent.get("name") or "").strip()
        if not ticker or not name:
            continue
        saved = db.upsert_entity(
            ticker=ticker,
            name=name,
            sector=str(ent.get("sector") or sector).upper(),
            owner_holder=label_name,
            ip_type=str(ent.get("ip_type") or "artist"),
            aliases=list(ent.get("aliases") or [name]),
            description=str(ent.get("description") or ""),
        )
        seeded.append(saved)
    return {
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "seeded_count": len(seeded),
        "entities": seeded,
    }


def render_client_brief_html(
    db: TerminalDB,
    project: Optional[Dict[str, Any]] = None,
) -> str:
    """Render a standalone, print-to-PDF-ready visual Executive Brief & Creative Playbook HTML report."""
    from ipx_terminal.quant import build_quant_workspace
    from ipx_terminal.quant_agent import list_quant_memos

    ws = build_quant_workspace(db, include_vcrm=True)
    memos = list_quant_memos(limit=1)
    memo = memos[0] if memos else {}
    briefs = db.list_briefs(limit=12)
    screener = (ws.get("screener") or [])[:12]
    summary = ws.get("summary") or {}

    e = html_lib.escape
    proj_name = str(project.get("name") or "IPX Cultural Velocity Desk") if project else "IPX Cultural Velocity Desk"
    proj_label = str(project.get("label_name") or "Content IP Intelligence") if project else "Content IP Intelligence"
    faceless_badge = (
        '<span class="badge badge-green">FACELESS AT SCALE</span>'
        if project and project.get("production_mode") == "faceless_at_scale"
        else ""
    )
    langs = " / ".join(project.get("languages") or []) if project else "EN"
    geos = ", ".join((project.get("target_geos") or [])[:8]) if project else "US National"
    created_at = str(memo.get("created_at") or "Live Snapshot")
    headline = str(memo.get("headline") or f"{proj_name} — Cultural Velocity & Trend Playbook")
    exec_summary = str(
        memo.get("executive_summary")
        or "Live cross-platform cultural velocity snapshot ranked by derivative remake breadth, share-to-like velocity, and breakout ratio."
    )

    top_signals_html = ""
    for sig in memo.get("top_signals") or []:
        flag = str(sig.get("signal_flag") or "WATCH")
        cls = "badge-green" if flag == "STRONG_SIGNAL" else ("badge-amber" if flag == "WATCH" else "badge-muted")
        top_signals_html += (
            f'<div class="signal-card">'
            f'<div class="signal-head"><span class="ticker">{e(str(sig.get("ticker") or ""))}</span>'
            f'<span class="badge {cls}">{e(flag)}</span></div>'
            f'<p class="signal-thesis">{e(str(sig.get("thesis") or ""))}</p>'
            f'</div>'
        )
    if not top_signals_html:
        top_signals_html = '<p class="muted">Run Gemini Quant to populate tailored signal theses.</p>'

    briefs_html = ""
    for b in briefs[:6]:
        beats = b.get("edit_beats") or []
        beats_li = "".join(f"<li>{e(str(item))}</li>" for item in beats)
        verdict = b.get("verdict")
        verdict_badge = f'<span class="badge badge-green">{e(str(verdict).upper())}</span>' if verdict else '<span class="badge badge-cyan">READY TO PRODUCE</span>'
        beats_block = (
            f'<div class="beats-box"><div class="field-label">TIMED EDIT BEATS</div><ol>{beats_li}</ol></div>'
            if beats_li
            else ""
        )
        briefs_html += (
            f'<div class="brief-card">'
            f'<div class="brief-head">'
            f'<div><span class="ticker">{e(str(b.get("ticker") or ""))}</span> '
            f'<span class="badge badge-purple">{e(str(b.get("target_platform") or "TikTok"))}</span></div>'
            f'{verdict_badge}'
            f'</div>'
            f'<div class="brief-angle">{e(str(b.get("angle") or ""))}</div>'
            f'<div class="brief-grid">'
            f'<div><div class="field-label">2-SECOND HOOK</div><div class="field-val">{e(str(b.get("hook_2s") or ""))}</div></div>'
            f'<div><div class="field-label">ON-SCREEN TEXT</div><div class="field-val ost">"{e(str(b.get("on_screen_text") or ""))}"</div></div>'
            f'</div>'
            f'<div class="audio-box"><span class="field-label">AUDIO / SOUND CUE</span><div>{e(str(b.get("audio_cue") or ""))}</div></div>'
            f'{beats_block}'
            f'<div class="caption-line"><span class="field-label">CAPTION:</span> {e(str(b.get("caption") or ""))}</div>'
            f'</div>'
        )
    if not briefs_html:
        briefs_html = '<p class="muted">No creative briefs saved yet. Click Generate Brief on any high-velocity signal.</p>'

    screener_rows = ""
    for r in screener:
        flag = str(r.get("signal_flag") or "NOISE")
        cls = "badge-green" if flag == "STRONG_SIGNAL" else ("badge-amber" if flag == "WATCH" else "badge-muted")
        stl = f"{r['share_to_like_pct']}%" if float(r.get("share_to_like_pct") or 0) > 0 else "--"
        brk = f"{r['breakout_ratio']}x" if float(r.get("breakout_ratio") or 0) > 0 else "--"
        screener_rows += (
            f"<tr>"
            f'<td class="mono strong">{e(str(r.get("ticker") or ""))}</td>'
            f'<td>{e(str(r.get("sector") or ""))}</td>'
            f'<td><span class="badge {cls}">{e(flag)}</span></td>'
            f'<td class="num strong">{float(r.get("alpha_score") or 0):.1f}</td>'
            f'<td class="num">{float(r.get("cvs_score") or 0):.1f}</td>'
            f'<td class="num">{e(stl)}</td>'
            f'<td class="num">{e(brk)}</td>'
            f"</tr>"
        )

    catalog_section = ""
    if project and (project.get("catalog_tracks") or []):
        track_chips = ""
        for t in (project.get("catalog_tracks") or []):
            is_prio = str(t.get("status") or "").lower() == "priority_push"
            badge_cls = "badge-green" if is_prio else "badge-muted"
            tags = " · ".join((t.get("vibe_tags") or [])[:3])
            track_chips += (
                f'<div class="track-pill">'
                f'<div class="track-title">{e(str(t.get("title") or ""))} '
                f'<span class="badge {badge_cls}" style="font-size:9px">{ "PUSH" if is_prio else "CATALOG" }</span></div>'
                f'<div class="track-meta">{e(tags)}</div>'
                f'</div>'
            )
        catalog_section = (
            f'<section class="section">'
            f'<div class="section-title">ACTIVE SONG-SEEDING CATALOG ({len(project.get("catalog_tracks") or [])} TRACKS)</div>'
            f'<div class="track-grid">{track_chips}</div>'
            f'</section>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>IPX Executive Brief — {e(proj_name)}</title>
<style>
  :root {{
    --bg: #0b1019;
    --card: #121a27;
    --border: #233146;
    --text: #e6edf5;
    --muted: #94a3b8;
    --cyan: #22d3ee;
    --green: #34d399;
    --amber: #f59e0b;
    --rose: #fb7185;
    --purple: #a78bfa;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    line-height: 1.5;
    padding: 28px 20px 60px;
  }}
  .page {{ max-width: 1020px; margin: 0 auto; }}
  .toolbar {{
    display: flex; justify-content: space-between; align-items: center; gap: 12px;
    margin-bottom: 18px; padding-bottom: 12px; border-bottom: 1px solid var(--border);
  }}
  .brand-row {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .logo {{
    background: linear-gradient(135deg, #22d3ee, #34d399);
    color: #071018; font-weight: 900; font-family: monospace;
    padding: 4px 10px; border-radius: 6px; letter-spacing: 1px; font-size: 13px;
  }}
  .btn-print {{
    background: var(--cyan); color: #061018; border: none; border-radius: 6px;
    padding: 8px 16px; font-weight: 700; font-size: 12.5px; cursor: pointer;
  }}
  .btn-print:hover {{ opacity: 0.9; }}
  .hero {{
    background: linear-gradient(135deg, rgba(34,211,238,0.10), rgba(167,139,250,0.08));
    border: 1px solid rgba(34,211,238,0.35); border-radius: 12px; padding: 22px 24px; margin-bottom: 18px;
  }}
  .hero-meta {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; font-size: 11.5px; color: var(--muted); }}
  .hero h1 {{ margin: 0 0 10px; font-size: 21px; line-height: 1.3; color: #f8fafc; }}
  .hero p {{ margin: 0; font-size: 14px; color: #cbd5e1; }}
  .kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px; }}
  .kpi {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  }}
  .kpi-label {{ font-family: monospace; font-size: 10.5px; color: var(--muted); letter-spacing: 0.5px; }}
  .kpi-val {{ font-size: 24px; font-weight: 800; margin-top: 4px; }}
  .section {{ margin-bottom: 22px; }}
  .section-title {{
    font-family: monospace; font-size: 12px; font-weight: 700; letter-spacing: 0.8px;
    color: var(--cyan); margin-bottom: 10px; text-transform: uppercase;
  }}
  .signal-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 12px; }}
  .signal-card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 14px 16px;
  }}
  .signal-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .signal-thesis {{ margin: 0; font-size: 13px; color: #cbd5e1; }}
  .brief-card {{
    background: var(--card); border: 1px solid rgba(34,211,238,0.28); border-radius: 10px;
    padding: 16px 18px; margin-bottom: 12px; break-inside: avoid;
  }}
  .brief-head {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  .brief-angle {{ font-size: 15px; font-weight: 700; color: #f8fafc; margin-bottom: 10px; }}
  .brief-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 10px; }}
  .field-label {{ font-family: monospace; font-size: 10px; color: var(--muted); letter-spacing: 0.6px; margin-bottom: 3px; }}
  .field-val {{ font-size: 13px; color: #e2e8f0; }}
  .ost {{ font-weight: 700; color: var(--amber); }}
  .audio-box {{
    background: rgba(34,211,238,0.08); border: 1px solid rgba(34,211,238,0.25);
    border-radius: 8px; padding: 10px 12px; font-size: 13px; margin-bottom: 10px; color: #e0f2fe;
  }}
  .beats-box ol {{ margin: 4px 0 10px; padding-left: 18px; font-size: 12.5px; color: #cbd5e1; }}
  .beats-box li {{ margin-bottom: 3px; }}
  .caption-line {{ font-size: 12.5px; color: var(--muted); border-top: 1px solid var(--border); padding-top: 8px; }}
  .ticker {{ font-family: monospace; font-weight: 800; color: var(--cyan); font-size: 13px; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px; font-family: monospace;
    font-size: 10.5px; font-weight: 700; border: 1px solid var(--border);
  }}
  .badge-green {{ background: rgba(52,211,153,0.16); color: var(--green); border-color: rgba(52,211,153,0.45); }}
  .badge-cyan {{ background: rgba(34,211,238,0.14); color: var(--cyan); border-color: rgba(34,211,238,0.4); }}
  .badge-amber {{ background: rgba(245,158,11,0.16); color: var(--amber); border-color: rgba(245,158,11,0.45); }}
  .badge-purple {{ background: rgba(167,139,250,0.16); color: var(--purple); border-color: rgba(167,139,250,0.45); }}
  .badge-muted {{ background: rgba(148,163,184,0.12); color: var(--muted); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; font-size: 12.5px; }}
  th, td {{ padding: 9px 12px; border-bottom: 1px solid var(--border); text-align: left; }}
  th {{ font-family: monospace; font-size: 10.5px; color: var(--muted); background: rgba(255,255,255,0.02); }}
  .num {{ text-align: right; font-family: monospace; }}
  .mono {{ font-family: monospace; }}
  .strong {{ font-weight: 700; }}
  .track-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 8px; }}
  .track-pill {{ background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; }}
  .track-title {{ font-size: 12.5px; font-weight: 700; color: #f8fafc; display: flex; justify-content: space-between; align-items: center; gap: 4px; }}
  .track-meta {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  @media (max-width: 700px) {{
    .kpi-row {{ grid-template-columns: repeat(2, 1fr); }}
    .brief-grid {{ grid-template-columns: 1fr; }}
  }}
  @media print {{
    body {{ background: #ffffff; color: #0f172a; padding: 0; }}
    .toolbar {{ display: none; }}
    .hero, .kpi, .signal-card, .brief-card, table, .track-pill {{
      background: #ffffff !important; border-color: #cbd5e1 !important; color: #0f172a !important;
    }}
    .hero h1, .brief-angle, .track-title {{ color: #0f172a !important; }}
    .hero p, .signal-thesis, .field-val, .beats-box ol, .caption-line {{ color: #334155 !important; }}
    .audio-box {{ background: #f1f5f9 !important; color: #0f172a !important; border-color: #94a3b8 !important; }}
    .ticker, .section-title {{ color: #0369a1 !important; }}
    .ost {{ color: #b45309 !important; }}
  }}
</style>
</head>
<body>
  <div class="page">
    <div class="toolbar">
      <div class="brand-row">
        <span class="logo">IPX TERMINAL</span>
        <span style="font-weight:700;font-size:14px">{e(proj_name)}</span>
        <span class="badge badge-muted">{e(proj_label)}</span>
        {faceless_badge}
      </div>
      <button type="button" class="btn-print" onclick="window.print()">🖨 Print / Save as PDF</button>
    </div>

    <div class="hero">
      <div class="hero-meta">
        <span>GENERATED: <b>{e(created_at)}</b></span>
        <span>·</span>
        <span>LANGUAGES: <b>{e(langs)}</b></span>
        <span>·</span>
        <span>TARGET GEOS: <b>{e(geos)}</b></span>
      </div>
      <h1>{e(headline)}</h1>
      <p>{e(exec_summary)}</p>
    </div>

    <div class="kpi-row">
      <div class="kpi"><div class="kpi-label">STRONG SIGNALS</div><div class="kpi-val" style="color:var(--green)">{summary.get("strong_signals", 0)}</div></div>
      <div class="kpi"><div class="kpi-label">TRACKED TICKERS</div><div class="kpi-val" style="color:var(--cyan)">{summary.get("tracked_tickers", 0)}</div></div>
      <div class="kpi"><div class="kpi-label">QUANT HIT RATE</div><div class="kpi-val" style="color:var(--purple)">{f"{summary['human_hit_rate_pct']}%" if summary.get("human_hit_rate_pct") is not None else "--"}</div></div>
      <div class="kpi"><div class="kpi-label">BRIER CALIBRATION</div><div class="kpi-val" style="color:var(--amber)">{f"{summary['brier_calibration_pct']}%" if summary.get("brier_calibration_pct") is not None else "--"}</div></div>
    </div>

    <section class="section">
      <div class="section-title">TOP ACTIONABLE TREND → SONG PLAYBOOKS</div>
      <div class="signal-grid">{top_signals_html}</div>
    </section>

    <section class="section">
      <div class="section-title">READY-TO-PRODUCE CREATIVE BRIEFS ({len(briefs[:6])})</div>
      {briefs_html}
    </section>

    <section class="section">
      <div class="section-title">TOP CULTURAL VELOCITY SCREENER</div>
      <table>
        <thead><tr><th>TICKER</th><th>SECTOR</th><th>SIGNAL</th><th class="num">ALPHA</th><th class="num">CVS</th><th class="num">SHARE/LIKE</th><th class="num">BREAKOUT</th></tr></thead>
        <tbody>{screener_rows}</tbody>
      </table>
    </section>

    {catalog_section}
  </div>
</body>
</html>
"""
