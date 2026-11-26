# Deploying IPX Command Center (4-Tab Live Hub)

IPX Terminal ships as a zero-dependency Python 3.12 container serving all 4 tabs from one URL:
1. **`#evals`** — Eval Tracking (DGX Spark training runs + `Beef1498/IPX-eval` GitHub sync)
2. **`#terminal`** — Live 4-Pane Content IP Terminal (SQLite WAL)
3. **`#orchestration`** — Software & Hardware System Map + Live Telemetry
4. **`#updates`** — Live GitHub Repo Links, Releases & Commit Stream

---

## Option 1: Deploy to Railway (Recommended — 2 Minutes)
1. Push this repo (`Beef1498/IPX-Terminal`) to GitHub.
2. In [Railway](https://railway.app), click **New Project → Deploy from GitHub repo** and select `Beef1498/IPX-Terminal` (it auto-detects `Dockerfile` and `railway.json`).
3. Add a **Persistent Volume** mounted at `/data` so your SQLite database persists across redeploys.
4. Set environment variables in Railway **Variables**:
   - `IPX_DB_PATH=/data/ipx_terminal.db`
   - `IPX_WRITE_TOKEN=<choose-a-team-passcode>` *(enables public read-only viewing + passcode-gated writes)*
   - `GITHUB_TOKEN=<optional-read-only-gh-pat>` *(recommended for private repos & higher GitHub API limits)*
   - `SCRAPECREATORS_API_KEY=<your-key>` *(for live URL ingestion & 48–72h rechecks)*
   - `OPENAI_API_KEY=<optional>` *(for AI scoring & creative briefs)*
5. Generate a public domain in Railway **Settings → Networking**.

---

## Option 2: Deploy to Render (1-Click Blueprint)
1. Push this repo to GitHub.
2. In [Render](https://render.com), click **New → Blueprint** and connect `Beef1498/IPX-Terminal`.
3. `render.yaml` automatically configures the Docker web service, `/data` persistent disk, and `/api/health` check.
4. Fill in `IPX_WRITE_TOKEN`, `GITHUB_TOKEN`, and `SCRAPECREATORS_API_KEY` when prompted.

---

## Pushing Live Training / Eval Runs from DGX Spark
At the end of any training checkpoint or `IPX-Eval` run on DGX Spark, POST JSON to `/api/evals/runs`:

```python
import json, urllib.request

payload = {
    "run_id": "dgx-spark-qwen3-v0.4-step500",
    "model_name": "ipx-qwen3-32b-sft",
    "dataset_version": "v0.4",
    "hardware": "DGX Spark",
    "status": "completed",
    "overall_score": 81.4,
    "accuracy_pct": 82.0,
    "concept_recall_pct": 79.5,
    "train_loss": 0.412,
    "eval_loss": 0.468,
    "step": 500,
    "category_scores": {
        "breakout": 85.0,
        "lineage": 78.0,
        "contagion": 80.5,
        "ip_catalyst": 82.0,
    },
}

req = urllib.request.Request(
    "https://<your-hosted-url>/api/evals/runs",
    data=json.dumps(payload).encode(),
    headers={
        "Content-Type": "application/json",
        "X-IPX-Token": "<IPX_WRITE_TOKEN>",
    },
)
print(urllib.request.urlopen(req).read().decode())
```
