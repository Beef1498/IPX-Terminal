"""Command-line interface for IPX Terminal."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from ipx_terminal.config import (
    DEFAULT_DB_PATH,
    DEFAULT_EXPORT_DIR,
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    VALID_SECTORS,
    VALID_SOURCES,
)
from ipx_terminal.ai_scorer import DEFAULT_AI_BASE_URL, DEFAULT_AI_MODEL, score_signal_with_ai
from ipx_terminal.db import TerminalDB
from ipx_terminal.exporter import export_resolved_to_jsonl, parse_concepts_text
from ipx_terminal.ingest import (
    auto_pair_creator_ab,
    fetch_prediction_markets,
    ingest_gdelt,
    ingest_url,
    ingest_youtube,
    recheck_prediction_metrics,
    seed_demo_workspace,
    sweep_watchlist,
)
from ipx_terminal.server import run_server


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipx-terminal",
        description="IPX Terminal — Bloomberg-style Content IP workstation and IPX-Eval outcome logger.",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite WAL database (default: {DEFAULT_DB_PATH})",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="Initialize the SQLite WAL database.")

    p_seed = sub.add_parser("seed", help="Seed realistic Content IP entities, signals, and sample predictions.")
    p_seed.add_argument("--force", action="store_true", help="Seed even if entities already exist.")

    p_top = sub.add_parser("top", help="Show Top Cultural Velocity movers (TOP).")
    p_top.add_argument("--sector", default="ALL", help="Filter by sector (default: ALL).")
    p_top.add_argument("--limit", type=int, default=15, help="Max rows to display.")

    p_man = sub.add_parser("ingest-manual", help="Capture a manual t_0 signal snapshot.")
    p_man.add_argument("--ticker", required=True)
    p_man.add_argument("--title", required=True)
    p_man.add_argument("--summary", required=True)
    p_man.add_argument("--platforms", required=True, help="Comma-separated platforms, e.g. 'TikTok,X'")
    p_man.add_argument("--sector", default="POP", choices=VALID_SECTORS)
    p_man.add_argument("--entity-name", default=None)
    p_man.add_argument("--owner", default="Independent / Unknown")
    p_man.add_argument("--metrics-json", default="{}", help="JSON object of t_0 metrics.")
    p_man.add_argument("--samples", default="", help="Semicolon-separated verbatim sample quotes.")
    p_man.add_argument("--url", default="")

    p_gdelt = sub.add_parser("ingest-gdelt", help="Ingest live news velocity from GDELT DOC 2.0.")
    p_gdelt.add_argument("--ticker", required=True)
    p_gdelt.add_argument("--query", required=True)
    p_gdelt.add_argument("--sector", default="POP", choices=VALID_SECTORS)
    p_gdelt.add_argument("--entity-name", default=None)
    p_gdelt.add_argument("--timespan", default="24h")
    p_gdelt.add_argument("--max-records", type=int, default=12)

    p_yt = sub.add_parser("ingest-youtube", help="Ingest live video stats from YouTube Data API v3.")
    p_yt.add_argument("--ticker", required=True)
    p_yt.add_argument("--query", required=True)
    p_yt.add_argument("--sector", default="CREATORS", choices=VALID_SECTORS)
    p_yt.add_argument("--entity-name", default=None)
    p_yt.add_argument("--max-results", type=int, default=5)

    p_url = sub.add_parser("ingest-url", help="Auto-ingest metadata from a YouTube, TikTok, X, or web URL.")
    p_url.add_argument("--url", required=True)
    p_url.add_argument("--ticker", required=True)
    p_url.add_argument("--sector", default="POP", choices=VALID_SECTORS)
    p_url.add_argument("--entity-name", default=None)
    p_url.add_argument("--owner", default="Independent / Unknown")
    p_url.add_argument("--notes", default="")

    p_swp = sub.add_parser("sweep", help="Sweep GDELT across watchlist entities and report overdue 48-72h calls.")
    p_swp.add_argument("--timespan", default="24h")
    p_swp.add_argument("--max-records", type=int, default=8)
    p_swp.add_argument("--limit", type=int, default=5, help="Max watchlist entities to sweep per run.")
    p_swp.add_argument("--delay", type=float, default=6.5, help="Delay in seconds between GDELT requests.")
    p_swp.add_argument("--tickers", default=None, help="Optional comma-separated tickers to sweep.")
    p_swp.add_argument(
        "--include-empty",
        action="store_true",
        help="Also insert 0-article GDELT signals (skipped by default to avoid CVS artifacts).",
    )

    p_rec = sub.add_parser(
        "recheck",
        help="Re-fetch live social metrics for a logged prediction URL (uses SCRAPECREATORS_API_KEY when set).",
    )
    p_rec.add_argument("--prediction-id", type=int, required=True)
    p_rec.add_argument("--api-key", default=None, help="Optional ScrapeCreators API key (defaults to SCRAPECREATORS_API_KEY).")

    p_aab = sub.add_parser(
        "auto-ab",
        help="1-click ScrapeCreators creator fetch -> balanced blind Winner-vs-Flop A/B JSONL for IPX-Eval v0.5-creative.",
    )
    p_aab.add_argument("--platform", default="TikTok", choices=("TikTok", "YouTube Shorts", "YouTube", "Instagram Reels", "Instagram", "X"))
    p_aab.add_argument("--handle", required=True, help="Creator handle (e.g. @mrbeast or handle without @).")
    p_aab.add_argument("--sector", default="CREATORS", choices=VALID_SECTORS)
    p_aab.add_argument("--pairs", type=int, default=5, help="Max blind Winner-vs-Flop pairs to build (default: 5).")
    p_aab.add_argument("--min-ratio", type=float, default=2.0, help="Min winner/flop performance multiplier (default: 2.0).")
    p_aab.add_argument("--out-dir", type=Path, default=None, help="Output directory (defaults to IPX-Eval/datasets/v0.5-creative).")

    p_mkts = sub.add_parser(
        "markets",
        help="Fetch live Polymarket & Kalshi Content IP prediction markets (zero API keys required).",
    )
    p_mkts.add_argument("--source", default="all", choices=("all", "polymarket", "kalshi"))
    p_mkts.add_argument("--query", default="", help="Optional keyword filter.")
    p_mkts.add_argument("--all-categories", action="store_true", help="Include non-IP/culture markets too.")
    p_mkts.add_argument("--limit", type=int, default=15)

    p_ai = sub.add_parser("ask-ai", help="Run live AI t_0 scoring against a captured signal (Gemini / DGX Spark).")
    p_ai.add_argument("--signal-id", type=int, required=True)
    p_ai.add_argument("--category", required=True, choices=VALID_CATEGORIES)
    p_ai.add_argument("--model", default=DEFAULT_AI_MODEL)
    p_ai.add_argument("--base-url", default=DEFAULT_AI_BASE_URL)

    p_log = sub.add_parser("log", help="Log a prediction against a captured t_0 signal (freezes snapshot).")
    p_log.add_argument("--signal-id", type=int, required=True)
    p_log.add_argument("--category", required=True, choices=VALID_CATEGORIES)
    p_log.add_argument("--label", required=True, help="Predicted canonical label.")
    p_log.add_argument("--confidence", type=float, default=0.75)
    p_log.add_argument("--window-hours", type=int, default=48)
    p_log.add_argument("--difficulty", default="medium", choices=VALID_DIFFICULTIES)
    p_log.add_argument("--source", default="ipx_terminal_export", choices=VALID_SOURCES)
    p_log.add_argument("--question", default=None)
    p_log.add_argument("--notes", default="")

    p_res = sub.add_parser("resolve", help="Resolve a logged prediction after the 48-72h outcome window.")
    p_res.add_argument("--prediction-id", type=int, required=True)
    p_res.add_argument("--label", required=True, help="Verified ground-truth label.")
    p_res.add_argument("--secondary-label", default=None)
    p_res.add_argument(
        "--concepts",
        required=True,
        help="Semicolon-separated concept groups, comma-separated aliases (e.g. '12x, baseline; save rate').",
    )
    p_res.add_argument("--rationale", required=True)
    p_res.add_argument("--window-hours", type=int, default=None)
    p_res.add_argument("--outcome-metrics-json", default="{}")

    p_exp = sub.add_parser("export", help="Export resolved predictions to IPX-Eval JSONL files.")
    p_exp.add_argument("--out-dir", type=Path, default=DEFAULT_EXPORT_DIR)
    p_exp.add_argument("--version", default="0.4")
    p_exp.add_argument("--category", default=None, choices=VALID_CATEGORIES)

    p_srv = sub.add_parser("serve", help="Start the local 4-pane IPX Terminal Launchpad Web UI.")
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8765)
    p_srv.add_argument("--seed-if-empty", action="store_true", help="Auto-seed demo IP data if DB is empty.")

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    db = TerminalDB(db_path=args.db)

    if args.command == "init":
        print(f"Initialized IPX Terminal database at {db.db_path}")
        return 0

    if args.command == "seed":
        stats = seed_demo_workspace(db, force=args.force)
        print(f"Seeded workspace -> {json.dumps(stats)}")
        return 0

    if args.command == "top":
        movers = db.get_top_movers(sector=None if args.sector.upper() == "ALL" else args.sector, limit=args.limit)
        if not movers:
            print("No IP entities found. Run `python3 -m ipx_terminal seed` to populate demo data.")
            return 0
        print(f"{'TICKER':<12} {'SECTOR':<9} {'CVS':>6} {'DELTA':>7} {'CONTAGION':>10} {'STAGE':<20} NAME")
        print("-" * 92)
        for m in movers:
            delta_str = f"{m['cvs_delta']:+0.1f}"
            print(
                f"{m['ticker']:<12} {m['sector']:<9} {m['cvs_score']:>6.1f} {delta_str:>7} "
                f"{m['contagion_index']:>10.1f} {m['contagion_stage']:<20} {m['name']}"
            )
        return 0

    if args.command == "ingest-manual":
        platforms = [p.strip() for p in args.platforms.split(",") if p.strip()]
        samples = [s.strip() for s in args.samples.split(";") if s.strip()]
        metrics = json.loads(args.metrics_json) if args.metrics_json.strip() else {}
        sig = db.insert_signal(
            ticker=args.ticker,
            title=args.title,
            summary=args.summary,
            platforms=platforms,
            metrics=metrics,
            samples=samples,
            sector=args.sector,
            entity_name=args.entity_name,
            owner_holder=args.owner,
            url=args.url,
            source_type="manual",
        )
        print(f"Captured signal #{sig['id']} [{sig['ticker']}] CVS={sig['cvs_score']} Contagion={sig['contagion_index']} ({sig['contagion_stage']})")
        return 0

    if args.command == "ingest-gdelt":
        sig = ingest_gdelt(
            db=db,
            query=args.query,
            ticker=args.ticker,
            sector=args.sector,
            entity_name=args.entity_name,
            max_records=args.max_records,
            timespan=args.timespan,
        )
        print(f"Ingested GDELT signal #{sig['id']} [{sig['ticker']}] -> {sig['title']} (CVS={sig['cvs_score']})")
        return 0

    if args.command == "ingest-youtube":
        sig = ingest_youtube(
            db=db,
            query=args.query,
            ticker=args.ticker,
            sector=args.sector,
            entity_name=args.entity_name,
            max_results=args.max_results,
        )
        print(f"Ingested YouTube signal #{sig['id']} [{sig['ticker']}] -> {sig['title']} (CVS={sig['cvs_score']})")
        return 0

    if args.command == "ingest-url":
        sig = ingest_url(
            db=db,
            url=args.url,
            ticker=args.ticker,
            sector=args.sector,
            entity_name=args.entity_name,
            owner_holder=args.owner,
            notes=args.notes,
        )
        print(f"Auto-ingested URL signal #{sig['id']} [{sig['ticker']}] -> {sig['title']} (CVS={sig['cvs_score']})")
        return 0

    if args.command == "sweep":
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()] if args.tickers else None
        res = sweep_watchlist(
            db=db,
            tickers=tickers,
            timespan=args.timespan,
            max_records=args.max_records,
            delay_sec=args.delay,
            limit=args.limit,
            skip_empty=not args.include_empty,
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "recheck":
        res = recheck_prediction_metrics(
            db=db,
            prediction_id=args.prediction_id,
            api_key=args.api_key,
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "ask-ai":
        sig = db.get_signal(args.signal_id)
        if not sig:
            print(f"Signal #{args.signal_id} not found")
            return 1
        res = score_signal_with_ai(
            signal=sig,
            category=args.category,
            model=args.model,
            base_url=args.base_url,
        )
        print(json.dumps(res, indent=2))
        return 0

    if args.command == "log":
        pred = db.create_prediction(
            signal_id=args.signal_id,
            category=args.category,
            predicted_label=args.label,
            confidence=args.confidence,
            difficulty=args.difficulty,
            source=args.source,
            outcome_window_hours=args.window_hours,
            question=args.question,
            analyst_notes=args.notes,
        )
        print(f"Logged prediction #{pred['id']} ({pred['case_code']}) [{pred['ticker']}] pred={pred['predicted_label']} due={pred['due_at']}")
        return 0

    if args.command == "resolve":
        concepts = parse_concepts_text(args.concepts)
        outcome_metrics = json.loads(args.outcome_metrics_json) if args.outcome_metrics_json.strip() else {}
        pred = db.resolve_prediction(
            prediction_id=args.prediction_id,
            ground_truth_label=args.label,
            secondary_label=args.secondary_label,
            required_concepts=concepts,
            rationale=args.rationale,
            outcome_window_hours=args.window_hours,
            outcome_metrics=outcome_metrics,
        )
        verdict = "CORRECT" if pred["outcome"]["prediction_correct"] else "MISSED"
        print(f"Resolved prediction #{pred['id']} ({pred['case_code']}) -> gt={args.label} [{verdict}]")
        return 0

    if args.command == "export":
        result = export_resolved_to_jsonl(
            db=db,
            out_dir=args.out_dir,
            version=args.version,
            category=args.category,
        )
        print(f"Exported {result['total_exported']} IPX-Eval cases -> {result['out_dir']}")
        for f in result["files"]:
            print(f"  - {f['category']:<12} {f['count']:>3} cases -> {f['path']}")
        if result["errors"]:
            print("Errors:")
            for err in result["errors"]:
                print(f"  ! {err}")
            return 1
        return 0

    if args.command == "auto-ab":
        res = auto_pair_creator_ab(
            platform=args.platform,
            handle=args.handle,
            sector=args.sector,
            max_pairs=args.pairs,
            min_ratio=args.min_ratio,
            out_dir=args.out_dir,
        )
        print(
            f"Fetched {res['posts_fetched']} posts for {res['handle']} ({res['platform']}) -> "
            f"built {res['pairs_created']} blind A/B pairs"
        )
        if res["out_path"]:
            print(f"Saved -> {res['out_path']}")
        return 0

    if args.command == "markets":
        res = fetch_prediction_markets(
            source=args.source,
            query=args.query,
            ip_only=not args.all_categories,
            limit=args.limit,
        )
        print(f"Live Prediction Markets ({res['count']} loaded; source={res['source']}):")
        for m in res["markets"]:
            odds = f"{m['yes_pct']:5.1f}%" if m["yes_pct"] is not None else "  n/a"
            print(f"  [{m['source']:<10}] {m['sector']:<8} {odds} YES  vol24=${m['volume_24h']:>10,.0f}  {m['title'][:75]}")
        if res["errors"]:
            for err in res["errors"]:
                print(f"  ! {err}")
        return 0

    if args.command == "serve":
        if args.seed_if_empty:
            seed_demo_workspace(db, force=False)
        run_server(db=db, host=args.host, port=args.port)
        return 0

    return 0
