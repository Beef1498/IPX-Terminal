"""Yearly Cultural Timeline & Lineage Tree engine for IPX Command Center.

Maps recurring US consumer/holiday anchors, weather/mood cycles, and Spotify/Billboard
priority seeding cities, then dynamically branches live t_0 signals, custom future
catalysts, and client catalog tracks onto the active 14-45 day pre-wave seeding window.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import urllib.request

from ipx_terminal.config import PROJECT_ROOT
from ipx_terminal.db import TerminalDB

DEFAULT_TIMELINE_PATH = PROJECT_ROOT / "data" / "cultural_timeline.json"


def load_cultural_timeline(timeline_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the base recurring Cultural Timeline JSON configuration."""
    path = timeline_path or DEFAULT_TIMELINE_PATH
    if not path.exists():
        return {"version": "0.0.0", "spotify_billboard_cities": [], "seasonal_moods": [], "anchors": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_date(year: int, month: int, day: int) -> date:
    """Build a date safely clamping day for shorter months (e.g., Feb 29 -> Feb 28)."""
    m = max(1, min(12, int(month)))
    d = max(1, min(31, int(day)))
    while d >= 28:
        try:
            return date(year, m, d)
        except ValueError:
            d -= 1
    return date(year, m, d)


def _next_occurrence_and_delta(month: int, day: int, duration_days: int, ref_date: date) -> tuple[date, int]:
    """Return (occurrence_date, days_until) where active events in-window return <= 0."""
    this_year = _safe_date(ref_date.year, month, day)
    delta = (this_year - ref_date).days
    # If currently inside the event's active duration window, keep this year's date
    if -max(1, duration_days) < delta <= 366:
        return this_year, delta
    next_year = _safe_date(ref_date.year + 1, month, day)
    return next_year, (next_year - ref_date).days


def _classify_window(days_until: int, duration_days: int, seed_lead_days: int) -> str:
    if -max(1, duration_days) < days_until <= 3:
        return "PEAK_NOW"
    if 3 < days_until <= max(7, seed_lead_days):
        return "SEED_NOW"
    if days_until <= max(7, seed_lead_days) + 25:
        return "PREP_NEXT"
    return "UPCOMING"


def _match_signals_to_anchor(
    anchor: Dict[str, Any],
    signals: List[Dict[str, Any]],
    limit: int = 4,
) -> List[Dict[str, Any]]:
    """Cross-reference recent live t_0 signals to a cultural anchor via keywords & vibe tags."""
    keywords = [str(k).lower() for k in (anchor.get("keywords") or []) if str(k).strip()]
    vibes = [str(v).lower().replace("_", " ") for v in (anchor.get("vibe_tags") or []) if str(v).strip()]
    cities = [str(c).lower().split("(")[0].strip() for c in (anchor.get("target_cities") or [])]

    matches: List[tuple[float, Dict[str, Any]]] = []
    for sig in signals:
        haystack = " ".join(
            [
                str(sig.get("ticker") or ""),
                str(sig.get("sector") or ""),
                str(sig.get("title") or ""),
                str(sig.get("summary") or ""),
                " ".join(str(s) for s in (sig.get("samples") or [])),
            ]
        ).lower()
        score = 0.0
        matched_terms: List[str] = []
        for kw in keywords:
            if len(kw) >= 3 and kw in haystack:
                score += 3.0
                matched_terms.append(kw)
        for vb in vibes:
            if len(vb) >= 4 and vb in haystack:
                score += 1.5
                matched_terms.append(vb)
        if anchor.get("scope") == "regional":
            for city in cities:
                if len(city) >= 4 and city in haystack:
                    score += 2.5
                    matched_terms.append(city)
        if score >= 3.0:
            matches.append(
                (
                    score + float(sig.get("cvs_score") or 0.0) * 0.02,
                    {
                        "signal_id": sig.get("id"),
                        "ticker": sig.get("ticker"),
                        "sector": sig.get("sector"),
                        "title": sig.get("title"),
                        "cvs_score": sig.get("cvs_score"),
                        "source_type": sig.get("source_type"),
                        "captured_at": sig.get("captured_at"),
                        "matched_terms": sorted(set(matched_terms))[:4],
                    },
                )
            )
    matches.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in matches[:limit]]


