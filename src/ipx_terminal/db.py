"""SQLite WAL storage for Entity-Resolution IP Graph, t_0 signals, predictions, and outcomes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional, Sequence

from ipx_terminal.config import (
    CATEGORY_LABELS,
    DEFAULT_DB_PATH,
    DEFAULT_QUESTIONS,
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    VALID_SECTORS,
    VALID_SOURCES,
)
from ipx_terminal.scoring import compute_velocity_and_contagion, parse_iso_utc, utc_now_iso

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entities (
    ticker TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    sector TEXT NOT NULL,
    owner_holder TEXT NOT NULL DEFAULT 'Independent / Unknown',
    ip_type TEXT NOT NULL DEFAULT 'franchise',
    aliases_json TEXT NOT NULL DEFAULT '[]',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'manual',
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    platforms_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    samples_json TEXT NOT NULL DEFAULT '[]',
    entities_mentioned_json TEXT NOT NULL DEFAULT '[]',
    cvs_score REAL NOT NULL DEFAULT 0.0,
    contagion_index REAL NOT NULL DEFAULT 0.0,
    contagion_stage TEXT NOT NULL DEFAULT 'echo_chamber',
    url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    FOREIGN KEY (ticker) REFERENCES entities(ticker) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_signals_ticker_time ON signals(ticker, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_signals_captured_at ON signals(captured_at DESC);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_code TEXT NOT NULL UNIQUE,
    signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    category TEXT NOT NULL,
    sector TEXT NOT NULL,
    title TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'ipx_terminal_export',
    difficulty TEXT NOT NULL DEFAULT 'medium',
    question TEXT NOT NULL,
    predicted_label TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.70,
    analyst_notes TEXT NOT NULL DEFAULT '',
    outcome_window_hours INTEGER,
    due_at TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    frozen_snapshot_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE,
    FOREIGN KEY (ticker) REFERENCES entities(ticker) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_predictions_status ON predictions(status, due_at);

CREATE TABLE IF NOT EXISTS outcomes (
    prediction_id INTEGER PRIMARY KEY,
    resolved_at TEXT NOT NULL,
    ground_truth_label TEXT NOT NULL,
    secondary_label TEXT,
    required_concepts_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    outcome_window_hours INTEGER,
    outcome_metrics_json TEXT NOT NULL DEFAULT '{}',
    prediction_correct INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS creative_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    sector TEXT NOT NULL,
    target_platform TEXT NOT NULL DEFAULT 'TikTok',
    angle TEXT NOT NULL,
    hook_2s TEXT NOT NULL,
    on_screen_text TEXT NOT NULL,
    caption TEXT NOT NULL,
    edit_beats_json TEXT NOT NULL DEFAULT '[]',
    audio_cue TEXT NOT NULL DEFAULT '',
    model_used TEXT NOT NULL DEFAULT 'manual',
    status TEXT NOT NULL DEFAULT 'draft',
    account_handle TEXT NOT NULL DEFAULT '',
    posted_url TEXT NOT NULL DEFAULT '',
    views_48h INTEGER,
    likes_48h INTEGER,
    shares_48h INTEGER,
    saves_48h INTEGER,
    comments_48h INTEGER,
    follower_baseline INTEGER,
    verdict TEXT,
    outcome_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    graded_at TEXT,
    FOREIGN KEY (signal_id) REFERENCES signals(id) ON DELETE CASCADE,
    FOREIGN KEY (ticker) REFERENCES entities(ticker) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_briefs_status ON creative_briefs(status, created_at DESC);
"""


def normalize_ticker(raw: str) -> str:
    cleaned = raw.strip().upper().replace(" ", "_")
    if not cleaned:
        raise ValueError("Ticker cannot be empty")
    return cleaned


