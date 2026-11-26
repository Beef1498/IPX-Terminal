/* IPX Command Center v0.2 — 4-Tab Hub (Eval Tracking, Terminal, Orchestration, Updates & GitHub) */

const hubState = {
  activeView: "terminal",
  auth: { write_protected: false, unlocked: true },
  evals: null,
  evalMetric: "score", // "score" | "loss"
  evalModelFilter: "ALL",
  evalDatasetFilter: "ALL",
  orchestration: null,
  selectedHardwareId: null,
  updates: null,
  updatesRepoFilter: "ALL",
};

function fmtTime(iso) {
  if (!iso) return "--";
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return String(iso).slice(0, 16);
    return d.toISOString().replace("T", " ").slice(0, 16) + " UTC";
  } catch {
    return String(iso).slice(0, 16);
  }
}

/* ---------------- Auth / Passcode Lock ---------------- */
async function refreshAuthStatus() {
  try {
    const res = await api("/api/auth/status");
    hubState.auth = {
      write_protected: Boolean(res.write_protected),
      unlocked: Boolean(res.unlocked),
    };
    renderAuthButton();
  } catch {
    // Non-fatal on startup
  }
}

function renderAuthButton() {
  const btn = document.getElementById("btn-auth-lock");
  if (!btn) return;
  btn.classList.remove("locked", "unlocked");
  if (!hubState.auth.write_protected) {
    btn.textContent = "OPEN ACCESS";
    btn.title = "No IPX_WRITE_TOKEN set on server (open local/dev mode).";
  } else if (hubState.auth.unlocked) {
    btn.textContent = "UNLOCKED · ADMIN";
    btn.classList.add("unlocked");
    btn.title = "Write passcode verified in this browser session. Click to lock.";
  } else {
    btn.textContent = "READ-ONLY · UNLOCK";
    btn.classList.add("locked");
    btn.title = "Viewing in public read-only mode. Click to enter write passcode.";
  }
}

