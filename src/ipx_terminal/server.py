"""Zero-dependency local HTTP server for the IPX Terminal 4-pane Launchpad Web UI and REST API."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.parse

from ipx_terminal.config import (
    CATEGORY_LABELS,
    DEFAULT_EXPORT_DIR,
    DEFAULT_QUESTIONS,
    FUNCTION_CODES,
    SECTOR_COLORS,
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    VALID_SECTORS,
    VALID_SOURCES,
)
from ipx_terminal.ai_scorer import (
    DEFAULT_AI_BASE_URL,
    DEFAULT_AI_MODEL,
    generate_creative_brief,
    score_signal_with_ai,
)
from ipx_terminal.db import TerminalDB, normalize_ticker
from ipx_terminal.exporter import export_creative_feedback, export_resolved_to_jsonl, parse_concepts_text
from ipx_terminal.ingest import (
    auto_pair_creator_ab,
    fetch_prediction_markets,
    fetch_us_contagion_map,
    ingest_contagion_map_signal,
    ingest_gdelt,
    ingest_market_signal,
    ingest_url,
    recheck_prediction_metrics,
    seed_demo_workspace,
    sweep_watchlist,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def parse_command_bar(raw_command: str, db: TerminalDB) -> Dict[str, Any]:
    """Parse Bloomberg-style `<TICKER> <FUNCTION> <GO>` or `<SECTOR> TOP` commands."""
    tokens = [tok.strip().upper() for tok in raw_command.strip().split() if tok.strip()]
    if tokens and tokens[-1] == "GO":
        tokens = tokens[:-1]
    if not tokens:
        return {"action": "focus_function", "function": "TOP", "message": "Loaded TOP movers tape."}

    if tokens[0] == "SEED":
        stats = seed_demo_workspace(db, force=False)
        return {"action": "refresh", "function": "TOP", "message": f"Workspace seed: {stats}"}

    # Single token: could be a function, a sector, or a ticker
    if len(tokens) == 1:
        tok = tokens[0]
        if tok in FUNCTION_CODES:
            return {"action": "focus_function", "function": tok, "message": f"{tok}: {FUNCTION_CODES[tok]}"}
        if tok in VALID_SECTORS or tok == "ALL":
            return {"action": "filter_sector", "sector": tok, "function": "TOP", "message": f"Filtered sector -> {tok}"}
        if db.get_entity(tok):
            return {"action": "select_ticker", "ticker": tok, "function": "DES", "message": f"Loaded {tok} DES"}
        return {"action": "error", "message": f"Unknown ticker, sector, or function: '{tok}'"}

    first, second = tokens[0], tokens[1]
    if first in VALID_SECTORS or first == "ALL":
        func = second if second in FUNCTION_CODES else "TOP"
        return {
            "action": "filter_sector",
            "sector": first,
            "function": func,
            "message": f"Sector {first} -> {func}",
        }

    if second in FUNCTION_CODES:
        ent = db.get_entity(first)
        if not ent:
            return {"action": "error", "message": f"Ticker '{first}' not found in IP Graph."}
        return {
            "action": "select_ticker",
            "ticker": first,
            "function": second,
            "message": f"{first} <{second}> GO — {FUNCTION_CODES[second]}",
        }

    return {"action": "error", "message": f"Could not parse command '{raw_command}'. Try 'NVDA.IP GP' or 'MUSIC TOP'."}


def make_handler(db: TerminalDB) -> type[BaseHTTPRequestHandler]:
    class IPXHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            return

        def _send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_static(self, rel_path: str) -> None:
            target = (STATIC_DIR / rel_path).resolve()
            if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return
            mime, _ = mimetypes.guess_type(str(target))
            data = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            return json.loads(raw.decode("utf-8"))

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                self._send_static("index.html")
                return
            if path.startswith("/static/"):
                self._send_static(path[len("/static/"):])
                return

            try:
                if path == "/api/bootstrap":
                    sector = qs.get("sector", ["ALL"])[0]
                    movers = db.get_top_movers(sector=None if sector == "ALL" else sector)
                    self._send_json(
                        {
                            "config": {
                                "sectors": list(VALID_SECTORS),
                                "categories": list(VALID_CATEGORIES),
                                "category_labels": CATEGORY_LABELS,
                                "default_questions": DEFAULT_QUESTIONS,
                                "difficulties": list(VALID_DIFFICULTIES),
                                "sources": list(VALID_SOURCES),
                                "function_codes": FUNCTION_CODES,
                                "sector_colors": SECTOR_COLORS,
                                "default_export_dir": str(DEFAULT_EXPORT_DIR),
                            },
                            "stats": db.get_dashboard_stats(),
                            "movers": movers,
                            "signals": db.list_signals(
                                sector=None if sector == "ALL" else sector,
                                limit=40,
                            ),
                            "predictions": db.list_predictions(limit=60),
                            "briefs": db.list_briefs(limit=40),
                            "entities": db.list_entities(),
                        }
                    )
                    return

                if path == "/api/markets":
                    q_text = qs.get("q", [""])[0]
                    src = qs.get("source", ["all"])[0]
                    ip_only = qs.get("ip_only", ["1"])[0].lower() not in ("0", "false", "no")
                    lim = int(qs.get("limit", ["24"])[0])
                    data = fetch_prediction_markets(source=src, query=q_text, ip_only=ip_only, limit=lim)
                    self._send_json({"ok": True, **data})
                    return

                if path == "/api/contagion-map":
                    q_text = qs.get("q", [""])[0]
                    force = qs.get("refresh", ["0"])[0].lower() in ("1", "true", "yes")
                    data = fetch_us_contagion_map(query=q_text, force_refresh=force)
                    self._send_json({"ok": True, **data})
                    return

                if path.startswith("/api/ticker/"):
                    ticker = urllib.parse.unquote(path[len("/api/ticker/"):])
                    norm = normalize_ticker(ticker)
                    ent = db.get_entity(norm)
                    if not ent:
                        self._send_json({"error": f"Ticker '{norm}' not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    self._send_json(
                        {
                            "entity": ent,
                            "history": db.get_ticker_history(norm, limit=30),
                            "predictions": db.list_predictions(ticker=norm, limit=30),
                        }
                    )
                    return

                self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path

            try:
                body = self._read_json_body()

                if path == "/api/command":
                    result = parse_command_bar(str(body.get("command", "")), db)
                    self._send_json(result)
                    return

                if path == "/api/seed":
                    stats = seed_demo_workspace(db, force=bool(body.get("force", False)))
                    self._send_json({"ok": True, "seeded": stats})
                    return

                if path == "/api/signals":
                    platforms = body.get("platforms", [])
                    if isinstance(platforms, str):
                        platforms = [p.strip() for p in platforms.split(",") if p.strip()]
                    samples = body.get("samples", [])
                    if isinstance(samples, str):
                        samples = [s.strip() for s in samples.splitlines() if s.strip()]
                    metrics = body.get("metrics") or {}
                    if isinstance(metrics, str):
                        metrics = json.loads(metrics) if metrics.strip() else {}
                    sig = db.insert_signal(
                        ticker=str(body["ticker"]),
                        title=str(body["title"]),
                        summary=str(body["summary"]),
                        platforms=platforms,
                        metrics=metrics,
                        samples=samples,
                        entities_mentioned=body.get("entities_mentioned"),
                        source_type=str(body.get("source_type", "manual")),
                        captured_at=body.get("captured_at") or None,
                        url=str(body.get("url", "")),
                        sector=str(body.get("sector", "POP")),
                        entity_name=body.get("entity_name"),
                        owner_holder=str(body.get("owner_holder", "Independent / Unknown")),
                    )
                    self._send_json({"ok": True, "signal": sig}, status=HTTPStatus.CREATED)
                    return

                if path == "/api/ingest/market":
                    sig = ingest_market_signal(
                        db=db,
                        market=body.get("market") or body,
                        ticker=body.get("ticker") or None,
                        sector=body.get("sector") or None,
                    )
                    self._send_json({"ok": True, "signal": sig}, status=HTTPStatus.CREATED)
                    return

                if path == "/api/ingest/contagion-map":
                    sig = ingest_contagion_map_signal(
                        db=db,
                        cluster=body.get("cluster") or body,
                        ticker=body.get("ticker") or None,
                        sector=str(body.get("sector") or "POP"),
                    )
                    self._send_json({"ok": True, "signal": sig}, status=HTTPStatus.CREATED)
                    return

                if path == "/api/ingest/gdelt":
                    sig = ingest_gdelt(
                        db=db,
                        query=str(body["query"]),
                        ticker=str(body["ticker"]),
                        sector=str(body.get("sector", "POP")),
                        entity_name=body.get("entity_name"),
                        owner_holder=str(body.get("owner_holder", "Independent / Unknown")),
                        max_records=int(body.get("max_records", 12)),
                        timespan=str(body.get("timespan", "24h")),
                    )
                    self._send_json({"ok": True, "signal": sig}, status=HTTPStatus.CREATED)
                    return

                if path == "/api/ingest/url":
                    extra_metrics = body.get("extra_metrics") or {}
                    if isinstance(extra_metrics, str):
                        extra_metrics = json.loads(extra_metrics) if extra_metrics.strip() else {}
                    sig = ingest_url(
                        db=db,
                        url=str(body["url"]),
                        ticker=str(body["ticker"]),
                        sector=str(body.get("sector", "POP")),
                        entity_name=body.get("entity_name") or None,
                        owner_holder=str(body.get("owner_holder", "Independent / Unknown")),
                        extra_metrics=extra_metrics,
                        notes=str(body.get("notes", "")),
                    )
                    self._send_json({"ok": True, "signal": sig}, status=HTTPStatus.CREATED)
                    return

                if path == "/api/sweep":
                    result = sweep_watchlist(
                        db=db,
                        tickers=body.get("tickers"),
                        timespan=str(body.get("timespan", "24h")),
                        max_records=int(body.get("max_records", 8)),
                        delay_sec=float(body.get("delay_sec", 6.5)),
                        limit=int(body.get("limit", 5)),
                        skip_empty=bool(body.get("skip_empty", True)),
                    )
                    self._send_json({"ok": True, **result})
                    return

                if path == "/api/ai/score":
                    sig = db.get_signal(int(body["signal_id"]))
                    if not sig:
                        self._send_json({"error": "Signal not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    result = score_signal_with_ai(
                        signal=sig,
                        category=str(body["category"]),
                        question=body.get("question") or None,
                        api_key=body.get("api_key") or None,
                        base_url=body.get("base_url") or DEFAULT_AI_BASE_URL,
                        model=body.get("model") or DEFAULT_AI_MODEL,
                    )
                    self._send_json({"ok": True, "ai": result})
                    return

                if path == "/api/predictions":
                    window_raw = body.get("outcome_window_hours", 48)
                    window_val = None if window_raw in ("", None) else int(window_raw)
                    ai_conf_raw = body.get("ai_confidence")
                    ai_conf_val = None if ai_conf_raw in ("", None) else float(ai_conf_raw)
                    pred = db.create_prediction(
                        signal_id=int(body["signal_id"]),
                        category=str(body["category"]),
                        predicted_label=str(body["predicted_label"]),
                        confidence=float(body.get("confidence", 0.75)),
                        question=body.get("question") or None,
                        title=body.get("title") or None,
                        difficulty=str(body.get("difficulty", "medium")),
                        source=str(body.get("source", "ipx_terminal_export")),
                        outcome_window_hours=window_val,
                        analyst_notes=str(body.get("analyst_notes", "")),
                        ai_model=body.get("ai_model") or None,
                        ai_predicted_label=body.get("ai_predicted_label") or None,
                        ai_confidence=ai_conf_val,
                        ai_reasoning=body.get("ai_reasoning") or None,
                    )
                    self._send_json({"ok": True, "prediction": pred}, status=HTTPStatus.CREATED)
                    return

                if path.startswith("/api/predictions/") and path.endswith("/recheck"):
                    pred_id_str = path[len("/api/predictions/") : -len("/recheck")].strip("/")
                    pred_id = int(pred_id_str)
                    result = recheck_prediction_metrics(
                        db=db,
                        prediction_id=pred_id,
                        api_key=body.get("api_key") or None,
                    )
                    self._send_json({"ok": True, **result})
                    return

                if path.startswith("/api/predictions/") and path.endswith("/resolve"):
                    pred_id_str = path[len("/api/predictions/") : -len("/resolve")].strip("/")
                    pred_id = int(pred_id_str)
                    concepts = body.get("required_concepts")
                    if isinstance(concepts, str):
                        concepts = parse_concepts_text(concepts)
                    window_raw = body.get("outcome_window_hours")
                    window_val = None if window_raw in ("", None) else int(window_raw)
                    outcome_metrics = body.get("outcome_metrics") or {}
                    if isinstance(outcome_metrics, str):
                        outcome_metrics = json.loads(outcome_metrics) if outcome_metrics.strip() else {}
                    resolved = db.resolve_prediction(
                        prediction_id=pred_id,
                        ground_truth_label=str(body["ground_truth_label"]),
                        secondary_label=body.get("secondary_label") or None,
                        required_concepts=concepts or [],
                        rationale=str(body["rationale"]),
                        outcome_window_hours=window_val,
                        outcome_metrics=outcome_metrics,
                    )
                    self._send_json({"ok": True, "prediction": resolved})
                    return

                if path == "/api/export":
                    out_dir = Path(body["out_dir"]) if body.get("out_dir") else DEFAULT_EXPORT_DIR
                    version = str(body.get("version", "0.4"))
                    result = export_resolved_to_jsonl(db=db, out_dir=out_dir, version=version)
                    self._send_json({"ok": True, **result})
                    return

                if path == "/api/briefs/generate":
                    sig = db.get_signal(int(body["signal_id"]))
                    if not sig:
                        self._send_json({"error": "Signal not found"}, status=HTTPStatus.NOT_FOUND)
                        return
                    draft = generate_creative_brief(
                        signal=sig,
                        target_platform=str(body.get("target_platform", "TikTok")),
                        api_key=body.get("api_key") or None,
                        base_url=body.get("base_url") or DEFAULT_AI_BASE_URL,
                        model=body.get("model") or DEFAULT_AI_MODEL,
                    )
                    self._send_json({"ok": True, "draft": draft})
                    return

                if path == "/api/briefs":
                    beats = body.get("edit_beats", [])
                    if isinstance(beats, str):
                        beats = [b.strip() for b in beats.splitlines() if b.strip()]
                    brief = db.create_brief(
                        signal_id=int(body["signal_id"]),
                        target_platform=str(body.get("target_platform", "TikTok")),
                        angle=str(body["angle"]),
                        hook_2s=str(body["hook_2s"]),
                        on_screen_text=str(body["on_screen_text"]),
                        caption=str(body["caption"]),
                        edit_beats=beats,
                        audio_cue=str(body.get("audio_cue", "")),
                        model_used=str(body.get("model_used", "manual")),
                    )
                    self._send_json({"ok": True, "brief": brief}, status=HTTPStatus.CREATED)
                    return

                if path.startswith("/api/briefs/") and path.endswith("/grade"):
                    brief_id = int(path[len("/api/briefs/") : -len("/grade")].strip("/"))
                    def _opt_int(key: str) -> Optional[int]:
                        v = body.get(key)
                        return None if v in ("", None) else int(v)
                    graded = db.grade_brief(
                        brief_id=brief_id,
                        verdict=str(body["verdict"]),
                        account_handle=str(body.get("account_handle", "")),
                        posted_url=str(body.get("posted_url", "")),
                        views_48h=_opt_int("views_48h"),
                        likes_48h=_opt_int("likes_48h"),
                        shares_48h=_opt_int("shares_48h"),
                        saves_48h=_opt_int("saves_48h"),
                        comments_48h=_opt_int("comments_48h"),
                        follower_baseline=_opt_int("follower_baseline"),
                        outcome_notes=str(body.get("outcome_notes", "")),
                    )
                    self._send_json({"ok": True, "brief": graded})
                    return

                if path == "/api/briefs/export":
                    out_dir = Path(body["out_dir"]) if body.get("out_dir") else (DEFAULT_EXPORT_DIR / "creative-feedback")
                    version = str(body.get("version", "0.5"))
                    result = export_creative_feedback(db=db, out_dir=out_dir, version=version)
                    self._send_json({"ok": True, **result})
                    return

                if path == "/api/briefs/auto-ab":
                    result = auto_pair_creator_ab(
                        platform=str(body.get("platform", "TikTok")),
                        handle=str(body["handle"]),
                        sector=str(body.get("sector", "CREATORS")),
                        max_pairs=int(body.get("max_pairs", 5)),
                        min_ratio=float(body.get("min_ratio", 2.0)),
                        out_dir=Path(body["out_dir"]) if body.get("out_dir") else None,
                        version=str(body.get("version", "0.5")),
                    )
                    self._send_json({"ok": True, **result})
                    return

                self._send_json({"error": f"Unknown endpoint: {path}"}, status=HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

    return IPXHandler


def create_server(db: TerminalDB, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(db))


def run_server(db: TerminalDB, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = create_server(db, host=host, port=port)
    print(f"IPX Terminal Launchpad running at http://{host}:{port}")
    print(f"SQLite WAL database: {db.db_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down IPX Terminal server.")
    finally:
        server.server_close()
