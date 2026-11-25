"""Strict eval_case.schema.json validator and JSONL exporter from IPX Terminal to IPX-Eval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ipx_terminal.config import (
    CATEGORY_LABELS,
    DEFAULT_EXPORT_DIR,
    ID_PATTERN,
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    VALID_SECTORS,
    VALID_SOURCES,
)
from ipx_terminal.db import TerminalDB


def validate_eval_case(raw: Dict[str, Any]) -> List[str]:
    """Validate an exported eval case dict against the IPX-Eval schema contract."""
    errors: List[str] = []
    if not isinstance(raw, dict):
        return ["Case must be a JSON object"]

    required_top = (
        "id",
        "version",
        "category",
        "sector",
        "title",
        "captured_at",
        "signal_snapshot",
        "question",
        "ground_truth",
    )
    for key in required_top:
        if key not in raw:
            errors.append(f"Missing required field '{key}'")

    case_id = raw.get("id")
    category = raw.get("category")
    if isinstance(case_id, str):
        if not ID_PATTERN.match(case_id):
            errors.append(f"Invalid id format '{case_id}'")
        elif isinstance(category, str) and not case_id.startswith(f"ipx-{category}-"):
            errors.append(f"Case id '{case_id}' does not match category '{category}'")
    else:
        errors.append("Field 'id' must be a string")

    if category not in VALID_CATEGORIES:
        errors.append(f"Invalid category '{category}'")
    if raw.get("sector") not in VALID_SECTORS:
        errors.append(f"Invalid sector '{raw.get('sector')}'")
    if raw.get("source", "curated_seed") not in VALID_SOURCES:
        errors.append(f"Invalid source '{raw.get('source')}'")
    if raw.get("difficulty", "medium") not in VALID_DIFFICULTIES:
        errors.append(f"Invalid difficulty '{raw.get('difficulty')}'")

    title = raw.get("title")
    if not isinstance(title, str) or len(title.strip()) < 3:
        errors.append("Field 'title' must be a string of length >= 3")

    snap = raw.get("signal_snapshot")
    if not isinstance(snap, dict):
        errors.append("Field 'signal_snapshot' must be an object")
    else:
        if not isinstance(snap.get("summary"), str) or not snap["summary"].strip():
            errors.append("signal_snapshot.summary must be a non-empty string")
        platforms = snap.get("platforms")
        if not isinstance(platforms, list) or not platforms or not all(isinstance(p, str) for p in platforms):
            errors.append("signal_snapshot.platforms must be a non-empty list of strings")

    gt = raw.get("ground_truth")
    if not isinstance(gt, dict):
        errors.append("Field 'ground_truth' must be an object")
    else:
        label = gt.get("label")
        if category in CATEGORY_LABELS and label not in CATEGORY_LABELS[category]:
            errors.append(f"Invalid ground_truth.label '{label}' for category '{category}'")
        concepts = gt.get("required_concepts")
        if not isinstance(concepts, list) or not concepts:
            errors.append("ground_truth.required_concepts must be a non-empty list")
        else:
            for idx, group in enumerate(concepts):
                if isinstance(group, str):
                    if not group.strip():
                        errors.append(f"required_concepts[{idx}] cannot be empty")
                elif isinstance(group, list):
                    if not group or not all(isinstance(x, str) and x.strip() for x in group):
                        errors.append(f"required_concepts[{idx}] must be a non-empty list of strings")
                else:
                    errors.append(f"required_concepts[{idx}] must be a string or list of strings")
        if not isinstance(gt.get("rationale"), str) or not gt["rationale"].strip():
            errors.append("ground_truth.rationale must be a non-empty string")

    return errors


def prediction_to_eval_case(pred: Dict[str, Any], version: str = "0.4") -> Dict[str, Any]:
    """Convert a resolved IPX Terminal prediction into a zero-leakage IPX-Eval case."""
    outcome = pred.get("outcome")
    if pred.get("status") != "resolved" or not outcome:
        raise ValueError(f"Prediction {pred.get('case_code')} is not resolved yet")

    # Strictly use the frozen t_0 snapshot (never merge post-window outcome_metrics)
    snap = pred["signal_snapshot"]
    case: Dict[str, Any] = {
        "id": pred["case_code"],
        "version": str(version),
        "category": pred["category"],
        "sector": pred["sector"],
        "title": pred["title"],
        "captured_at": pred["captured_at"],
        "source": pred.get("source") or "ipx_terminal_export",
        "difficulty": pred.get("difficulty") or "medium",
        "signal_snapshot": {
            "summary": snap["summary"],
            "platforms": list(snap["platforms"]),
            "metrics": dict(snap.get("metrics", {})),
            "samples": list(snap.get("samples", [])),
            "entities_mentioned": list(snap.get("entities_mentioned", [])),
        },
        "question": pred["question"],
        "ground_truth": {
            "label": outcome["label"],
            "secondary_label": outcome.get("secondary_label"),
            "required_concepts": list(outcome["required_concepts"]),
            "rationale": outcome["rationale"],
            "outcome_window_hours": outcome.get("outcome_window_hours"),
        },
    }
    errors = validate_eval_case(case)
    if errors:
        raise ValueError(f"Export validation failed for {case['id']}: {'; '.join(errors)}")
    return case


def export_resolved_to_jsonl(
    db: TerminalDB,
    out_dir: Optional[Path] = None,
    version: str = "0.4",
    category: Optional[str] = None,
) -> Dict[str, Any]:
    """Export all resolved predictions to category-split JSONL files compatible with IPX-Eval."""
    target_dir = Path(out_dir) if out_dir else DEFAULT_EXPORT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    resolved = db.list_predictions(status="resolved", category=category, limit=1000)
    by_category: Dict[str, List[Dict[str, Any]]] = {}
    errors: List[str] = []

    for pred in resolved:
        try:
            case = prediction_to_eval_case(pred, version=version)
            by_category.setdefault(case["category"], []).append(case)
        except ValueError as exc:
            errors.append(str(exc))

    written_files: List[Dict[str, Any]] = []
    preview_lines: List[str] = []
    total_exported = 0

    for cat in sorted(by_category.keys()):
        cases = sorted(by_category[cat], key=lambda c: c["id"])
        file_path = target_dir / f"{cat}.jsonl"
        lines = [json.dumps(case, ensure_ascii=False) for case in cases]
        file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written_files.append(
            {
                "category": cat,
                "path": str(file_path),
                "count": len(cases),
            }
        )
        total_exported += len(cases)
        preview_lines.extend(lines[:2])

    return {
        "out_dir": str(target_dir),
        "version": version,
        "total_exported": total_exported,
        "files": written_files,
        "errors": errors,
        "preview_jsonl": "\n".join(preview_lines),
    }


def parse_concepts_text(raw: str) -> List[Any]:
    """Parse semi-colon separated concept groups (comma-separated aliases) for CLI/UI forms.

    Example:
      '12.1x, follower baseline; 38, independent; save rate, song name'
      -> [['12.1x', 'follower baseline'], ['38', 'independent'], ['save rate', 'song name']]
    """
    groups: List[Any] = []
    for chunk in raw.split(";"):
        aliases = [item.strip() for item in chunk.split(",") if item.strip()]
        if not aliases:
            continue
        groups.append(aliases[0] if len(aliases) == 1 else aliases)
    return groups


def export_creative_feedback(
    db: TerminalDB,
    out_dir: Optional[Path] = None,
    version: str = "0.5",
) -> Dict[str, Any]:
    """Export graded Creative Briefs as blind winner-vs-flop A/B pairs (for IPX-Eval v0.5-creative & DPO)."""
    target_dir = Path(out_dir) if out_dir else (DEFAULT_EXPORT_DIR / "creative-feedback")
    target_dir.mkdir(parents=True, exist_ok=True)

    graded = db.list_briefs(status="graded", limit=500)
    winners = [b for b in graded if b["verdict"] == "winner"]
    flops = [b for b in graded if b["verdict"] == "flop"]

    # 1. Full graded feedback ledger
    ledger_path = target_dir / "content_factory_feedback.jsonl"
    ledger_lines = [json.dumps(b, ensure_ascii=False) for b in graded]
    if ledger_lines:
        ledger_path.write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")

    # 2. Blind pairwise Winner vs. Flop A/B eval & DPO training pairs (metrics stripped from candidates!)
    pairs: List[Dict[str, Any]] = []
    pair_idx = 1
    for w in winners:
        for f in flops:
            if len(pairs) >= 50:
                break
            pairs.append(
                {
                    "id": f"ipx-creative_ab-{pair_idx:03d}",
                    "version": version,
                    "source": "content_factory_feedback",
                    "platform": w["target_platform"],
                    "question": (
                        "Given these two real short-form creative executions (metrics hidden), "
                        "pick which post outperformed (A or B) and explain why the hook, on-screen text, "
                        "caption, and edit pacing worked better."
                    ),
                    "candidate_a": {
                        "ticker": w["ticker"],
                        "angle": w["angle"],
                        "hook_2s": w["hook_2s"],
                        "on_screen_text": w["on_screen_text"],
                        "caption": w["caption"],
                        "edit_beats": w["edit_beats"],
                        "audio_cue": w["audio_cue"],
                    },
                    "candidate_b": {
                        "ticker": f["ticker"],
                        "angle": f["angle"],
                        "hook_2s": f["hook_2s"],
                        "on_screen_text": f["on_screen_text"],
                        "caption": f["caption"],
                        "edit_beats": f["edit_beats"],
                        "audio_cue": f["audio_cue"],
                    },
                    "ground_truth": {
                        "winner": "A",
                        "winner_metrics": {
                            "views_48h": w["views_48h"],
                            "breakout_ratio": w["breakout_ratio"],
                            "share_to_like_pct": w["share_to_like_pct"],
                        },
                        "flop_metrics": {
                            "views_48h": f["views_48h"],
                            "breakout_ratio": f["breakout_ratio"],
                            "share_to_like_pct": f["share_to_like_pct"],
                        },
                        "rationale": f"Winner notes: {w['outcome_notes']} | Flop notes: {f['outcome_notes']}".strip(),
                    },
                }
            )
            pair_idx += 1

    pairs_path = target_dir / "creative_ab_pairs.jsonl"
    if pairs:
        pairs_path.write_text(
            "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs) + "\n",
            encoding="utf-8",
        )

    return {
        "out_dir": str(target_dir),
        "graded_count": len(graded),
        "winners_count": len(winners),
        "flops_count": len(flops),
        "pairs_exported": len(pairs),
        "ledger_path": str(ledger_path) if ledger_lines else None,
        "pairs_path": str(pairs_path) if pairs else None,
        "preview_jsonl": "\n".join(json.dumps(p, ensure_ascii=False) for p in pairs[:2]),
    }
