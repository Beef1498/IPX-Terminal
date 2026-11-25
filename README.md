# IPX Terminal

**Bloomberg Terminal for Content IP** — a zero-dependency Python + SQLite WAL workstation that ingests cross-platform $t_0$ signals, computes time-decayed Cultural Velocity Scores (CVS) and Cross-Platform Contagion Indexes, logs predictions with frozen $t_0$ snapshots, and exports verified 48–72h outcomes directly to **`IPX-Eval`** (`eval_case.schema.json`).

---

## Quickstart (Zero External Dependencies, Python 3.9+)

```bash
# 1. Seed realistic Content IP entities, CVS histories, and sample predictions
PYTHONPATH=src python3 -m ipx_terminal seed

# 2. View Top Cultural Velocity Movers in the CLI
PYTHONPATH=src python3 -m ipx_terminal top

# 3. Launch the 4-Pane Bloomberg Launchpad Web UI (http://127.0.0.1:8765)
PYTHONPATH=src python3 -m ipx_terminal serve --seed-if-empty
```

---

## Live Ingestion & 48–72h `IPX-Eval` Flywheel

### 1. Capture a $t_0$ Signal
```bash
# Manual social/platform snapshot
PYTHONPATH=src python3 -m ipx_terminal ingest-manual \
  --ticker "KATT.FMT" \
  --sector CREATORS \
  --title "CapCut template hits 45% share-to-like ratio" \
  --summary "Creator posted 1-tap CapCut cutout template; 78.6K likes, 35.3K shares." \
  --platforms "TikTok,Instagram Reels" \
  --metrics-json '{"likes": 78600, "shares": 35300, "share_to_like_ratio": 0.45}'

# Live GDELT DOC 2.0 news sweep (no API key required)
PYTHONPATH=src python3 -m ipx_terminal ingest-gdelt \
  --ticker "NVDA.IP" --sector POP --query "Jensen Huang NVIDIA"

# Live YouTube Data API v3 sweep (requires YOUTUBE_API_KEY)
YOUTUBE_API_KEY=... PYTHONPATH=src python3 -m ipx_terminal ingest-youtube \
  --ticker "GTA6" --sector GAMING --query "GTA 6 trailer"
```

### 2. Log a Prediction (Freezes $t_0$ Snapshot — Zero Future Leakage)
```bash
PYTHONPATH=src python3 -m ipx_terminal log \
  --signal-id 1 \
  --category breakout \
  --label breakout \
  --confidence 0.85 \
  --window-hours 48
```

### 3. Resolve After 48–72h & Export Directly to `IPX-Eval`
```bash
PYTHONPATH=src python3 -m ipx_terminal resolve \
  --prediction-id 1 \
  --label breakout \
  --secondary-label capcut_template_high_share_ratio \
  --concepts "45%, share-to-like; capcut, template; katt williams" \
  --rationale "Verified at t_0+48h: spawned 210+ creator clones across TikTok and Reels."

# Export schema-validated JSONL straight into IPX-Eval
PYTHONPATH=src python3 -m ipx_terminal export \
  --out-dir "/Users/vieth/Documents/IPX/IPX-Eval/datasets/v0.4-terminal" \
  --version 0.4
```

Then validate and benchmark immediately in **`IPX-Eval`**:
```bash
cd "/Users/vieth/Documents/IPX/IPX-Eval"
PYTHONPATH=src python3 -m ipx_eval validate --dataset-dir datasets/v0.4-terminal
```

---

## Command Bar Shortcuts (`<TICKER> <FUNCTION> <GO>`)
- `KATT.FMT GP` — Load Katt Williams CapCut format velocity & contagion graph
- `NVDA.IP DES` — Load NVIDIA / Jensen Huang Entity-Resolution IP profile
- `MUSIC TOP` / `DEALS TOP` / `ALL` — Filter Launchpad by Sector Key
- `LOG` — Open 48–72h prediction & outcome resolution desk
- `EXPORT` — Open schema-validated `IPX-Eval` JSONL exporter
- Press **`/`** anywhere in the UI to focus the command bar.