def _match_project_tracks_to_anchor(
    anchor: Dict[str, Any],
    project: Optional[Dict[str, Any]],
    limit: int = 2,
) -> List[Dict[str, Any]]:
    """Rank client project tracks against an anchor's mood, vibe tags, and format archetypes."""
    if not project:
        return []
    tracks = list(project.get("catalog_tracks") or [])
    if not tracks:
        return []
    anchor_vibes = {str(v).lower() for v in (anchor.get("vibe_tags") or [])}
    anchor_formats = {str(f).lower() for f in (anchor.get("format_archetypes") or [])}
    anchor_text = " ".join(
        [
            str(anchor.get("name") or ""),
            str(anchor.get("spotify_billboard_angle") or ""),
            " ".join(anchor_vibes),
            " ".join(anchor_formats),
        ]
    ).lower()

    scored: List[tuple[float, int, Dict[str, Any]]] = []
    for idx, tr in enumerate(tracks):
        score = 1.0 if str(tr.get("status") or "").lower() == "priority_push" else 0.0
        for tag in tr.get("vibe_tags") or []:
            tl = str(tag).lower()
            if tl in anchor_vibes:
                score += 4.0
            elif tl.replace("_", " ") in anchor_text:
                score += 2.0
        for arch in tr.get("format_archetypes") or []:
            al = str(arch).lower()
            if al in anchor_formats:
                score += 3.0
            elif al.replace("_", " ") in anchor_text:
                score += 1.5
        scored.append(
            (
                score,
                -idx,
                {
                    "title": tr.get("title"),
                    "artist": tr.get("artist"),
                    "status": tr.get("status"),
                    "clip_timestamp": tr.get("clip_timestamp"),
                    "match_score": round(score, 1),
                },
            )
        )
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [item[2] for item in scored[:limit] if item[0] > 0]


