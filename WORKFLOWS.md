# IPX Terminal — Real-World Desk Workflows (Bloomberg → IPX)

Every workflow below maps a real **Bloomberg Terminal** daily routine directly onto **IPX Terminal**, using live commands you can run right now in `http://127.0.0.1:8765`.

---

## Workflow 1: The Morning Market Open — *Separate Real Breakouts from Echo Chambers*
- **Bloomberg Equivalent:** Equity trader opening `TOP` + `MOST` at 9:25 AM ET to separate real institutional volume breakouts from thin retail noise.
- **Who Uses This:** Content IP investors, studio/agency scouts, `IPX Live` hosts prepping the daily rundown.
- **Step-by-Step in IPX Terminal:**
  1. Press **`/`**, type **`ALL`**, press **Enter** — loads every tracked IP in **`TOP`**.
  2. Compare the top vs. bottom of the tape:
     - **`KATT.FMT`** (`CVS 79.1`, `Δ +38.2`, `mainstream_breakout`) — accelerating fast across multiple platforms.
     - **`GTA6`** (`CVS 13.3`, `CONTAGION 1.0`, `echo_chamber`) — has **1M views on X**, yet ranks dead last because of 89% audience overlap and zero cross-platform escape.
  3. Type **`KATT.FMT GP`** → inspect the 3-point velocity curve jumping from 14 creators → 45% share-to-like CapCut template → 210+ cross-platform clones.
  4. Type **`GTA6 GP`** → verify why raw views fooled people while Contagion caught the bubble.
- **Decision Output:** Spend time/capital on `KATT.FMT`; fade `GTA6` until it jumps off X.

---

## Workflow 2: Music A&R & Catalog Rights Scout — *Track a TikTok → Billboard Hot 100 Breakout*
- **Bloomberg Equivalent:** Event-driven analyst filtering by sector, spotting an unusual volume/price divergence in `GP`, and pulling `DES` to see who owns the underlying security.
- **Who Uses This:** Record labels, music-rights funds, sync agencies, independent catalog buyers.
- **Step-by-Step in IPX Terminal:**
  1. Click the cyan **`MUSIC`** Sector Key (or type **`MUSIC TOP`**).
  2. Click **`FAOUZ.UN`** (*Faouzia — "UNETHICAL"*) → look at **`GP`**: watch the curve move from TikTok/Spotify viral save acceleration into her first-ever Billboard Hot 100 & Billboard Global 200 debut.
  3. Check **`DES`** → instantly see who owns/monetizes the IP (**Faouzia / Warner Music Group**) and compare against **`SOMBR.BF`** (*Sombr — "Back to Friends"*).
  4. Click **`+ Log Prediction`** on any new music signal to lock in a timestamped 48h call.
- **Decision Output:** Spot the track and rights holder *before* charts catch up, and grade your calls in `LOG`.

---

## Workflow 3: Brand Safety & Executive Likeness Risk Desk — *Triage an AI Deepfake Catalyst*
- **Bloomberg Equivalent:** Corporate risk / equity desk monitoring `CN` (Company News) when an unexpected executive headline hits the wire.
- **Who Uses This:** Public-company comms/IR teams, talent agencies, brand-safety desks, equity analysts.
- **Step-by-Step in IPX Terminal:**
  1. Type **`NVDA.IP DES`** → review the rights holder (`NVIDIA Corp.`) and aliases (`Jensen Huang`, `Leather Jacket CEO`).
  2. Inspect **`GP`** & **`WIRE`**: two distinct AI waves — a benign `character_transplant` parody (Kanye 2005 Grammys speech, 488K views) followed by an unauthorized suggestive mirror selfie with branded GPU hardware (`106K` likes on IG).
  3. Click **`GDELT Sweep`** in the toolbar, enter ticker `NVDA.IP` and query `"Jensen Huang" NVIDIA` → check live whether mainstream financial press has picked it up.
  4. Open the **`LOG / 48-72H`** tab → track `ipx-ip_catalyst-401` (`rights_risk`) over the 48h window.
- **Decision Output:** Distinguish harmless AI meme parody (`character_transplant`) from actionable reputational/trademark exposure (`rights_risk`).

---

## Workflow 4: Catalog M&A & Licensing Deal Desk — *Track Sony × Recognition ($3.5B–$4B)*
- **Bloomberg Equivalent:** M&A arbitrage desk filtering `MA` / `DEALS` and tracking trade-press velocity + deal catalysts.
- **Who Uses This:** Media bankers, PE/VC funds, streaming & licensing execs.
- **Step-by-Step in IPX Terminal:**
  1. Click the gold **`DEALS`** Sector Key (or type **`DEALS TOP`**).
  2. Click **`SONY.RMG`** → check **`GP`** (`mainstream_breakout`, 45,000+ song Hipgnosis/Recognition catalog acquired by Sony Music Publishing & GIC for $3.5B–$4.0B).
  3. Open **`DES`** → inspect the rights-holder JV structure and linked `ma_deal` prediction.
  4. Run a follow-up **`GDELT Sweep`** to monitor ongoing music-catalog M&A coverage.
- **Decision Output:** One-screen view of press velocity, library valuation context, and open deal thesis.

---

## Workflow 5: The `IPX Live` → `IPX-Eval` Flywheel — *Build Your Proprietary AI Moat*
- **Bloomberg Equivalent:** Bloomberg TV anchor pulling a live chart on air, making a timestamped market call, and auditing the track record afterward.
- **Who Uses This:** You — running IPX Terminal daily and/or live on `IPX Live` ("Call Your Shot") to continuously train and grade your own AI models on DGX Spark.
- **Step-by-Step in IPX Terminal:**
  1. **Day 0 ($t_0$):** See a real post on TikTok, X, Reels, or YouTube Shorts → click **`+ Capture t₀ Signal`** and enter the raw metrics & quotes.
  2. **Freeze the Call:** Click **`Log Prediction`** on that signal in **`WIRE`**. IPX Terminal freezes the exact $t_0$ snapshot so future data can never leak backward.
  3. **Day 2–3 (+48–72h):** Type **`LOG`**, find the pending prediction, click **`Resolve 48-72h Outcome`**, and record what actually happened (`ground_truth_label`, `required_concepts`, `rationale`).
  4. **Export to Benchmark:** Type **`EXPORT`**, click **`Target IPX-Eval/datasets/v0.4-terminal`**, then **`Export Resolved Cases to JSONL`**.
- **Decision Output:** Your **HIT RATE** updates live in the top bar, and your resolved calls become contamination-proof real-world test cases for **`IPX-Eval`** and future DGX Spark fine-tuning.
