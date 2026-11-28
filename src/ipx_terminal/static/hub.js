/* IPX Command Center v0.2 — 4-Tab Hub (Eval Tracking, Terminal, Orchestration, Updates & GitHub) */

const hubState = {
  activeView: "terminal",
  auth: { write_protected: false, unlocked: true },
  evals: null,
  evalMetric: "score", // "score" | "loss"
  evalModelFilter: "ALL",
  evalDatasetFilter: "ALL",
  quant: null,
  quantSectorFilter: "ALL",
  quantFlagFilter: "ALL",
  quantProjectOnly: false,
  quantMinShare: 0,
  quantMinBreakout: 0,
  quantSortBy: "alpha_score",
  timeline: null,
  timelineScopeFilter: "ALL",
  timelineWindowFilter: "ALL",
  timelineCityFilter: "ALL",
  timelineTreeMode: "year", // "year" | "canopy"
  selectedTreeNodeId: null,
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

/* ---------------- Top-Level 6-Tab Switching ---------------- */
async function switchHubView(view, updateHash = true) {
  const valid = ["evals", "terminal", "quant", "timeline", "orchestration", "updates"];
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
  } else if (target === "quant") {
    await loadQuant();
  } else if (target === "timeline") {
    await loadTimeline();
  } else if (target === "orchestration") {
    await loadOrchestration();
  } else if (target === "updates") {
    await loadUpdates(false);
  }
}

/* ---------------- TAB 3: QUANT DESK ---------------- */
async function loadQuant() {
  const el = document.getElementById("view-quant");
  if (!hubState.quant) {
    el.innerHTML = `<div class="hub-page"><p style="color:#8b9bb0">Loading Quant Desk factor screener &amp; calibration scorecard...</p></div>`;
  }
  try {
    const projId = typeof state !== "undefined" && state.activeProjectId ? state.activeProjectId : "";
    const qs = projId ? `?project_id=${encodeURIComponent(projId)}` : "";
    hubState.quant = await api(`/api/quant${qs}`);
    renderQuantView();
  } catch (err) {
    el.innerHTML = `<div class="hub-page"><p style="color:#fb7185">Failed to load Quant Desk: ${esc(err.message)}</p></div>`;
  }
}

