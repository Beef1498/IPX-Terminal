"""Client Project & Music Catalog workspace loader for IPX Terminal (e.g. Street Mob / Fuerza Regida)."""

from __future__ import annotations

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
