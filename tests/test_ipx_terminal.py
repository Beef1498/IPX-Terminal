"""End-to-end tests for IPX Terminal (SQLite IP Graph, CVS, 48-72h logger, IPX-Eval export, HTTP API)."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock
import urllib.error
import urllib.request

from ipx_terminal.ai_scorer import _extract_json_object, generate_creative_brief
from ipx_terminal.db import TerminalDB
from ipx_terminal.exporter import (
    export_creative_feedback,
    export_resolved_to_jsonl,
    parse_concepts_text,
    validate_eval_case,
)
from ipx_terminal.ingest import (
    _detect_platform_from_url,
    _parse_scrapecreators_payload,
    extract_url_metadata,
    recheck_prediction_metrics,
    seed_demo_workspace,
    sweep_watchlist,
)
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

    def test_creative_brief_and_blind_winner_vs_flop_ab_export(self) -> None:
        sig = self.db.insert_signal(
            ticker="KATT.FMT",
            title="Katt Williams CapCut template",
            summary="35.3K shares on 78.6K likes.",
            platforms=["TikTok"],
            sector="CREATORS",
        )
        draft = generate_creative_brief(sig, target_platform="TikTok", api_key="")
        self.assertIn("hook_2s", draft)

        win = self.db.create_brief(
            signal_id=sig["id"],
            target_platform="TikTok",
            angle="Deadpan marriage-chores cutout",
            hook_2s="Cold open on Katt cutout at 0.0s",
            on_screen_text="My husband's work ethic when it's time to unload the dishwasher",
            caption="45 seconds of effort max",
            edit_beats=["0-2s: cutout drop", "2-7s: punchline"],
            audio_cue="original sound",
        )
        flop = self.db.create_brief(
            signal_id=sig["id"],
            target_platform="TikTok",
            angle="Generic AI reaction",
            hook_2s="Hey guys check out this funny trend!",
            on_screen_text="Wait until the end for this hilarious meme!",
            caption="Like and subscribe for more trending content! #fyp #viral",
            edit_beats=["0-4s: slow intro"],
            audio_cue="generic track",
        )
        self.db.grade_brief(
            brief_id=win["id"],
            verdict="winner",
            account_handle="@ipx_test",
            views_48h=185000,
            likes_48h=14200,
            shares_48h=5100,
            follower_baseline=12000,
            outcome_notes="15.4x follower breakout; deadpan hook held 64% past 3s.",
        )
        self.db.grade_brief(
            brief_id=flop["id"],
            verdict="flop",
            account_handle="@ipx_test",
            views_48h=920,
            likes_48h=24,
            shares_48h=1,
            follower_baseline=12000,
            outcome_notes="0.08x baseline; generic AI clickbait intro caused immediate swipe-away.",
        )

        out_dir = Path(self._tmp.name) / "creative"
        exp = export_creative_feedback(self.db, out_dir=out_dir, version="0.5")
        self.assertEqual(exp["graded_count"], 2)
        self.assertEqual(exp["pairs_exported"], 1)
        pair_line = json.loads((out_dir / "creative_ab_pairs.jsonl").read_text(encoding="utf-8").strip())
        # Ensure metrics are stripped from blind candidates!
        self.assertNotIn("views_48h", pair_line["candidate_a"])
        self.assertEqual(pair_line["ground_truth"]["winner"], "A")

    def test_scrapecreators_normalization_enrichment_and_recheck(self) -> None:
        tiktok_payload = {
            "aweme_detail": {
                "desc": "When someone asks me about my husband's work ethic",
                "author": {"unique_id": "jcrow73", "follower_count": 15000},
                "statistics": {
                    "play_count": 900000,
                    "digg_count": 80000,
                    "share_count": 36000,
                    "comment_count": 500,
                    "collect_count": 6200,
                },
            }
        }
        parsed = _parse_scrapecreators_payload(
            platform="TikTok",
            payload=tiktok_payload,
            url="https://www.tiktok.com/@jcrow73/video/7701835190682881293",
        )
        self.assertEqual(parsed["author"], "jcrow73")
        self.assertEqual(parsed["metrics"]["views"], 900000)
        self.assertEqual(parsed["metrics"]["likes"], 80000)
        self.assertEqual(parsed["metrics"]["shares"], 36000)
        self.assertEqual(parsed["metrics"]["bookmarks"], 6200)
        self.assertEqual(parsed["metrics"]["creator_followers"], 15000)
        self.assertEqual(parsed["metrics"]["share_to_like_ratio"], 0.45)
        self.assertEqual(parsed["metrics"]["breakout_ratio_views_to_followers"], 60.0)
        self.assertEqual(parsed["metrics"]["enrichment_provider"], "scrapecreators")

        # extract_url_metadata should use ScrapeCreators when key is provided
        with mock.patch("ipx_terminal.ingest._http_get_json", return_value=tiktok_payload) as mock_get:
            meta = extract_url_metadata(
                "https://www.tiktok.com/@jcrow73/video/7701835190682881293",
                scrapecreators_api_key="test-sc-key",
            )
            self.assertEqual(meta["metrics"]["views"], 900000)
            self.assertEqual(meta["metrics"]["enrichment_provider"], "scrapecreators")
            called_url = mock_get.call_args[0][0]
            called_headers = mock_get.call_args[1]["headers"]
            self.assertIn("/v2/tiktok/video?", called_url)
            self.assertEqual(called_headers["x-api-key"], "test-sc-key")

        # recheck_prediction_metrics should compute deltas without mutating frozen t_0 snapshot
        sig = self.db.insert_signal(
            ticker="KATT.FMT",
            title="Katt Williams CapCut template",
            summary="Early snapshot.",
            platforms=["TikTok"],
            metrics={"views": 300000, "likes": 40000, "shares": 18000, "url": "https://www.tiktok.com/@jcrow73/video/7701835190682881293"},
            url="https://www.tiktok.com/@jcrow73/video/7701835190682881293",
            sector="CREATORS",
        )
        pred = self.db.create_prediction(
            signal_id=sig["id"],
            category="breakout",
            predicted_label="breakout",
            confidence=0.88,
            outcome_window_hours=48,
        )
        with mock.patch("ipx_terminal.ingest._http_get_json", return_value=tiktok_payload):
            recheck = recheck_prediction_metrics(self.db, pred["id"], api_key="test-sc-key")
        self.assertEqual(recheck["provider"], "scrapecreators")
        self.assertEqual(recheck["deltas"]["views_delta"], 600000)
        self.assertEqual(recheck["deltas"]["views_multiplier"], 3.0)
        self.assertEqual(recheck["deltas"]["likes_delta"], 40000)
        # Verify t_0 snapshot remained frozen
        stored = self.db.get_prediction(pred["id"])
        self.assertEqual(stored["signal_snapshot"]["metrics"]["views"], 300000)

    def test_sweep_watchlist_skips_empty_rotates_and_retries_429(self) -> None:
        self.db.insert_signal(
            ticker="LOW.IP",
            title="Low CVS ticker",
            summary="Quiet signal.",
            platforms=["X"],
            metrics={"likes": 100},
            sector="POP",
            entity_name="Low Entity",
        )
        self.db.insert_signal(
            ticker="HIGH.IP",
            title="High CVS ticker",
            summary="Big cross-platform breakout.",
            platforms=["TikTok", "Spotify", "Google Trends"],
            metrics={"breakout_ratio_views_to_followers": 10.0, "google_trends_index": 70},
            sector="MUSIC",
            entity_name="High Entity",
        )

        call_log = []

        def fake_get_json(url: str, timeout: int = 15, headers=None):
            call_log.append(url)
            if "High+Entity" in url:
                if len([u for u in call_log if "High+Entity" in u]) == 1:
                    raise urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
                return {
                    "articles": [
                        {"title": "High Entity breaks out", "domain": "variety.com", "language": "English", "url": "https://variety.com/1"}
                    ]
                }
            # Low Entity returns 0 articles -> should be skipped when skip_empty=True
            return {"articles": []}

        with mock.patch("ipx_terminal.ingest._http_get_json", side_effect=fake_get_json), mock.patch("ipx_terminal.ingest.time.sleep"):
            res = sweep_watchlist(self.db, limit=2, delay_sec=0.0, skip_empty=True, max_retries=1)

        self.assertEqual(res["swept_count"], 1)
        self.assertEqual(res["ingested"][0]["ticker"], "HIGH.IP")
        self.assertEqual(res["skipped_empty"], ["LOW.IP"])
        self.assertEqual(res["errors"], [])
        # High CVS entity should have been prioritized first
        self.assertIn("High+Entity", call_log[0])


if __name__ == "__main__":
    unittest.main()
