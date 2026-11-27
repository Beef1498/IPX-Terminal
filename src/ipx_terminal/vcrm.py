"""Config-driven Verification Cross-Reference Matrix (VCRM) live evaluator for IPX Terminal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ipx_terminal.db import TerminalDB

DEFAULT_VCRM_SPEC_PATH = Path(__file__).resolve().parents[2] / "data" / "requirements_vcrm.json"


def load_vcrm_spec(spec_path: Optional[Path] = None) -> Dict[str, Any]:
    path = spec_path or DEFAULT_VCRM_SPEC_PATH
    if not path.exists():
        return {"version": "1.0", "title": "IPX VCRM", "requirements": []}
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def evaluate_vcrm(
    db: TerminalDB,
    quant_data: Optional[Dict[str, Any]] = None,
    spec_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Evaluate all SHALL gates from requirements_vcrm.json against live SQLite & Eval telemetry."""
    from ipx_terminal.quant import build_quant_workspace

    spec = load_vcrm_spec(spec_path)
    q = quant_data if quant_data is not None else build_quant_workspace(db, include_vcrm=False)
    summary = q.get("summary") or {}

    signals = db.list_signals(limit=500)
    predictions = db.list_predictions(limit=500)
    briefs = db.list_briefs(limit=250)
    eval_runs = db.list_eval_runs(limit=100)

    sig_ts_by_id = {s["id"]: str(s.get("captured_at") or "") for s in signals}

    # 1. Zero future leakage: signal captured_at <= outcome resolved_at
    leakage_violations = 0
    resolved_count = 0
    ai_scored_resolved = 0
    for p in predictions:
        out = p.get("outcome")
        if p.get("status") == "resolved" and out:
            resolved_count += 1
            if p.get("ai_predicted_label"):
                ai_scored_resolved += 1
            sig_ts = sig_ts_by_id.get(p.get("signal_id"), "")
            res_ts = str(out.get("resolved_at") or "")
            if sig_ts and res_ts and sig_ts > res_ts:
                leakage_violations += 1

    # 2. Frozen prediction markets
    frozen_markets = sum(1 for s in signals if s.get("source_type") == "prediction_market")

    # 3. Completed eval runs
    completed_evals = [
        r for r in eval_runs
        if str(r.get("status") or "").lower() == "completed" and r.get("overall_score") is not None
    ]
    best_eval_score = max((float(r["overall_score"]) for r in completed_evals), default=None)
    latest_eval = completed_evals[0] if completed_evals else None

    # 4. Graded creative briefs
    graded_briefs = sum(
        1 for b in briefs if str(b.get("verdict") or "").strip().lower() in ("winner", "flop", "mixed")
    )

    overdue_calls = int(summary.get("overdue_calls") or 0)
    brier_pct = summary.get("brier_calibration_pct")
    tracked_tickers = int(summary.get("tracked_tickers") or 0)
    strong_signals = int(summary.get("strong_signals") or 0)

    gates: List[Dict[str, Any]] = []
    for req in spec.get("requirements") or []:
        key = req.get("check_key", "")
        status = "PENDING"
        observed = "--"

        if key == "zero_future_leakage":
            status = "PASS" if leakage_violations == 0 else "FAIL"
            observed = f"{leakage_violations} violation(s) across {resolved_count} resolved"
        elif key == "zero_overdue_calls":
            status = "PASS" if overdue_calls == 0 else "FAIL"
            observed = f"{overdue_calls} overdue"
        elif key == "brier_calibration_floor":
            if resolved_count < 3 or brier_pct is None:
                status = "PENDING"
                observed = f"{brier_pct}% (n={resolved_count}/3)" if brier_pct is not None else f"n={resolved_count}/3 resolved"
            else:
                status = "PASS" if float(brier_pct) >= 70.0 else "FAIL"
                observed = f"{brier_pct}% (n={resolved_count})"
        elif key == "screener_coverage":
            status = "PASS" if (tracked_tickers >= 5 and strong_signals >= 1) else ("PENDING" if tracked_tickers < 5 else "FAIL")
            observed = f"{tracked_tickers} tickers · {strong_signals} strong"
        elif key == "prediction_market_grounding":
            status = "PASS" if frozen_markets >= 1 else "PENDING"
            observed = f"{frozen_markets} frozen market(s)"
        elif key == "independent_eval_gate":
            if latest_eval is None:
                status = "PENDING"
                observed = "No completed eval run synced"
            else:
                sc = float(latest_eval["overall_score"])
                status = "PASS" if sc >= 75.0 else "FAIL"
                observed = f"{sc:.1f}% ({latest_eval.get('model_name', 'model')})"
        elif key == "creative_outcomes_graded":
            status = "PASS" if graded_briefs >= 2 else "PENDING"
            observed = f"{graded_briefs} graded brief(s)"
        elif key == "human_vs_ai_audit":
            status = "PASS" if ai_scored_resolved >= 1 else "PENDING"
            observed = f"{ai_scored_resolved} AI-scored resolved call(s)"

        gates.append(
            {
                "id": req["id"],
                "kind": req.get("kind", "Verification"),
                "category": req.get("category", "General"),
                "title": req.get("title", req["id"]),
                "requirement": req.get("requirement", ""),
                "method": req.get("method", "Inspection"),
                "target": req.get("target", ""),
                "status": status,
                "observed": observed,
            }
        )

    passed = sum(1 for g in gates if g["status"] == "PASS")
    failed = sum(1 for g in gates if g["status"] == "FAIL")
    pending = sum(1 for g in gates if g["status"] == "PENDING")
    total = len(gates)
    compliance_pct = round(100.0 * passed / total, 1) if total else 0.0

    return {
        "version": spec.get("version", "1.0"),
        "title": spec.get("title", "IPX VCRM"),
        "spec_file": "data/requirements_vcrm.json",
        "summary": {
            "passed": passed,
            "failed": failed,
            "pending": pending,
            "total": total,
            "compliance_pct": compliance_pct,
            "release_ready": failed == 0 and passed >= max(1, total - pending),
            "best_eval_score": best_eval_score,
        },
        "gates": gates,
    }