function renderQuantView() {
  const el = document.getElementById("view-quant");
  const q = hubState.quant;
  if (!el || !q) return;

  const s = q.summary || {};
  const activeProj = typeof getActiveProject === "function" ? getActiveProject() : null;
  const projTickers = new Set((activeProj?.roster_entities || []).map((e) => String(e.ticker || "").toUpperCase()));
  const allRows = q.screener || [];
  const filtered = allRows
    .filter((r) => !hubState.quantProjectOnly || !activeProj || projTickers.has(String(r.ticker || "").toUpperCase()) || r.sector === "MUSIC" || r.sector === "POP")
    .filter((r) => hubState.quantSectorFilter === "ALL" || r.sector === hubState.quantSectorFilter)
    .filter((r) => hubState.quantFlagFilter === "ALL" || r.signal_flag === hubState.quantFlagFilter)
    .filter((r) => Number(r.share_to_like_pct || 0) >= Number(hubState.quantMinShare || 0))
    .filter((r) => Number(r.breakout_ratio || 0) >= Number(hubState.quantMinBreakout || 0))
    .sort((a, b) => Number(b[hubState.quantSortBy] || 0) - Number(a[hubState.quantSortBy] || 0));

  const flagPill = (f) => {
    if (f === "STRONG_SIGNAL") return `<span class="pill" style="background:rgba(52,211,153,0.16);color:#34d399;border-color:#34d399">STRONG</span>`;
    if (f === "WATCH") return `<span class="pill" style="background:rgba(245,158,11,0.16);color:#f59e0b;border-color:#f59e0b">WATCH</span>`;
    return `<span class="pill" style="color:#64748b">NOISE</span>`;
  };

  const rowsHtml = filtered.length
    ? filtered
        .map(
          (r) => `
          <tr>
            <td>
              <button type="button" class="btn-action" data-quant-jump="${esc(r.ticker)}" style="padding:2px 6px;font-family:monospace;color:#38bdf8">${esc(r.ticker)}</button>
            </td>
            <td><span class="pill">${esc(r.sector)}</span></td>
            <td>${flagPill(r.signal_flag)}</td>
            <td class="num" style="font-weight:700;color:#fb7185">${r.alpha_score.toFixed(1)}</td>
            <td class="num" style="color:#22d3ee">${r.cvs_score.toFixed(1)}</td>
            <td class="num" style="color:${r.cvs_delta > 0 ? "#34d399" : r.cvs_delta < 0 ? "#fb7185" : "#64748b"}">${r.cvs_delta > 0 ? "+" : ""}${r.cvs_delta.toFixed(1)}</td>
            <td class="num" style="color:${r.share_to_like_pct >= 15 ? "#f59e0b" : "#cbd5e1"}">${r.share_to_like_pct > 0 ? `${r.share_to_like_pct}%` : "--"}</td>
            <td class="num" style="color:${r.breakout_ratio >= 5 ? "#34d399" : "#cbd5e1"}">${r.breakout_ratio > 0 ? `${r.breakout_ratio}x` : "--"}</td>
            <td class="num">${r.remix_breadth > 0 ? r.remix_breadth : "--"}</td>
            <td class="num">${r.market_yes_pct != null ? `<span style="color:#a78bfa">${r.market_yes_pct}%</span>` : "--"}</td>
            <td class="num">
              ${r.signal_id ? `<button type="button" class="btn-action amber" data-quant-log="${r.signal_id}" style="padding:2px 7px;font-size:10px">Log Call</button>` : ""}
            </td>
          </tr>`
        )
        .join("")
    : `<tr><td colspan="11" style="color:#8b9bb0;text-align:center;padding:18px">No tickers match current factor thresholds. Try lowering Min Share/Like or Min Breakout.</td></tr>`;

  const divHtml = (q.divergences || []).length
    ? q.divergences
        .map(
          (d) => `
          <div class="commit-row">
            <div>
              <div class="commit-msg"><b style="color:#38bdf8">${esc(d.ticker)}</b> · ${esc(d.name)}</div>
              <div class="commit-meta">${esc(d.market_source)} YES: <b>${d.market_yes_pct}%</b> vs Social CVS: <b>${d.cvs_score}</b></div>
            </div>
            <span class="pill" style="color:${d.direction === "SOCIAL_AHEAD" ? "#34d399" : d.direction === "MARKET_AHEAD" ? "#f59e0b" : "#94a3b8"}">${esc(d.direction)} (${d.divergence_pts > 0 ? "+" : ""}${d.divergence_pts})</span>
          </div>`
        )
        .join("")
    : `<p style="color:#8b9bb0;font-size:12px;margin:0">No frozen Polymarket/Kalshi signals yet. Open <b>LIVE TERMINAL → MKTS</b> and click <b>Freeze t₀ Signal</b> on any live market to track Social-vs-Odds divergences here.</p>`;

  const secHtml = (q.sector_scorecard || []).length
    ? `<table class="hub-table"><thead><tr><th>SECTOR</th><th class="num">RESOLVED</th><th class="num">CORRECT</th><th class="num">HIT RATE</th></tr></thead><tbody>${q.sector_scorecard
        .map(
          (x) => `<tr><td><span class="pill">${esc(x.sector)}</span></td><td class="num">${x.resolved}</td><td class="num">${x.correct}</td><td class="num" style="color:#34d399;font-weight:700">${x.hit_rate_pct}%</td></tr>`
        )
        .join("")}</tbody></table>`
    : `<p style="color:#8b9bb0;font-size:12px;margin:0">Resolve 48–72h predictions in <b>LOG / 48-72H</b> to populate per-sector Quant hit rates.</p>`;

  el.innerHTML = `
    <div class="hub-page">
      <div class="hub-header-row" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
        <div>
          <h2 style="margin:0;font-size:16px;font-family:monospace;color:#fb7185">QUANT DESK // MULTI-FACTOR CULTURAL ALPHA SCREENER</h2>
          <div style="font-size:11.5px;color:#94a3b8;margin-top:2px">Ranks Content IP by <b>Derivative/Geo Breadth</b>, <b>Share-to-Like %</b>, <b>Breakout Ratio</b>, and <b>CVS Momentum</b>—plus Market-vs-Social divergence &amp; Brier calibration.</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn-action" id="btn-run-quant-morning" style="border-color:#fb7185;color:#fb7185">⚡ Run Gemini Quant (Pro)</button>
          <button type="button" class="btn-action cyan" id="btn-run-quant-intraday">⚡ Intraday Scout (Flash-Lite)</button>
          <a class="btn-action" id="btn-export-brief-html" href="/api/quant/export-brief.html${activeProj ? `?project_id=${encodeURIComponent(activeProj.id)}` : ""}" target="_blank" rel="noopener" style="text-decoration:none;border-color:#a78bfa;color:#c4b5fd">📄 Visual Brief (HTML/PDF)</a>
          <a class="btn-action green" href="/api/quant/export.csv" download="ipx_quant_factors.csv" style="text-decoration:none">⬇ Export CSV</a>
          <button type="button" class="btn-action" id="btn-quant-open-mkts">MKTS</button>
          <button type="button" class="btn-action amber" id="btn-quant-open-map">US MAP</button>
          <button type="button" class="btn-action" id="btn-refresh-quant">Refresh</button>
        </div>
      </div>

      ${(() => {
        if (!activeProj) return "";
        const rosterHtml = (activeProj.roster_entities || [])
          .map(
            (e) =>
              `<button type="button" class="btn-action" data-quant-jump="${esc(e.ticker)}" style="padding:3px 8px;font-family:monospace;color:#22d3ee;border-color:rgba(34,211,238,0.35)">${esc(e.ticker)} · ${esc(e.name)}</button>`
          )
          .join("");
        const tracksHtml = (activeProj.catalog_tracks || [])
          .map((t) => {
            const st = String(t.status || "").toLowerCase() === "priority_push";
            return `<tr>
              <td style="font-weight:700;color:#f8fafc">${esc(t.title)}</td>
              <td style="color:#cbd5e1">${esc(t.artist)}</td>
              <td><span class="pill ${st ? "green" : "amber"}">${st ? "PRIORITY PUSH" : "CATALOG REVIVAL"}</span></td>
              <td style="font-family:monospace;font-size:11px;color:#22d3ee">${esc(t.clip_timestamp || "--")}</td>
              <td style="font-size:11px;color:#94a3b8">${(t.vibe_tags || []).slice(0, 5).map((v) => `<span class="pill" style="margin-right:3px">${esc(v)}</span>`).join("")}</td>
            </tr>`;
          })
          .join("");
        return `<div class="hub-card" style="margin-bottom:14px;border-color:rgba(34,211,238,0.45)">
          <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
            <span>★ CLIENT PROJECT // ${esc((activeProj.name || activeProj.id).toUpperCase())}</span>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
              ${activeProj.production_mode === "faceless_at_scale" ? `<span class="pill green">FACELESS AT SCALE</span>` : ""}
              <span class="pill cyan">${esc((activeProj.languages || []).join(" / "))}</span>
              <span class="pill">${(activeProj.priority_niches || []).length} Priority Niches</span>
              <span class="pill">${(activeProj.target_geos || []).slice(0, 6).join(", ")}</span>
              <button type="button" class="btn-action cyan" id="btn-seed-active-project" style="padding:2px 8px;font-size:10.5px">Seed Roster</button>
            </div>
          </div>
          <div class="hub-card-body">
            <div style="font-size:11.5px;color:#94a3b8;margin-bottom:8px">${esc(activeProj.brand_voice || "")}</div>
            ${rosterHtml ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">${rosterHtml}</div>` : ""}
            ${
              tracksHtml
                ? `<div style="overflow-x:auto"><table class="hub-table"><thead><tr><th>TRACK</th><th>ARTIST</th><th>STATUS</th><th>15S AUDIO CUE</th><th>VIBE / TREND TAGS</th></tr></thead><tbody>${tracksHtml}</tbody></table></div>`
                : ""
            }
          </div>
        </div>`;
      })()}

      ${(() => {
        const m = q.latest_memo;
        if (!m) {
          return `<div class="hub-card" style="margin-bottom:14px;border-color:rgba(251,113,133,0.35)">
            <div class="hub-card-header"><span>GEMINI AI QUANT // DAILY DESK MEMO</span><span class="pill amber">READY TO RUN</span></div>
            <div class="hub-card-body" style="font-size:12px;color:#94a3b8">No Gemini Quant memo logged yet. Click <b>⚡ Run Gemini Quant (Pro)</b> or <b>⚡ Intraday Scout (Flash-Lite)</b> above (or run <code>python3 -m ipx_terminal quant-run</code>) to execute your daily Quant routine automatically.</div>
          </div>`;
        }
        const sigList = (m.top_signals || [])
          .map((x) => `<div style="margin-top:4px;font-size:12px"><b style="color:#e2e8f0;font-family:monospace">${esc(x.ticker || "")}</b> <span class="pill">${esc(x.signal_flag || "WATCH")}</span> — <span style="color:#cbd5e1">${esc(x.thesis || "")}</span></div>`)
          .join("");
        const acts = (m.actions_taken || [])
          .map((a) => `<li style="color:#34d399;font-size:11.5px;margin:2px 0">${esc(a)}</li>`)
          .join("");
        const vActs = (m.vcrm_actions || [])
          .map((a) => `<li style="color:#f59e0b;font-size:11.5px;margin:2px 0">${esc(a)}</li>`)
          .join("");
        const briefsHtml = (m.drafted_briefs || [])
          .map(
            (b) => `<div style="margin-top:4px;font-size:11.5px;padding:6px 8px;background:rgba(34,211,238,0.06);border:1px solid rgba(34,211,238,0.2);border-radius:6px"><b style="color:#22d3ee;font-family:monospace">${esc(b.ticker)}</b> <span class="pill cyan">${esc(b.target_platform)}</span> — <span style="color:#f1f5f9">${esc(b.angle)}</span><div style="color:#94a3b8;margin-top:2px">Hook: "${esc(b.hook_2s)}"</div></div>`
          )
          .join("");
        return `<div class="hub-card" style="margin-bottom:14px;border-color:rgba(251,113,133,0.45)">
          <div class="hub-card-header" style="flex-wrap:wrap;gap:6px">
            <span>GEMINI AI QUANT MEMO // ${esc((m.mode || "morning").toUpperCase())}</span>
            <div style="display:flex;gap:6px;align-items:center">
              <span class="pill cyan">${esc(m.model_used || "gemini")}</span>
              <span class="pill">${esc(fmtTime(m.created_at))}</span>
            </div>
          </div>
          <div class="hub-card-body">
            <div style="font-weight:700;font-size:13.5px;color:#f8fafc;margin-bottom:6px">${esc(m.headline || "")}</div>
            <p style="margin:0 0 10px;font-size:12.5px;color:#cbd5e1;line-height:1.45">${esc(m.executive_summary || "")}</p>
            ${sigList ? `<div style="margin-bottom:10px">${sigList}</div>` : ""}
            ${briefsHtml ? `<div style="margin-bottom:10px"><div style="font-family:monospace;font-size:10.5px;color:#22d3ee;margin-bottom:4px">AUTO-DRAFTED VIDEO BRIEFS (SAVED IN LIVE TERMINAL → BRIEF)</div>${briefsHtml}</div>` : ""}
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px">
              ${acts ? `<div><div style="font-family:monospace;font-size:10.5px;color:#94a3b8;margin-bottom:4px">AUTONOMOUS ACTIONS EXECUTED</div><ul style="margin:0;padding-left:16px">${acts}</ul></div>` : ""}
              ${vActs ? `<div><div style="font-family:monospace;font-size:10.5px;color:#94a3b8;margin-bottom:4px">VCRM GATE ACTION ITEMS</div><ul style="margin:0;padding-left:16px">${vActs}</ul></div>` : ""}
            </div>
          </div>
        </div>`;
      })()}

      ${(() => {
        const tl = q.active_timeline;
        if (!tl || !(tl.seed_now_waves || []).length) return "";
        const season = tl.current_season || {};
        const cities = (tl.priority_spotify_cities_now || [])
          .map((c) => `<span class="pill" style="background:rgba(16,185,129,0.14);color:#34d399;border-color:rgba(16,185,129,0.45)">📍 ${esc(c)}</span>`)
          .join("");
        const cards = (tl.seed_now_waves || [])
          .slice(0, 4)
          .map((w) => {
            const isPeak = w.status === "PEAK_NOW";
            const badgeColor = isPeak ? "#f59e0b" : "#10b981";
            const daysLbl = w.days_until <= 0 ? "ACTIVE NOW" : `T-${w.days_until}d`;
            const tracksLine = (w.matched_tracks || []).length
              ? `<div style="margin-top:4px;font-size:10.5px;color:#22d3ee">🎵 Seed: ${esc(w.matched_tracks.join(" · "))}</div>`
              : "";
            return `<div style="padding:8px 10px;background:rgba(15,23,42,0.75);border:1px solid rgba(16,185,129,0.28);border-radius:6px">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:3px">
                <b style="font-size:12px;color:#f8fafc">${esc(w.name)}</b>
                <span class="pill" style="color:${badgeColor};border-color:${badgeColor};font-size:9.5px">${esc(w.status)} · ${daysLbl}</span>
              </div>
              <div style="font-size:11px;color:#94a3b8;line-height:1.35">${esc(w.spotify_billboard_angle || w.first_mover_cohort || "")}</div>
              ${tracksLine}
            </div>`;
          })
          .join("");
        return `<div class="hub-card" style="margin-bottom:14px;border-color:rgba(16,185,129,0.45)">
          <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
            <span style="color:#34d399">🗓 ACTIVE CULTURAL SEEDING WINDOW // ${esc((season.label || "PRE-WAVE RADAR").toUpperCase())}</span>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
              ${cities}
              <button type="button" class="btn-action green" id="btn-quant-open-timeline" style="padding:2px 8px;font-size:10.5px">Open 12-Mo Timeline →</button>
            </div>
          </div>
          <div class="hub-card-body">
            <div style="font-size:11px;color:#94a3b8;margin-bottom:8px"><b>Weather / Mood:</b> ${esc(season.weather_vibe || "")} — <b>Collective Mood:</b> ${esc(season.collective_mood || "")}</div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px">${cards}</div>
          </div>
        </div>`;
      })()}

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-bottom:14px">
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">STRONG SIGNALS</div><div style="font-size:20px;font-weight:800;color:#34d399">${s.strong_signals ?? 0}</div><div style="font-size:10.5px;color:#64748b">${s.watch_signals ?? 0} on watch · ${s.tracked_tickers ?? 0} tracked</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">QUANT HIT RATE</div><div style="font-size:20px;font-weight:800;color:#22d3ee">${s.human_hit_rate_pct != null ? `${s.human_hit_rate_pct}%` : "--"}</div><div style="font-size:10.5px;color:#64748b">${s.resolved_calls ?? 0} resolved calls</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">EDGE VS AI</div><div style="font-size:20px;font-weight:800;color:${(s.edge_vs_ai_pct ?? 0) >= 0 ? "#34d399" : "#fb7185"}">${s.edge_vs_ai_pct != null ? `${s.edge_vs_ai_pct >= 0 ? "+" : ""}${s.edge_vs_ai_pct}%` : "--"}</div><div style="font-size:10.5px;color:#64748b">AI hit: ${s.ai_hit_rate_pct != null ? `${s.ai_hit_rate_pct}%` : "--"}</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">BRIER CALIBRATION</div><div style="font-size:20px;font-weight:800;color:#f59e0b">${s.brier_calibration_pct != null ? `${s.brier_calibration_pct}%` : "--"}</div><div style="font-size:10.5px;color:#64748b">Confidence accuracy</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">PENDING 48-72H</div><div style="font-size:20px;font-weight:800;color:#a78bfa">${s.pending_calls ?? 0}</div><div style="font-size:10.5px;color:${(s.overdue_calls ?? 0) > 0 ? "#fb7185" : "#64748b"}">${s.overdue_calls ?? 0} overdue for resolution</div></div>
      </div>

      <div class="hub-card" style="margin-bottom:14px">
        <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
          <span>MULTI-FACTOR SCREENER (${filtered.length} / ${allRows.length})</span>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            ${
              activeProj
                ? `<button type="button" class="btn-action ${hubState.quantProjectOnly ? "cyan" : ""}" id="q-proj-only" style="padding:3px 8px;font-size:10.5px">${hubState.quantProjectOnly ? `★ ${esc(activeProj.id)} Focus: ON` : `★ ${esc(activeProj.id)} Focus: OFF`}</button>`
                : ""
            }
            <select id="q-sector" class="hub-filter-select">
              ${["ALL", "POP", "MUSIC", "FILM_TV", "GAMING", "CREATORS", "SPORTS", "DEALS"].map((x) => `<option value="${x}" ${hubState.quantSectorFilter === x ? "selected" : ""}>Sector: ${x}</option>`).join("")}
            </select>
            <select id="q-flag" class="hub-filter-select">
              ${["ALL", "STRONG_SIGNAL", "WATCH", "NOISE"].map((x) => `<option value="${x}" ${hubState.quantFlagFilter === x ? "selected" : ""}>Signal: ${x}</option>`).join("")}
            </select>
            <select id="q-min-share" class="hub-filter-select">
              <option value="0" ${hubState.quantMinShare == 0 ? "selected" : ""}>Min Share/Like: Any</option>
              <option value="10" ${hubState.quantMinShare == 10 ? "selected" : ""}>Share/Like ≥ 10%</option>
              <option value="20" ${hubState.quantMinShare == 20 ? "selected" : ""}>Share/Like ≥ 20%</option>
            </select>
            <select id="q-min-breakout" class="hub-filter-select">
              <option value="0" ${hubState.quantMinBreakout == 0 ? "selected" : ""}>Min Breakout: Any</option>
              <option value="3" ${hubState.quantMinBreakout == 3 ? "selected" : ""}>Breakout ≥ 3x</option>
              <option value="8" ${hubState.quantMinBreakout == 8 ? "selected" : ""}>Breakout ≥ 8x</option>
            </select>
            <select id="q-sort" class="hub-filter-select">
              <option value="alpha_score" ${hubState.quantSortBy === "alpha_score" ? "selected" : ""}>Sort: Alpha Score</option>
              <option value="share_to_like_pct" ${hubState.quantSortBy === "share_to_like_pct" ? "selected" : ""}>Sort: Share/Like %</option>
              <option value="breakout_ratio" ${hubState.quantSortBy === "breakout_ratio" ? "selected" : ""}>Sort: Breakout Ratio</option>
              <option value="remix_breadth" ${hubState.quantSortBy === "remix_breadth" ? "selected" : ""}>Sort: Remix/Geo Breadth</option>
              <option value="cvs_score" ${hubState.quantSortBy === "cvs_score" ? "selected" : ""}>Sort: CVS Score</option>
              <option value="cvs_delta" ${hubState.quantSortBy === "cvs_delta" ? "selected" : ""}>Sort: Δ CVS</option>
            </select>
          </div>
        </div>
        <div class="hub-card-body" style="overflow-x:auto">
          <table class="hub-table">
            <thead>
              <tr>
                <th>TICKER</th><th>SECTOR</th><th>SIGNAL</th>
                <th class="num">ALPHA</th><th class="num">CVS</th><th class="num">Δ CVS</th>
                <th class="num">SHARE/LIKE</th><th class="num">BREAKOUT</th><th class="num">REMIX/GEO</th><th class="num">MKT YES</th><th class="num">ACTION</th>
              </tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:14px;margin-bottom:14px">
        <div class="hub-card">
          <div class="hub-card-header"><span>ODDS VS. SOCIAL DIVERGENCE RADAR</span></div>
          <div class="hub-card-body">${divHtml}</div>
        </div>
        <div class="hub-card">
          <div class="hub-card-header"><span>SECTOR CALIBRATION SCORECARD</span></div>
          <div class="hub-card-body">${secHtml}</div>
        </div>
      </div>

      ${(() => {
        const vcrm = q.vcrm || {};
        const vs = vcrm.summary || {};
        const gates = vcrm.gates || [];
        if (!gates.length) return "";
        const stBadge = (st) =>
          st === "PASS"
            ? `<span class="pill green">PASS</span>`
            : st === "FAIL"
              ? `<span class="pill" style="background:rgba(251,113,133,0.18);color:#fb7185;border-color:rgba(251,113,133,0.45)">FAIL</span>`
              : `<span class="pill amber">PENDING</span>`;
        const kindBadge = (k) =>
          k === "Verification"
            ? `<span class="pill cyan">VERIFICATION</span>`
            : `<span class="pill" style="color:#c4b5fd;border-color:rgba(167,139,250,0.4)">VALIDATION</span>`;
        return `
        <div class="hub-card">
          <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
            <span>LIVE VCRM // 8-GATE REQUIREMENTS &amp; RELEASE MATRIX (${vs.passed ?? 0}/${vs.total ?? 0} PASS)</span>
            <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
              <span class="pill green">${vs.passed ?? 0} PASS</span>
              ${(vs.failed ?? 0) > 0 ? `<span class="pill" style="background:rgba(251,113,133,0.18);color:#fb7185;border-color:rgba(251,113,133,0.45)">${vs.failed} FAIL</span>` : ""}
              ${(vs.pending ?? 0) > 0 ? `<span class="pill amber">${vs.pending} PENDING</span>` : ""}
              <span class="pill" style="color:#94a3b8">${esc(vcrm.spec_file || "data/requirements_vcrm.json")}</span>
            </div>
          </div>
          <div class="hub-card-body" style="overflow-x:auto">
            <table class="hub-table">
              <thead>
                <tr>
                  <th>ID</th><th>TYPE</th><th>REQUIREMENT (SHALL)</th><th>METHOD</th><th>TARGET</th><th>LIVE EVIDENCE</th><th>STATUS</th>
                </tr>
              </thead>
              <tbody>
                ${gates
                  .map(
                    (g) => `<tr>
                      <td style="font-family:monospace;font-weight:700;color:#e2e8f0;white-space:nowrap">${esc(g.id)}</td>
                      <td>${kindBadge(g.kind)}</td>
                      <td><div style="font-weight:600;color:#f1f5f9">${esc(g.title)}</div><div style="font-size:11px;color:#94a3b8">${esc(g.requirement)}</div></td>
                      <td style="font-family:monospace;font-size:11px;color:#cbd5e1">${esc(g.method)}</td>
                      <td style="font-family:monospace;font-size:11px;color:#94a3b8;white-space:nowrap">${esc(g.target)}</td>
                      <td style="font-family:monospace;font-size:11.5px;color:#e2e8f0;white-space:nowrap">${esc(g.observed)}</td>
                      <td>${stBadge(g.status)}</td>
                    </tr>`
                  )
                  .join("")}
              </tbody>
            </table>
          </div>
        </div>`;
      })()}
    </div>
  `;

  document.getElementById("btn-refresh-quant").addEventListener("click", loadQuant);
  const triggerQuantRun = async (mode, btnId) => {
    const btn = document.getElementById(btnId);
    const prev = btn.textContent;
    btn.disabled = true;
    btn.textContent = mode === "morning" ? "Running Pro Quant..." : "Running Flash-Lite...";
    setStatus(`Running Gemini Quant (${mode})...`);
    try {
      const projId = typeof state !== "undefined" ? state.activeProjectId : null;
      const res = await api("/api/quant/run", {
        method: "POST",
        body: JSON.stringify({ mode, project_id: projId && projId !== "NONE" ? projId : null }),
      });
      setStatus(`Gemini Quant (${res.memo.model_used}) complete: ${res.memo.headline}`);
      await loadQuant();
    } catch (err) {
      setStatus(`Gemini Quant failed: ${err.message}`, true);
      btn.disabled = false;
      btn.textContent = prev;
    }
  };
  document.getElementById("btn-run-quant-morning").addEventListener("click", () => triggerQuantRun("morning", "btn-run-quant-morning"));
  document.getElementById("btn-run-quant-intraday").addEventListener("click", () => triggerQuantRun("intraday", "btn-run-quant-intraday"));
  document.getElementById("btn-quant-open-mkts").addEventListener("click", () => {
    switchHubView("terminal", true);
    state.activeTab = "MKTS";
    renderDesk();
  });
  document.getElementById("btn-quant-open-map").addEventListener("click", () => {
    switchHubView("terminal", true);
    state.activeTab = "MAP";
    renderDesk();
  });
  const openTlBtn = document.getElementById("btn-quant-open-timeline");
  if (openTlBtn) {
    openTlBtn.addEventListener("click", () => switchHubView("timeline", true));
  }
  const seedProjBtn = document.getElementById("btn-seed-active-project");
  if (seedProjBtn && activeProj) {
    seedProjBtn.addEventListener("click", async () => {
      try {
        const res = await api(`/api/projects/${encodeURIComponent(activeProj.id)}/seed`, { method: "POST", body: "{}" });
        setStatus(`Seeded ${res.seeded_count} roster entities for ${res.project_name}`);
        await loadBootstrap(true);
        await loadQuant();
      } catch (err) {
        setStatus(`Seed failed: ${err.message}`, true);
      }
    });
  }
  const projOnlyBtn = document.getElementById("q-proj-only");
  if (projOnlyBtn) {
    projOnlyBtn.addEventListener("click", () => {
      hubState.quantProjectOnly = !hubState.quantProjectOnly;
      renderQuantView();
    });
  }
  document.getElementById("q-sector").addEventListener("change", (e) => { hubState.quantSectorFilter = e.target.value; renderQuantView(); });
  document.getElementById("q-flag").addEventListener("change", (e) => { hubState.quantFlagFilter = e.target.value; renderQuantView(); });
  document.getElementById("q-min-share").addEventListener("change", (e) => { hubState.quantMinShare = Number(e.target.value); renderQuantView(); });
  document.getElementById("q-min-breakout").addEventListener("change", (e) => { hubState.quantMinBreakout = Number(e.target.value); renderQuantView(); });
  document.getElementById("q-sort").addEventListener("change", (e) => { hubState.quantSortBy = e.target.value; renderQuantView(); });

  el.querySelectorAll("[data-quant-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchHubView("terminal", true);
      if (typeof selectTicker === "function") selectTicker(btn.dataset.quantJump);
    });
  });
  el.querySelectorAll("[data-quant-log]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sig = (state.signals || []).find((x) => x.id === Number(btn.dataset.quantLog));
      if (sig && typeof openLogPredictionModal === "function") openLogPredictionModal(sig);
    });
  });
}