class TerminalDB:
    """Thin, zero-dependency SQLite WAL store for IPX Terminal."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_SQL)
            # Safe schema migration for Human vs. AI prediction columns on existing DBs
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(predictions)").fetchall()
            }
            migrations = [
                ("ai_model", "TEXT"),
                ("ai_predicted_label", "TEXT"),
                ("ai_confidence", "REAL"),
                ("ai_reasoning", "TEXT"),
            ]
            for col_name, col_type in migrations:
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE predictions ADD COLUMN {col_name} {col_type}")

    # ------------------------------------------------------------------
    # Entities (Entity-Resolution IP Graph)
    # ------------------------------------------------------------------
    def upsert_entity(
        self,
        ticker: str,
        name: str,
        sector: str,
        owner_holder: str = "Independent / Unknown",
        ip_type: str = "franchise",
        aliases: Optional[Sequence[str]] = None,
        description: str = "",
    ) -> Dict[str, Any]:
        norm_ticker = normalize_ticker(ticker)
        norm_sector = sector.strip().upper()
        if norm_sector not in VALID_SECTORS:
            raise ValueError(f"Invalid sector '{sector}'. Must be one of {VALID_SECTORS}")

        now = utc_now_iso()
        aliases_list = [a.strip() for a in (aliases or []) if a and a.strip()]
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO entities (
                    ticker, name, sector, owner_holder, ip_type,
                    aliases_json, description, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    name = excluded.name,
                    sector = excluded.sector,
                    owner_holder = excluded.owner_holder,
                    ip_type = excluded.ip_type,
                    aliases_json = excluded.aliases_json,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (
                    norm_ticker,
                    name.strip(),
                    norm_sector,
                    owner_holder.strip() or "Independent / Unknown",
                    ip_type.strip() or "franchise",
                    json.dumps(aliases_list),
                    description.strip(),
                    now,
                    now,
                ),
            )
        return self.get_entity(norm_ticker)  # type: ignore[return-value]

    def get_entity(self, ticker: str) -> Optional[Dict[str, Any]]:
        norm_ticker = normalize_ticker(ticker)
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM entities WHERE ticker = ?", (norm_ticker,)).fetchone()
        return self._decode_entity(row) if row else None

    def list_entities(self, sector: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if sector and sector.upper() != "ALL":
                rows = conn.execute(
                    "SELECT * FROM entities WHERE sector = ? ORDER BY ticker ASC",
                    (sector.upper(),),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM entities ORDER BY ticker ASC").fetchall()
        return [self._decode_entity(r) for r in rows]

    @staticmethod
    def _decode_entity(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "ticker": row["ticker"],
            "name": row["name"],
            "sector": row["sector"],
            "owner_holder": row["owner_holder"],
            "ip_type": row["ip_type"],
            "aliases": json.loads(row["aliases_json"]),
            "description": row["description"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    # ------------------------------------------------------------------
    # Signals (t_0 snapshots)
    # ------------------------------------------------------------------
    def insert_signal(
        self,
        ticker: str,
        title: str,
        summary: str,
        platforms: Sequence[str],
        metrics: Optional[Dict[str, Any]] = None,
        samples: Optional[Sequence[str]] = None,
        entities_mentioned: Optional[Sequence[str]] = None,
        source_type: str = "manual",
        captured_at: Optional[str] = None,
        url: str = "",
        sector: str = "POP",
        entity_name: Optional[str] = None,
        owner_holder: str = "Independent / Unknown",
    ) -> Dict[str, Any]:
        norm_ticker = normalize_ticker(ticker)
        if not self.get_entity(norm_ticker):
            self.upsert_entity(
                ticker=norm_ticker,
                name=entity_name or norm_ticker,
                sector=sector,
                owner_holder=owner_holder,
            )

        clean_platforms = [p.strip() for p in platforms if p and p.strip()]
        if not clean_platforms:
            raise ValueError("At least one platform is required for a signal snapshot")

        cap_ts = captured_at.strip() if captured_at else utc_now_iso()
        metrics_dict = dict(metrics or {})
        if url and "url" not in metrics_dict:
            metrics_dict["url"] = url

        samples_list = [s.strip() for s in (samples or []) if s and s.strip()]
        mentioned_list = [e.strip() for e in (entities_mentioned or []) if e and e.strip()]
        if not mentioned_list:
            ent = self.get_entity(norm_ticker)
            if ent:
                mentioned_list = [ent["name"]]

        cvs, contagion_idx, stage = compute_velocity_and_contagion(
            platforms=clean_platforms,
            metrics=metrics_dict,
            captured_at=cap_ts,
        )
        now = utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO signals (
                    ticker, captured_at, source_type, title, summary,
                    platforms_json, metrics_json, samples_json, entities_mentioned_json,
                    cvs_score, contagion_index, contagion_stage, url, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    norm_ticker,
                    cap_ts,
                    source_type.strip() or "manual",
                    title.strip(),
                    summary.strip(),
                    json.dumps(clean_platforms),
                    json.dumps(metrics_dict),
                    json.dumps(samples_list),
                    json.dumps(mentioned_list),
                    cvs,
                    contagion_idx,
                    stage,
                    url.strip(),
                    now,
                ),
            )
            sig_id = cur.lastrowid
        return self.get_signal(int(sig_id))  # type: ignore[return-value]

    def get_signal(self, signal_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT s.*, e.name AS entity_name, e.sector AS entity_sector, e.owner_holder
                FROM signals s
                JOIN entities e ON e.ticker = s.ticker
                WHERE s.id = ?
                """,
                (signal_id,),
            ).fetchone()
        return self._decode_signal(row) if row else None

    def list_signals(
        self,
        ticker: Optional[str] = None,
        sector: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if ticker:
            clauses.append("s.ticker = ?")
            params.append(normalize_ticker(ticker))
        if sector and sector.upper() != "ALL":
            clauses.append("e.sector = ?")
            params.append(sector.upper())

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT s.*, e.name AS entity_name, e.sector AS entity_sector, e.owner_holder
                FROM signals s
                JOIN entities e ON e.ticker = s.ticker
                {where_sql}
                ORDER BY s.captured_at DESC, s.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._decode_signal(r) for r in rows]

    @staticmethod
    def _decode_signal(row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "ticker": row["ticker"],
            "entity_name": row["entity_name"],
            "sector": row["entity_sector"],
            "owner_holder": row["owner_holder"],
            "captured_at": row["captured_at"],
            "source_type": row["source_type"],
            "title": row["title"],
            "summary": row["summary"],
            "platforms": json.loads(row["platforms_json"]),
            "metrics": json.loads(row["metrics_json"]),
            "samples": json.loads(row["samples_json"]),
            "entities_mentioned": json.loads(row["entities_mentioned_json"]),
            "cvs_score": row["cvs_score"],
            "contagion_index": row["contagion_index"],
            "contagion_stage": row["contagion_stage"],
            "url": row["url"],
            "created_at": row["created_at"],
        }

    # ------------------------------------------------------------------
    # Predictions & 48-72h Outcome Logger
    # ------------------------------------------------------------------
    def next_case_code(self, category: str, start_num: int = 401) -> str:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{category}'")
        prefix = f"ipx-{category}-"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT case_code FROM predictions WHERE category = ?",
                (category,),
            ).fetchall()
        max_num = start_num - 1
        for row in rows:
            code = str(row["case_code"])
            if code.startswith(prefix):
                suffix = code[len(prefix):]
                if suffix.isdigit():
                    max_num = max(max_num, int(suffix))
        return f"{prefix}{max_num + 1:03d}"

    def create_prediction(
        self,
        signal_id: int,
        category: str,
        predicted_label: str,
        confidence: float = 0.70,
        question: Optional[str] = None,
        title: Optional[str] = None,
        difficulty: str = "medium",
        source: str = "ipx_terminal_export",
        outcome_window_hours: Optional[int] = 48,
        analyst_notes: str = "",
        case_code: Optional[str] = None,
        ai_model: Optional[str] = None,
        ai_predicted_label: Optional[str] = None,
        ai_confidence: Optional[float] = None,
        ai_reasoning: Optional[str] = None,
    ) -> Dict[str, Any]:
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category '{category}'. Expected one of {VALID_CATEGORIES}")
        if predicted_label not in CATEGORY_LABELS[category]:
            raise ValueError(
                f"Invalid predicted_label '{predicted_label}' for '{category}'. "
                f"Expected one of {CATEGORY_LABELS[category]}"
            )
        if difficulty not in VALID_DIFFICULTIES:
            raise ValueError(f"Invalid difficulty '{difficulty}'")
        if source not in VALID_SOURCES:
            raise ValueError(f"Invalid source '{source}'")

        sig = self.get_signal(signal_id)
        if not sig:
            raise ValueError(f"Signal #{signal_id} not found")

        # Freeze the exact t_0 snapshot at prediction time (zero future leakage)
        frozen_snapshot = {
            "summary": sig["summary"],
            "platforms": list(sig["platforms"]),
            "metrics": dict(sig["metrics"]),
            "samples": list(sig["samples"]),
            "entities_mentioned": list(sig["entities_mentioned"]),
        }

        code = case_code or self.next_case_code(category)
        cap_ts = sig["captured_at"]
        due_at: Optional[str] = None
        if outcome_window_hours is not None:
            try:
                due_dt = parse_iso_utc(cap_ts) + timedelta(hours=int(outcome_window_hours))
                due_at = due_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            except ValueError:
                due_at = None

        now = utc_now_iso()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO predictions (
                    case_code, signal_id, ticker, category, sector, title, captured_at,
                    source, difficulty, question, predicted_label, confidence, analyst_notes,
                    outcome_window_hours, due_at, status, frozen_snapshot_json, created_at,
                    ai_model, ai_predicted_label, ai_confidence, ai_reasoning
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?)
                """,
                (
                    code,
                    signal_id,
                    sig["ticker"],
                    category,
                    sig["sector"],
                    (title or sig["title"]).strip(),
                    cap_ts,
                    source,
                    difficulty,
                    (question or DEFAULT_QUESTIONS[category]).strip(),
                    predicted_label,
                    max(0.0, min(1.0, float(confidence))),
                    analyst_notes.strip(),
                    outcome_window_hours,
                    due_at,
                    json.dumps(frozen_snapshot),
                    now,
                    ai_model.strip() if ai_model else None,
                    ai_predicted_label.strip() if ai_predicted_label else None,
                    float(ai_confidence) if ai_confidence is not None else None,
                    ai_reasoning.strip() if ai_reasoning else None,
                ),
            )
            pred_id = cur.lastrowid
        return self.get_prediction(int(pred_id))  # type: ignore[return-value]

    def resolve_prediction(
        self,
        prediction_id: int,
        ground_truth_label: str,
        required_concepts: Sequence[Any],
        rationale: str,
        secondary_label: Optional[str] = None,
        outcome_window_hours: Optional[int] = None,
        outcome_metrics: Optional[Dict[str, Any]] = None,
        resolved_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        pred = self.get_prediction(prediction_id)
        if not pred:
            raise ValueError(f"Prediction #{prediction_id} not found")

        category = pred["category"]
        if ground_truth_label not in CATEGORY_LABELS[category]:
            raise ValueError(
                f"Invalid ground_truth_label '{ground_truth_label}' for '{category}'. "
                f"Expected one of {CATEGORY_LABELS[category]}"
            )
        if not required_concepts:
            raise ValueError("required_concepts must contain at least one concept or alias group")
        if not rationale.strip():
            raise ValueError("rationale cannot be empty")

        window_hrs = (
            outcome_window_hours
            if outcome_window_hours is not None
            else pred["outcome_window_hours"]
        )
        is_correct = 1 if pred["predicted_label"] == ground_truth_label else 0
        res_ts = resolved_at.strip() if resolved_at else utc_now_iso()

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO outcomes (
                    prediction_id, resolved_at, ground_truth_label, secondary_label,
                    required_concepts_json, rationale, outcome_window_hours,
                    outcome_metrics_json, prediction_correct
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id) DO UPDATE SET
                    resolved_at = excluded.resolved_at,
                    ground_truth_label = excluded.ground_truth_label,
                    secondary_label = excluded.secondary_label,
                    required_concepts_json = excluded.required_concepts_json,
                    rationale = excluded.rationale,
                    outcome_window_hours = excluded.outcome_window_hours,
                    outcome_metrics_json = excluded.outcome_metrics_json,
                    prediction_correct = excluded.prediction_correct
                """,
                (
                    prediction_id,
                    res_ts,
                    ground_truth_label,
                    secondary_label.strip() if secondary_label else None,
                    json.dumps(list(required_concepts)),
                    rationale.strip(),
                    window_hrs,
                    json.dumps(dict(outcome_metrics or {})),
                    is_correct,
                ),
            )
            conn.execute(
                "UPDATE predictions SET status = 'resolved' WHERE id = ?",
                (prediction_id,),
            )
        return self.get_prediction(prediction_id)  # type: ignore[return-value]

    def get_prediction(self, prediction_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    p.*,
                    o.resolved_at, o.ground_truth_label, o.secondary_label,
                    o.required_concepts_json, o.rationale AS outcome_rationale,
                    o.outcome_window_hours AS resolved_window_hours,
                    o.outcome_metrics_json, o.prediction_correct
                FROM predictions p
                LEFT JOIN outcomes o ON o.prediction_id = p.id
                WHERE p.id = ?
                """,
                (prediction_id,),
            ).fetchone()
        return self._decode_prediction(row) if row else None

    def list_predictions(
        self,
        status: Optional[str] = None,
        ticker: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if status and status != "all":
            clauses.append("p.status = ?")
            params.append(status)
        if ticker:
            clauses.append("p.ticker = ?")
            params.append(normalize_ticker(ticker))
        if category and category != "all":
            clauses.append("p.category = ?")
            params.append(category)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    p.*,
                    o.resolved_at, o.ground_truth_label, o.secondary_label,
                    o.required_concepts_json, o.rationale AS outcome_rationale,
                    o.outcome_window_hours AS resolved_window_hours,
                    o.outcome_metrics_json, o.prediction_correct
                FROM predictions p
                LEFT JOIN outcomes o ON o.prediction_id = p.id
                {where_sql}
                ORDER BY
                    CASE p.status WHEN 'pending' THEN 0 ELSE 1 END ASC,
                    p.captured_at DESC, p.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._decode_prediction(r) for r in rows]

    @staticmethod
    def _decode_prediction(row: sqlite3.Row) -> Dict[str, Any]:
        outcome = None
        if row["ground_truth_label"] is not None:
            outcome = {
                "resolved_at": row["resolved_at"],
                "label": row["ground_truth_label"],
                "secondary_label": row["secondary_label"],
                "required_concepts": json.loads(row["required_concepts_json"]),
                "rationale": row["outcome_rationale"],
                "outcome_window_hours": row["resolved_window_hours"],
                "outcome_metrics": json.loads(row["outcome_metrics_json"] or "{}"),
                "prediction_correct": bool(row["prediction_correct"]),
            }

        overdue = False
        if row["status"] == "pending" and row["due_at"]:
            try:
                overdue = parse_iso_utc(row["due_at"]) <= datetime.now(timezone.utc)
            except ValueError:
                overdue = False

        ai_prediction = None
        if row["ai_predicted_label"]:
            ai_correct = (
                bool(row["ai_predicted_label"] == row["ground_truth_label"])
                if row["ground_truth_label"] is not None
                else None
            )
            ai_prediction = {
                "model": row["ai_model"],
                "label": row["ai_predicted_label"],
                "confidence": row["ai_confidence"],
                "reasoning": row["ai_reasoning"] or "",
                "correct": ai_correct,
            }

        return {
            "id": row["id"],
            "case_code": row["case_code"],
            "signal_id": row["signal_id"],
            "ticker": row["ticker"],
            "category": row["category"],
            "sector": row["sector"],
            "title": row["title"],
            "captured_at": row["captured_at"],
            "source": row["source"],
            "difficulty": row["difficulty"],
            "question": row["question"],
            "predicted_label": row["predicted_label"],
            "confidence": row["confidence"],
            "analyst_notes": row["analyst_notes"],
            "outcome_window_hours": row["outcome_window_hours"],
            "due_at": row["due_at"],
            "overdue": overdue,
            "status": row["status"],
            "signal_snapshot": json.loads(row["frozen_snapshot_json"]),
            "ai_prediction": ai_prediction,
            "outcome": outcome,
            "created_at": row["created_at"],
        }

    # ------------------------------------------------------------------
    # Terminal Analytics (TOP movers, GP history, Dashboard KPIs)
    # ------------------------------------------------------------------
    def get_top_movers(self, sector: Optional[str] = None, limit: int = 25) -> List[Dict[str, Any]]:
        entities = self.list_entities(sector=sector)
        movers: List[Dict[str, Any]] = []
        for ent in entities:
            sigs = self.list_signals(ticker=ent["ticker"], limit=5)
            if not sigs:
                movers.append(
                    {
                        **ent,
                        "latest_signal_id": None,
                        "latest_title": "No signals captured yet",
                        "latest_captured_at": None,
                        "cvs_score": 0.0,
                        "cvs_delta": 0.0,
                        "contagion_index": 0.0,
                        "contagion_stage": "echo_chamber",
                        "platforms": [],
                        "signal_count": 0,
                    }
                )
                continue

            latest = sigs[0]
            prev_cvs = sigs[1]["cvs_score"] if len(sigs) > 1 else latest["cvs_score"]
            movers.append(
                {
                    **ent,
                    "latest_signal_id": latest["id"],
                    "latest_title": latest["title"],
                    "latest_captured_at": latest["captured_at"],
                    "cvs_score": latest["cvs_score"],
                    "cvs_delta": round(latest["cvs_score"] - prev_cvs, 1),
                    "contagion_index": latest["contagion_index"],
                    "contagion_stage": latest["contagion_stage"],
                    "platforms": latest["platforms"],
                    "signal_count": len(sigs),
                }
            )
        movers.sort(key=lambda item: (item["cvs_score"], item["contagion_index"]), reverse=True)
        return movers[:limit]

    def get_ticker_history(self, ticker: str, limit: int = 30) -> List[Dict[str, Any]]:
        sigs = self.list_signals(ticker=ticker, limit=limit)
        return list(reversed(sigs))

    def get_dashboard_stats(self) -> Dict[str, Any]:
        with self.connect() as conn:
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            signal_count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status = 'pending'"
            ).fetchone()[0]
            resolved_count = conn.execute(
                "SELECT COUNT(*) FROM predictions WHERE status = 'resolved'"
            ).fetchone()[0]
            correct_count = conn.execute(
                "SELECT COUNT(*) FROM outcomes WHERE prediction_correct = 1"
            ).fetchone()[0]
            ai_resolved = conn.execute(
                """
                SELECT COUNT(*) FROM predictions p
                JOIN outcomes o ON o.prediction_id = p.id
                WHERE p.ai_predicted_label IS NOT NULL
                """
            ).fetchone()[0]
            ai_correct = conn.execute(
                """
                SELECT COUNT(*) FROM predictions p
                JOIN outcomes o ON o.prediction_id = p.id
                WHERE p.ai_predicted_label IS NOT NULL
                  AND p.ai_predicted_label = o.ground_truth_label
                """
            ).fetchone()[0]

        preds = self.list_predictions(status="pending", limit=200)
        overdue_count = sum(1 for p in preds if p["overdue"])
        accuracy = round((correct_count / resolved_count) * 100.0, 1) if resolved_count else None
        ai_accuracy = round((ai_correct / ai_resolved) * 100.0, 1) if ai_resolved else None
        return {
            "entities": entity_count,
            "signals": signal_count,
            "pending_predictions": pending_count,
            "overdue_predictions": overdue_count,
            "resolved_predictions": resolved_count,
            "prediction_accuracy_pct": accuracy,
            "ai_resolved_predictions": ai_resolved,
            "ai_accuracy_pct": ai_accuracy,
        }

    # ------------------------------------------------------------------
    # Creative Briefs & Content Factory Feedback (Winner vs. Flop Loop)
    # ------------------------------------------------------------------
    def create_brief(
        self,
        signal_id: int,
        target_platform: str,
        angle: str,
        hook_2s: str,
        on_screen_text: str,
        caption: str,
        edit_beats: Optional[Sequence[str]] = None,
        audio_cue: str = "",
        model_used: str = "manual",
    ) -> Dict[str, Any]:
        sig = self.get_signal(signal_id)
        if not sig:
            raise ValueError(f"Signal #{signal_id} not found")
        now = utc_now_iso()
        beats = [b.strip() for b in (edit_beats or []) if b and b.strip()]
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO creative_briefs (
                    signal_id, ticker, sector, target_platform, angle, hook_2s,
                    on_screen_text, caption, edit_beats_json, audio_cue,
                    model_used, status, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                """,
                (
                    signal_id,
                    sig["ticker"],
                    sig["sector"],
                    target_platform.strip() or "TikTok",
                    angle.strip(),
                    hook_2s.strip(),
                    on_screen_text.strip(),
                    caption.strip(),
                    json.dumps(beats),
                    audio_cue.strip(),
                    model_used.strip() or "manual",
                    now,
                ),
            )
            brief_id = cur.lastrowid
        return self.get_brief(int(brief_id))  # type: ignore[return-value]

    def grade_brief(
        self,
        brief_id: int,
        verdict: str,
        account_handle: str = "",
        posted_url: str = "",
        views_48h: Optional[int] = None,
        likes_48h: Optional[int] = None,
        shares_48h: Optional[int] = None,
        saves_48h: Optional[int] = None,
        comments_48h: Optional[int] = None,
        follower_baseline: Optional[int] = None,
        outcome_notes: str = "",
    ) -> Dict[str, Any]:
        norm_verdict = verdict.strip().lower()
        if norm_verdict not in ("winner", "average", "flop"):
            raise ValueError("verdict must be 'winner', 'average', or 'flop'")
        if not self.get_brief(brief_id):
            raise ValueError(f"Creative brief #{brief_id} not found")
        now = utc_now_iso()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE creative_briefs SET
                    status = 'graded',
                    verdict = ?,
                    account_handle = ?,
                    posted_url = ?,
                    views_48h = ?,
                    likes_48h = ?,
                    shares_48h = ?,
                    saves_48h = ?,
                    comments_48h = ?,
                    follower_baseline = ?,
                    outcome_notes = ?,
                    graded_at = ?
                WHERE id = ?
                """,
                (
                    norm_verdict,
                    account_handle.strip(),
                    posted_url.strip(),
                    views_48h,
                    likes_48h,
                    shares_48h,
                    saves_48h,
                    comments_48h,
                    follower_baseline,
                    outcome_notes.strip(),
                    now,
                    brief_id,
                ),
            )
        return self.get_brief(brief_id)  # type: ignore[return-value]

    def get_brief(self, brief_id: int) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT b.*, s.title AS signal_title, s.summary AS signal_summary
                FROM creative_briefs b
                JOIN signals s ON s.id = b.signal_id
                WHERE b.id = ?
                """,
                (brief_id,),
            ).fetchone()
        return self._decode_brief(row) if row else None

    def list_briefs(
        self,
        ticker: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if ticker:
            clauses.append("b.ticker = ?")
            params.append(normalize_ticker(ticker))
        if status and status != "all":
            clauses.append("b.status = ?")
            params.append(status)
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT b.*, s.title AS signal_title, s.summary AS signal_summary
                FROM creative_briefs b
                JOIN signals s ON s.id = b.signal_id
                {where_sql}
                ORDER BY b.created_at DESC, b.id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._decode_brief(r) for r in rows]

    @staticmethod
    def _decode_brief(row: sqlite3.Row) -> Dict[str, Any]:
        views = row["views_48h"]
        followers = row["follower_baseline"]
        breakout_ratio = round(views / followers, 2) if (views and followers and followers > 0) else None
        shares = row["shares_48h"]
        likes = row["likes_48h"]
        share_to_like = round((shares / likes) * 100.0, 1) if (shares is not None and likes and likes > 0) else None
        return {
            "id": row["id"],
            "signal_id": row["signal_id"],
            "signal_title": row["signal_title"],
            "signal_summary": row["signal_summary"],
            "ticker": row["ticker"],
            "sector": row["sector"],
            "target_platform": row["target_platform"],
            "angle": row["angle"],
            "hook_2s": row["hook_2s"],
            "on_screen_text": row["on_screen_text"],
            "caption": row["caption"],
            "edit_beats": json.loads(row["edit_beats_json"]),
            "audio_cue": row["audio_cue"],
            "model_used": row["model_used"],
            "status": row["status"],
            "account_handle": row["account_handle"],
            "posted_url": row["posted_url"],
            "views_48h": views,
            "likes_48h": likes,
            "shares_48h": shares,
            "saves_48h": row["saves_48h"],
            "comments_48h": row["comments_48h"],
            "follower_baseline": followers,
            "breakout_ratio": breakout_ratio,
            "share_to_like_pct": share_to_like,
            "verdict": row["verdict"],
            "outcome_notes": row["outcome_notes"],
            "created_at": row["created_at"],
            "graded_at": row["graded_at"],
        }
