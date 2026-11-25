"""End-to-end tests for IPX Terminal (SQLite IP Graph, CVS, 48-72h logger, IPX-Eval export, HTTP API)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request

from ipx_terminal.ai_scorer import _extract_json_object
from ipx_terminal.db import TerminalDB
from ipx_terminal.exporter import export_resolved_to_jsonl, parse_concepts_text, validate_eval_case
from ipx_terminal.ingest import _detect_platform_from_url, seed_demo_workspace
from ipx_terminal.scoring import compute_velocity_and_contagion
from ipx_terminal.server import create_server, parse_command_bar


class TestIPXTerminal(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "test_ipx.db"
        self.db = TerminalDB(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cvs_and_contagion_scoring_distinguishes_breakout_from_echo_chamber(self) -> None:
        breakout_cvs, breakout_cnt, breakout_stage = compute_velocity_and_contagion(
            platforms=["TikTok", "Instagram Reels", "Spotify", "Shazam", "Google Trends"],
            metrics={
                "breakout_ratio_views_to_followers": 12.1,
                "unique_creators_using_sound": 120,
                "save_rate_pct": 4.8,
                "google_trends_index": 55,
            },
            captured_at="2026-11-24T20:00:00Z",
        )
        echo_cvs, echo_cnt, echo_stage = compute_velocity_and_contagion(
            platforms=["X"],
            metrics={
                "views": 1000000,
                "likes": 46000,
                "x_audience_overlap_pct": 92,
                "gdelt_articles": 0,
            },
            captured_at="2026-11-24T20:00:00Z",
        )
        self.assertGreater(breakout_cvs, echo_cvs)
        self.assertGreater(breakout_cnt, echo_cnt)
        self.assertEqual(breakout_stage, "mainstream_breakout")
        self.assertEqual(echo_stage, "echo_chamber")

    def test_zero_future_leakage_and_schema_valid_export(self) -> None:
        sig = self.db.insert_signal(
            ticker="TEST.IP",
            title="Test early breakout signal",
            summary="38 independent accounts used this 1998 bridge at 12.1x follower baseline.",
            platforms=["TikTok", "Instagram Reels"],
            metrics={"breakout_ratio_views_to_followers": 12.1, "unique_creators": 38},
            samples=["'What song is this?'"],
            sector="MUSIC",
            entity_name="Test Catalog Track",
            owner_holder="Sony Music",
        )
        pred = self.db.create_prediction(
            signal_id=sig["id"],
            category="breakout",
            predicted_label="breakout",
            confidence=0.88,
            outcome_window_hours=48,
        )
        resolved = self.db.resolve_prediction(
            prediction_id=pred["id"],
            ground_truth_label="breakout",
            secondary_label="organic_catalog_revival",
            required_concepts=parse_concepts_text("12.1x, baseline; 38, independent"),
            rationale="Verified at t_0+48h: Shazam #38 and +420% Spotify streams.",
            outcome_metrics={"shazam_rank_48h": 38, "spotify_lift_pct_48h": 420},
        )
        self.assertTrue(resolved["outcome"]["prediction_correct"])

        out_dir = Path(self._tmp.name) / "export"
        result = export_resolved_to_jsonl(self.db, out_dir=out_dir, version="0.4")
        self.assertEqual(result["total_exported"], 1)
        self.assertEqual(result["errors"], [])

        exported_file = out_dir / "breakout.jsonl"
        self.assertTrue(exported_file.exists())
        exported = json.loads(exported_file.read_text(encoding="utf-8").strip())
        self.assertEqual(validate_eval_case(exported), [])
        self.assertEqual(exported["source"], "ipx_terminal_export")
        # Ensure post-window outcome_metrics did NOT leak into frozen t_0 signal_snapshot
        self.assertNotIn("shazam_rank_48h", exported["signal_snapshot"]["metrics"])
        self.assertEqual(exported["signal_snapshot"]["metrics"]["unique_creators"], 38)

    def test_seed_command_bar_and_http_api(self) -> None:
        stats = seed_demo_workspace(self.db)
        self.assertGreaterEqual(stats["entities"], 7)
        self.assertEqual(stats["resolved"], 4)

        cmd = parse_command_bar("KATT.FMT GP GO", self.db)
        self.assertEqual(cmd["action"], "select_ticker")
        self.assertEqual(cmd["ticker"], "KATT.FMT")
        self.assertEqual(cmd["function"], "GP")

        sec_cmd = parse_command_bar("MUSIC TOP", self.db)
        self.assertEqual(sec_cmd["action"], "filter_sector")
        self.assertEqual(sec_cmd["sector"], "MUSIC")

        dash = self.db.get_dashboard_stats()
        self.assertEqual(dash["resolved_predictions"], 4)
        self.assertEqual(dash["pending_predictions"], 3)
        self.assertEqual(dash["prediction_accuracy_pct"], 100.0)

        movers = self.db.get_top_movers()
        self.assertGreaterEqual(len(movers), 7)

        exp = export_resolved_to_jsonl(
            self.db,
            out_dir=Path(self._tmp.name) / "api_export",
            version="0.4",
        )
        self.assertEqual(exp["total_exported"], 4)
        self.assertEqual(exp["errors"], [])

    def test_url_platform_detection_and_human_vs_ai_tracking(self) -> None:
        self.assertEqual(_detect_platform_from_url("https://www.youtube.com/shorts/O8P8iXzWlzQ"), "YouTube Shorts")
        self.assertEqual(_detect_platform_from_url("https://www.tiktok.com/@jcrow73/video/123"), "TikTok")
        self.assertEqual(_detect_platform_from_url("https://x.com/greghunkins/status/123"), "X")

        parsed = _extract_json_object("<thought>reasoning</thought>```json\n{\"label\": \"breakout\", \"confidence\": 0.85}\n```")
        self.assertEqual(parsed["label"], "breakout")

        sig = self.db.insert_signal(
            ticker="AI.TEST",
            title="Human vs AI test",
            summary="Test signal for side-by-side grading.",
            platforms=["TikTok"],
            sector="POP",
        )
        pred = self.db.create_prediction(
            signal_id=sig["id"],
            category="breakout",
            predicted_label="breakout",
            confidence=0.85,
            ai_model="gemini-3.5-flash-lite",
            ai_predicted_label="noise",
            ai_confidence=0.72,
            ai_reasoning="Model missed share-to-like velocity.",
        )
        resolved = self.db.resolve_prediction(
            prediction_id=pred["id"],
            ground_truth_label="breakout",
            required_concepts=["share-to-like"],
            rationale="Human beat AI on real breakout.",
        )
        self.assertTrue(resolved["outcome"]["prediction_correct"])
        self.assertFalse(resolved["ai_prediction"]["correct"])
        stats = self.db.get_dashboard_stats()
        self.assertEqual(stats["prediction_accuracy_pct"], 100.0)
        self.assertEqual(stats["ai_accuracy_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
