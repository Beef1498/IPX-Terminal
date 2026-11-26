#!/usr/bin/env python3
"""Push a training or IPX-Eval run to the hosted IPX Command Center (works on Mac, Cloud GPU, or DGX Spark)."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.request

DEFAULT_URL = os.environ.get(
    "IPX_DASHBOARD_URL",
    "https://ipx-command-center-production.up.railway.app",
)


def push_eval_run(
    payload: dict,
    dashboard_url: str = DEFAULT_URL,
    token: str | None = None,
    timeout: int = 20,
) -> dict:
    """POST an eval/training run payload to /api/evals/runs and return the JSON response."""
    endpoint = dashboard_url.rstrip("/") + "/api/evals/runs"
    headers = {"Content-Type": "application/json"}
    tok = (token or os.environ.get("IPX_WRITE_TOKEN", "")).strip()
    if tok:
        headers["X-IPX-Token"] = tok
    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Push an eval/training run to the live IPX Command Center.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Hosted IPX Command Center base URL.")
    parser.add_argument("--token", default=os.environ.get("IPX_WRITE_TOKEN", ""), help="IPX_WRITE_TOKEN passcode.")
    parser.add_argument("--json-file", type=Path, default=None, help="Path to an existing eval result JSON file.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--dataset", default="v0.4")
    parser.add_argument("--hardware", default="Mac / Local")
    parser.add_argument("--status", default="completed", choices=["running", "completed", "queued", "failed"])
    parser.add_argument("--score", type=float, default=None, help="Overall score (0-100).")
    parser.add_argument("--accuracy", type=float, default=None, help="Accuracy % (0-100).")
    parser.add_argument("--concept-recall", type=float, default=None, help="Concept recall % (0-100).")
    parser.add_argument("--train-loss", type=float, default=None)
    parser.add_argument("--eval-loss", type=float, default=None)
    parser.add_argument("--step", type=int, default=None)
    parser.add_argument("--epoch", type=float, default=None)
    parser.add_argument("--category-scores-json", default="{}")
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    if args.json_file:
        payload = json.loads(args.json_file.read_text(encoding="utf-8"))
    else:
        if not args.run_id or not args.model:
            parser.error("Provide either --json-file or both --run-id and --model.")
        payload = {
            "run_id": args.run_id,
            "model_name": args.model,
            "dataset_version": args.dataset,
            "hardware": args.hardware,
            "status": args.status,
            "overall_score": args.score,
            "accuracy_pct": args.accuracy,
            "concept_recall_pct": args.concept_recall,
            "train_loss": args.train_loss,
            "eval_loss": args.eval_loss,
            "step": args.step,
            "epoch": args.epoch,
            "category_scores": json.loads(args.category_scores_json),
            "source": "cli_push",
            "notes": args.notes,
        }

    res = push_eval_run(payload, dashboard_url=args.url, token=args.token)
    print(json.dumps(res, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
