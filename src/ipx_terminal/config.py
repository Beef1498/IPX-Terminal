"""Shared constants, IPX-Eval schema enums, and Bloomberg function codes."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Dict, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = Path(os.environ.get("IPX_DB_PATH", str(PROJECT_ROOT / "data" / "ipx_terminal.db")))
DEFAULT_EXPORT_DIR = PROJECT_ROOT / "exports" / "ipx-eval"
DEFAULT_SCHEMA_PATH = PROJECT_ROOT / "schemas" / "eval_case.schema.json"
DEFAULT_ORCHESTRATION_PATH = PROJECT_ROOT / "data" / "orchestration.json"
APP_VERSION = "0.2.0"

DEFAULT_GITHUB_REPOS: Tuple[str, ...] = (
    "Beef1498/IPX-Terminal",
    "Beef1498/IPX-eval",
)
DEFAULT_EVAL_REPO = "Beef1498/IPX-eval"


def load_dotenv(dotenv_path: Optional[Path] = None) -> None:
    """Load KEY=VALUE pairs from local .env without overriding existing environment variables."""
    path = dotenv_path or (PROJECT_ROOT / ".env")
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_dotenv()

# Exact IPX-Eval contract enums (kept 1:1 with eval_case.schema.json)
VALID_CATEGORIES: Tuple[str, ...] = ("breakout", "lineage", "contagion", "ip_catalyst")
VALID_SECTORS: Tuple[str, ...] = (
    "POP",
    "MUSIC",
    "FILM_TV",
    "GAMING",
    "CREATORS",
    "SPORTS",
    "DEALS",
)
VALID_SOURCES: Tuple[str, ...] = (
    "curated_seed",
    "ipx_terminal_export",
    "ipx_live_prediction",
    "content_factory_feedback",
)
VALID_DIFFICULTIES: Tuple[str, ...] = ("easy", "medium", "hard")

CATEGORY_LABELS: Dict[str, Tuple[str, ...]] = {
    "breakout": ("breakout", "watch", "noise"),
    "lineage": ("audio_flip", "visual_parody", "character_transplant", "format_mashup"),
    "contagion": ("echo_chamber", "emerging_contagion", "mainstream_breakout"),
    "ip_catalyst": (
        "catalog_revival",
        "licensing_merch",
        "ma_deal",
        "brand_partnership",
        "rights_risk",
    ),
}

ID_PATTERN = re.compile(r"^ipx-(breakout|lineage|contagion|ip_catalyst)-[0-9]{3,}$")

DEFAULT_QUESTIONS: Dict[str, str] = {
    "breakout": (
        "Based on this t_0 signal snapshot, classify whether this IP/format will break out "
        "over the next 48-72 hours (breakout, watch, or noise) and identify the key driving signals."
    ),
    "lineage": (
        "Trace the format lineage: classify the primary mutation type "
        "(audio_flip, visual_parody, character_transplant, or format_mashup), identify the "
        "originating IP or pop-culture moment, and explain how it mutated."
    ),
    "contagion": (
        "Classify the cross-platform spread stage (echo_chamber, emerging_contagion, or "
        "mainstream_breakout) and explain the audience overlap and cross-platform dynamics."
    ),
    "ip_catalyst": (
        "Classify the primary IP/commercial catalyst (catalog_revival, licensing_merch, "
        "ma_deal, brand_partnership, or rights_risk) and explain the rights-holder and "
        "commercial valuation implications."
    ),
}

FUNCTION_CODES: Dict[str, str] = {
    "TOP": "Top Cultural Velocity movers and breakout tape",
    "GP": "Cultural Velocity (CVS) & Cross-Platform Contagion graph",
    "DES": "IP Entity profile, rights holder, aliases, and catalysts",
    "WIRE": "Live t_0 signal ingestion tape and manual capture",
    "LOG": "Prediction logger and 48-72h outcome resolution desk",
    "BRIEFS": "Creative Brief generator & Content Factory post outcome logger",
    "MKTS": "Live Polymarket & Kalshi Content IP prediction markets",
    "MAP": "Live 50-state US Cultural Contagion Map (Google Trends geo spread)",
    "EXPORT": "Schema-validated IPX-Eval JSONL export",
    "CN": "Catalyst and news signals for active ticker",
    "MA": "Deals, licensing, and M&A sector filter",
    "COMP": "Peer comparison within the active sector",
    "ALRT": "High-velocity alerts and overdue outcome resolutions",
    "HELP": "Open the Bloomberg-style operator's key & command cheat-sheet",
}

SECTOR_COLORS: Dict[str, str] = {
    "POP": "#f59e0b",
    "MUSIC": "#22d3ee",
    "FILM_TV": "#a78bfa",
    "GAMING": "#34d399",
    "CREATORS": "#fb7185",
    "SPORTS": "#60a5fa",
    "DEALS": "#facc15",
}
