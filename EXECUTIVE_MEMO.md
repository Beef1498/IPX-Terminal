# MEMO: IPX Command Center & Autonomous Cultural Quant Flywheel

**To:** CEO, CTO, Engineering & Creative Leadership  
**From:** Justin Vieth  
**Date:** November 26, 2026  
**Live App:** https://ipx-command-center-production.up.railway.app  
**Repositories:** [Beef1498/IPX-Terminal](https://github.com/Beef1498/IPX-Terminal) (Command Center) · [Beef1498/IPX-eval](https://github.com/Beef1498/IPX-eval) (Benchmarks & Model Training Data)

---

## 1. The Idea (In One Paragraph)

**IPX Command Center** is a Bloomberg-style workstation built specifically for Content IP. Instead of reacting to trends after they peak, it ingests live cross-platform signals (TikTok, Instagram Reels, YouTube Shorts, X, 50-state Google Trends, GDELT news, and Polymarket/Kalshi odds), ranks emerging formats by real cultural velocity, automatically drafts shootable short-form video briefs, and logs time-stamped predictions that are graded 48–72 hours later against real-world outcomes. Every verified outcome feeds directly into **`IPX-Eval`** to benchmark and fine-tune our own open-source models on DGX Spark.

---

## 2. Thought Process & Why We Built It This Way

Three observations drove the architecture:

1. **Vanity metrics lag reality.** Raw likes and views tell you what *already* happened. Early breakouts show up first in **derivative remakes** (other creators copying an audio/format), **US geographic spread**, **share-to-like ratios**, and **views-to-follower breakout multiples**. The terminal scores signals strictly in that hierarchy.
2. **Never let AI grade its own homework.** Generic LLM workflows fail because the same model that predicts a trend also invents the evaluation. Every prediction in IPX Terminal freezes an immutable `t_0` snapshot first; outcomes are adjudicated 48–72 hours later strictly from objective real-world metrics (or human review)—creating zero-leakage ground truth.
3. **One closed flywheel beats five disconnected tools.** Discovery, creative briefing, prediction logging, model evaluation, and fine-tuning data export all live in one system so every day of operation compounds our proprietary dataset.

---

## 3. What Is Live & Running Today

The system is deployed on **Railway** (read-only public view + passcode-protected writes) and runs an automated daily/weekly schedule:

- **`1 EVALS` (Model Leaderboard & Training Tracker):** Tracks model benchmarks, loss curves, and promotion gates across `IPX-Eval` (current baseline: `gemini-3.5-flash-lite` at **79.64 composite / 72.0% accuracy** across **143 blind, same-creator Winner-vs-Flop A/B pairs** on TikTok, Reels, Shorts, and X).
- **`2 LIVE TERMINAL` (4-Pane Workstation):** Real-time Top Movers (`TOP`), Polymarket & Kalshi live odds (`MKTS`), 50-state US Cultural Contagion Map (`US MAP`), 48–72h Prediction Logger (`LOG`), and Creative Studio (`BRIEF`).
- **`3 QUANT DESK` (Autonomous Gemini Quant + 8-Gate VCRM):** Multi-factor alpha screener, Odds-vs-Social Divergence Radar, Human-vs-AI Brier Calibration Scorecard, 1-click CSV export, and a live **8-Gate Verification & Validation Matrix (VCRM)** that flags data or cadence drift automatically.
- **`4 ORCHESTRATION` & `5 UPDATES`:** Live software/hardware topology map and automatic GitHub commit/release stream for full company visibility.
- **Autonomous Schedule (`America/Chicago`):**
  - **8:30 AM Daily:** Gemini Quant Morning Pass (rechecks overdue 48–72h calls, auto-resolves clear-cut numeric outcomes into `IPX-Eval`, freezes divergent Polymarket/Kalshi markets, logs calibrated `t_0` calls, and auto-drafts up to 2 ready-to-shoot Video Briefs).
  - **9:00 AM Daily:** GDELT news sweep & 48–72h ScrapeCreators metric recheck.
  - **1:00 PM & 6:00 PM Daily:** Gemini Flash-Lite Intraday Breakout Scout.
  - **Sundays 8:00 PM:** Deduplicated creator watchlist rotation → new blind 4-platform A/B pairs + DPO/GRPO training JSONL export for DGX Spark.

---

## 4. Clean Handover Process

When transitioning ownership or onboarding teammates across Product, Creative, Engineering, and ML:

| Role | Immediate Access & Ownership | Day-1 Starting Point |
| :--- | :--- | :--- |
| **CEO / Leadership** | Read-only live dashboard, Daily Quant Memos, Model Leaderboard, GitHub Updates | Open [Quant Desk](https://ipx-command-center-production.up.railway.app/#quant) and [Evals](https://ipx-command-center-production.up.railway.app/#evals) |
| **Creative / Content Team** | Review auto-drafted Morning Video Briefs, shoot/post, log 48h real-world verdicts (`winner`/`flop`) | [Live Terminal → BRIEF](https://ipx-command-center-production.up.railway.app/#terminal) |
| **Quant / Strategy** | Monitor Multi-Factor Screener, Odds-vs-Social divergences, Brier calibration, and 8-Gate VCRM | [Quant Desk](https://ipx-command-center-production.up.railway.app/#quant) · [QUANT_PLAYBOOK.md](https://github.com/Beef1498/IPX-Terminal/blob/main/QUANT_PLAYBOOK.md) |
| **CTO / Engineering** | Railway hosting (`ipx-command-center`), GitHub auto-deploy (`main`), API keys (`GEMINI_API_KEY`, `SCRAPECREATORS_API_KEY`, `IPX_WRITE_TOKEN`), unit test suite (`14/14` passing) | [DEPLOY.md](https://github.com/Beef1498/IPX-Terminal/blob/main/DEPLOY.md) · [Dockerfile](https://github.com/Beef1498/IPX-Terminal/blob/main/Dockerfile) · [src/ipx_terminal/](https://github.com/Beef1498/IPX-Terminal/tree/main/src/ipx_terminal) |
| **ML / DGX Spark Team** | Pull weekly DPO/GRPO exports (`IPX-Eval/exports/dgx-training/`), run `ipx-eval` benchmarks, POST run metrics to `/api/evals/runs`, enforce Promotion Gate (`ipx-eval gate`) | [IPX-eval Repo](https://github.com/Beef1498/IPX-eval) · [1 EVALS](https://ipx-command-center-production.up.railway.app/#evals) |

**Deployment & Governance Rules:**
- **Zero-downtime deploys:** Every push to `main` on `IPX-Terminal` automatically builds and deploys to Railway via `Dockerfile`.
- **Write protection:** Public viewers can inspect all tabs safely; write actions (`POST`) require the team passcode (`IPX_WRITE_TOKEN`) unlocked via the top-right lock button.
- **No silent regressions:** Run `PYTHONPATH=src python3 -m unittest discover -s tests -v` before merging changes, and monitor the 8-Gate VCRM in `3 QUANT DESK` for operational health.

---

## 5. Deep-Dive Appendix (For Engineering & Technical Review)

For anyone who wants to inspect the underlying mechanics, scoring math, and infrastructure in full detail:

1. **Zero-Dependency Backend & Storage:** Built intentionally on Python standard library + SQLite WAL mode (`data/ipx_terminal.db`) with zero third-party runtime dependencies—fast cold starts, trivial Docker builds (`python:3.12-slim`), and simple horizontal/volume backup on Railway.
2. **Scoring & Factor Engine ([scoring.py](https://github.com/Beef1498/IPX-Terminal/blob/main/src/ipx_terminal/scoring.py), [quant.py](https://github.com/Beef1498/IPX-Terminal/blob/main/src/ipx_terminal/quant.py)):**
   - **CVS (0–100) & Contagion Index:** Weights cross-platform breadth, derivative remix adoption (`unique_creators_using_sound`, `derivative_videos`), `share_to_like_ratio`, and `breakout_ratio_views_to_followers`.
   - **Quant Alpha Score (0–100):** Combines log-scaled remix/US-state breadth, share-to-like %, breakout multiple, CVS, and CVS momentum; flags `STRONG_SIGNAL` when `alpha >= 60`, `share/like >= 20%`, `breakout >= 8x`, or `remix_breadth >= 15`.
3. **Verification Cross-Reference Matrix ([requirements_vcrm.json](https://github.com/Beef1498/IPX-Terminal/blob/main/data/requirements_vcrm.json), [vcrm.py](https://github.com/Beef1498/IPX-Terminal/blob/main/src/ipx_terminal/vcrm.py)):**
   - Separates **Verification** (*built right*: zero future timestamp leakage, independent eval score ≥ 75%, AI audit trail) from **Validation** (*built the right thing*: 0 overdue 48–72h rechecks, Brier calibration ≥ 70%, live market grounding, graded real-world creative outcomes).
4. **Deterministic Auto-Resolution & Zero Leakage ([quant_agent.py](https://github.com/Beef1498/IPX-Terminal/blob/main/src/ipx_terminal/quant_agent.py), [exporter.py](https://github.com/Beef1498/IPX-Terminal/blob/main/src/ipx_terminal/exporter.py)):**
   - Clear-cut 48–72h metric deltas (`views_ratio >= 2.0x` or `+250k` views → `breakout`; `<= 1.15x` and `< 25k` → `noise`) resolve deterministically and auto-export to `IPX-Eval` JSONL; ambiguous cases stay pending for human review.
5. **Key Reference Docs (Clickable on GitHub):**
   - [QUANT_PLAYBOOK.md](https://github.com/Beef1498/IPX-Terminal/blob/main/QUANT_PLAYBOOK.md) — Daily Quant SOP & factor definitions
   - [TERMINAL_GUIDE.md](https://github.com/Beef1498/IPX-Terminal/blob/main/TERMINAL_GUIDE.md) — Full Command Center & ticker guide
   - [DEPLOY.md](https://github.com/Beef1498/IPX-Terminal/blob/main/DEPLOY.md) — Railway/Render deployment & webhook reference
   - [requirements_vcrm.json](https://github.com/Beef1498/IPX-Terminal/blob/main/data/requirements_vcrm.json) — Live 8-gate requirements spec
   - [IPX-eval Repository](https://github.com/Beef1498/IPX-eval) — Benchmark runner, 143-pair creative dataset, and DGX Spark DPO/GRPO exports
