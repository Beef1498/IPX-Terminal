# IPX Terminal — Operator's Guide & Bloomberg Key

> You don't need prior Bloomberg Terminal experience to operate IPX Terminal—and nothing in the terminal is dumbed down. This guide maps every institutional code, score, and workflow to plain English.

---

## 1. The Bloomberg Mental Model: `<TICKER> <FUNCTION> <GO>`

A Bloomberg Terminal is driven by a **3-part sentence** typed into the top command bar:

1. **WHO (`<TICKER>` or `<SECTOR>`)**: What IP asset or asset class you're looking at (e.g., `KATT.FMT`, `NVDA.IP`, `MUSIC`, `DEALS`).
2. **WHAT (`<FUNCTION>`)**: A 2–6 letter shorthand for the screen you want (e.g., `GP`, `DES`, `TOP`, `LOG`).
3. **EXECUTE (`<GO>` or `Enter`)**: Runs the command.

### Try These 5 Commands First
| Command | What It Does |
| :--- | :--- |
| `KATT.FMT GP` | Loads the Katt Williams CapCut format into the **Velocity & Contagion Graph** |
| `NVDA.IP DES` | Opens the **IP Profile / Rights Holder** card for NVIDIA / Jensen Huang |
| `MUSIC TOP` | Filters the **Top Movers** tape to Music catalog & audio signals only |
| `LOG` | Switches the desk pane to your **48–72h Prediction & Outcome Logger** |
| `EXPORT` | Opens the **IPX-Eval JSONL Exporter** (zero-leakage benchmark export) |
| `HELP` (or press `?`) | Opens the interactive Operator's Key right inside the terminal |

---

## 2. Function Code Key (Bloomberg Origin → IPX Terminal Meaning)

| Code | Bloomberg Origin | What It Means in IPX Terminal |
| :--- | :--- | :--- |
| **`TOP`** | Top News / Market Movers | Ranked leaderboard of all tracked Content IP tickers sorted by **CVS** (Cultural Velocity Score). Click any row to load it. |
| **`GP`** | Graph Price | Time-series chart plotting **CVS** (cyan line) and **Contagion Index** (amber dashed line) across captured $t_0$ snapshots. |
| **`DES`** | Description (Tear Sheet) | Entity-Resolution IP Graph card: who owns/monetizes the IP (studio, label, creator, brand), asset type, aliases, and linked predictions. |
| **`WIRE`** | News Wire / Live Tape | Chronological feed of raw $t_0$ signals from social platforms, search, and GDELT news. Every card has a 1-click **Log Prediction** button. |
| **`LOG`** | Trade / Blotter Log | Your prediction ledger. Freezes the exact $t_0$ signal snapshot and tracks the 48–72h resolution clock. |
| **`EXPORT`** | Data Export | Validates resolved outcomes against `eval_case.schema.json` and writes JSONL files straight into **`IPX-Eval`**. |
| **`HELP`** | `<HELP>` / `F1` Key | Opens the built-in cheat-sheet with clickable "Try It" command buttons. |

---

## 3. Reading the Scores & Badges

### Cultural Velocity Score (`CVS`, 0–100) & Delta (`Δ`)
- **What it measures:** Real-time, time-decayed momentum of an IP asset.
- **What pushes it up:** High views-to-followers breakout ratio (e.g., `12.1x`), high share-to-like or save rate, spread across many independent creators, and multi-platform pickup.
- **What pushes it down:** Paid/boosted promo flags, single-account flukes, and age (exponential time decay with a 48h half-life).
- **`Δ` (Delta):** Change in CVS compared to the previous captured snapshot for that ticker (`+38.2` = accelerating fast).

### Cross-Platform Contagion Index (`CONTAGION`, 0–100) & `STAGE`
Raw views lie—a post can get 1M views inside one niche bubble and die there. Contagion measures **escape velocity across surfaces**:
- **`echo_chamber` (< 38):** Trapped inside one platform or high-overlap community (e.g., `GTA6` with 1M views on X but 89% audience overlap and 0 news/TikTok spillover).
- **`emerging_contagion` (38–67):** Jumping from its origin platform into a second surface or early search/creator pickup.
- **`mainstream_breakout` (68+):** Confirmed cross-platform spread across short-form video, audio/charts (Spotify/Shazam), Google Trends, or GDELT press.

### Sector Keys (Color-Coded Asset Classes)
- `POP` (Amber) · `MUSIC` (Cyan) · `FILM_TV` (Violet) · `GAMING` (Green) · `CREATORS` (Coral) · `SPORTS` (Blue) · `DEALS` (Gold)

---

## 4. The Daily 4-Step Operator Workflow (The `IPX-Eval` Flywheel)

1. **Capture at $t_0$:** Spot something moving on TikTok/X/Reels/Shorts/YouTube/News → click **`+ Capture t₀ Signal`** (or **`GDELT Sweep`**) so the exact metrics and quotes are timestamped.
2. **Analyze in `TOP` + `GP` + `DES`:** Check whether CVS is accelerating (`Δ > 0`), whether Contagion shows real cross-platform escape or an `echo_chamber`, and who owns the underlying IP in `DES`.
3. **Log a Prediction (`LOG`):** Click **Log Prediction** on any signal. IPX Terminal **freezes the $t_0$ snapshot** (preventing future leakage) and starts a 48h or 72h clock.
4. **Resolve & Export (`EXPORT`):** After 48–72h, record the real-world outcome (`ground_truth_label`, `required_concepts`, `rationale`) and click **Export Resolved Cases to JSONL** to feed fresh, contamination-proof real-world cases directly into **`IPX-Eval`**.

---

## 5. Keyboard Shortcuts
- **`/`** — Jump straight to the top command bar
- **`?`** — Open the interactive Operator's Key (`HELP`)
- **`Esc`** — Close any open modal