def build_timeline_workspace(
    db: TerminalDB,
    project: Optional[Dict[str, Any]] = None,
    ref_date: Optional[date] = None,
    timeline_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Build the live Cultural Timeline & Lineage Tree workspace."""
    today = ref_date or datetime.now(timezone.utc).date()
    cfg = load_cultural_timeline(timeline_path=timeline_path)
    cities_registry = list(cfg.get("spotify_billboard_cities") or [])
    seasons = list(cfg.get("seasonal_moods") or [])
    anchors = list(cfg.get("anchors") or [])

    current_season = next(
        (s for s in seasons if today.month in (s.get("months") or [])),
        seasons[0] if seasons else {},
    )
    season_by_id = {str(s.get("id")): s for s in seasons}

    recent_signals = db.list_signals(limit=80)
    custom_catalysts = db.list_timeline_catalysts(limit=100)

    # Group custom catalysts by parent_anchor_id (family-tree children)
    children_by_anchor: Dict[str, List[Dict[str, Any]]] = {}
    standalone_custom: List[Dict[str, Any]] = []
    for cat in custom_catalysts:
        ev_date_str = str(cat.get("event_date") or "")
        try:
            ev_date = date.fromisoformat(ev_date_str[:10])
            days_until = (ev_date - today).days
        except ValueError:
            ev_date = today
            days_until = 0
        seed_lead = int(cat.get("seed_lead_days") or 21)
        status = _classify_window(days_until, duration_days=3, seed_lead_days=seed_lead)
        enriched = {
            **cat,
            "next_date": ev_date.isoformat(),
            "days_until": days_until,
            "window_status": status,
        }
        parent_id = str(cat.get("parent_anchor_id") or "").strip()
        if parent_id:
            children_by_anchor.setdefault(parent_id, []).append(enriched)
        else:
            standalone_custom.append(enriched)

    nodes: List[Dict[str, Any]] = []
    for anchor in anchors:
        occ_date, days_until = _next_occurrence_and_delta(
            month=int(anchor["month"]),
            day=int(anchor["day"]),
            duration_days=int(anchor.get("duration_days") or 3),
            ref_date=today,
        )
        seed_lead = int(anchor.get("seed_lead_days") or 25)
        duration = int(anchor.get("duration_days") or 3)
        status = _classify_window(days_until, duration, seed_lead)
        season_info = season_by_id.get(str(anchor.get("season_mood") or ""), {})
        linked_signals = _match_signals_to_anchor(anchor, recent_signals, limit=4)
        matched_tracks = _match_project_tracks_to_anchor(anchor, project, limit=2)
        child_catalysts = children_by_anchor.get(str(anchor["id"]), [])

        nodes.append(
            {
                "id": anchor["id"],
                "name": anchor["name"],
                "scope": anchor.get("scope", "national"),
                "month": int(anchor["month"]),
                "day": int(anchor["day"]),
                "next_date": occ_date.isoformat(),
                "days_until": days_until,
                "duration_days": duration,
                "seed_lead_days": seed_lead,
                "window_status": status,
                "season_mood": anchor.get("season_mood", ""),
                "season_label": season_info.get("label", ""),
                "weather_vibe": season_info.get("weather_vibe", ""),
                "first_mover_cohort": anchor.get("first_mover_cohort", ""),
                "target_cities": list(anchor.get("target_cities") or []),
                "spotify_billboard_angle": anchor.get("spotify_billboard_angle", ""),
                "vibe_tags": list(anchor.get("vibe_tags") or []),
                "format_archetypes": list(anchor.get("format_archetypes") or []),
                "linked_signals": linked_signals,
                "matched_tracks": matched_tracks,
                "child_catalysts": child_catalysts,
                "is_custom": False,
            }
        )

    # Include standalone custom catalysts in the chronological timeline too
    for cat in standalone_custom:
        nodes.append(
            {
                "id": f"custom-{cat['id']}",
                "custom_id": cat["id"],
                "name": cat["name"],
                "scope": cat.get("scope") or "custom",
                "month": int(cat["next_date"][5:7]),
                "day": int(cat["next_date"][8:10]),
                "next_date": cat["next_date"],
                "days_until": cat["days_until"],
                "duration_days": 3,
                "seed_lead_days": int(cat.get("seed_lead_days") or 21),
                "window_status": cat["window_status"],
                "season_mood": current_season.get("id", ""),
                "season_label": "Custom Real-Time Catalyst",
                "weather_vibe": "",
                "first_mover_cohort": cat.get("first_mover_cohort") or "Custom / Real-Time Branch",
                "target_cities": list(cat.get("target_cities") or []),
                "spotify_billboard_angle": cat.get("notes") or "",
                "vibe_tags": list(cat.get("vibe_tags") or []),
                "format_archetypes": [],
                "linked_signals": [],
                "matched_tracks": _match_project_tracks_to_anchor(cat, project, limit=2),
                "child_catalysts": [],
                "project_id": cat.get("project_id") or "",
                "is_custom": True,
            }
        )

    # Sort chronologically from today (closest upcoming first)
    nodes.sort(key=lambda n: (n["days_until"], n["name"]))

    active_seeding = [n for n in nodes if n["window_status"] in ("PEAK_NOW", "SEED_NOW")]
    prep_next = [n for n in nodes if n["window_status"] == "PREP_NEXT"]

    # Tally top priority Spotify/Billboard cities across the active seeding window
    city_counts: Dict[str, int] = {}
    for n in active_seeding or prep_next[:4]:
        for c in n.get("target_cities") or []:
            city_counts[c] = city_counts.get(c, 0) + 1
    priority_cities_now = [
        {"city": city, "active_waves": cnt}
        for city, cnt in sorted(city_counts.items(), key=lambda kv: (-kv[1], kv[0]))[:8]
    ]

    return {
        "reference_date": today.isoformat(),
        "current_season": current_season,
        "summary": {
            "total_anchors": len(anchors),
            "custom_catalysts": len(custom_catalysts),
            "peak_now_count": sum(1 for n in nodes if n["window_status"] == "PEAK_NOW"),
            "seed_now_count": sum(1 for n in nodes if n["window_status"] == "SEED_NOW"),
            "prep_next_count": len(prep_next),
            "linked_signal_branches": sum(len(n.get("linked_signals") or []) for n in nodes),
        },
        "priority_cities_now": priority_cities_now,
        "active_seeding_window": active_seeding,
        "prep_next_window": prep_next[:6],
        "timeline_nodes": nodes,
        "spotify_billboard_cities": cities_registry,
        "seasonal_moods": seasons,
        "custom_catalysts": custom_catalysts,
    }


def get_compact_quant_timeline_context(
    db: TerminalDB,
    project: Optional[Dict[str, Any]] = None,
    ref_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Return a compact token-efficient cultural timeline snapshot for Gemini Quant & Brief prompts."""
    ws = build_timeline_workspace(db=db, project=project, ref_date=ref_date)
    active = ws.get("active_seeding_window") or []
    prep = ws.get("prep_next_window") or []
    return {
        "reference_date": ws["reference_date"],
        "current_season": {
            "label": (ws.get("current_season") or {}).get("label"),
            "weather_vibe": (ws.get("current_season") or {}).get("weather_vibe"),
            "collective_mood": (ws.get("current_season") or {}).get("collective_mood"),
            "winning_song_vibes": (ws.get("current_season") or {}).get("winning_song_vibes"),
        },
        "priority_spotify_cities_now": [c["city"] for c in (ws.get("priority_cities_now") or [])[:6]],
        "upcoming_regional_sports": [
            {
                "name": c.get("name"),
                "event_date": c.get("event_date"),
                "target_cities": c.get("target_cities") or [],
                "source": c.get("source"),
            }
            for c in (ws.get("custom_catalysts") or [])
            if str(c.get("scope") or "") == "sports"
            and 0 <= (date.fromisoformat(str(c.get("event_date") or ws["reference_date"])[:10]) - (ref_date or datetime.now(timezone.utc).date())).days <= 14
        ][:6],
        "seed_now_waves": [
            {
                "id": n["id"],
                "name": n["name"],
                "scope": n["scope"],
                "status": n["window_status"],
                "days_until": n["days_until"],
                "next_date": n["next_date"],
                "first_mover_cohort": n["first_mover_cohort"],
                "target_cities": n["target_cities"][:5],
                "spotify_billboard_angle": n["spotify_billboard_angle"],
                "vibe_tags": n["vibe_tags"][:5],
                "matched_tracks": [f"{t['artist']} — {t['title']}" for t in (n.get("matched_tracks") or [])],
            }
            for n in (active[:4] if active else prep[:3])
        ],
    }


# ------------------------------------------------------------------
# Live Pro & College Sports Schedule Sync (ESPN Public API — Free)
# ------------------------------------------------------------------
ESPN_LEAGUES: List[Dict[str, str]] = [
    {"code": "NFL", "path": "football/nfl", "label": "NFL", "college": "0"},
    {"code": "CFB", "path": "football/college-football", "label": "College Football", "college": "1"},
    {"code": "NBA", "path": "basketball/nba", "label": "NBA", "college": "0"},
    {"code": "NCAAM", "path": "basketball/mens-college-basketball", "label": "Men's College Basketball", "college": "1"},
    {"code": "NCAAW", "path": "basketball/womens-college-basketball", "label": "Women's College Basketball", "college": "1"},
    {"code": "MLB", "path": "baseball/mlb", "label": "MLB", "college": "0"},
    {"code": "NHL", "path": "hockey/nhl", "label": "NHL", "college": "0"},
]

VENUE_CITY_TO_SPOTIFY: Dict[str, str] = {
    "los angeles": "Los Angeles",
    "inglewood": "Los Angeles",
    "anaheim": "Los Angeles",
    "pasadena": "Los Angeles",
    "new york": "New York City",
    "brooklyn": "New York City",
    "bronx": "New York City",
    "queens": "New York City",
    "east rutherford": "New York City",
    "atlanta": "Atlanta",
    "chicago": "Chicago",
    "evanston": "Chicago",
    "houston": "Houston",
    "dallas": "Dallas-Fort Worth",
    "arlington": "Dallas-Fort Worth",
    "fort worth": "Dallas-Fort Worth",
    "miami": "Miami",
    "miami gardens": "Miami",
    "sunrise": "Miami",
    "nashville": "Nashville",
    "phoenix": "Phoenix",
    "glendale": "Phoenix",
    "tempe": "Phoenix",
    "austin": "Austin",
    "las vegas": "Las Vegas",
    "paradise": "Las Vegas",
    "san francisco": "Bay Area",
    "oakland": "Bay Area",
    "santa clara": "Bay Area",
    "san jose": "Bay Area",
    "berkeley": "Bay Area",
    "stanford": "Bay Area",
    "washington": "DMV (DC/Baltimore)",
    "landover": "DMV (DC/Baltimore)",
    "baltimore": "DMV (DC/Baltimore)",
    "college park": "DMV (DC/Baltimore)",
    "philadelphia": "Philadelphia",
    "new orleans": "New Orleans",
    "seattle": "Seattle",
}


def _map_venue_to_spotify_city(raw_city: str) -> Optional[str]:
    clean = str(raw_city or "").strip().lower()
    if not clean:
        return None
    if clean in VENUE_CITY_TO_SPOTIFY:
        return VENUE_CITY_TO_SPOTIFY[clean]
    for k, v in VENUE_CITY_TO_SPOTIFY.items():
        if k in clean:
            return v
    return None


def _default_espn_fetcher(league_path: str, start_ymd: str, end_ymd: str, timeout: int = 12) -> Dict[str, Any]:
    url = (
        f"https://site.api.espn.com/apis/site/v2/sports/{league_path}/scoreboard"
        f"?dates={start_ymd}-{end_ymd}&limit=50"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "IPX-Terminal/0.2 (+https://github.com/Beef1498/IPX-Terminal)"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _infer_parent_sports_anchor(league_code: str, ev_date: date, event_name: str) -> str:
    nl = event_name.lower()
    m = ev_date.month
    if league_code == "CFB":
        if "championship" in nl or m == 12:
            return "cfb_rivalry_and_conf_championships"
        if m == 1:
            return "cfp_national_championship"
        if m in (8, 9):
            return "college_football_kickoff"
    if league_code == "NFL":
        if "super bowl" in nl:
            return "super_bowl_sunday"
        if m == 1:
            return "nfl_playoffs_conf_champ"
        if m == 9:
            return "labor_day_nfl_kickoff"
    if league_code in ("NCAAM", "NCAAW"):
        if m == 3:
            return "march_madness"
        if m == 4:
            return "ncaa_final_four"
    if league_code == "NBA":
        if m == 2 and "all-star" in nl:
            return "nba_all_star_weekend"
        if m in (4, 5):
            return "nba_nhl_playoffs_tipoff"
        if m == 6:
            return "nba_stanley_cup_finals"
    if league_code == "MLB":
        if m in (3, 4):
            return "mlb_opening_day"
        if m == 10:
            return "mlb_world_series"
    if league_code == "NHL":
        if m in (4, 5):
            return "nba_nhl_playoffs_tipoff"
        if m == 6:
            return "nba_stanley_cup_finals"
    return ""


def sync_espn_sports_schedules(
    db: TerminalDB,
    days_ahead: int = 21,
    leagues: Optional[List[str]] = None,
    max_per_league: int = 4,
    ref_date: Optional[date] = None,
    fetcher: Optional[Callable[[str, str, str], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pull upcoming marquee Pro & College Sports matchups from ESPN and branch them onto the Timeline Tree.

    Prioritizes:
    - Championships, Playoffs, Bowl Games, and Ranked Top-25 College matchups
    - Games hosted in Tier 1/2 Spotify/Billboard music-seeding cities
    Deduplicates cleanly against existing timeline_catalysts.
    """
    today = ref_date or datetime.now(timezone.utc).date()
    end_day = today + timedelta(days=max(3, min(45, int(days_ahead))))
    start_ymd = today.strftime("%Y%m%d")
    end_ymd = end_day.strftime("%Y%m%d")

    allowed = {c.upper() for c in leagues} if leagues else None
    fetch_fn = fetcher or _default_espn_fetcher

    existing = db.list_timeline_catalysts(limit=500)
    existing_keys = {
        (str(c.get("name") or "").strip().lower(), str(c.get("event_date") or "")[:10])
        for c in existing
    }

    added: List[Dict[str, Any]] = []
    skipped_existing = 0
    errors: List[str] = []

    for lg in ESPN_LEAGUES:
        code = lg["code"]
        if allowed and code not in allowed:
            continue
        try:
            data = fetch_fn(lg["path"], start_ymd, end_ymd)
        except Exception as exc:
            errors.append(f"{code}: {exc}")
            continue

        events = data.get("events") or []
        scored_events: List[tuple[float, Dict[str, Any]]] = []
        is_college = lg["college"] == "1"

        for ev in events:
            raw_date = str(ev.get("date") or "")[:10]
            if len(raw_date) != 10:
                continue
            try:
                ev_dt = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if ev_dt < today:
                continue

            ev_name = str(ev.get("shortName") or ev.get("name") or "").strip()
            if not ev_name:
                continue

            comps = ev.get("competitions") or []
            comp0 = comps[0] if comps else {}
            venue = comp0.get("venue") or {}
            addr = venue.get("address") or {}
            raw_city = str(addr.get("city") or "").strip()
            spotify_city = _map_venue_to_spotify_city(raw_city)

            notes_list = [str(n.get("headline") or "") for n in (comp0.get("notes") or []) if n.get("headline")]
            headline_note = notes_list[0] if notes_list else ""
            hl_lower = f"{ev_name} {headline_note}".lower()

            # Check college Top-25 ranks
            ranked_count = 0
            for c_team in comp0.get("competitors") or []:
                cur_rank = (c_team.get("curatedRank") or {}).get("current")
                if isinstance(cur_rank, int) and 1 <= cur_rank <= 25:
                    ranked_count += 1

            is_marquee = any(
                kw in hl_lower
                for kw in (
                    "championship", "playoff", "final", "bowl", "semifinal", "quarterfinal",
                    "wild card", "divisional", "all-star", "classic", "invitational", "rivalry",
                    "world series", "stanley cup", "super bowl", "tournament",
                )
            )
            # For college sports, keep marquee/ranked games or games in top Spotify cities
            if is_college and not (is_marquee or ranked_count >= 1):
                continue

            priority = 0.0
            if is_marquee:
                priority += 10.0
            priority += ranked_count * 4.0
            if spotify_city:
                priority += 5.0
            if (comp0.get("broadcasts") or []):
                priority += 1.5

            # Prefer sooner games slightly within equal importance
            days_out = (ev_dt - today).days
            priority -= days_out * 0.05

            scored_events.append(
                (
                    priority,
                    {
                        "league": code,
                        "league_label": lg["label"],
                        "name": f"[{code}] {ev_name}" + (f" — {headline_note}" if headline_note and len(headline_note) <= 55 else ""),
                        "event_date": raw_date,
                        "ev_dt": ev_dt,
                        "spotify_city": spotify_city,
                        "raw_city": raw_city,
                        "venue_name": str(venue.get("fullName") or ""),
                        "is_college": is_college,
                        "ranked_count": ranked_count,
                        "headline_note": headline_note,
                    },
                )
            )

        scored_events.sort(key=lambda item: item[0], reverse=True)
        for _, item in scored_events[: max(1, int(max_per_league))]:
            dedup_key = (item["name"].lower(), item["event_date"])
            if dedup_key in existing_keys:
                skipped_existing += 1
                continue
            target_cities = [item["spotify_city"]] if item["spotify_city"] else ([item["raw_city"]] if item["raw_city"] else [])
            parent_id = _infer_parent_sports_anchor(code, item["ev_dt"], item["name"])
            note_parts = [f"Live {item['league_label']} schedule sync (ESPN)."]
            if item["venue_name"]:
                note_parts.append(f"Venue: {item['venue_name']} ({item['raw_city']}).")
            if item["spotify_city"]:
                note_parts.append(f"Spotify City Target: {item['spotify_city']}.")
            vibes = ["sports", "hype", "win", "grit"]
            if item["is_college"]:
                vibes.append("party")
            saved = db.create_timeline_catalyst(
                name=item["name"],
                event_date=item["event_date"],
                scope="sports",
                parent_anchor_id=parent_id,
                seed_lead_days=14,
                target_cities=target_cities,
                vibe_tags=vibes,
                first_mover_cohort=f"{item['league_label']} Highlight Clippers & {'College Campus' if item['is_college'] else 'City Fanbase'} Accounts",
                notes=" ".join(note_parts),
                source=f"espn_{code.lower()}",
            )
            existing_keys.add(dedup_key)
            added.append(saved)

    return {
        "window_start": today.isoformat(),
        "window_end": end_day.isoformat(),
        "added_count": len(added),
        "skipped_existing": skipped_existing,
        "added": added,
        "errors": errors,
    }