function openUnlockModal(reason = "") {
  if (!hubState.auth.write_protected) {
    openModal(
      "ACCESS CONTROL (OPEN DEV MODE)",
      `<p style="color:#8b9bb0;margin-top:0">No <code>IPX_WRITE_TOKEN</code> environment variable is configured on this server, so all read and write actions are currently open.</p>
       <p style="color:#8b9bb0">When deploying publicly (Railway / Render / Fly.io), set <code>IPX_WRITE_TOKEN=your-team-passcode</code> to enable public read-only viewing with passcode-gated writes.</p>`
    );
    return;
  }

  if (hubState.auth.unlocked) {
    openModal(
      "ADMIN WRITE ACCESS UNLOCKED",
      `<p style="color:#34d399;margin-top:0">Your browser session is currently unlocked for Terminal writes and Eval pushes.</p>
       <div class="form-actions">
         <button type="button" class="btn-action" id="btn-relock-session">Lock Session (Return to Read-Only)</button>
       </div>`
    );
    document.getElementById("btn-relock-session").addEventListener("click", async () => {
      sessionStorage.removeItem("ipx_write_token");
      await refreshAuthStatus();
      closeModal();
      setStatus("Session locked (read-only mode).");
    });
    return;
  }

  openModal(
    "UNLOCK WRITE ACCESS",
    `
    ${reason ? `<p style="color:#fb7185;margin-top:0">${esc(reason)}</p>` : ""}
    <p style="color:#8b9bb0;margin-top:0">Viewing all 4 tabs is open to anyone with the link. Enter the team write passcode (<code>IPX_WRITE_TOKEN</code>) to enable Terminal ingestion, logging, resolution, and Eval pushes.</p>
    <form id="form-unlock-passcode">
      <div class="form-row">
        <label>WRITE PASSCODE</label>
        <input type="password" name="token" placeholder="Enter IPX_WRITE_TOKEN..." required autofocus />
      </div>
      <div class="form-actions">
        <button type="submit" class="btn-action amber">Unlock Writes</button>
      </div>
    </form>
    `
  );
  document.getElementById("form-unlock-passcode").addEventListener("submit", async (e) => {
    e.preventDefault();
    const token = new FormData(e.target).get("token").toString().trim();
    try {
      const res = await fetch("/api/auth/verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
      });
      const data = await res.json();
      if (!res.ok || !data.unlocked) {
        setStatus(data.error || "Invalid passcode.", true);
        return;
      }
      sessionStorage.setItem("ipx_write_token", token);
      await refreshAuthStatus();
      closeModal();
      setStatus("Admin write access unlocked for this session.");
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}
window.openUnlockModal = openUnlockModal;

/* ---------------- Top-Level 4-Tab Switching ---------------- */
async function switchHubView(view, updateHash = true) {
  const valid = ["evals", "terminal", "orchestration", "updates"];
  const target = valid.includes(view) ? view : "terminal";
  hubState.activeView = target;

  document.querySelectorAll(".hub-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.view === target);
  });
  valid.forEach((v) => {
    const el = document.getElementById(`view-${v}`);
    if (el) el.classList.toggle("hidden", v !== target);
  });
  if (updateHash && window.location.hash !== `#${target}`) {
    history.replaceState(null, "", `#${target}`);
  }

  if (target === "evals") {
    await loadEvals();
  } else if (target === "orchestration") {
    await loadOrchestration();
  } else if (target === "updates") {
    await loadUpdates(false);
  }
}

/* ---------------- TAB 1: EVAL TRACKING ---------------- */
async function loadEvals() {
  const el = document.getElementById("view-evals");
  if (!hubState.evals) {
    el.innerHTML = `<div class="hub-page"><p style="color:#8b9bb0">Loading IPX-Eval tracking dashboard...</p></div>`;
  }
  try {
    const qs = new URLSearchParams({
      model: hubState.evalModelFilter,
      dataset: hubState.evalDatasetFilter,
      limit: "100",
    });
    hubState.evals = await api(`/api/evals?${qs.toString()}`);
    renderEvalsView();
  } catch (err) {
    el.innerHTML = `<div class="hub-page"><p style="color:#fb7185">Failed to load evals: ${esc(err.message)}</p></div>`;
  }
}

function buildEvalSvgChart(series, metricMode) {
  const pts = (series || []).filter((r) =>
    metricMode === "loss"
      ? r.eval_loss != null || r.train_loss != null
      : r.overall_score != null || r.accuracy_pct != null
  );
  if (!pts.length) {
    return `<div style="padding:26px;text-align:center;color:#8b9bb0;font-family:var(--mono);font-size:11.5px">
      No ${metricMode === "loss" ? "loss" : "score"} points recorded yet. Push a training/eval run from DGX Spark or click <b>+ Log / Push Run</b>.
    </div>`;
  }

  const W = 760;
  const H = 210;
  const padL = 44;
  const padR = 20;
  const padT = 18;
  const padB = 30;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const vals = pts.map((r) =>
    metricMode === "loss"
      ? Number(r.eval_loss ?? r.train_loss ?? 0)
      : Number(r.overall_score ?? r.accuracy_pct ?? 0)
  );
  const maxY = metricMode === "loss" ? Math.max(1.0, ...vals) * 1.1 : 100;
  const minY = 0;

  const xAt = (i) => padL + (pts.length === 1 ? plotW / 2 : (i / (pts.length - 1)) * plotW);
  const yAt = (v) => padT + plotH - ((v - minY) / Math.max(0.001, maxY - minY)) * plotH;

  const linePath = pts.map((r, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(1)},${yAt(vals[i]).toFixed(1)}`).join(" ");
  const gridTicks = metricMode === "loss" ? [0, maxY * 0.5, maxY] : [0, 25, 50, 75, 100];
  const color = metricMode === "loss" ? "#fb7185" : "#22d3ee";

  return `
    <svg viewBox="0 0 ${W} ${H}" style="width:100%;height:210px;display:block;background:#090d14;border:1px solid #1d2735;border-radius:4px">
      ${gridTicks
        .map((t) => {
          const y = yAt(t).toFixed(1);
          const lbl = metricMode === "loss" ? t.toFixed(2) : `${Math.round(t)}%`;
          return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#1b2533" stroke-dasharray="3 3"/>
                  <text x="${padL - 6}" y="${Number(y) + 3}" text-anchor="end" fill="#6f8096" font-size="10" font-family="monospace">${lbl}</text>`;
        })
        .join("")}
      <path d="${linePath}" fill="none" stroke="${color}" stroke-width="2.2" />
      ${pts
        .map((r, i) => {
          const cx = xAt(i).toFixed(1);
          const cy = yAt(vals[i]).toFixed(1);
          const label = `${r.model_name} (${r.dataset_version}): ${vals[i]}`;
          return `<circle cx="${cx}" cy="${cy}" r="4.2" fill="${color}" stroke="#080b10" stroke-width="1.5"><title>${esc(label)}</title></circle>`;
        })
        .join("")}
      <text x="${padL}" y="${H - 8}" fill="#6f8096" font-size="10" font-family="monospace">${esc(pts[0].run_id)}</text>
      <text x="${W - padR}" y="${H - 8}" text-anchor="end" fill="#6f8096" font-size="10" font-family="monospace">${esc(pts[pts.length - 1].run_id)}</text>
    </svg>
  `;
}

function renderEvalsView() {
  const el = document.getElementById("view-evals");
  const data = hubState.evals || {};
  const summary = data.summary || {};
  const runs = data.runs || [];
  const leaderboard = summary.leaderboard || [];
  const origin = window.location.origin;

  const webhookSnippet = `import json, urllib.request

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
    "category_scores": {"breakout": 85.0, "lineage": 78.0, "contagion": 80.5, "ip_catalyst": 82.0},
}
req = urllib.request.Request(
    "${origin}/api/evals/runs",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json", "X-IPX-Token": "<IPX_WRITE_TOKEN>"},
)
urllib.request.urlopen(req).read()`;

  el.innerHTML = `
    <div class="hub-page">
      <div class="hub-header-row">
        <div>
          <h2 class="hub-page-title">IPX-EVAL LIVE TRAINING &amp; BENCHMARK TRACKER</h2>
          <p class="hub-page-sub">Tracks DGX Spark training runs, frontier model benchmarks, and contamination-proof 48–72h Terminal exports from <a href="${esc(data.eval_repo_url || "https://github.com/Beef1498/IPX-eval")}" target="_blank" rel="noopener" style="color:var(--cyan)">${esc(data.eval_repo || "Beef1498/IPX-eval")} ↗</a>.</p>
        </div>
        <div class="hub-actions">
          <button type="button" class="btn-action green" id="btn-log-eval-run">+ Log / Push Run</button>
          <button type="button" class="btn-action cyan" id="btn-sync-eval-gh">Sync IPX-eval GitHub</button>
          <button type="button" class="btn-action" id="btn-refresh-evals">Refresh</button>
        </div>
      </div>

      <div class="hub-kpi-grid">
        <div class="hub-kpi-card">
          <div class="label">TOTAL EVAL RUNS</div>
          <div class="val">${summary.total_runs ?? 0}</div>
          <div class="sub">${summary.active_runs ?? 0} currently running</div>
        </div>
        <div class="hub-kpi-card">
          <div class="label">BEST OVERALL SCORE</div>
          <div class="val" style="color:var(--green)">${summary.best_score != null ? `${Number(summary.best_score).toFixed(1)}%` : "--"}</div>
          <div class="sub">${esc(summary.best_model || "No runs yet")}</div>
        </div>
        <div class="hub-kpi-card">
          <div class="label">TRACKED MODELS</div>
          <div class="val" style="color:var(--cyan)">${summary.models_count ?? 0}</div>
          <div class="sub">DGX Spark + Frontier</div>
        </div>
        <div class="hub-kpi-card">
          <div class="label">LATEST DATASET</div>
          <div class="val" style="color:var(--amber)">${esc(summary.latest_dataset || "--")}</div>
          <div class="sub">${(summary.datasets || []).length} dataset version(s)</div>
        </div>
        <div class="hub-kpi-card">
          <div class="label">TERMINAL RESOLVED</div>
          <div class="val" style="color:var(--violet)">${state.stats?.resolved_predictions ?? 0}</div>
          <div class="sub">${state.stats?.pending_predictions ?? 0} pending 48–72h</div>
        </div>
      </div>

      <div class="hub-grid-2">
        <div class="hub-card">
          <div class="hub-card-header">
            <span>TRAINING &amp; EVAL PROGRESSION</span>
            <div class="hub-actions">
              <button type="button" class="btn-action ${hubState.evalMetric === "score" ? "cyan" : ""}" id="btn-metric-score">Score %</button>
              <button type="button" class="btn-action ${hubState.evalMetric === "loss" ? "amber" : ""}" id="btn-metric-loss">Loss</button>
            </div>
          </div>
          <div class="hub-card-body">
            ${buildEvalSvgChart(summary.series || [], hubState.evalMetric)}
          </div>
        </div>

        <div class="hub-card">
          <div class="hub-card-header">
            <span>PUSH LIVE RUNS FROM DGX SPARK (WEBHOOK)</span>
            <span class="pill cyan">POST /api/evals/runs</span>
          </div>
          <div class="hub-card-body">
            <pre class="code-snippet">${esc(webhookSnippet)}</pre>
          </div>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>MODEL LEADERBOARD (BEST SCORE PER MODEL)</span>
          <span class="pill green">${leaderboard.length} MODEL(S)</span>
        </div>
        <div class="hub-card-body" style="padding:0;overflow-x:auto">
          <table class="hub-table">
            <thead>
              <tr>
                <th>#</th>
                <th>MODEL</th>
                <th>HARDWARE</th>
                <th>DATASET</th>
                <th class="num">OVERALL</th>
                <th class="num">ACCURACY</th>
                <th class="num">CONCEPT RECALL</th>
                <th class="num">BREAKOUT</th>
                <th class="num">LINEAGE</th>
                <th class="num">CONTAGION</th>
                <th class="num">CATALYST</th>
                <th>STATUS</th>
              </tr>
            </thead>
            <tbody>
              ${
                leaderboard.length
                  ? leaderboard
                      .map((r, i) => {
                        const cs = r.category_scores || {};
                        const fmt = (v) => (v != null ? `${Number(v).toFixed(1)}%` : "--");
                        return `<tr>
                          <td>${i + 1}</td>
                          <td><b>${esc(r.model_name)}</b><div style="color:#6f8096;font-size:10px">${esc(r.run_id)}</div></td>
                          <td>${esc(r.hardware)}</td>
                          <td><span class="pill amber">${esc(r.dataset_version)}</span></td>
                          <td class="num" style="color:var(--green);font-weight:700">${fmt(r.overall_score)}</td>
                          <td class="num">${fmt(r.accuracy_pct)}</td>
                          <td class="num">${fmt(r.concept_recall_pct)}</td>
                          <td class="num">${fmt(cs.breakout)}</td>
                          <td class="num">${fmt(cs.lineage)}</td>
                          <td class="num">${fmt(cs.contagion)}</td>
                          <td class="num">${fmt(cs.ip_catalyst)}</td>
                          <td><span class="pill ${r.status === "running" ? "amber" : r.status === "failed" ? "coral" : "green"}">${esc(r.status)}</span></td>
                        </tr>`;
                      })
                      .join("")
                  : `<tr><td colspan="12" style="text-align:center;color:#8b9bb0;padding:18px">No eval runs logged yet. Click <b>Sync IPX-eval GitHub</b> or <b>+ Log / Push Run</b> to populate the leaderboard.</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>ALL TRAINING &amp; EVAL RUNS (${runs.length})</span>
          <div class="hub-actions">
            <select id="filter-eval-model" class="hub-filter-select">
              <option value="ALL">Model: ALL</option>
              ${(summary.models || []).map((m) => `<option value="${esc(m)}" ${hubState.evalModelFilter === m ? "selected" : ""}>${esc(m)}</option>`).join("")}
            </select>
            <select id="filter-eval-dataset" class="hub-filter-select">
              <option value="ALL">Dataset: ALL</option>
              ${(summary.datasets || []).map((d) => `<option value="${esc(d)}" ${hubState.evalDatasetFilter === d ? "selected" : ""}>${esc(d)}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="hub-card-body" style="padding:0;overflow-x:auto">
          <table class="hub-table">
            <thead>
              <tr>
                <th>RUN ID</th>
                <th>MODEL</th>
                <th>DATASET</th>
                <th>STEP / EPOCH</th>
                <th class="num">SCORE</th>
                <th class="num">TRAIN LOSS</th>
                <th class="num">EVAL LOSS</th>
                <th>SOURCE</th>
                <th>TIMESTAMP</th>
              </tr>
            </thead>
            <tbody>
              ${
                runs.length
                  ? runs
                      .map((r) => `<tr>
                        <td><code>${esc(r.run_id)}</code></td>
                        <td>${esc(r.model_name)}</td>
                        <td>${esc(r.dataset_version)}</td>
                        <td>${r.step != null ? `step ${r.step}` : "--"}${r.epoch != null ? ` · ep ${r.epoch}` : ""}</td>
                        <td class="num" style="color:var(--cyan)">${r.overall_score != null ? `${Number(r.overall_score).toFixed(1)}%` : "--"}</td>
                        <td class="num">${r.train_loss != null ? Number(r.train_loss).toFixed(3) : "--"}</td>
                        <td class="num">${r.eval_loss != null ? Number(r.eval_loss).toFixed(3) : "--"}</td>
                        <td><span class="pill">${esc(r.source)}</span></td>
                        <td style="color:var(--muted)">${esc(fmtTime(r.created_at))}</td>
                      </tr>`)
                      .join("")
                  : `<tr><td colspan="9" style="text-align:center;color:#8b9bb0;padding:16px">No runs match the current filter.</td></tr>`
              }
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-log-eval-run").addEventListener("click", openLogEvalRunModal);
  document.getElementById("btn-refresh-evals").addEventListener("click", loadEvals);
  document.getElementById("btn-metric-score").addEventListener("click", () => {
    hubState.evalMetric = "score";
    renderEvalsView();
  });
  document.getElementById("btn-metric-loss").addEventListener("click", () => {
    hubState.evalMetric = "loss";
    renderEvalsView();
  });
  document.getElementById("btn-sync-eval-gh").addEventListener("click", async () => {
    setStatus("Syncing eval run artifacts from GitHub IPX-eval...");
    try {
      const res = await api("/api/evals/sync", { method: "POST", body: JSON.stringify({}) });
      setStatus(`IPX-eval sync complete: ${res.synced_count} run(s) synced (${res.files_checked.length} file(s) checked).`);
      await loadEvals();
    } catch (err) {
      setStatus(`Eval sync failed: ${err.message}`, true);
    }
  });
  document.getElementById("filter-eval-model").addEventListener("change", (e) => {
    hubState.evalModelFilter = e.target.value;
    loadEvals();
  });
  document.getElementById("filter-eval-dataset").addEventListener("change", (e) => {
    hubState.evalDatasetFilter = e.target.value;
    loadEvals();
  });
}

function openLogEvalRunModal() {
  openModal(
    "LOG / PUSH TRAINING OR EVAL RUN",
    `
    <form id="form-eval-run" class="form-grid">
      <div class="form-row">
        <label>RUN ID</label>
        <input name="run_id" placeholder="dgx-spark-qwen3-v0.4-001" required />
      </div>
      <div class="form-row">
        <label>MODEL NAME</label>
        <input name="model_name" placeholder="ipx-qwen3-32b-sft" required />
      </div>
      <div class="form-row">
        <label>DATASET VERSION</label>
        <input name="dataset_version" value="v0.4" />
      </div>
      <div class="form-row">
        <label>HARDWARE</label>
        <input name="hardware" value="DGX Spark" />
      </div>
      <div class="form-row">
        <label>OVERALL SCORE (%)</label>
        <input type="number" step="0.1" name="overall_score" placeholder="81.4" />
      </div>
      <div class="form-row">
        <label>ACCURACY (%)</label>
        <input type="number" step="0.1" name="accuracy_pct" placeholder="82.0" />
      </div>
      <div class="form-row">
        <label>TRAIN LOSS</label>
        <input type="number" step="0.001" name="train_loss" placeholder="0.412" />
      </div>
      <div class="form-row">
        <label>EVAL LOSS</label>
        <input type="number" step="0.001" name="eval_loss" placeholder="0.468" />
      </div>
      <div class="form-row">
        <label>STEP</label>
        <input type="number" name="step" placeholder="500" />
      </div>
      <div class="form-row">
        <label>STATUS</label>
        <select name="status">
          <option value="completed">completed</option>
          <option value="running">running</option>
          <option value="queued">queued</option>
          <option value="failed">failed</option>
        </select>
      </div>
      <div class="form-row full">
        <label>CATEGORY SCORES JSON (OPTIONAL)</label>
        <input name="category_scores" placeholder='{"breakout": 85.0, "lineage": 78.0, "contagion": 80.5, "ip_catalyst": 82.0}' />
      </div>
      <div class="form-row full">
        <label>NOTES</label>
        <textarea name="notes" placeholder="LoRA r=16 on v0.4 resolved Terminal outcomes + blind creator A/B pairs..."></textarea>
      </div>
      <div class="form-actions full">
        <button type="submit" class="btn-action green">Save Eval Run</button>
      </div>
    </form>
    `
  );
  document.getElementById("form-eval-run").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    const payload = Object.fromEntries(fd.entries());
    payload.source = "manual_ui";
    try {
      await api("/api/evals/runs", { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      setStatus(`Saved eval run ${payload.run_id}.`);
      await loadEvals();
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

/* ---------------- TAB 3: ORCHESTRATION (SOFTWARE + HARDWARE) ---------------- */
async function loadOrchestration() {
  const el = document.getElementById("view-orchestration");
  if (!hubState.orchestration) {
    el.innerHTML = `<div class="hub-page"><p style="color:#8b9bb0">Loading system orchestration map...</p></div>`;
  }
  try {
    hubState.orchestration = await api("/api/orchestration");
    renderOrchestrationView();
  } catch (err) {
    el.innerHTML = `<div class="hub-page"><p style="color:#fb7185">Failed to load orchestration map: ${esc(err.message)}</p></div>`;
  }
}

function renderOrchestrationView() {
  const el = document.getElementById("view-orchestration");
  const data = hubState.orchestration || {};
  const hw = data.hardware || [];
  const sw = data.software || [];
  const flows = data.flows || [];
  const rt = data.runtime || {};
  const ints = rt.integrations || {};

  const badge = (ok, label) =>
    `<span class="pill ${ok ? "green" : "amber"}">${ok ? "●" : "○"} ${esc(label)}</span>`;

  el.innerHTML = `
    <div class="hub-page">
      <div class="hub-header-row">
        <div>
          <h2 class="hub-page-title">${esc(data.title || "IPX SYSTEM ORCHESTRATION")}</h2>
          <p class="hub-page-sub">${esc(data.subtitle || "Software & hardware topology across the IPX flywheel.")}</p>
        </div>
        <div class="hub-actions">
          <button type="button" class="btn-action" id="btn-refresh-orch">Refresh Telemetry</button>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>LIVE RUNTIME TELEMETRY &amp; INTEGRATIONS</span>
          <span class="pill cyan">v${esc(rt.app_version || "0.2.0")} · SQLite ${rt.db_size_kb ?? 0} KB</span>
        </div>
        <div class="hub-card-body" style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap">
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            ${badge(ints.write_passcode, ints.write_passcode ? "Write Passcode Active" : "Open Write Mode")}
            ${badge(ints.scrapecreators, "ScrapeCreators")}
            ${badge(ints.github_token, "GitHub Token")}
            ${badge(ints.ai_scorer, "AI Scorer")}
            ${badge(ints.youtube_api, "YouTube API")}
          </div>
          <div style="font-family:var(--mono);font-size:11px;color:var(--muted)">
            Entities: <b style="color:var(--text)">${rt.stats?.entities ?? 0}</b> ·
            Signals: <b style="color:var(--text)">${rt.stats?.signals ?? 0}</b> ·
            Eval Runs: <b style="color:var(--text)">${rt.eval_runs_total ?? 0}</b>
          </div>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>HARDWARE INFRASTRUCTURE LAYER (CLICK A NODE TO HIGHLIGHT HOSTED SOFTWARE)</span>
          <span class="pill amber">${hw.length} HARDWARE NODES</span>
        </div>
        <div class="hub-card-body">
          <div class="hub-grid-4">
            ${hw
              .map((h) => {
                const sel = hubState.selectedHardwareId === h.id;
                return `<div class="node-card ${sel ? "selected" : ""}" data-hw-id="${esc(h.id)}">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
                    <span class="node-title">${esc(h.name)}</span>
                    <span class="pill ${h.status === "planned" ? "amber" : "green"}">${esc(h.status || "active")}</span>
                  </div>
                  <div class="node-role">${esc(h.role)}</div>
                  <div class="node-specs">${esc(h.specs)}</div>
                  <p style="font-size:11.5px;color:#b8c4d4;margin:8px 0 0;line-height:1.45">${esc(h.description)}</p>
                </div>`;
              })
              .join("")}
          </div>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>SOFTWARE SERVICES &amp; FLYWHEEL MODULES</span>
          <span class="pill violet">${sw.length} SERVICES</span>
        </div>
        <div class="hub-card-body">
          <div class="hub-grid-3">
            ${sw
              .map((s) => {
                const highlighted = hubState.selectedHardwareId && s.hardware_id === hubState.selectedHardwareId;
                const hostHw = hw.find((h) => h.id === s.hardware_id);
                return `<div class="node-card ${highlighted ? "selected" : ""}" style="cursor:default">
                  <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
                    <span class="node-title">${esc(s.name)}</span>
                    ${
                      s.repo
                        ? `<a href="${esc(s.repo)}" target="_blank" rel="noopener" class="commit-sha">GitHub ↗</a>`
                        : `<span class="pill">Internal</span>`
                    }
                  </div>
                  <div class="node-role">Runs on: ${esc(hostHw ? hostHw.name : s.hardware_id)}</div>
                  <div class="node-specs">${esc(s.stack)} · ${esc(s.cadence)}</div>
                  <ul class="node-list">
                    ${(s.responsibilities || []).map((r) => `<li>${esc(r)}</li>`).join("")}
                  </ul>
                </div>`;
              })
              .join("")}
          </div>
        </div>
      </div>

      <div class="hub-card">
        <div class="hub-card-header">
          <span>DATA FLOWS, CONTRACTS &amp; ZERO-LEAKAGE GUARDRAILS</span>
          <span class="pill cyan">${flows.length} PIPELINES</span>
        </div>
        <div class="hub-card-body" style="padding:0;overflow-x:auto">
          <table class="hub-table">
            <thead>
              <tr>
                <th>SOURCE</th>
                <th>DESTINATION</th>
                <th>PAYLOAD / SCHEMA</th>
                <th>CADENCE</th>
                <th>GUARDRAIL</th>
              </tr>
            </thead>
            <tbody>
              ${flows
                .map(
                  (f) => `<tr>
                    <td><b>${esc(f.from)}</b></td>
                    <td style="color:var(--cyan)"><b>→ ${esc(f.to)}</b></td>
                    <td>${esc(f.payload)}</td>
                    <td style="color:var(--muted)">${esc(f.cadence)}</td>
                    <td style="color:var(--green)">${esc(f.guardrail)}</td>
                  </tr>`
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-refresh-orch").addEventListener("click", loadOrchestration);
  el.querySelectorAll("[data-hw-id]").forEach((card) => {
    card.addEventListener("click", () => {
      const id = card.dataset.hwId;
      hubState.selectedHardwareId = hubState.selectedHardwareId === id ? null : id;
      renderOrchestrationView();
    });
  });
}

/* ---------------- TAB 4: UPDATES & LIVE GITHUB ---------------- */
async function loadUpdates(forceRefresh = false) {
  const el = document.getElementById("view-updates");
  if (!hubState.updates || forceRefresh) {
    el.innerHTML = `<div class="hub-page"><p style="color:#8b9bb0">Fetching live GitHub repository updates...</p></div>`;
  }
  try {
    hubState.updates = await api(`/api/updates${forceRefresh ? "?refresh=1" : ""}`);
    renderUpdatesView();
  } catch (err) {
    el.innerHTML = `<div class="hub-page"><p style="color:#fb7185">Failed to fetch GitHub updates: ${esc(err.message)}</p></div>`;
  }
}

function renderUpdatesView() {
  const el = document.getElementById("view-updates");
  const data = hubState.updates || {};
  const repos = data.repos || [];
  const releases = data.releases || [];
  const allCommits = data.commits || [];
  const commits =
    hubState.updatesRepoFilter === "ALL"
      ? allCommits
      : allCommits.filter((c) => c.repo === hubState.updatesRepoFilter);
  const errors = data.errors || [];

  el.innerHTML = `
    <div class="hub-page">
      <div class="hub-header-row">
        <div>
          <h2 class="hub-page-title">UPDATES, VERSIONS &amp; LIVE GITHUB REPOSITORIES</h2>
          <p class="hub-page-sub">Live repository links, version releases, and commit stream across the IPX ecosystem. Last synced: ${esc(fmtTime(data.fetched_at))}${data.cached ? " (cached)" : ""}.</p>
        </div>
        <div class="hub-actions">
          <button type="button" class="btn-action cyan" id="btn-refresh-updates">Refresh from GitHub</button>
        </div>
      </div>

      ${
        errors.length
          ? `<div class="hub-card" style="border-color:rgba(245,158,11,0.5)">
              <div class="hub-card-body" style="color:var(--amber);font-family:var(--mono);font-size:11px">
                GitHub notices: ${errors.map((e) => esc(e)).join(" · ")}
                ${!data.github_token_configured ? " (Tip: set GITHUB_TOKEN env var for private repos & higher rate limits.)" : ""}
              </div>
            </div>`
          : ""
      }

      <div class="hub-grid-2">
        ${repos
          .map(
            (r) => `<div class="hub-card">
              <div class="hub-card-header">
                <span>${esc(r.slug)}</span>
                <div style="display:flex;gap:6px;align-items:center">
                  ${r.latest_version ? `<span class="pill amber">${esc(r.latest_version)}</span>` : ""}
                  <span class="pill ${r.status === "live" ? "green" : "amber"}">${esc(r.status)}</span>
                </div>
              </div>
              <div class="hub-card-body">
                <p style="margin:0 0 10px;color:#c5d1e0;font-size:12.5px">${esc(r.description || "IPX Content IP Intelligence repository.")}</p>
                <div style="font-family:var(--mono);font-size:11px;color:var(--muted);margin-bottom:12px">
                  Branch: <b style="color:var(--text)">${esc(r.default_branch)}</b> ·
                  Last push: <b style="color:var(--text)">${esc(fmtTime(r.pushed_at))}</b>
                  ${r.stars != null ? ` · ★ ${r.stars}` : ""}
                </div>
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <a class="btn-action cyan" style="text-decoration:none" href="${esc(r.html_url)}" target="_blank" rel="noopener">Open Repo ↗</a>
                  <a class="btn-action" style="text-decoration:none" href="${esc(r.commits_url)}" target="_blank" rel="noopener">Commits ↗</a>
                  <a class="btn-action" style="text-decoration:none" href="${esc(r.releases_url)}" target="_blank" rel="noopener">Releases ↗</a>
                  <a class="btn-action" style="text-decoration:none" href="${esc(r.issues_url)}" target="_blank" rel="noopener">Issues ↗</a>
                </div>
              </div>
            </div>`
          )
          .join("")}
      </div>

      <div class="hub-grid-2">
        <div class="hub-card">
          <div class="hub-card-header">
            <span>RELEASES &amp; VERSION MILESTONES</span>
            <span class="pill green">APP v${esc(data.app_version || "0.2.0")}</span>
          </div>
          <div class="hub-card-body">
            <div class="commit-row">
              <div>
                <div class="commit-msg"><b>v0.2.0 — 4-Tab IPX Command Center</b></div>
                <div class="commit-meta">Added Eval Tracking (DGX Spark webhook + GitHub sync), Software/Hardware Orchestration map, Live GitHub Updates tab, passcode-gated write mode, and Railway/Render deploy configs.</div>
              </div>
              <span class="pill amber">CURRENT</span>
            </div>
            ${
              releases.length
                ? releases
                    .map(
                      (rel) => `<div class="commit-row">
                        <div>
                          <div class="commit-msg"><b>${esc(rel.name)}</b> <span class="pill">${esc(rel.repo.split("/")[1])}</span></div>
                          <div class="commit-meta">${esc(fmtTime(rel.published_at))}${rel.body ? ` — ${esc(rel.body)}` : ""}</div>
                        </div>
                        <a class="commit-sha" href="${esc(rel.url)}" target="_blank" rel="noopener">${esc(rel.tag || "View")} ↗</a>
                      </div>`
                    )
                    .join("")
                : `<p style="color:#8b9bb0;font-size:12px;margin:10px 0 0">Tag releases on GitHub (e.g. <code>v0.2.0</code>) to have them appear automatically here.</p>`
            }
          </div>
        </div>

        <div class="hub-card">
          <div class="hub-card-header">
            <span>LIVE COMMIT STREAM (${commits.length})</span>
            <div class="hub-actions">
              <select id="filter-updates-repo" class="hub-filter-select">
                <option value="ALL">Repo: ALL</option>
                ${repos.map((r) => `<option value="${esc(r.slug)}" ${hubState.updatesRepoFilter === r.slug ? "selected" : ""}>${esc(r.name)}</option>`).join("")}
              </select>
            </div>
          </div>
          <div class="hub-card-body" style="max-height:420px;overflow-y:auto">
            ${
              commits.length
                ? commits
                    .map(
                      (c) => `<div class="commit-row">
                        <div style="min-width:0">
                          <div class="commit-msg">${esc(c.message)}</div>
                          <div class="commit-meta">
                            <span class="pill" style="margin-right:5px">${esc(c.repo.split("/")[1])}</span>
                            ${esc(c.author)} · ${esc(fmtTime(c.date))}
                          </div>
                        </div>
                        <a class="commit-sha" href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.short_sha)} ↗</a>
                      </div>`
                    )
                    .join("")
                : `<p style="color:#8b9bb0;font-size:12px">No commits loaded yet.</p>`
            }
          </div>
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-refresh-updates").addEventListener("click", () => loadUpdates(true));
  document.getElementById("filter-updates-repo").addEventListener("change", (e) => {
    hubState.updatesRepoFilter = e.target.value;
    renderUpdatesView();
  });
}

/* ---------------- Hub Event Wiring ---------------- */
document.querySelectorAll(".hub-tab").forEach((btn) => {
  btn.addEventListener("click", () => switchHubView(btn.dataset.view, true));
});
document.getElementById("btn-auth-lock")?.addEventListener("click", () => openUnlockModal());

window.addEventListener("hashchange", () => {
  const h = window.location.hash.replace("#", "").toLowerCase();
  if (["evals", "terminal", "orchestration", "updates"].includes(h) && h !== hubState.activeView) {
    switchHubView(h, false);
  }
});

// Initialize auth status & deep-link view from hash
refreshAuthStatus();
const initialHash = window.location.hash.replace("#", "").toLowerCase();
if (["evals", "terminal", "orchestration", "updates"].includes(initialHash)) {
  switchHubView(initialHash, false);
}
