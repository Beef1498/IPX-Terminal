# IPX Terminal — Quant Analyst Onboarding Playbook

> **Role:** Cultural & Content IP Quant Analyst  
> **Primary Surface:** `http://127.0.0.1:8765/#quant` (**Tab 3: `QUANT DESK`**)

---

## 1. Core Signal Hierarchy (What Actually Predicts Breakouts)
Do **not** chase raw solo-video views or likes. Passive entertainment gets likes and dies inside one feed. Rank every opportunity by this strict hierarchy:

1. **Derivative / Remix Breadth (`remix_breadth`):** Independent creators making videos *to* the sound, template, or joke (or a trend lighting up `>= 4` US states on **`US MAP`**).
2. **Share-to-Like Ratio (`share_to_like_pct`):** The #1 early leading indicator at $t_0$. Look for **`>= 15–20%`** (e.g., 35K shares on 78K likes = 45%).
3. **Breakout Ratio (`views / followers`):** Look for **`>= 5x`** follower baseline across mid-tier accounts rather than celebrity baseline views.
4. **Odds vs. Social Divergence (`MKTS`):** When **Social CVS / Share Velocity** spikes *before* **Polymarket or Kalshi YES %** reprices, log the divergence.

---

## 2. Daily 30-Minute Quant Routine

### Step A — Morning Factor Screen (10 min)
1. Open **`QUANT DESK`** (`#quant`).
2. Filter the **Multi-Factor Screener** by `STRONG_SIGNAL` (or set `Min Share/Like >= 15%` / `Min Breakout >= 5x`).
3. Check **`LIVE TERMINAL` → `US MAP`** (`Hide utility noise` ON) to spot newly igniting multi-state clusters and their Peak/Origin state.
4. Check **`LIVE TERMINAL` → `MKTS`** for live Polymarket & Kalshi markets (settled 99%+ markets are auto-hidden). Click **`Freeze t₀ Signal`** on any mispriced IP/culture market.

### Step B — Log 3–5 Timestamped $t_0$ Calls (10 min)
1. Click **`+ Paste URL`** in `LIVE TERMINAL` for any fresh TikTok, Instagram Reel, YouTube Short, or X post (ScrapeCreators auto-pulls live views, likes, shares, followers, and ratios).
2. Click **`Log Call`** (either from `QUANT DESK` or `WIRE`).
3. Pick your canonical label (`breakout` / `watch` / `noise`, etc.), set an **honest calibrated confidence** (`0.55–0.95`), and run **AI Compare** so your call is tracked head-to-head against the AI baseline.

### Step C — Resolve Overdue 48–72h Calls & Backtest (10 min)
1. Open **`LOG / 48-72H`** and click **`Re-Check Live`** (or run `PYTHONPATH=src python3 -m ipx_terminal recheck-due`) on any overdue predictions.
2. Record the verified ground truth without altering the frozen $t_0$ snapshot.
3. Click **`Export → IPX-Eval`** so verified outcomes flow straight into `IPX-Eval` and DGX Spark DPO/GRPO training splits.
4. Click **`⬇ Export Factors CSV`** in `QUANT DESK` whenever you want to pull `ipx_quant_factors.csv` into Python / Jupyter / Excel to backtest new factor weights.
