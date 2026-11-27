"""Quant Factor Engine, Calibration Scorecard, and CSV exporter for IPX Terminal."""

from __future__ import annotations

import csv
import io
import math
from typing import Any, Dict, List, Optional

from ipx_terminal.db import TerminalDB


def _f(val: Any, default: float = 0.0) -> float:
    if val is None or isinstance(val, bool):
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def build_quant_workspace(db: TerminalDB, include_vcrm: bool = True) -> Dict[str, Any]:
    """Compute multi-factor screener rows, market-vs-social divergences, and calibration scorecard."""
    movers = db.get_top_movers(limit=200)
    signals = db.list_signals(limit=250)
    predictions = db.list_predictions(limit=250)

    latest_sig_by_ticker: Dict[str, Dict[str, Any]] = {}
    market_sig_by_ticker: Dict[str, Dict[str, Any]] = {}
    for sig in signals:
        tk = sig["ticker"]
        if tk not in latest_sig_by_ticker:
            latest_sig_by_ticker[tk] = sig
        if sig.get("source_type") == "prediction_market" and tk not in market_sig_by_ticker:
            market_sig_by_ticker[tk] = sig

    screener: List[Dict[str, Any]] = []
    divergences: List[Dict[str, Any]] = []

    for m in movers:
        tk = m["ticker"]
        sig = latest_sig_by_ticker.get(tk) or {}
        metrics = dict(sig.get("metrics") or {})

        views = _f(metrics.get("views") or metrics.get("median_views") or metrics.get("total_views"))
        likes = _f(metrics.get("likes"))
        shares = _f(metrics.get("shares") or metrics.get("reposts"))
        followers = _f(
            metrics.get("creator_subscribers")
            or metrics.get("creator_followers")
            or metrics.get("median_creator_followers")
        )
        breakout_ratio = _f(metrics.get("breakout_ratio_views_to_followers"))
        if breakout_ratio <= 0 and views > 0 and followers > 0:
            breakout_ratio = round(views / followers, 2)

        share_to_like = _f(metrics.get("share_to_like_ratio"))
        if share_to_like <= 0 and shares > 0 and likes > 0:
            share_to_like = shares / likes
        share_to_like_pct = round(share_to_like * 100.0, 1)

        remix_breadth = int(
            _f(
                metrics.get("unique_creators_using_sound")
                or metrics.get("derivative_videos")
                or metrics.get("matching_clips_24h")
                or metrics.get("us_states_active")
                or metrics.get("unique_creators")
            )
        )
        cvs = _f(m.get("cvs_score"))
        cvs_delta = _f(m.get("cvs_delta"))
        contagion = _f(m.get("contagion_index"))

        mkt_sig = market_sig_by_ticker.get(tk)
        market_yes_pct: Optional[float] = None
        market_source: Optional[str] = None
        if mkt_sig:
            mm = mkt_sig.get("metrics") or {}
            if mm.get("yes_pct") is not None:
                market_yes_pct = round(_f(mm.get("yes_pct")), 1)
                market_source = str(mm.get("market_source") or "Market")

        # Quant Alpha Score (0-100): Remix/Geo Breadth + Share-to-Like + Breakout Ratio + CVS + Momentum
        alpha = (
            min(30.0, math.log1p(max(0, remix_breadth)) * 7.5)
            + min(25.0, share_to_like_pct * 0.75)
            + min(20.0, math.log1p(max(0.0, breakout_ratio)) * 6.5)
            + min(20.0, cvs * 0.22)
            + max(-5.0, min(5.0, cvs_delta * 0.4))
        )
        alpha_score = round(max(0.0, min(100.0, alpha)), 1)

        if alpha_score >= 60.0 or share_to_like_pct >= 20.0 or breakout_ratio >= 8.0 or remix_breadth >= 15:
            signal_flag = "STRONG_SIGNAL"
        elif alpha_score >= 35.0 or cvs >= 55.0:
            signal_flag = "WATCH"
        else:
            signal_flag = "NOISE"

        row = {
            "ticker": tk,
            "name": m.get("name") or tk,
            "sector": m.get("sector") or "POP",
            "signal_id": sig.get("id"),
            "alpha_score": alpha_score,
            "signal_flag": signal_flag,
            "cvs_score": round(cvs, 1),
            "cvs_delta": round(cvs_delta, 1),
            "contagion_index": round(contagion, 1),
            "contagion_stage": m.get("contagion_stage") or "echo_chamber",
            "breakout_ratio": round(breakout_ratio, 2),
            "share_to_like_pct": share_to_like_pct,
            "remix_breadth": remix_breadth,
            "market_yes_pct": market_yes_pct,
            "market_source": market_source,
            "captured_at": sig.get("captured_at") or "",
            "latest_title": sig.get("title") or "",
        }
        screener.append(row)

        if market_yes_pct is not None:
            gap = round(cvs - market_yes_pct, 1)
            divergences.append(
                {
                    "ticker": tk,
                    "name": row["name"],
                    "sector": row["sector"],
                    "market_source": market_source,
                    "market_yes_pct": market_yes_pct,
                    "cvs_score": row["cvs_score"],
                    "divergence_pts": gap,
                    "direction": "SOCIAL_AHEAD" if gap >= 12 else ("MARKET_AHEAD" if gap <= -12 else "ALIGNED"),
                }
            )

    screener.sort(key=lambda r: (r["alpha_score"], r["cvs_score"]), reverse=True)
    divergences.sort(key=lambda d: abs(d["divergence_pts"]), reverse=True)

    # Calibration & Edge Scorecard (Human Quant vs. AI)
    resolved = [p for p in predictions if p.get("status") == "resolved" and p.get("outcome")]
    pending = [p for p in predictions if p.get("status") == "pending"]
    overdue = [p for p in pending if p.get("overdue")]

    human_correct = 0
    brier_sum = 0.0
    ai_total = 0
    ai_correct = 0
    by_sector: Dict[str, Dict[str, int]] = {}

    for p in resolved:
        out = p["outcome"]
        sec = p.get("sector") or "POP"
        sec_rec = by_sector.setdefault(sec, {"resolved": 0, "correct": 0})
        sec_rec["resolved"] += 1
        ok = bool(out.get("prediction_correct"))
        if ok:
            human_correct += 1
            sec_rec["correct"] += 1
        conf = max(0.0, min(1.0, _f(p.get("confidence"), 0.5)))
        brier_sum += 1.0 - ((conf - (1.0 if ok else 0.0)) ** 2)

        if p.get("ai_predicted_label"):
            ai_total += 1
            if str(p["ai_predicted_label"]).strip().lower() == str(out.get("label", "")).strip().lower():
                ai_correct += 1

    n_res = len(resolved)
    human_hit = round(100.0 * human_correct / n_res, 1) if n_res else None
    ai_hit = round(100.0 * ai_correct / ai_total, 1) if ai_total else None
    brier_pct = round(100.0 * brier_sum / n_res, 1) if n_res else None
    edge_vs_ai = round(human_hit - ai_hit, 1) if (human_hit is not None and ai_hit is not None) else None

    sector_scorecard = [
        {
            "sector": sec,
            "resolved": d["resolved"],
            "correct": d["correct"],
            "hit_rate_pct": round(100.0 * d["correct"] / d["resolved"], 1) if d["resolved"] else 0.0,
        }
        for sec, d in sorted(by_sector.items())
    ]

    result: Dict[str, Any] = {
        "summary": {
            "tracked_tickers": len(screener),
            "strong_signals": sum(1 for r in screener if r["signal_flag"] == "STRONG_SIGNAL"),
            "watch_signals": sum(1 for r in screener if r["signal_flag"] == "WATCH"),
            "pending_calls": len(pending),
            "overdue_calls": len(overdue),
            "resolved_calls": n_res,
            "human_hit_rate_pct": human_hit,
            "ai_hit_rate_pct": ai_hit,
            "edge_vs_ai_pct": edge_vs_ai,
            "brier_calibration_pct": brier_pct,
        },
        "screener": screener,
        "divergences": divergences,
        "sector_scorecard": sector_scorecard,
    }
    if include_vcrm:
        from ipx_terminal.vcrm import evaluate_vcrm

        result["vcrm"] = evaluate_vcrm(db, quant_data=result)
    return result


def export_quant_factors_csv(db: TerminalDB) -> str:
    """Serialize the Quant Factor Screener table to a clean CSV for Python/Jupyter/Excel."""
    data = build_quant_workspace(db)
    buf = io.StringIO()
    cols = [
        "ticker",
        "name",
        "sector",
        "signal_flag",
        "alpha_score",
        "cvs_score",
        "cvs_delta",
        "contagion_index",
        "contagion_stage",
        "breakout_ratio",
        "share_to_like_pct",
        "remix_breadth",
        "market_yes_pct",
        "market_source",
        "captured_at",
        "latest_title",
    ]
    writer = csv.DictWriter(buf, fieldnames=cols)
    writer.writeheader()
    for row in data["screener"]:
        writer.writerow({k: row.get(k, "") for k in cols})
    return buf.getvalue()