/* ---------------- TAB 4: CULTURAL TIMELINE & LINEAGE TREE ---------------- */
async function loadTimeline() {
  const el = document.getElementById("view-timeline");
  if (!hubState.timeline) {
    el.innerHTML = `<div class="hub-page"><p style="color:#8b9bb0">Loading Yearly Cultural Timeline &amp; Spotify/Billboard seeding calendar...</p></div>`;
  }
  try {
    const projId = typeof state !== "undefined" && state.activeProjectId ? state.activeProjectId : "";
    const qs = projId ? `?project_id=${encodeURIComponent(projId)}` : "";
    hubState.timeline = await api(`/api/timeline${qs}`);
    renderTimelineView();
  } catch (err) {
    el.innerHTML = `<div class="hub-page"><p style="color:#fb7185">Failed to load Cultural Timeline: ${esc(err.message)}</p></div>`;
  }
}

function renderCulturalTreeSection(tl) {
  const sg = tl.social_graph;
  if (!sg || !(sg.branches || []).length) return "";

  const mode = hubState.timelineTreeMode || "year";
  const todayM = Number(sg.today_month || 1);
  const allBranches = sg.branches || [];
  let visibleBranches = allBranches;
  if (mode === "canopy") {
    const prevM = todayM === 1 ? 12 : todayM - 1;
    const nextM = todayM === 12 ? 1 : todayM + 1;
    const order = [prevM, todayM, nextM];
    visibleBranches = order.map((m) => allBranches.find((b) => b.month === m)).filter(Boolean);
  }

  const W = 820;
  const H = mode === "canopy" ? 440 : 560;
  const trunkX = W / 2;
  const yBottom = H - 36;
  const yTop = 44;
  const count = Math.max(1, visibleBranches.length);
  const stepY = count > 1 ? (yBottom - yTop) / (count - 1) : 0;

  // Map every node to SVG coordinates for interactive clicks & glowing social-graph edges
  const nodeMap = {};
  const nodeCoords = {};
  const branchSvgs = [];
  const leafSvgs = [];
  const budSvgs = [];

  let todayTrunkY = yBottom - ((todayM - 1) / 11) * (yBottom - yTop);

  visibleBranches.forEach((br, idx) => {
    const y = count > 1 ? yBottom - idx * stepY : (yBottom + yTop) / 2;
    if (br.month === todayM) todayTrunkY = y;
    const dir = idx % 2 === 0 ? -1 : 1; // alternate left/right off trunk
    const limbLen = mode === "canopy" ? 290 : 250;
    const endX = trunkX + dir * limbLen;
    const endY = y - (mode === "canopy" ? 30 : 20);
    const ctrlX = trunkX + dir * (limbLen * 0.48);
    const ctrlY = y + 8;

    const strokeW = br.is_current_month ? 4.2 : 2.6;
    const op = br.is_current_month ? 0.95 : 0.65;
    branchSvgs.push(
      `<path d="M ${trunkX} ${y} Q ${ctrlX} ${ctrlY} ${endX} ${endY}" fill="none" stroke="${br.color}" stroke-width="${strokeW}" stroke-linecap="round" opacity="${op}" />`
    );
    // Month label at branch tip
    const lblX = endX + dir * 10;
    const anchor = dir < 0 ? "end" : "start";
    branchSvgs.push(
      `<text x="${lblX}" y="${endY + 4}" text-anchor="${anchor}" fill="${br.is_current_month ? "#f8fafc" : br.color}" font-family="monospace" font-size="${br.is_current_month ? "13" : "11"}" font-weight="800">${esc(br.name.toUpperCase())}${br.is_current_month ? " ●" : ""}</text>`
    );

    // Helper: point along quadratic Bezier at t in [0,1]
    const ptOnBranch = (t) => {
      const omt = 1 - t;
      return {
        x: omt * omt * trunkX + 2 * omt * t * ctrlX + t * t * endX,
        y: omt * omt * y + 2 * omt * t * ctrlY + t * t * endY,
      };
    };

    // Render Day-Leaves (captured live signals) along the upper side of the branch
    const leaves = (br.leaves || []).slice(0, mode === "canopy" ? 16 : 9);
    leaves.forEach((lf, li) => {
      const t = Math.max(0.16, Math.min(0.92, 0.18 + (li / Math.max(1, leaves.length)) * 0.72));
      const p = ptOnBranch(t);
      const offsetY = (li % 2 === 0 ? -1 : 1) * (12 + (li % 3) * 5);
      const lx = p.x;
      const ly = p.y + offsetY;
      nodeCoords[lf.id] = { x: lx, y: ly };
      nodeMap[lf.id] = lf;
      const isSel = hubState.selectedTreeNodeId === lf.id;
      const sz = lf.size || 7;
      const angle = dir < 0 ? -35 + (li % 3) * 18 : 35 - (li % 3) * 18;
      // Botanical teardrop leaf path
      leafSvgs.push(
        `<g class="tree-node-hit" data-tree-node="${esc(lf.id)}" transform="translate(${lx.toFixed(1)},${ly.toFixed(1)}) rotate(${angle})">
          ${lf.is_today || isSel ? `<circle cx="0" cy="0" r="${sz + 5}" fill="${lf.color}" opacity="0.22" />` : ""}
          <path d="M 0 ${-sz} C ${sz * 0.85} ${-sz * 0.35}, ${sz * 0.85} ${sz * 0.55}, 0 ${sz} C ${-sz * 0.85} ${sz * 0.55}, ${-sz * 0.85} ${-sz * 0.35}, 0 ${-sz} Z" fill="${lf.color}" stroke="${isSel ? "#ffffff" : "#070b12"}" stroke-width="${isSel ? "1.8" : "0.9"}" opacity="0.92" />
          <title>${esc(lf.ticker)} (${esc(lf.date)}) · CVS ${lf.cvs_score} — ${esc(lf.title || "")}</title>
        </g>`
      );
    });

    // Render Future Buds / Blossoms (cultural anchors, sports, custom catalysts) along the branch
    const buds = (br.buds || []).slice(0, mode === "canopy" ? 10 : 5);
    buds.forEach((bd, bi) => {
      const t = Math.max(0.22, Math.min(0.94, 0.24 + (bi / Math.max(1, buds.length)) * 0.68));
      const p = ptOnBranch(t);
      const offsetY = (bi % 2 === 0 ? -1 : 1) * (mode === "canopy" ? 26 : 18);
      const bx = p.x;
      const by = p.y + offsetY;
      nodeCoords[bd.id] = { x: bx, y: by };
      nodeMap[bd.id] = bd;
      const isSel = hubState.selectedTreeNodeId === bd.id;
      const isActive = bd.window_status === "PEAK_NOW" || bd.window_status === "SEED_NOW";
      const fill =
        bd.window_status === "PEAK_NOW"
          ? "#f59e0b"
          : bd.window_status === "SEED_NOW"
          ? "#10b981"
          : bd.scope === "sports"
          ? "#38bdf8"
          : bd.scope === "regional"
          ? "#a78bfa"
          : "#64748b";
      const r = isActive ? 7.5 : 5.5;
      const shortName = String(bd.name || "").replace(/^\[[A-Z]+\]\s*/, "").slice(0, mode === "canopy" ? 22 : 16);
      budSvgs.push(
        `<g class="tree-node-hit" data-tree-node="${esc(bd.id)}">
          ${isActive ? `<circle class="tree-pulse-ring" cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="11" fill="none" stroke="${fill}" stroke-width="1.4" />` : ""}
          <circle cx="${bx.toFixed(1)}" cy="${by.toFixed(1)}" r="${r}" fill="${fill}" stroke="${isSel ? "#ffffff" : "#070b12"}" stroke-width="${isSel ? "2.2" : "1.2"}" />
          ${
            isActive || mode === "canopy" || isSel
              ? `<text x="${(bx + dir * 10).toFixed(1)}" y="${(by + 3).toFixed(1)}" text-anchor="${dir < 0 ? "end" : "start"}" fill="${isActive || isSel ? "#f8fafc" : "#94a3b8"}" font-family="monospace" font-size="9.5" font-weight="${isActive ? "700" : "500"}">${esc(shortName)}</text>`
              : ""
          }
          <title>${esc(bd.name)} (${esc(bd.date)} · ${bd.days_until <= 0 ? "ACTIVE" : `T-${bd.days_until}d`})</title>
        </g>`
      );
    });
  });

  // Default selected node: first active SEED_NOW/PEAK_NOW bud or first leaf
  if (!hubState.selectedTreeNodeId || !nodeMap[hubState.selectedTreeNodeId]) {
    const firstActive = Object.values(nodeMap).find(
      (n) => n.node_type === "bud" && (n.window_status === "PEAK_NOW" || n.window_status === "SEED_NOW")
    );
    const firstAny = firstActive || Object.values(nodeMap)[0] || null;
    hubState.selectedTreeNodeId = firstAny ? firstAny.id : null;
  }
  const selNode = hubState.selectedTreeNodeId ? nodeMap[hubState.selectedTreeNodeId] : null;

  // Render Glowing Social Graph Edges (signal_to_anchor arcs)
  const edgeSvgs = [];
  (sg.edges || []).forEach((ed) => {
    if (ed.relation !== "signal_to_anchor") return;
    const a = nodeCoords[ed.source];
    const b = nodeCoords[ed.target];
    if (!a || !b) return;
    const isHit = selNode && (ed.source === selNode.id || ed.target === selNode.id);
    const midX = (a.x + b.x) / 2;
    const midY = Math.min(a.y, b.y) - 28;
    edgeSvgs.push(
      `<path class="tree-edge ${isHit ? "active" : ""}" d="M ${a.x.toFixed(1)} ${a.y.toFixed(1)} Q ${midX.toFixed(1)} ${midY.toFixed(1)} ${b.x.toFixed(1)} ${b.y.toFixed(1)}" />`
    );
  });

  // Build Inspector Card HTML for the selected leaf or bud
  let inspectorHtml = `<div style="color:#94a3b8;font-size:12px">Tap any glowing leaf (captured signal) or bud (upcoming holiday / sports wave) on the tree to inspect its social graph connections.</div>`;
  if (selNode) {
    const relatedEdges = (sg.edges || []).filter((e) => e.source === selNode.id || e.target === selNode.id);
    const cityEdges = relatedEdges.filter((e) => e.relation === "anchor_to_city");
    const trackEdges = relatedEdges.filter((e) => e.relation === "anchor_to_track");
    const sigEdges = relatedEdges.filter((e) => e.relation === "signal_to_anchor");

    if (selNode.node_type === "leaf") {
      inspectorHtml = `
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px">
            <span class="pill green">🍃 DAY LEAF · ${esc(selNode.date)}</span>
            <span class="pill" style="color:${selNode.color};border-color:${selNode.color}">${esc(selNode.sector)} · CVS ${selNode.cvs_score}</span>
          </div>
          <div style="font-size:15px;font-weight:800;color:#f8fafc;font-family:monospace;margin-bottom:4px">${esc(selNode.ticker)}</div>
          <div style="font-size:12px;color:#cbd5e1;line-height:1.4;margin-bottom:8px">${esc(selNode.title || "")}</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:8px">Platforms: <b style="color:#e2e8f0">${esc((selNode.platforms || []).join(", ") || selNode.source_type || "live")}</b></div>
          ${
            sigEdges.length
              ? `<div style="padding:7px 9px;background:rgba(16,185,129,0.08);border:1px solid rgba(16,185,129,0.3);border-radius:7px;margin-bottom:8px">
                  <div style="font-family:monospace;font-size:9.5px;color:#34d399;margin-bottom:4px">↳ GROWING TOWARD UPCOMING WAVES (${sigEdges.length})</div>
                  ${sigEdges
                    .map((e) => {
                      const targetBud = nodeMap[e.target];
                      return `<div style="font-size:11px;color:#f8fafc;margin-bottom:2px">→ <b>${esc(targetBud ? targetBud.name : e.target)}</b> <span style="color:#94a3b8">(${esc(e.label)})</span></div>`;
                    })
                    .join("")}
                </div>`
              : `<div style="font-size:11px;color:#64748b">No direct holiday/sports edge linked yet — organic standalone signal leaf.</div>`
          }
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn-action cyan" data-tl-jump="${esc(selNode.ticker)}">Open ${esc(selNode.ticker)} in Terminal →</button>
        </div>
      `;
    } else {
      const dLbl = selNode.days_until <= 0 ? "ACTIVE NOW" : `T-${selNode.days_until}d`;
      inspectorHtml = `
        <div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap">
            <span class="pill" style="color:#34d399;border-color:#10b981">🌱 ${esc(selNode.window_status)} · ${dLbl}</span>
            <span class="pill">${esc(selNode.date)}</span>
          </div>
          <div style="font-size:14.5px;font-weight:800;color:#f8fafc;margin-bottom:4px">${esc(selNode.name)}</div>
          <div style="font-size:11px;color:#94a3b8;margin-bottom:6px">🎯 First Movers: <b style="color:#e2e8f0">${esc(selNode.first_mover_cohort || "--")}</b></div>
          ${selNode.spotify_billboard_angle ? `<div style="font-size:11.5px;color:#cbd5e1;line-height:1.4;margin-bottom:8px"><b style="color:#34d399">Spotify / Billboard:</b> ${esc(selNode.spotify_billboard_angle)}</div>` : ""}
          ${
            cityEdges.length
              ? `<div style="margin-bottom:8px"><div style="font-family:monospace;font-size:9.5px;color:#94a3b8;margin-bottom:4px">CONNECTED SPOTIFY CITIES</div><div style="display:flex;gap:4px;flex-wrap:wrap">${cityEdges
                  .map((e) => `<button type="button" class="btn-action" data-tl-city="${esc(e.label)}" style="padding:2px 7px;font-size:10px;color:#34d399">📍 ${esc(e.label)}</button>`)
                  .join("")}</div></div>`
              : ""
          }
          ${
            trackEdges.length
              ? `<div style="padding:6px 8px;background:rgba(34,211,238,0.08);border:1px solid rgba(34,211,238,0.28);border-radius:6px;margin-bottom:8px">
                  <div style="font-family:monospace;font-size:9.5px;color:#22d3ee;margin-bottom:3px">🎵 MATCHED CLIENT TRACK EDGES</div>
                  ${trackEdges.map((e) => `<div style="font-size:11px;color:#f8fafc">${esc(e.label)}</div>`).join("")}
                </div>`
              : ""
          }
          ${
            sigEdges.length
              ? `<div style="padding:6px 8px;background:rgba(15,23,42,0.8);border-left:2px solid #38bdf8;border-radius:0 6px 6px 0">
                  <div style="font-family:monospace;font-size:9.5px;color:#38bdf8;margin-bottom:3px">↳ LIVE SIGNAL LEAVES FEEDING THIS WAVE (${sigEdges.length})</div>
                  ${sigEdges
                    .map((e) => {
                      const lf = nodeMap[e.source];
                      return `<div style="font-size:11px;color:#cbd5e1">🍃 <b style="color:#38bdf8">${esc(lf ? lf.ticker : e.source)}</b> — ${esc(e.label)}</div>`;
                    })
                    .join("")}
                </div>`
              : ""
          }
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn-action green" id="btn-tree-branch-here" data-parent-anchor="${esc(selNode.anchor_id || "")}">+ Branch Catalyst Here</button>
        </div>
      `;
    }
  }

  return `
    <div class="hub-card" style="margin-bottom:14px;border-color:rgba(16,185,129,0.45)">
      <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
        <span style="color:#34d399">🌳 LIVING CULTURAL SOCIAL GRAPH TREE // ${sg.year} (${sg.stats.total_leaves} LEAVES · ${sg.stats.total_buds} BUDS · ${sg.stats.total_edges} EDGES)</span>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn-action ${mode === "year" ? "green" : ""}" id="btn-tree-mode-year" style="padding:2px 8px;font-size:10.5px">🌳 Full Year (12 Mo)</button>
          <button type="button" class="btn-action ${mode === "canopy" ? "cyan" : ""}" id="btn-tree-mode-canopy" style="padding:2px 8px;font-size:10.5px">🌿 Active Canopy (90d)</button>
        </div>
      </div>
      <div class="hub-card-body">
        <div class="tree-hero-grid">
          <div class="tree-canvas-wrap">
            <svg class="tree-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Living Cultural Timeline Social Graph Tree">
              <defs>
                <linearGradient id="trunkGrad" x1="0" y1="1" x2="0" y2="0">
                  <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.7" />
                  <stop offset="35%" stop-color="#34d399" stop-opacity="0.85" />
                  <stop offset="65%" stop-color="#f59e0b" stop-opacity="0.85" />
                  <stop offset="100%" stop-color="#a78bfa" stop-opacity="0.9" />
                </linearGradient>
              </defs>

              <!-- Roots at bottom of the Year Trunk -->
              <path d="M ${trunkX} ${yBottom} Q ${trunkX - 45} ${yBottom + 18} ${trunkX - 95} ${yBottom + 24}" fill="none" stroke="#38bdf8" stroke-width="2.5" opacity="0.4" />
              <path d="M ${trunkX} ${yBottom} Q ${trunkX + 45} ${yBottom + 18} ${trunkX + 95} ${yBottom + 24}" fill="none" stroke="#38bdf8" stroke-width="2.5" opacity="0.4" />
              <path d="M ${trunkX} ${yBottom} Q ${trunkX - 18} ${yBottom + 22} ${trunkX - 38} ${yBottom + 28}" fill="none" stroke="#34d399" stroke-width="2" opacity="0.35" />

              <!-- Main Organic Year Trunk -->
              <path d="M ${trunkX} ${yBottom + 6} C ${trunkX - 10} ${(yBottom + yTop) * 0.65}, ${trunkX + 10} ${(yBottom + yTop) * 0.35}, ${trunkX} ${yTop - 10}" fill="none" stroke="url(#trunkGrad)" stroke-width="9" stroke-linecap="round" opacity="0.88" />
              <path d="M ${trunkX} ${yBottom + 6} C ${trunkX - 10} ${(yBottom + yTop) * 0.65}, ${trunkX + 10} ${(yBottom + yTop) * 0.35}, ${trunkX} ${todayTrunkY}" fill="none" stroke="#34d399" stroke-width="3" stroke-linecap="round" opacity="0.95" />

              <!-- Glowing TODAY Growth Ring on Trunk -->
              <circle cx="${trunkX}" cy="${todayTrunkY.toFixed(1)}" r="9" fill="#070b12" stroke="#34d399" stroke-width="2.5" />
              <circle class="tree-pulse-ring" cx="${trunkX}" cy="${todayTrunkY.toFixed(1)}" r="12" fill="none" stroke="#34d399" stroke-width="1.5" />
              <rect x="${trunkX - 46}" y="${(todayTrunkY - 27).toFixed(1)}" width="92" height="16" rx="4" fill="#064e3b" stroke="#34d399" stroke-width="1" />
              <text x="${trunkX}" y="${(todayTrunkY - 16).toFixed(1)}" text-anchor="middle" fill="#ecfdf5" font-family="monospace" font-size="9" font-weight="800">TODAY · ${esc(sg.today.slice(5))}</text>

              <!-- 12 Month Branches -->
              ${branchSvgs.join("")}

              <!-- Social Graph Cross-Branch Vines (Edges) -->
              ${edgeSvgs.join("")}

              <!-- Day Leaves (Live Signals) -->
              ${leafSvgs.join("")}

              <!-- Future Buds (Holidays, Sports, Catalysts) -->
              ${budSvgs.join("")}
            </svg>
            <div class="tree-legend">
              <span><span class="tree-legend-dot" style="background:#34d399"></span>Seed Now Bud</span>
              <span><span class="tree-legend-dot" style="background:#f59e0b"></span>Peak Now Bud</span>
              <span><span class="tree-legend-dot" style="background:#38bdf8"></span>Sports / City Bud</span>
              <span><span class="tree-legend-dot" style="background:#22d3ee"></span>Day Leaf (Live t₀ Signal)</span>
              <span>--- Social Graph Edge</span>
            </div>
          </div>

          <div class="tree-inspector">
            ${inspectorHtml}
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderTimelineView() {
  const el = document.getElementById("view-timeline");
  const tl = hubState.timeline;
  if (!el || !tl) return;

  const s = tl.summary || {};
  const season = tl.current_season || {};
  const activeProj = typeof getActiveProject === "function" ? getActiveProject() : null;
  const allNodes = tl.timeline_nodes || [];
  const allCities = (tl.spotify_billboard_cities || []).map((c) => c.city);

  const filtered = allNodes
    .filter((n) => hubState.timelineScopeFilter === "ALL" || n.scope === hubState.timelineScopeFilter)
    .filter((n) => {
      if (hubState.timelineWindowFilter === "ALL") return true;
      if (hubState.timelineWindowFilter === "ACTIVE") return n.window_status === "PEAK_NOW" || n.window_status === "SEED_NOW";
      return n.window_status === hubState.timelineWindowFilter;
    })
    .filter((n) => hubState.timelineCityFilter === "ALL" || (n.target_cities || []).includes(hubState.timelineCityFilter));

  const statusBadge = (st, days) => {
    const dLbl = days <= 0 ? "ACTIVE NOW" : `T-${days}d`;
    if (st === "PEAK_NOW") return `<span class="pill" style="background:rgba(245,158,11,0.18);color:#f59e0b;border-color:#f59e0b">🔥 PEAK NOW · ${dLbl}</span>`;
    if (st === "SEED_NOW") return `<span class="pill" style="background:rgba(16,185,129,0.18);color:#34d399;border-color:#10b981">🌱 SEED NOW · ${dLbl}</span>`;
    if (st === "PREP_NEXT") return `<span class="pill" style="background:rgba(34,211,238,0.14);color:#22d3ee;border-color:#22d3ee">⏳ PREP NEXT · ${dLbl}</span>`;
    return `<span class="pill" style="color:#94a3b8">${dLbl}</span>`;
  };

  const scopeBadge = (sc) => {
    if (sc === "sports") return `<span class="pill" style="color:#38bdf8;border-color:rgba(56,189,248,0.45)">PRO / COLLEGE SPORTS</span>`;
    if (sc === "regional") return `<span class="pill" style="color:#a78bfa;border-color:rgba(167,139,250,0.45)">REGIONAL / CITY</span>`;
    if (sc === "music_industry") return `<span class="pill" style="color:#34d399;border-color:rgba(16,185,129,0.45)">SPOTIFY / BILLBOARD</span>`;
    if (sc === "custom") return `<span class="pill" style="color:#fb7185;border-color:rgba(251,113,133,0.45)">CUSTOM BRANCH</span>`;
    return `<span class="pill">NATIONAL</span>`;
  };

  const cityPillsHtml = (tl.priority_cities_now || [])
    .map(
      (c) => `<button type="button" class="btn-action ${hubState.timelineCityFilter === c.city ? "green" : ""}" data-tl-city="${esc(c.city)}" style="padding:3px 9px;font-size:11px">📍 ${esc(c.city)} <span style="opacity:0.75">(${c.active_waves})</span></button>`
    )
    .join("");

  const nodesHtml = filtered.length
    ? filtered
        .map((n) => {
          const borderCol =
            n.window_status === "PEAK_NOW"
              ? "rgba(245,158,11,0.5)"
              : n.window_status === "SEED_NOW"
              ? "rgba(16,185,129,0.5)"
              : n.is_custom
              ? "rgba(251,113,133,0.45)"
              : "rgba(51,65,85,0.85)";

          const citiesRow = (n.target_cities || [])
            .map((c) => `<span class="pill" style="font-size:10px;color:#34d399;border-color:rgba(16,185,129,0.35)">${esc(c)}</span>`)
            .join("");

          const vibesRow = (n.vibe_tags || [])
            .slice(0, 6)
            .map((v) => `<span class="pill" style="font-size:9.5px">${esc(v)}</span>`)
            .join("");

          const tracksHtml = (n.matched_tracks || []).length
            ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(34,211,238,0.07);border:1px solid rgba(34,211,238,0.25);border-radius:6px">
                <div style="font-family:monospace;font-size:9.5px;color:#22d3ee;margin-bottom:3px">🎵 MATCHED CLIENT TRACKS (${esc(activeProj?.name || "CATALOG")})</div>
                ${n.matched_tracks
                  .map(
                    (t) => `<div style="font-size:11px;color:#e2e8f0"><b>${esc(t.artist)} — ${esc(t.title)}</b> <span style="color:#94a3b8;font-family:monospace;font-size:10px">${esc(t.clip_timestamp || "")}</span></div>`
                  )
                  .join("")}
              </div>`
            : "";

          const signalsHtml = (n.linked_signals || []).length
            ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(15,23,42,0.75);border-left:2px solid #38bdf8;border-radius:0 6px 6px 0">
                <div style="font-family:monospace;font-size:9.5px;color:#38bdf8;margin-bottom:4px">↳ AUTO-LINKED LIVE SIGNAL BRANCHES (${n.linked_signals.length})</div>
                ${n.linked_signals
                  .map(
                    (sig) => `<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:3px;font-size:11px">
                      <span style="color:#cbd5e1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">
                        <button type="button" class="btn-action" data-tl-jump="${esc(sig.ticker)}" style="padding:1px 5px;font-size:10px;font-family:monospace;color:#38bdf8;margin-right:4px">${esc(sig.ticker)}</button>
                        ${esc(sig.title || "")}
                      </span>
                      <span style="font-family:monospace;font-size:10px;color:#34d399;flex-shrink:0">CVS ${Number(sig.cvs_score || 0).toFixed(0)}</span>
                    </div>`
                  )
                  .join("")}
              </div>`
            : "";

          const childrenHtml = (n.child_catalysts || []).length
            ? `<div style="margin-top:8px;padding:6px 8px;background:rgba(251,113,133,0.07);border-left:2px solid #fb7185;border-radius:0 6px 6px 0">
                <div style="font-family:monospace;font-size:9.5px;color:#fb7185;margin-bottom:4px">↳ CUSTOM LINEAGE BRANCHES (${n.child_catalysts.length})</div>
                ${n.child_catalysts
                  .map(
                    (ch) => `<div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:3px;font-size:11px">
                      <span style="color:#f8fafc"><b>${esc(ch.name)}</b> <span style="color:#94a3b8">(${esc(ch.next_date)} · T-${ch.days_until}d)</span>${ch.notes ? ` — <span style="color:#cbd5e1">${esc(ch.notes)}</span>` : ""}</span>
                      <button type="button" class="btn-action" data-tl-del="${ch.id}" style="padding:1px 6px;font-size:9.5px;color:#fb7185;border-color:rgba(251,113,133,0.4)">✕</button>
                    </div>`
                  )
                  .join("")}
              </div>`
            : "";

          return `<div class="hub-card" style="border-color:${borderCol};display:flex;flex-direction:column;justify-content:space-between">
            <div class="hub-card-header" style="flex-wrap:wrap;gap:6px">
              <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
                <span style="font-weight:800;color:#f8fafc">${esc(n.name)}</span>
                ${scopeBadge(n.scope)}
              </div>
              <div style="display:flex;align-items:center;gap:5px">
                ${statusBadge(n.window_status, n.days_until)}
                ${n.is_custom && n.custom_id ? `<button type="button" class="btn-action" data-tl-del="${n.custom_id}" style="padding:1px 6px;font-size:10px;color:#fb7185">✕</button>` : ""}
              </div>
            </div>
            <div class="hub-card-body">
              <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:6px;font-size:11px;color:#94a3b8;margin-bottom:6px">
                <span>📅 <b>${esc(n.next_date)}</b> · Pre-Wave Seed: <b>${n.seed_lead_days}d before</b></span>
                <span>🎯 First Movers: <b style="color:#e2e8f0">${esc(n.first_mover_cohort || "--")}</b></span>
              </div>
              ${n.spotify_billboard_angle ? `<div style="font-size:11.5px;color:#cbd5e1;margin-bottom:8px;line-height:1.4"><b style="color:#34d399">Spotify / Billboard Edge:</b> ${esc(n.spotify_billboard_angle)}</div>` : ""}
              ${citiesRow ? `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">${citiesRow}</div>` : ""}
              ${vibesRow ? `<div style="display:flex;gap:4px;flex-wrap:wrap">${vibesRow}</div>` : ""}
              ${tracksHtml}
              ${signalsHtml}
              ${childrenHtml}
            </div>
          </div>`;
        })
        .join("")
    : `<div class="hub-card" style="grid-column:1/-1;padding:24px;text-align:center;color:#94a3b8">No timeline anchors match your current filters. Try clearing the City or Scope filter.</div>`;

  el.innerHTML = `
    <div class="hub-page">
      <div class="hub-header-row" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px;margin-bottom:12px">
        <div>
          <h2 style="margin:0;font-size:16px;font-family:monospace;color:#34d399">CULTURAL TIMELINE // YEARLY LINEAGE TREE &amp; SPOTIFY CITY SEEDING</h2>
          <div style="font-size:11.5px;color:#94a3b8;margin-top:2px">Recurring holiday, weather-mood, and regional anchors with <b>2–5 week pre-wave seeding windows</b> + auto-linked live signals &amp; custom future catalysts.</div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn-action cyan" id="btn-tl-sync-sports">⚡ Sync Live Sports (ESPN)</button>
          <button type="button" class="btn-action green" id="btn-tl-add-catalyst">+ Add Future Catalyst</button>
          <button type="button" class="btn-action" id="btn-tl-refresh">Refresh</button>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-bottom:14px">
        <div class="hub-card" style="padding:10px 12px;border-color:rgba(16,185,129,0.4)"><div style="font-family:monospace;font-size:10px;color:#94a3b8">SEED NOW / PEAK</div><div style="font-size:20px;font-weight:800;color:#34d399">${(s.seed_now_count ?? 0) + (s.peak_now_count ?? 0)}</div><div style="font-size:10.5px;color:#64748b">${s.peak_now_count ?? 0} peaking · ${s.seed_now_count ?? 0} in seed window</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">PREP NEXT (30-60D)</div><div style="font-size:20px;font-weight:800;color:#22d3ee">${s.prep_next_count ?? 0}</div><div style="font-size:10.5px;color:#64748b">Queue client audio &amp; clips</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">CONFIRMED TRUNK</div><div style="font-size:20px;font-weight:800;color:#f8fafc">${s.total_anchors ?? 0}</div><div style="font-size:10.5px;color:#64748b">+ ${s.custom_catalysts ?? 0} custom branches</div></div>
        <div class="hub-card" style="padding:10px 12px"><div style="font-family:monospace;font-size:10px;color:#94a3b8">LIVE SIGNAL BRANCHES</div><div style="font-size:20px;font-weight:800;color:#a78bfa">${s.linked_signal_branches ?? 0}</div><div style="font-size:10.5px;color:#64748b">Auto-linked from Terminal t₀</div></div>
      </div>

      ${renderCulturalTreeSection(tl)}

      <div class="hub-card" style="margin-bottom:14px;border-color:rgba(16,185,129,0.4)">
        <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
          <span>🌤 CURRENT SEASONAL MOOD // ${esc((season.label || "").toUpperCase())} (${esc(tl.reference_date || "")})</span>
          <span class="pill green">SPOTIFY / BILLBOARD PRIORITY CITIES NOW</span>
        </div>
        <div class="hub-card-body">
          <div style="font-size:12px;color:#cbd5e1;margin-bottom:8px">
            <b>Weather / Atmosphere:</b> ${esc(season.weather_vibe || "")} &nbsp;|&nbsp; <b>Collective Consciousness Mood:</b> ${esc(season.collective_mood || "")}
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            <span style="font-family:monospace;font-size:10.5px;color:#94a3b8">SEED PRIORITY CITIES:</span>
            ${cityPillsHtml}
            ${hubState.timelineCityFilter !== "ALL" ? `<button type="button" class="btn-action" id="btn-tl-clear-city" style="padding:2px 8px;font-size:10.5px">Clear City</button>` : ""}
          </div>
        </div>
      </div>

      <div class="hub-card" style="margin-bottom:14px">
        <div class="hub-card-header" style="flex-wrap:wrap;gap:8px">
          <span>12-MONTH CULTURAL LINEAGE TREE (${filtered.length} / ${allNodes.length} ANCHORS)</span>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            <select id="tl-scope" class="hub-filter-select">
              <option value="ALL" ${hubState.timelineScopeFilter === "ALL" ? "selected" : ""}>Scope: ALL</option>
              <option value="national" ${hubState.timelineScopeFilter === "national" ? "selected" : ""}>National / Holidays</option>
              <option value="sports" ${hubState.timelineScopeFilter === "sports" ? "selected" : ""}>Pro &amp; College Sports</option>
              <option value="regional" ${hubState.timelineScopeFilter === "regional" ? "selected" : ""}>Regional / Spotify Cities</option>
              <option value="music_industry" ${hubState.timelineScopeFilter === "music_industry" ? "selected" : ""}>Spotify &amp; Billboard</option>
              <option value="custom" ${hubState.timelineScopeFilter === "custom" ? "selected" : ""}>Custom Branches</option>
            </select>
            <select id="tl-window" class="hub-filter-select">
              <option value="ALL" ${hubState.timelineWindowFilter === "ALL" ? "selected" : ""}>Window: Full 12 Months</option>
              <option value="ACTIVE" ${hubState.timelineWindowFilter === "ACTIVE" ? "selected" : ""}>Active Seed / Peak Now</option>
              <option value="PREP_NEXT" ${hubState.timelineWindowFilter === "PREP_NEXT" ? "selected" : ""}>Prep Next (30-60d)</option>
            </select>
            <select id="tl-city" class="hub-filter-select">
              <option value="ALL" ${hubState.timelineCityFilter === "ALL" ? "selected" : ""}>Spotify City: ALL</option>
              ${allCities.map((c) => `<option value="${esc(c)}" ${hubState.timelineCityFilter === c ? "selected" : ""}>${esc(c)}</option>`).join("")}
            </select>
          </div>
        </div>
        <div class="hub-card-body">
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));gap:12px">
            ${nodesHtml}
          </div>
        </div>
      </div>
    </div>
  `;

  document.getElementById("btn-tl-refresh").addEventListener("click", loadTimeline);
  document.getElementById("btn-tl-add-catalyst").addEventListener("click", () => openAddCatalystModal(""));
  document.getElementById("btn-tree-mode-year")?.addEventListener("click", () => {
    hubState.timelineTreeMode = "year";
    renderTimelineView();
  });
  document.getElementById("btn-tree-mode-canopy")?.addEventListener("click", () => {
    hubState.timelineTreeMode = "canopy";
    renderTimelineView();
  });
  document.getElementById("btn-tree-branch-here")?.addEventListener("click", (e) => {
    openAddCatalystModal(e.currentTarget.dataset.parentAnchor || "");
  });
  el.querySelectorAll("[data-tree-node]").forEach((nodeEl) => {
    nodeEl.addEventListener("click", () => {
      hubState.selectedTreeNodeId = nodeEl.dataset.treeNode;
      renderTimelineView();
    });
  });
  document.getElementById("btn-tl-sync-sports").addEventListener("click", async () => {
    const btn = document.getElementById("btn-tl-sync-sports");
    btn.disabled = true;
    btn.textContent = "Syncing NFL/CFB/NBA/NCAA...";
    setStatus("Pulling live Pro & College Sports schedules from ESPN...");
    try {
      const res = await api("/api/timeline/sync-sports", {
        method: "POST",
        body: JSON.stringify({ days_ahead: 21, max_per_league: 4 }),
      });
      setStatus(`ESPN Sports Sync complete: added ${res.added_count} upcoming marquee games (${res.skipped_existing} already tracked).`);
      await loadTimeline();
    } catch (err) {
      setStatus(`Sports sync failed: ${err.message}`, true);
      btn.disabled = false;
      btn.textContent = "⚡ Sync Live Sports (ESPN)";
    }
  });
  document.getElementById("tl-scope").addEventListener("change", (e) => { hubState.timelineScopeFilter = e.target.value; renderTimelineView(); });
  document.getElementById("tl-window").addEventListener("change", (e) => { hubState.timelineWindowFilter = e.target.value; renderTimelineView(); });
  document.getElementById("tl-city").addEventListener("change", (e) => { hubState.timelineCityFilter = e.target.value; renderTimelineView(); });
  document.getElementById("btn-tl-clear-city")?.addEventListener("click", () => { hubState.timelineCityFilter = "ALL"; renderTimelineView(); });

  el.querySelectorAll("[data-tl-city]").forEach((btn) => {
    btn.addEventListener("click", () => {
      hubState.timelineCityFilter = hubState.timelineCityFilter === btn.dataset.tlCity ? "ALL" : btn.dataset.tlCity;
      renderTimelineView();
    });
  });
  el.querySelectorAll("[data-tl-jump]").forEach((btn) => {
    btn.addEventListener("click", () => {
      switchHubView("terminal", true);
      if (typeof selectTicker === "function") selectTicker(btn.dataset.tlJump);
    });
  });
  el.querySelectorAll("[data-tl-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      try {
        await api(`/api/timeline/catalysts/${encodeURIComponent(btn.dataset.tlDel)}/delete`, { method: "POST", body: "{}" });
        setStatus("Removed custom timeline catalyst.");
        await loadTimeline();
      } catch (err) {
        setStatus(`Delete failed: ${err.message}`, true);
      }
    });
  });
}

function openAddCatalystModal(preselectParentId = "") {
  const tl = hubState.timeline || {};
  const anchors = (tl.timeline_nodes || []).filter((n) => !n.is_custom);
  const anchorOpts = anchors
    .map((a) => `<option value="${esc(a.id)}" ${preselectParentId && preselectParentId === a.id ? "selected" : ""}>${esc(a.name)} (${esc(a.next_date)})</option>`)
    .join("");
  const activeProj = typeof getActiveProject === "function" ? getActiveProject() : null;

  openModal(
    "ADD FUTURE CATALYST // GROW LINEAGE TREE",
    `
    <form id="form-add-catalyst">
      <div class="form-row">
        <label>CATALYST NAME (ALBUM DROP, TOUR, MOVIE, REGIONAL MOMENT, CLIENT RELEASE)</label>
        <input type="text" name="name" placeholder="e.g. Fuerza Regida LA Arena Show / GTA VI Trailer 3" required autofocus />
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
        <div class="form-row">
          <label>EVENT DATE</label>
          <input type="date" name="event_date" required />
        </div>
        <div class="form-row">
          <label>SEED LEAD DAYS</label>
          <input type="number" name="seed_lead_days" value="21" min="1" max="90" />
        </div>
        <div class="form-row">
          <label>SCOPE</label>
          <select name="scope">
            <option value="custom">Custom / Client Drop</option>
            <option value="regional">Regional / City Event</option>
            <option value="music_industry">Spotify / Billboard</option>
            <option value="national">National Pop Culture</option>
          </select>
        </div>
      </div>
      <div class="form-row">
        <label>BRANCH OFF RECURRING ANCHOR (OPTIONAL — FAMILY TREE PARENT)</label>
        <select name="parent_anchor_id">
          <option value="">Standalone Future Node (Top-Level)</option>
          ${anchorOpts}
        </select>
      </div>
      <div class="form-row">
        <label>PRIORITY SPOTIFY / BILLBOARD CITIES (COMMA-SEPARATED)</label>
        <input type="text" name="target_cities" placeholder="Los Angeles, Houston, Dallas-Fort Worth, Miami" value="${activeProj ? "Los Angeles, Houston, Dallas-Fort Worth, Phoenix" : "Los Angeles, New York City, Atlanta"}" />
      </div>
      <div class="form-row">
        <label>VIBE / TREND TAGS (COMMA-SEPARATED)</label>
        <input type="text" name="vibe_tags" placeholder="party, hype, desamor, car, capcut_template" />
      </div>
      <div class="form-row">
        <label>SEEDING ANGLE / NOTES</label>
        <textarea name="notes" rows="2" placeholder="Why this matters and how we seed client songs 2-4 weeks ahead..."></textarea>
      </div>
      <div class="form-actions">
        <button type="submit" class="btn-action green">Save to Timeline Tree</button>
      </div>
    </form>
    `
  );
  document.getElementById("form-add-catalyst").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await api("/api/timeline/catalysts", {
        method: "POST",
        body: JSON.stringify({
          name: fd.get("name"),
          event_date: fd.get("event_date"),
          seed_lead_days: Number(fd.get("seed_lead_days") || 21),
          scope: fd.get("scope"),
          parent_anchor_id: fd.get("parent_anchor_id") || "",
          target_cities: fd.get("target_cities") || "",
          vibe_tags: fd.get("vibe_tags") || "",
          notes: fd.get("notes") || "",
          project_id: activeProj ? activeProj.id : "",
        }),
      });
      closeModal();
      setStatus("Added future catalyst branch to Cultural Timeline.");
      await loadTimeline();
    } catch (err) {
      setStatus(`Failed to save catalyst: ${err.message}`, true);
    }
  });
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
document.getElementById("btn-open-brief-ab")?.addEventListener("click", () => {
  if (typeof openBriefAbSwipeModal === "function") openBriefAbSwipeModal();
});

window.addEventListener("hashchange", () => {
  const h = window.location.hash.replace("#", "").toLowerCase();
  if (["evals", "terminal", "quant", "timeline", "orchestration", "updates"].includes(h) && h !== hubState.activeView) {
    switchHubView(h, false);
  }
});

// Initialize auth status & deep-link view from hash
refreshAuthStatus();
const initialHash = window.location.hash.replace("#", "").toLowerCase();
if (["evals", "terminal", "quant", "timeline", "orchestration", "updates"].includes(initialHash)) {
  switchHubView(initialHash, false);
}
