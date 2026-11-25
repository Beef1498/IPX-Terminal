# IPX Terminal — Project Context & Architecture

> **Core Thesis:** Content IP (franchises, artists, songs, films/TV, creators, gaming, sports, rights/catalogs) is becoming an investable, tradable asset class. **IPX Terminal** is the Bloomberg Terminal for Content IP—pairing a keyboard-driven multi-pane workstation with a live $t_0$ signal ingestion and 48–72h prediction/outcome engine that feeds directly back into `IPX-Eval`.

## 1. Clean 4-Project Boundary
- **`IPX Terminal`** *(this repo)*: Desktop-first 4-pane Launchpad workstation (`<TICKER> <FUNCTION> <GO>`), Entity-Resolution IP Graph, live ingestion (GDELT DOC 2.0, YouTube Data API v3, manual social snapshots), time-decayed Cultural Velocity Score (CVS), Cross-Platform Contagion Index, and prediction/outcome logger exporting directly to `IPX-Eval`.
- **`IPX-Eval`** *(`/Users/vieth/Documents/IPX/IPX-Eval`)*: Benchmark datasets (`v0.1`–`v0.3-real`), `eval_case.schema.json` contract, Python eval harness, and DGX Spark / frontier model leaderboard.
- **`IPX Live`** *(separate project)*: Daily weekday broadcast/podcast using IPX Terminal as live studio graphics and logging predictions ("Call Your Shot").
- **`Content Factory`** *(separate repo)*: Creative synthesis (B200 MiniMax H3) and 60-phone distribution fleet.

## 2. The IPX-Eval Flywheel (Zero Future Leakage)
1. **Capture at $t_0$:** IPX Terminal ingests structured cross-platform signals (`summary`, `platforms`, `metrics`, `samples`, `entities_mentioned`) and freezes the exact `signal_snapshot` at `captured_at`.
2. **Log Prediction:** Analyst or model logs a prediction (`breakout`, `lineage`, `contagion`, or `ip_catalyst`) with predicted label, confidence, and rationale.
3. **Resolve at $t_0 + 48\text{h}..72\text{h}$:** After the outcome window elapses, real-world ground truth (`label`, `secondary_label`, `required_concepts`, `rationale`, `outcome_window_hours`) is recorded without mutating the frozen $t_0$ snapshot.
4. **Export to `IPX-Eval`:** Resolved cases export as schema-validated JSONL (`source: "ipx_terminal_export"`) directly into `IPX-Eval/datasets/` so models can be continuously graded on contamination-proof live outcomes.

## 3. Terminal Function Codes & Sector Keys
- **Sectors:** `POP`, `MUSIC`, `FILM_TV`, `GAMING`, `CREATORS`, `SPORTS`, `DEALS`
- **Functions:**
  - `TOP` — Top Cultural Velocity movers & breakout tape
  - `GP` — Velocity & Contagion Graph (time-decayed CVS curve + platform breakdown)
  - `DES` — IP Entity Description (rights holder, aliases, sector, catalysts)
  - `WIRE` — Live $t_0$ signal ingestion tape
  - `LOG` — Prediction & 48–72h Outcome Logger
  - `EXPORT` — Schema-validated `IPX-Eval` JSONL exporter
  - `CN` / `MA` / `COMP` / `ALRT` — Catalysts, M&A/deals, comps, and velocity alerts
