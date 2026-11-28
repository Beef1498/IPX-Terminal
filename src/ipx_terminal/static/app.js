/* IPX Terminal v0.1 — 4-Pane Bloomberg Launchpad Client */

const state = {
  config: null,
  stats: null,
  sector: "ALL",
  movers: [],
  signals: [],
  predictions: [],
  briefs: [],
  entities: [],
  projects: [],
  activeProjectId: localStorage.getItem("ipx_active_project") || "",
  activeTicker: null,
  tickerDetail: null,
  activeTab: "DES",
  lastExport: null,
  lastCreativeExport: null,
  lastAutoAb: null,
  markets: [],
  marketsLoaded: false,
  marketsSource: "all",
  marketsSector: "ALL",
  marketsQuery: "",
  marketsIpOnly: true,
  mapData: null,
  mapLoaded: false,
  mapQuery: "",
  mapHideNoise: true,
  mapSelectedClusterIdx: 0,
  mapSelectedState: null,
};

function esc(str) {
  return String(str ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setStatus(msg, isError = false) {
  const el = document.getElementById("status-text");
  el.textContent = msg;
  el.style.color = isError ? "#fb7185" : "#8b9bb0";
}

async function api(path, options = {}) {
  const token = sessionStorage.getItem("ipx_write_token") || "";
  const extraHeaders = options.headers || {};
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { "X-IPX-Token": token } : {}),
    ...extraHeaders,
  };
  const res = await fetch(path, {
    ...options,
    headers,
  });
  const data = await res.json();
  if (!res.ok) {
    if (res.status === 401 && data.auth_required && typeof window.openUnlockModal === "function") {
      window.openUnlockModal(data.error);
    }
    throw new Error(data.error || `HTTP ${res.status}`);
  }
  return data;
}

async function loadBootstrap(preserveTicker = true) {
  const data = await api(`/api/bootstrap?sector=${encodeURIComponent(state.sector)}`);
  state.config = data.config;
  state.stats = data.stats;
  state.movers = data.movers;
  state.signals = data.signals;
  state.predictions = data.predictions;
  state.briefs = data.briefs || [];
  state.entities = data.entities;
  state.projects = data.projects || [];
  if (!state.activeProjectId) {
    const prim = state.projects.find((p) => p.active !== false && p.primary) || state.projects[0];
    state.activeProjectId = prim ? prim.id : "NONE";
  }

  renderProjectSelector();
  renderKpis();
  renderSectorKeys();
  renderMovers();
  renderWire();

  const candidate =
    preserveTicker && state.activeTicker && state.entities.some((e) => e.ticker === state.activeTicker)
      ? state.activeTicker
      : state.movers[0]?.ticker || state.entities[0]?.ticker || null;

  if (candidate) {
    await selectTicker(candidate, false);
  } else {
    renderGP();
    renderDesk();
  }
}

async function selectTicker(ticker, announce = true) {
  state.activeTicker = ticker;
  state.tickerDetail = await api(`/api/ticker/${encodeURIComponent(ticker)}`);
  renderMovers();
  renderGP();
  renderDesk();
  if (announce) setStatus(`Loaded ${ticker} — ${state.tickerDetail.entity.name}`);
}

function getActiveProject() {
  if (!state.activeProjectId || state.activeProjectId === "NONE") return null;
  return (state.projects || []).find((p) => p.id === state.activeProjectId) || null;
}

function renderProjectSelector() {
  const sel = document.getElementById("project-select");
  if (!sel) return;
  const opts = [
    `<option value="NONE"${state.activeProjectId === "NONE" ? " selected" : ""}>Client: All (General)</option>`,
    ...(state.projects || []).map(
      (p) =>
        `<option value="${esc(p.id)}"${state.activeProjectId === p.id ? " selected" : ""}>★ Client: ${esc(p.name || p.id)}</option>`
    ),
  ];
  sel.innerHTML = opts.join("");
  if (!sel.dataset.bound) {
    sel.dataset.bound = "1";
    sel.addEventListener("change", () => {
      state.activeProjectId = sel.value || "NONE";
      localStorage.setItem("ipx_active_project", state.activeProjectId);
      const proj = getActiveProject();
      setStatus(
        proj
          ? `Active client project: ${proj.name} (${(proj.catalog_tracks || []).length} catalog tracks ready for song-seeding)`
          : "Switched to General IPX view (no client project filter)."
      );
      if (typeof loadQuant === "function" && typeof hubState !== "undefined" && hubState.activeView === "quant") {
        loadQuant();
      } else if (typeof renderQuantView === "function" && typeof hubState !== "undefined" && hubState.quant) {
        renderQuantView();
      }
      if (typeof loadTimeline === "function" && typeof hubState !== "undefined" && hubState.activeView === "timeline") {
        loadTimeline();
      }
    });
  }
}

function updateBriefAbBadge() {
  const badge = document.getElementById("brief-ab-count");
  if (!badge) return;
  const pending = (state.briefs || []).filter((b) => b.status !== "graded").length;
  badge.textContent = String(pending);
  badge.classList.toggle("zero", pending === 0);
}

function renderSwipeCardDeck(containerEl, onAfterAction) {
  if (typeof state.swipeSkippedIds === "undefined") {
    state.swipeSkippedIds = [];
  }
  const draftBriefs = (state.briefs || []).filter((b) => b.status !== "graded" && !state.swipeSkippedIds.includes(b.id));
  const queue = draftBriefs.length
    ? draftBriefs
    : state.swipeReviewAll
    ? (state.briefs || []).filter((b) => !state.swipeSkippedIds.includes(b.id))
    : [];
  const cur = queue[0];
  if (!cur) {
    const totalBriefs = (state.briefs || []).length;
    containerEl.innerHTML = `
      <div class="swipe-deck-wrap" style="text-align:center;padding:24px 12px;border:1px dashed #2e3d52;border-radius:12px">
        <div style="font-size:24px;margin-bottom:6px">${totalBriefs === 0 ? "⚡" : "🎉"}</div>
        <div style="font-weight:700;color:#f8fafc;margin-bottom:4px">${totalBriefs === 0 ? "No generated briefs on this server yet" : "All generated briefs graded!"}</div>
        <div style="font-size:12px;color:#94a3b8;margin-bottom:14px">${totalBriefs === 0 ? "Run a quick Morning Quant pass to auto-draft fresh Creative Briefs ready to swipe." : "Every swipe + edit note is saved for Gemma 4 DPO fine-tuning."}</div>
        <div style="display:flex;gap:8px;justify-content:center;flex-wrap:wrap">
          ${totalBriefs === 0 ? `<button type="button" class="btn-action green" data-swipe-run-quant>⚡ Generate Briefs Now</button>` : ""}
          ${state.swipeSkippedIds.length ? `<button type="button" class="btn-action cyan" data-swipe-reset-skips>Review ${state.swipeSkippedIds.length} Skipped</button>` : ""}
          ${totalBriefs > 0 ? `<button type="button" class="btn-action" data-swipe-review-all>Re-Swipe All (${totalBriefs})</button>` : ""}
          ${totalBriefs > 0 ? `<button type="button" class="btn-action amber" data-swipe-export-dpo>Export DPO Pairs</button>` : ""}
        </div>
      </div>
    `;
    containerEl.querySelector("[data-swipe-run-quant]")?.addEventListener("click", async (ev) => {
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.textContent = "Generating fresh briefs...";
      setStatus("Running Morning Quant to generate fresh swipe briefs...");
      try {
        const projId = state.activeProjectId && state.activeProjectId !== "NONE" ? state.activeProjectId : null;
        await api("/api/quant/run", {
          method: "POST",
          body: JSON.stringify({ mode: "morning", project_id: projId }),
        });
        const data = await api(`/api/bootstrap?sector=${encodeURIComponent(state.sector || "ALL")}`);
        state.briefs = data.briefs || [];
        updateBriefAbBadge();
        setStatus(`Generated fresh briefs! Ready to swipe.`);
        onAfterAction();
      } catch (err) {
        btn.disabled = false;
        btn.textContent = "⚡ Generate Briefs Now";
        setStatus(`Generate failed: ${err.message}`, true);
      }
    });
    containerEl.querySelector("[data-swipe-reset-skips]")?.addEventListener("click", () => {
      state.swipeSkippedIds = [];
      onAfterAction();
    });
    containerEl.querySelector("[data-swipe-review-all]")?.addEventListener("click", () => {
      state.swipeSkippedIds = [];
      state.swipeReviewAll = true;
      onAfterAction();
    });
    containerEl.querySelector("[data-swipe-export-dpo]")?.addEventListener("click", async () => {
      try {
        state.lastCreativeExport = await api("/api/briefs/export", {
          method: "POST",
          body: JSON.stringify({ version: "0.5" }),
        });
        setStatus(`Exported ${state.lastCreativeExport.pairs_exported} A/B + ${state.lastCreativeExport.direct_dpo_pairs || 0} direct DPO pairs -> ${state.lastCreativeExport.out_dir}`);
        onAfterAction();
      } catch (err) {
        setStatus(err.message, true);
      }
    });
    return;
  }

  const tasteChips = [
    { id: "too_robotic", label: "🤖 Too robotic" },
    { id: "cringey", label: "😬 Cringey / out of touch" },
    { id: "overdid_emojis", label: "😀 Overdid emojis" },
    { id: "add_handle", label: "🏷️ Add @handle" },
    { id: "fire_caption", label: "🔥 Fire caption" },
    { id: "weak_hook", label: "🎯 Weak 2s hook" },
    { id: "great_song_fit", label: "🎵 Great song fit" },
    { id: "tighten_beats", label: "✂️ Tighten beats" },
  ];
  const beatsHtml = (cur.edit_beats || [])
    .map((bt) => `<li style="margin:2px 0;color:#cbd5e1;font-size:11.5px">${esc(bt)}</li>`)
    .join("");

  containerEl.innerHTML = `
    <div class="swipe-deck-wrap">
      <div class="swipe-deck-meta">
        <span>MATCH 1 OF ${queue.length} · SWIPE RIGHT = SHIP / LEFT = PASS</span>
        <span style="color:#34d399">${(state.briefs || []).filter((b) => b.status === "graded").length} GRADED FOR DPO</span>
      </div>
      <div class="swipe-stage">
        <div class="swipe-card" data-active-swipe-card>
          <div class="swipe-stamp right" data-stamp-right>♥ SHIP</div>
          <div class="swipe-stamp left" data-stamp-left>✕ PASS</div>

          <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:8px;flex-wrap:wrap">
            <span><b style="color:#f59e0b;font-family:monospace">${esc(cur.ticker)}</b> · <span class="pill cyan">${esc(cur.target_platform)}</span></span>
            <span class="pill" style="color:#94a3b8">${esc(cur.model_used)}</span>
          </div>

          <div style="font-size:15px;font-weight:800;color:#f8fafc;line-height:1.3;margin-bottom:6px">${esc(cur.on_screen_text)}</div>
          <div style="font-size:11.5px;color:#94a3b8;margin-bottom:6px"><b>Angle:</b> ${esc(cur.angle)}</div>
          <div style="font-size:12px;color:#e2e8f0;margin-bottom:4px"><b style="color:#22d3ee">2s Hook:</b> ${esc(cur.hook_2s)}</div>

          <div class="swipe-caption-box">
            <div style="font-family:monospace;font-size:9.5px;color:#38bdf8;margin-bottom:3px">CAPTION (STORY · @HANDLES · APPLE EMOJIS)</div>
            <div>${esc(cur.caption)}</div>
          </div>

          ${cur.audio_cue ? `<div style="font-size:11.5px;color:#34d399;margin-bottom:6px"><b>🎵 Audio Cue:</b> ${esc(cur.audio_cue)}</div>` : ""}
          ${beatsHtml ? `<details style="margin-bottom:8px"><summary style="cursor:pointer;font-family:monospace;font-size:10.5px;color:#94a3b8">Edit Beats (${cur.edit_beats.length})</summary><ul style="margin:4px 0 0;padding-left:16px">${beatsHtml}</ul></details>` : ""}

          <div class="swipe-chips">
            ${tasteChips.map((c) => `<button type="button" class="swipe-chip" data-chip="${c.id}">${c.label}</button>`).join("")}
          </div>

          <input type="text" data-swipe-note class="swipe-note-input" placeholder="Leave a message with edits/improvements (why it works or what to fix)..." value="${esc(cur.outcome_notes || "")}" />

          <details style="margin-top:7px">
            <summary style="cursor:pointer;font-family:monospace;font-size:10.5px;color:#22d3ee">✏ Rewrite Caption / Hook (builds direct DPO pair for Gemma 4)</summary>
            <div style="margin-top:6px;display:flex;flex-direction:column;gap:6px">
              <textarea data-swipe-rev-caption class="swipe-note-input" rows="2" placeholder="Improved caption with @handles & 0-2 Apple emojis...">${esc(cur.revised_caption || cur.caption || "")}</textarea>
              <input type="text" data-swipe-rev-hook class="swipe-note-input" placeholder="Improved 2s hook (optional)..." value="${esc(cur.revised_hook || "")}" />
            </div>
          </details>
        </div>
      </div>

      <div class="swipe-actions">
        <button type="button" class="swipe-btn pass" data-btn-swipe-left>✕ PASS</button>
        <button type="button" class="swipe-btn skip" data-btn-swipe-skip>Skip ⏭</button>
        <button type="button" class="swipe-btn ship" data-btn-swipe-right>♥ SHIP</button>
      </div>
    </div>
  `;

  const selectedTags = new Set(cur.feedback_tags || []);
  containerEl.querySelectorAll("[data-chip]").forEach((chip) => {
    if (selectedTags.has(chip.dataset.chip)) chip.classList.add("active");
    chip.addEventListener("click", (ev) => {
      ev.stopPropagation();
      const id = chip.dataset.chip;
      if (selectedTags.has(id)) {
        selectedTags.delete(id);
        chip.classList.remove("active");
      } else {
        selectedTags.add(id);
        chip.classList.add("active");
      }
    });
  });

  const card = containerEl.querySelector("[data-active-swipe-card]");
  const stampR = containerEl.querySelector("[data-stamp-right]");
  const stampL = containerEl.querySelector("[data-stamp-left]");

  let submitting = false;
  const submitSwipe = async (direction) => {
    if (submitting) return;
    submitting = true;
    const note = (containerEl.querySelector("[data-swipe-note]")?.value || "").trim();
    const revCapRaw = (containerEl.querySelector("[data-swipe-rev-caption]")?.value || "").trim();
    const revCap = revCapRaw && revCapRaw !== (cur.caption || "").trim() ? revCapRaw : "";
    const revHook = (containerEl.querySelector("[data-swipe-rev-hook]")?.value || "").trim();

    card.style.transition = "transform 0.24s ease, opacity 0.24s ease";
    card.style.transform = `translateX(${direction === "right" ? 420 : -420}px) rotate(${direction === "right" ? 18 : -18}deg)`;
    card.style.opacity = "0";
    try {
      const res = await api(`/api/briefs/${cur.id}/swipe`, {
        method: "POST",
        body: JSON.stringify({
          direction,
          feedback_note: note,
          feedback_tags: Array.from(selectedTags),
          revised_caption: revCap,
          revised_hook: revHook,
        }),
      });
      const idx = state.briefs.findIndex((b) => b.id === cur.id);
      if (idx >= 0) state.briefs[idx] = res.brief;
      updateBriefAbBadge();
      setStatus(
        `${direction === "right" ? "♥ SHIPPED" : "✕ PASSED"} brief #${cur.id} (${cur.ticker})${revCap || revHook ? " + saved direct DPO rewrite" : ""}.`
      );
      setTimeout(() => onAfterAction(), 180);
    } catch (err) {
      submitting = false;
      card.style.transform = "";
      card.style.opacity = "1";
      setStatus(`Swipe failed: ${err.message}`, true);
    }
  };

  containerEl.querySelector("[data-btn-swipe-right]").addEventListener("click", () => submitSwipe("right"));
  containerEl.querySelector("[data-btn-swipe-left]").addEventListener("click", () => submitSwipe("left"));
  containerEl.querySelector("[data-btn-swipe-skip]").addEventListener("click", () => {
    state.swipeSkippedIds.push(cur.id);
    onAfterAction();
  });

  let startX = 0;
  let startY = 0;
  let dx = 0;
  let dragging = false;
  let lockedAxis = null;

  const isInteractiveTarget = (t) =>
    Boolean(t && t.closest("input, textarea, button, summary, details, a, select"));

  const onStart = (x, y, target) => {
    if (submitting || isInteractiveTarget(target)) return;
    startX = x;
    startY = y;
    dx = 0;
    dragging = true;
    lockedAxis = null;
    card.classList.add("dragging");
  };
  const onMove = (x, y) => {
    if (!dragging) return;
    const curDx = x - startX;
    const curDy = y - startY;
    if (!lockedAxis && (Math.abs(curDx) > 8 || Math.abs(curDy) > 8)) {
      lockedAxis = Math.abs(curDx) > Math.abs(curDy) ? "x" : "y";
    }
    if (lockedAxis !== "x") return;
    dx = curDx;
    const rot = Math.max(-18, Math.min(18, dx * 0.06));
    card.style.transform = `translateX(${dx}px) rotate(${rot}deg)`;
    const ratio = Math.min(1, Math.abs(dx) / 95);
    if (dx > 18) {
      card.classList.add("hint-right");
      card.classList.remove("hint-left");
      stampR.style.opacity = String(ratio);
      stampL.style.opacity = "0";
    } else if (dx < -18) {
      card.classList.add("hint-left");
      card.classList.remove("hint-right");
      stampL.style.opacity = String(ratio);
      stampR.style.opacity = "0";
    } else {
      card.classList.remove("hint-right", "hint-left");
      stampR.style.opacity = "0";
      stampL.style.opacity = "0";
    }
  };
  const onEnd = () => {
    if (!dragging) return;
    dragging = false;
    card.classList.remove("dragging");
    if (dx >= 90) {
      submitSwipe("right");
    } else if (dx <= -90) {
      submitSwipe("left");
    } else {
      card.style.transform = "";
      card.classList.remove("hint-right", "hint-left");
      stampR.style.opacity = "0";
      stampL.style.opacity = "0";
    }
  };

  const handleMouseMove = (e) => onMove(e.clientX, e.clientY);
  const handleMouseUp = () => {
    window.removeEventListener("mousemove", handleMouseMove);
    window.removeEventListener("mouseup", handleMouseUp);
    onEnd();
  };
  card.addEventListener("touchstart", (e) => onStart(e.touches[0].clientX, e.touches[0].clientY, e.target), { passive: true });
  card.addEventListener("touchmove", (e) => onMove(e.touches[0].clientX, e.touches[0].clientY), { passive: true });
  card.addEventListener("touchend", onEnd);
  card.addEventListener("mousedown", (e) => {
    onStart(e.clientX, e.clientY, e.target);
    if (dragging) {
      window.addEventListener("mousemove", handleMouseMove);
      window.addEventListener("mouseup", handleMouseUp);
    }
  });
}

async function openBriefAbSwipeModal() {
  state.swipeReviewAll = false;
  openModal(
    "🔥 BRIEF A/B // SWIPE MATCH DECK",
    `<div id="modal-brief-ab-root"><p style="color:#94a3b8;text-align:center;padding:16px">Loading latest generated briefs...</p></div>`
  );
  try {
    const data = await api(`/api/bootstrap?sector=${encodeURIComponent(state.sector || "ALL")}`);
    state.briefs = data.briefs || [];
    updateBriefAbBadge();
  } catch {
    // Fallback to already-loaded briefs
  }
  const renderModalDeck = () => {
    const root = document.getElementById("modal-brief-ab-root");
    if (!root) return;
    renderSwipeCardDeck(root, () => {
      renderModalDeck();
      if (state.activeTab === "BRIEFS") renderDesk();
    });
  };
  renderModalDeck();
}
window.openBriefAbSwipeModal = openBriefAbSwipeModal;

function renderKpis() {
  updateBriefAbBadge();
  const s = state.stats || {};
  document.getElementById("kpi-entities").textContent = s.entities ?? 0;
  document.getElementById("kpi-signals").textContent = s.signals ?? 0;
  document.getElementById("kpi-pending").textContent = s.pending_predictions ?? 0;
  document.getElementById("kpi-resolved").textContent = s.resolved_predictions ?? 0;
  document.getElementById("kpi-accuracy").textContent =
    s.prediction_accuracy_pct != null ? `${s.prediction_accuracy_pct}%` : "--";
  const aiEl = document.getElementById("kpi-ai-accuracy");
  if (aiEl) {
    aiEl.textContent = s.ai_accuracy_pct != null ? `${s.ai_accuracy_pct}%` : "--";
  }
}

function renderSectorKeys() {
  const container = document.getElementById("sector-keys");
  const sectors = ["ALL", ...(state.config?.sectors || [])];
  const colors = state.config?.sector_colors || {};
  container.innerHTML = sectors
    .map((sec) => {
      const active = state.sector === sec ? "active" : "";
      const dot = sec !== "ALL" && colors[sec] ? `<span style="color:${colors[sec]}">●</span> ` : "";
      return `<button type="button" class="sector-key ${active}" data-sector="${sec}">${dot}${sec}</button>`;
    })
    .join("");
  container.querySelectorAll(".sector-key").forEach((btn) => {
    btn.addEventListener("click", async () => {
      state.sector = btn.dataset.sector;
      document.getElementById("top-sector-label").textContent = `SECTOR: ${state.sector}`;
      await loadBootstrap(true);
      setStatus(`Filtered Launchpad to sector ${state.sector}`);
    });
  });
}

function renderMovers() {
  const tbody = document.getElementById("movers-tbody");
  const colors = state.config?.sector_colors || {};
  if (!state.movers.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="color:#8b9bb0;padding:16px">No IP entities found. Run <code>SEED</code> in the command bar or click <b>+ Capture t₀ Signal</b>.</td></tr>`;
    return;
  }
  tbody.innerHTML = state.movers
    .map((m) => {
      const sel = m.ticker === state.activeTicker ? "selected" : "";
      const deltaCls = m.cvs_delta > 0 ? "delta-pos" : m.cvs_delta < 0 ? "delta-neg" : "delta-flat";
      const deltaTxt = m.cvs_delta > 0 ? `+${m.cvs_delta.toFixed(1)}` : m.cvs_delta.toFixed(1);
      const secColor = colors[m.sector] || "#94a3b8";
      return `
        <tr class="${sel}" data-ticker="${esc(m.ticker)}">
          <td class="ticker-cell">${esc(m.ticker)}</td>
          <td><span class="pill" style="color:${secColor};border-color:${secColor}44;background:${secColor}18">${esc(m.sector)}</span></td>
          <td class="num"><b>${Number(m.cvs_score).toFixed(1)}</b></td>
          <td class="num ${deltaCls}">${deltaTxt}</td>
          <td class="num">${Number(m.contagion_index).toFixed(1)}</td>
          <td><span class="pill stage-${esc(m.contagion_stage)}">${esc(m.contagion_stage)}</span></td>
        </tr>
      `;
    })
    .join("");

  tbody.querySelectorAll("tr[data-ticker]").forEach((row) => {
    row.addEventListener("click", () => selectTicker(row.dataset.ticker));
  });
}

function renderGP() {
  const labelEl = document.getElementById("gp-ticker-label");
  const chartWrap = document.getElementById("gp-chart-wrap");
  const latestCard = document.getElementById("gp-latest-card");

  if (!state.tickerDetail) {
    labelEl.textContent = "--";
    chartWrap.innerHTML = `<div style="color:#8b9bb0;padding:16px">Select a ticker in TOP to inspect its CVS &amp; Contagion trajectory.</div>`;
    latestCard.innerHTML = "";
    return;
  }

  const { entity, history } = state.tickerDetail;
  labelEl.textContent = `${entity.ticker} // ${entity.name}`;

  if (!history.length) {
    chartWrap.innerHTML = `<div style="color:#8b9bb0;padding:16px">No signal snapshots yet for ${esc(entity.ticker)}.</div>`;
    latestCard.innerHTML = "";
    return;
  }

  // Build crisp responsive SVG chart
  const W = 520, H = 140, padL = 36, padR = 26, padT = 14, padB = 24;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const n = history.length;

  const xAt = (i) => (n === 1 ? padL + innerW / 2 : padL + (i / (n - 1)) * innerW);
  const yAt = (v) => padT + innerH - (Math.max(0, Math.min(100, v)) / 100) * innerH;

  const cvsPts = history.map((h, i) => `${xAt(i).toFixed(1)},${yAt(h.cvs_score).toFixed(1)}`).join(" ");
  const cntPts = history.map((h, i) => `${xAt(i).toFixed(1)},${yAt(h.contagion_index).toFixed(1)}`).join(" ");
  const areaPts = `${xAt(0).toFixed(1)},${(padT + innerH).toFixed(1)} ${cvsPts} ${xAt(n - 1).toFixed(1)},${(padT + innerH).toFixed(1)}`;

  const gridLines = [0, 25, 50, 75, 100]
    .map((val) => {
      const y = yAt(val).toFixed(1);
      return `<line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#1c2635" stroke-width="1"/>
              <text x="${padL - 6}" y="${Number(y) + 3}" fill="#64748b" font-size="9" font-family="monospace" text-anchor="end">${val}</text>`;
    })
    .join("");

  const dots = history
    .map((h, i) => {
      const x = xAt(i).toFixed(1);
      const yCvs = yAt(h.cvs_score).toFixed(1);
      const yCnt = yAt(h.contagion_index).toFixed(1);
      const shortTime = (h.captured_at || "").slice(5, 16).replace("T", " ");
      const anchor = n === 1 ? "middle" : i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      return `
        <circle cx="${x}" cy="${yCvs}" r="3.5" fill="#22d3ee"><title>CVS ${h.cvs_score} (${shortTime})</title></circle>
        <circle cx="${x}" cy="${yCnt}" r="3" fill="#f59e0b"><title>Contagion ${h.contagion_index} (${shortTime})</title></circle>
        <text x="${x}" y="${H - 6}" fill="#64748b" font-size="8.5" font-family="monospace" text-anchor="${anchor}">${esc(shortTime)}</text>
      `;
    })
    .join("");

  chartWrap.innerHTML = `
    <div style="display:flex;justify-content:space-between;font-family:monospace;font-size:10px;color:#8b9bb0;margin-bottom:4px">
      <span><span style="color:#22d3ee">━</span> CVS (Cultural Velocity) &nbsp; <span style="color:#f59e0b">━</span> Contagion Index</span>
      <span>${history.length} t₀ snapshot(s)</span>
    </div>
    <svg viewBox="0 0 ${W} ${H}" width="100%" height="140" preserveAspectRatio="none">
      ${gridLines}
      <polygon points="${areaPts}" fill="rgba(34,211,238,0.12)" />
      <polyline fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-dasharray="4 2" points="${cntPts}" />
      <polyline fill="none" stroke="#22d3ee" stroke-width="2.2" points="${cvsPts}" />
      ${dots}
    </svg>
  `;

  const latest = history[history.length - 1];
  const metricsChips = Object.entries(latest.metrics || {})
    .slice(0, 8)
    .map(([k, v]) => `<span class="metric-chip">${esc(k)}: ${esc(v)}</span>`)
    .join("");

  latestCard.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
      <b style="color:#f59e0b">LATEST t₀ SNAPSHOT (#${latest.id})</b>
      <button type="button" class="btn-action amber" id="btn-gp-log">+ Log Prediction</button>
    </div>
    <div style="font-weight:600;margin-bottom:4px">${esc(latest.title)}</div>
    <div style="color:#94a3b8">${esc(latest.summary)}</div>
    <div class="metric-chips">${metricsChips || '<span class="metric-chip">no metrics</span>'}</div>
  `;

  document.getElementById("btn-gp-log").addEventListener("click", () => openLogPredictionModal(latest));
}

function renderWire() {
  const list = document.getElementById("wire-list");
  document.getElementById("wire-count-label").textContent = `${state.signals.length} SIGNALS`;
  if (!state.signals.length) {
    list.innerHTML = `<div style="color:#8b9bb0">No signals captured yet.</div>`;
    return;
  }

  list.innerHTML = state.signals
    .map((s) => {
      const ts = (s.captured_at || "").replace("T", " ").replace("Z", " UTC");
      return `
        <div class="wire-card">
          <div class="wire-top">
            <span><b style="color:#f59e0b;cursor:pointer" data-jump-ticker="${esc(s.ticker)}">${esc(s.ticker)}</b> · ${esc(s.platforms.join(", "))}</span>
            <span style="color:#64748b">${esc(ts)}</span>
          </div>
          <div class="wire-title">${esc(s.title)}</div>
          <div class="wire-summary">${esc(s.summary)}</div>
          <div class="wire-footer">
            <span>CVS <b style="color:#22d3ee">${s.cvs_score}</b> · CONTAGION <b>${s.contagion_index}</b> <span class="pill stage-${esc(s.contagion_stage)}">${esc(s.contagion_stage)}</span></span>
            <div style="display:flex;gap:5px">
              <button type="button" class="btn-action cyan" data-brief-signal="${s.id}">Brief</button>
              <button type="button" class="btn-action" data-log-signal="${s.id}">Log Prediction</button>
            </div>
          </div>
        </div>
      `;
    })
    .join("");

  list.querySelectorAll("[data-jump-ticker]").forEach((el) => {
    el.addEventListener("click", () => selectTicker(el.dataset.jumpTicker));
  });
  list.querySelectorAll("[data-brief-signal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sig = state.signals.find((x) => x.id === Number(btn.dataset.briefSignal));
      if (sig) openCreateBriefModal(sig);
    });
  });
  list.querySelectorAll("[data-log-signal]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const sig = state.signals.find((x) => x.id === Number(btn.dataset.logSignal));
      if (sig) openLogPredictionModal(sig);
    });
  });
}

function renderDesk() {
  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === state.activeTab);
  });
  const body = document.getElementById("desk-body");

  if (state.activeTab === "DES") {
    if (!state.tickerDetail) {
      body.innerHTML = `<div style="color:#8b9bb0">Select a ticker to inspect its Entity-Resolution IP Graph profile.</div>`;
      return;
    }
    const { entity, predictions } = state.tickerDetail;
    body.innerHTML = `
      <div class="des-grid">
        <div class="des-kv"><div class="des-k">TICKER / SECTOR</div><div class="des-v" style="color:#f59e0b">${esc(entity.ticker)} · ${esc(entity.sector)}</div></div>
        <div class="des-kv"><div class="des-k">RIGHTS HOLDER / OWNER</div><div class="des-v">${esc(entity.owner_holder)}</div></div>
        <div class="des-kv"><div class="des-k">IP ASSET TYPE</div><div class="des-v">${esc(entity.ip_type)}</div></div>
        <div class="des-kv"><div class="des-k">ALIASES</div><div class="des-v">${esc((entity.aliases || []).join(", ") || "None")}</div></div>
      </div>
      <div class="des-kv" style="margin-bottom:10px">
        <div class="des-k">IP PROFILE</div>
        <div style="color:#cbd5e1;line-height:1.45">${esc(entity.description || "No description yet.")}</div>
      </div>
      <div style="font-family:monospace;font-size:11px;color:#8b9bb0;margin-bottom:6px">LINKED PREDICTIONS (${predictions.length})</div>
      ${predictions.length ? predictions.map(renderPredictionCardHtml).join("") : `<div style="color:#64748b">No predictions logged for ${esc(entity.ticker)} yet.</div>`}
    `;
    wireResolveButtons(body);
    return;
  }

  if (state.activeTab === "LOG") {
    if (!state.predictions.length) {
      body.innerHTML = `<div style="color:#8b9bb0">No predictions logged yet. Click <b>Log Prediction</b> on any signal in WIRE.</div>`;
      return;
    }
    body.innerHTML = state.predictions.map(renderPredictionCardHtml).join("");
    wireResolveButtons(body);
    return;
  }

  if (state.activeTab === "BRIEFS") {
    if (typeof state.briefsViewMode === "undefined") {
      state.briefsViewMode = window.innerWidth <= 820 ? "swipe" : "swipe";
    }
    if (typeof state.swipeSkippedIds === "undefined") {
      state.swipeSkippedIds = [];
    }
    const draftBriefs = state.briefs.filter((b) => b.status !== "graded" && !state.swipeSkippedIds.includes(b.id));
    const allDraftsCount = state.briefs.filter((b) => b.status !== "graded").length;
    const exportBar = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:9px;flex-wrap:wrap">
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span style="font-family:monospace;font-size:11px;color:#94a3b8">BRIEFS (${state.briefs.length} · ${allDraftsCount} TO SWIPE)</span>
          <button type="button" class="btn-action ${state.briefsViewMode === "swipe" ? "green" : ""}" id="btn-briefs-mode-swipe" style="padding:3px 8px;font-size:10.5px">🔥 Swipe Deck</button>
          <button type="button" class="btn-action ${state.briefsViewMode === "list" ? "cyan" : ""}" id="btn-briefs-mode-list" style="padding:3px 8px;font-size:10.5px">☰ List</button>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="btn-action cyan" id="btn-auto-ab-creator">+ Auto-Pair A/B</button>
          <button type="button" class="btn-action amber" id="btn-export-creative">Export DPO Pairs</button>
        </div>
      </div>
      ${state.lastAutoAb ? `<div style="font-family:monospace;font-size:11px;color:#22d3ee;margin-bottom:8px">✓ ScrapeCreators fetched ${state.lastAutoAb.posts_fetched} posts for ${esc(state.lastAutoAb.handle)} (${esc(state.lastAutoAb.platform)}) → built ${state.lastAutoAb.pairs_created} blind A/B pairs → ${esc(state.lastAutoAb.out_path || "none")}</div>` : ""}
      ${state.lastCreativeExport ? `<div style="font-family:monospace;font-size:11px;color:#34d399;margin-bottom:8px">✓ Exported ${state.lastCreativeExport.graded_count} graded briefs · ${state.lastCreativeExport.pairs_exported} A/B pairs · ${state.lastCreativeExport.direct_dpo_pairs || 0} direct human-edit DPO pairs → ${esc(state.lastCreativeExport.out_dir)}</div>` : ""}
    `;

    const bindTopBriefButtons = () => {
      document.getElementById("btn-briefs-mode-swipe").addEventListener("click", () => {
        state.briefsViewMode = "swipe";
        renderDesk();
      });
      document.getElementById("btn-briefs-mode-list").addEventListener("click", () => {
        state.briefsViewMode = "list";
        renderDesk();
      });
      document.getElementById("btn-auto-ab-creator").addEventListener("click", () => {
        openAutoAbModal();
      });
      document.getElementById("btn-export-creative").addEventListener("click", async () => {
        try {
          state.lastCreativeExport = await api("/api/briefs/export", {
            method: "POST",
            body: JSON.stringify({ version: "0.5" }),
          });
          setStatus(`Exported ${state.lastCreativeExport.pairs_exported} A/B + ${state.lastCreativeExport.direct_dpo_pairs || 0} direct DPO pairs -> ${state.lastCreativeExport.out_dir}`);
          renderDesk();
        } catch (err) {
          setStatus(err.message, true);
        }
      });
    };

    if (state.briefsViewMode === "swipe") {
      body.innerHTML = exportBar + `<div id="desk-brief-swipe-root"></div>`;
      bindTopBriefButtons();
      renderSwipeCardDeck(document.getElementById("desk-brief-swipe-root"), () => renderDesk());
      return;
    }

    const cards = state.briefs.length
      ? state.briefs
          .map((b) => {
            const isGraded = b.status === "graded";
            const badgeCls =
              b.verdict === "winner"
                ? "badge-resolved"
                : b.verdict === "flop"
                ? "stage-echo_chamber"
                : "badge-pending";
            const swipeTag = b.swipe_direction === "right" ? "♥ SWIPED RIGHT" : b.swipe_direction === "left" ? "✕ SWIPED LEFT" : `POSTED · ${(b.verdict || "").toUpperCase()}`;
            const badgeTxt = isGraded ? swipeTag : "DRAFT BRIEF";
            const tagsHtml = (b.feedback_tags || []).length
              ? `<div style="display:flex;gap:4px;flex-wrap:wrap;margin-top:4px">${b.feedback_tags.map((t) => `<span class="pill" style="font-size:9.5px">${esc(t)}</span>`).join("")}</div>`
              : "";
            const revHtml = b.revised_caption
              ? `<div style="font-size:11px;color:#34d399;margin-top:3px"><b>✏ Human Rewrite:</b> ${esc(b.revised_caption)}</div>`
              : "";
            const statsLine = isGraded
              ? `<div style="font-family:monospace;font-size:11px;color:#22d3ee;margin-top:4px">
                   48h: ${b.views_48h != null ? b.views_48h.toLocaleString() + " views" : "--"}
                   ${b.breakout_ratio != null ? ` (${b.breakout_ratio}x subs)` : ""}
                   ${b.share_to_like_pct != null ? ` · ${b.share_to_like_pct}% share/like` : ""}
                   ${b.account_handle ? ` · ${esc(b.account_handle)}` : ""}
                 </div>
                 ${tagsHtml}
                 ${revHtml}
                 <div style="color:#94a3b8;font-size:11.5px;margin-top:3px">${esc(b.outcome_notes)}</div>`
              : `<div style="margin-top:6px;display:flex;justify-content:flex-end">
                   <button type="button" class="btn-action green" data-grade-brief="${b.id}">Log 48h Post Outcome</button>
                 </div>`;
            return `
              <div class="pred-card">
                <div class="pred-head">
                  <span><b style="color:#f59e0b">${esc(b.ticker)}</b> · ${esc(b.target_platform)} · <span style="color:#8b9bb0">${esc(b.model_used)}</span></span>
                  <span class="pill ${badgeCls}">${badgeTxt}</span>
                </div>
                <div style="font-weight:600;margin-bottom:3px">${esc(b.on_screen_text)}</div>
                <div style="font-size:11.5px;color:#cbd5e1"><b>2s Hook:</b> ${esc(b.hook_2s)}</div>
                <div style="font-size:11.5px;color:#94a3b8;margin-top:2px"><b>Caption:</b> ${esc(b.caption)}</div>
                ${statsLine}
              </div>
            `;
          })
          .join("")
      : `<div style="color:#8b9bb0">No Creative Briefs yet. Click <b>Brief</b> on any signal in <b>WIRE</b> to generate a hook, on-screen text, caption, and edit beats.</div>`;
    body.innerHTML = exportBar + cards;
    bindTopBriefButtons();
    body.querySelectorAll("[data-grade-brief]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const brief = state.briefs.find((x) => x.id === Number(btn.dataset.gradeBrief));
        if (brief) openGradeBriefModal(brief);
      });
    });
    return;
  }

  if (state.activeTab === "MKTS") {
    const fmtUsd = (v) => {
      const n = Number(v || 0);
      if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
      if (n >= 1_000) return `$${Math.round(n / 1_000)}K`;
      return `$${Math.round(n)}`;
    };
    const fmtEnd = (iso) => {
      if (!iso) return "";
      const d = new Date(iso);
      return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    };
    const sectorChips = ["ALL", "SPORTS", "DEALS", "POP", "MUSIC", "FILM_TV", "GAMING"].map((sec) => {
      const active = state.marketsSector === sec;
      return `<button type="button" class="btn-action ${active ? "amber" : ""}" data-mkts-sector="${sec}" style="font-size:10px;padding:2px 7px">${sec === "ALL" ? "ALL IP" : sec}</button>`;
    }).join("");
    const sourceBtns = [
      ["all", "All"],
      ["polymarket", "Polymarket"],
      ["kalshi", "Kalshi"],
    ].map(([val, lbl]) => `<button type="button" class="btn-action ${state.marketsSource === val ? "cyan" : ""}" data-mkts-src="${val}" style="font-size:10px;padding:2px 7px">${lbl}</button>`).join("");

    const controls = `
      <div style="font-size:11px;color:#94a3b8;margin-bottom:7px;line-height:1.4">
        Live real-money odds from <b style="color:#38bdf8">Polymarket</b> &amp; <b style="color:#34d399">Kalshi</b> (settled 99%+ markets hidden). Click <b>Freeze t₀</b> to lock odds into <b>WIRE</b> &amp; compare against social velocity.
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:6px;margin-bottom:6px;flex-wrap:wrap">
        <div style="display:flex;gap:4px;flex-wrap:wrap">${sourceBtns}</div>
        <div style="display:flex;gap:5px;align-items:center">
          <input id="mkts-query" value="${esc(state.marketsQuery)}" placeholder="Search (e.g. GTA, Oscar, NBA)..." style="background:#070a0f;border:1px solid #2b384b;color:#e6edf5;padding:3px 7px;border-radius:3px;font-size:11px;width:165px" />
          <button type="button" class="btn-action cyan" id="btn-refresh-mkts" style="font-size:10.5px;padding:3px 8px">Refresh</button>
        </div>
      </div>
      <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center;margin-bottom:8px">
        ${sectorChips}
        <label style="font-family:monospace;font-size:10px;color:#94a3b8;display:flex;align-items:center;gap:4px;margin-left:auto">
          <input type="checkbox" id="mkts-ip-only" ${state.marketsIpOnly ? "checked" : ""} /> IP/Culture only
        </label>
      </div>
    `;
    const listHtml = state.markets.length
      ? state.markets
          .map((m, idx) => {
            const yesVal = m.yes_pct != null ? Number(m.yes_pct) : null;
            const noVal = yesVal != null ? Math.max(0, Math.round((100 - yesVal) * 10) / 10) : null;
            const barW = yesVal != null ? Math.max(2, Math.min(100, yesVal)) : 0;
            const srcColor = m.source === "Polymarket" ? "#38bdf8" : "#34d399";
            const endTxt = fmtEnd(m.end_date);
            return `
              <div class="pred-card" style="padding:8px 10px">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
                  <div style="flex:1;min-width:0">
                    <div style="font-family:monospace;font-size:10px;color:#94a3b8;margin-bottom:3px">
                      <b style="color:${srcColor}">${esc(m.source.toUpperCase())}</b> · <span class="pill" style="font-size:9.5px">${esc(m.sector)}</span> · 24h Vol <b style="color:#e2e8f0">${fmtUsd(m.volume_24h)}</b>${endTxt ? ` · Ends ${endTxt}` : ""}
                    </div>
                    <div style="font-weight:600;font-size:12.5px;color:#f1f5f9;line-height:1.3">${esc(m.title)}</div>
                  </div>
                  <div style="text-align:right;shrink:0;font-family:monospace">
                    <div style="font-size:15px;font-weight:800;color:${yesVal != null && yesVal >= 50 ? "#34d399" : "#f59e0b"}">${yesVal != null ? `${yesVal}%` : "n/a"}</div>
                    <div style="font-size:9.5px;color:#64748b">${noVal != null ? `NO ${noVal}%` : "YES ODDS"}</div>
                  </div>
                </div>
                <div style="width:100%;height:6px;background:#1e293b;border-radius:99px;overflow:hidden;margin:7px 0">
                  <div style="width:${barW}%;height:100%;background:${srcColor}"></div>
                </div>
                <div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
                  <a href="${esc(m.url)}" target="_blank" rel="noopener" style="font-family:monospace;font-size:10.5px;color:#60a5fa;text-decoration:none">View on ${esc(m.source)} ↗</a>
                  <button type="button" class="btn-action amber" data-freeze-market="${idx}" style="font-size:10.5px;padding:3px 8px">Freeze t₀ Signal</button>
                </div>
              </div>
            `;
          })
          .join("")
      : `<div style="color:#8b9bb0;font-size:12px;padding:10px;background:#090f19;border:1px solid #1e293b;border-radius:4px">${state.marketsLoaded ? "No active live-odds markets match this filter. Try clicking <b>ALL IP</b> or unchecking <b>IP/Culture only</b>." : "Loading live Polymarket & Kalshi odds..."}</div>`;

    body.innerHTML = controls + listHtml;
    const runFetch = async () => {
      state.marketsQuery = document.getElementById("mkts-query")?.value.trim() || "";
      state.marketsIpOnly = document.getElementById("mkts-ip-only")?.checked ?? true;
      const btn = document.getElementById("btn-refresh-mkts");
      if (btn) { btn.disabled = true; btn.textContent = "Loading..."; }
      try {
        const qs = new URLSearchParams({
          source: state.marketsSource,
          sector: state.marketsSector,
          q: state.marketsQuery,
          ip_only: state.marketsIpOnly ? "1" : "0",
          live_only: "1",
          limit: "24",
        });
        const res = await api(`/api/markets?${qs.toString()}`);
        state.markets = res.markets || [];
        state.marketsLoaded = true;
        setStatus(`Loaded ${state.markets.length} live-odds markets (${state.marketsSource.toUpperCase()} · ${state.marketsSector})`);
        renderDesk();
      } catch (err) {
        setStatus(err.message, true);
        if (btn) { btn.disabled = false; btn.textContent = "Refresh"; }
      }
    };
    document.getElementById("btn-refresh-mkts").addEventListener("click", runFetch);
    document.getElementById("mkts-ip-only").addEventListener("change", runFetch);
    document.getElementById("mkts-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") runFetch();
    });
    body.querySelectorAll("[data-mkts-src]").forEach((btn) => {
      btn.addEventListener("click", () => { state.marketsSource = btn.dataset.mktsSrc; runFetch(); });
    });
    body.querySelectorAll("[data-mkts-sector]").forEach((btn) => {
      btn.addEventListener("click", () => { state.marketsSector = btn.dataset.mktsSector; runFetch(); });
    });
    body.querySelectorAll("[data-freeze-market]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const m = state.markets[Number(btn.dataset.freezeMarket)];
        if (!m) return;
        btn.disabled = true;
        btn.textContent = "Freezing...";
        try {
          const res = await api("/api/ingest/market", {
            method: "POST",
            body: JSON.stringify({ market: m }),
          });
          setStatus(`Froze ${m.source} t₀ signal (${res.signal.ticker}) in WIRE & IP Graph!`);
          await loadBootstrap();
        } catch (err) {
          btn.disabled = false;
          btn.textContent = "Freeze t₀ Signal";
          setStatus(err.message, true);
        }
      });
    });
    if (!state.marketsLoaded) {
      state.marketsLoaded = true;
      runFetch();
    }
    return;
  }

  if (state.activeTab === "MAP") {
    const US_GRID = [
      ["AK",0,0],["ME",10,0],
      ["VT",9,1],["NH",10,1],
      ["WA",0,2],["ID",1,2],["MT",2,2],["ND",3,2],["MN",4,2],["WI",5,2],["MI",6,2],["NY",8,2],["MA",9,2],["RI",10,2],
      ["OR",0,3],["NV",1,3],["WY",2,3],["SD",3,3],["IA",4,3],["IL",5,3],["IN",6,3],["OH",7,3],["PA",8,3],["NJ",9,3],["CT",10,3],
      ["CA",0,4],["UT",1,4],["CO",2,4],["NE",3,4],["MO",4,4],["KY",5,4],["WV",6,4],["VA",7,4],["MD",8,4],["DE",9,4],
      ["AZ",1,5],["NM",2,5],["KS",3,5],["AR",4,5],["TN",5,5],["NC",6,5],["SC",7,5],["DC",8,5],
      ["OK",3,6],["LA",4,6],["MS",5,6],["AL",6,6],["GA",7,6],
      ["HI",0,7],["TX",3,7],["FL",8,7]
    ];
    const md = state.mapData;
    const clusters = md?.clusters || [];
    const activeCluster = clusters[state.mapSelectedClusterIdx] || null;
    const activeTraffic = activeCluster ? activeCluster.state_traffic || {} : (md?.state_scores || {});
    const maxVal = Math.max(100, ...Object.values(activeTraffic).map(Number));
    const originSt = activeCluster?.origin_state || null;

    const buildMapSvg = (maxH = 225) => {
      const tiles = US_GRID.map(([code, col, row]) => {
        const x = col * 42 + 4;
        const y = row * 32 + 4;
        const val = Number(activeTraffic[code] || 0);
        const isOrigin = originSt && code === originSt;
        const isSelected = state.mapSelectedState === code;
        let fill = "#0c1320";
        let stroke = "#1e293b";
        let textCol = "#475569";
        if (val > 0) {
          const ratio = val / maxVal;
          if (isOrigin) {
            fill = "#f59e0b";
            stroke = "#fef08a";
            textCol = "#090d16";
          } else if (ratio >= 0.55) {
            fill = "#0ea5e9";
            stroke = "#7dd3fc";
            textCol = "#04111d";
          } else {
            fill = "#164e63";
            stroke = "#22d3ee";
            textCol = "#e0f2fe";
          }
        }
        if (isSelected) stroke = "#fb7185";
        const tip = val > 0 ? `US-${code}: ${val.toLocaleString()}+ searches (click to inspect)` : `US-${code}: click to see local trends`;
        return `
          <g data-map-state="${code}" style="cursor:pointer">
            <title>${esc(tip)}</title>
            <rect x="${x}" y="${y}" width="38" height="28" rx="4" fill="${fill}" stroke="${stroke}" stroke-width="${isSelected || isOrigin ? 2.2 : 1}"></rect>
            <text x="${x + 19}" y="${y + 17}" text-anchor="middle" fill="${textCol}" font-family="monospace" font-size="10.5" font-weight="700">${code}</text>
          </g>
        `;
      }).join("");
      return `<svg viewBox="0 0 470 264" style="width:100%;max-height:${maxH}px;display:block">${tiles}</svg>`;
    };

    const clusterCards = clusters.slice(0, 6).map((c, idx) => {
      const isAct = idx === state.mapSelectedClusterIdx;
      const stageColor = c.state_count >= 12 ? "#f59e0b" : c.state_count >= 4 ? "#22d3ee" : "#94a3b8";
      return `
        <button type="button" data-map-cluster="${idx}" style="text-align:left;padding:6px 8px;border-radius:4px;cursor:pointer;background:${isAct ? "#132238" : "#0a101b"};border:1px solid ${isAct ? "#f59e0b" : "#1e293b"};color:#e2e8f0">
          <div style="font-size:11px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(c.topic)}</div>
          <div style="font-family:monospace;font-size:9.5px;color:${stageColor};margin-top:2px">${c.state_count} states · Peak ${esc(c.origin_state)} · ${c.total_traffic.toLocaleString()}+</div>
        </button>
      `;
    }).join("");

    const selectedStateItems = state.mapSelectedState && md?.by_state?.[state.mapSelectedState]
      ? md.by_state[state.mapSelectedState].slice(0, 6).map((it) => `<li><b>${esc(it.title)}</b> <span style="color:#22d3ee">(${esc(it.traffic_label)})</span></li>`).join("")
      : "";

    body.innerHTML = `
      <div style="font-size:11px;color:#94a3b8;margin-bottom:7px;line-height:1.4">
        Scans all <b style="color:#e2e8f0">50 US states + DC</b> live. Pick a trending cluster below to see where it ignited (<b style="color:#f59e0b">Amber = Peak Hub</b>) and where it spread (<b style="color:#38bdf8">Cyan</b>), or click any state tile.
      </div>
      <div style="display:flex;justify-content:space-between;align-items:center;gap:5px;margin-bottom:7px;flex-wrap:wrap">
        <div style="display:flex;gap:5px;align-items:center">
          <input id="map-query" value="${esc(state.mapQuery)}" placeholder="Search topic (e.g. NFL, NBA)..." style="background:#070a0f;border:1px solid #2b384b;color:#e6edf5;padding:3px 7px;border-radius:3px;font-size:11px;width:165px" />
          <label style="font-family:monospace;font-size:10px;color:#94a3b8;display:flex;align-items:center;gap:4px">
            <input type="checkbox" id="map-hide-noise" ${state.mapHideNoise ? "checked" : ""} /> Hide utility noise
          </label>
        </div>
        <div style="display:flex;gap:5px">
          <button type="button" class="btn-action" id="btn-expand-map" style="font-size:10.5px;padding:3px 7px">Expand Map ⤢</button>
          <button type="button" class="btn-action cyan" id="btn-refresh-map" style="font-size:10.5px;padding:3px 7px">Rescan 50 States</button>
        </div>
      </div>
      ${clusters.length ? `<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(145px,1fr));gap:5px;margin-bottom:8px">${clusterCards}</div>` : ""}
      ${activeCluster ? `
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;padding:6px 8px;background:#090f19;border:1px solid #1e293b;border-radius:4px;margin-bottom:7px;flex-wrap:wrap">
          <span style="font-family:monospace;font-size:11px">
            <b style="color:#f59e0b">${esc(activeCluster.topic)}</b> ·
            <span style="color:#22d3ee">${activeCluster.state_count} states</span> ·
            Peak Hub: <b style="color:#fbbf24">${esc(activeCluster.origin_state)}</b>
          </span>
          <button type="button" class="btn-action amber" id="btn-freeze-map-cluster" style="font-size:10.5px;padding:3px 8px">Freeze t₀ Signal</button>
        </div>
      ` : ""}
      <div style="background:#070b12;border:1px solid #1e293b;border-radius:5px;padding:6px;overflow-x:auto">
        ${buildMapSvg(225)}
        <div style="display:flex;justify-content:space-between;gap:10px;font-family:monospace;font-size:10px;color:#8b9bb0;margin-top:4px;padding:0 4px;flex-wrap:wrap">
          <span><span style="color:#f59e0b">■</span> Peak/Origin Hub &nbsp; <span style="color:#0ea5e9">■</span> High Spread &nbsp; <span style="color:#164e63">■</span> Active</span>
          <span>${md ? `${md.states_loaded} states loaded` : "Scanning..."}</span>
        </div>
      </div>
      ${state.mapSelectedState ? `
        <div class="pred-card" style="margin-top:8px">
          <div class="pred-head">
            <span><b style="color:#fb7185">US-${esc(state.mapSelectedState)}</b> · LIVE BREAKING TRENDS</span>
            <button type="button" class="btn-action" id="btn-clear-map-state" style="padding:2px 6px;font-size:10px">Close</button>
          </div>
          <ul style="margin:4px 0 0 16px;padding:0;font-size:11.5px;color:#cbd5e1">${selectedStateItems || "<li>No trends loaded for this state.</li>"}</ul>
        </div>
      ` : ""}
    `;

    const fetchMap = async (force = false) => {
      state.mapQuery = document.getElementById("map-query")?.value.trim() || "";
      state.mapHideNoise = document.getElementById("map-hide-noise")?.checked ?? true;
      const btn = document.getElementById("btn-refresh-map");
      if (btn) { btn.disabled = true; btn.textContent = "Scanning..."; }
      try {
        const qs = new URLSearchParams({
          q: state.mapQuery,
          refresh: force ? "1" : "0",
          hide_noise: state.mapHideNoise ? "1" : "0",
        });
        state.mapData = await api(`/api/contagion-map?${qs.toString()}`);
        state.mapLoaded = true;
        state.mapSelectedClusterIdx = 0;
        setStatus(`US Contagion Map scanned ${state.mapData.states_loaded} states (${state.mapData.clusters.length} filtered clusters)`);
        renderDesk();
      } catch (err) {
        setStatus(err.message, true);
        if (btn) { btn.disabled = false; btn.textContent = "Rescan 50 States"; }
      }
    };
    document.getElementById("btn-refresh-map").addEventListener("click", () => fetchMap(true));
    document.getElementById("map-hide-noise").addEventListener("change", () => fetchMap(false));
    document.getElementById("map-query").addEventListener("keydown", (e) => {
      if (e.key === "Enter") fetchMap(false);
    });
    document.getElementById("btn-expand-map").addEventListener("click", () => {
      openModal(
        `US CULTURAL CONTAGION MAP // ${activeCluster ? activeCluster.topic : "ALL ACTIVE STATES"}`,
        `
        <div style="margin-bottom:8px;font-family:monospace;font-size:11px;color:#94a3b8">
          ${activeCluster ? `<b style="color:#f59e0b">${esc(activeCluster.topic)}</b> · ${activeCluster.state_count} active states · Peak Hub: <b style="color:#fbbf24">${esc(activeCluster.origin_state)}</b> · Combined Traffic: <b>${activeCluster.total_traffic.toLocaleString()}+</b>` : "Showing live US state search intensity."}
        </div>
        <div style="background:#070b12;border:1px solid #1e293b;border-radius:6px;padding:12px">
          ${buildMapSvg(460)}
        </div>
        <div id="modal-state-detail" style="margin-top:10px;font-size:12px;color:#94a3b8">Click any state tile above to inspect its live Top 6 breaking trends.</div>
        `
      );
      document.querySelectorAll("#modal-body [data-map-state]").forEach((el) => {
        el.addEventListener("click", () => {
          const code = el.dataset.mapState;
          const items = (md?.by_state?.[code] || []).slice(0, 6);
          const box = document.getElementById("modal-state-detail");
          if (box) {
            box.innerHTML = `<b style="color:#fb7185">US-${esc(code)} Live Trends:</b> ` + (items.length ? items.map((x) => `${esc(x.title)} <span style="color:#22d3ee">(${esc(x.traffic_label)})</span>`).join(" · ") : "No items.");
          }
        });
      });
    });
    body.querySelectorAll("[data-map-cluster]").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.mapSelectedClusterIdx = Number(btn.dataset.mapCluster);
        renderDesk();
      });
    });
    body.querySelectorAll("[data-map-state]").forEach((el) => {
      el.addEventListener("click", () => {
        state.mapSelectedState = el.dataset.mapState;
        renderDesk();
      });
    });
    const clrBtn = document.getElementById("btn-clear-map-state");
    if (clrBtn) clrBtn.addEventListener("click", () => { state.mapSelectedState = null; renderDesk(); });
    const frzBtn = document.getElementById("btn-freeze-map-cluster");
    if (frzBtn && activeCluster) {
      frzBtn.addEventListener("click", async () => {
        frzBtn.disabled = true;
        frzBtn.textContent = "Freezing...";
        try {
          const res = await api("/api/ingest/contagion-map", {
            method: "POST",
            body: JSON.stringify({ cluster: activeCluster }),
          });
          setStatus(`Froze US Contagion Map t₀ signal (${res.signal.ticker} · ${activeCluster.state_count} states)!`);
          await loadBootstrap();
        } catch (err) {
          frzBtn.disabled = false;
          frzBtn.textContent = "Freeze t₀ Signal";
          setStatus(err.message, true);
        }
      });
    }
    if (!state.mapLoaded) {
      state.mapLoaded = true;
      fetchMap(false);
    }
    return;
  }

  if (state.activeTab === "EXPORT") {
    const defaultDir = state.config?.default_export_dir || "exports/ipx-eval";
    const resolvedCount = state.stats?.resolved_predictions ?? 0;
    const preview = state.lastExport?.preview_jsonl || "Click 'Export Resolved Cases' to generate schema-validated IPX-Eval JSONL.";
    const filesHtml = (state.lastExport?.files || [])
      .map((f) => `<div style="font-family:monospace;font-size:11px;color:#34d399">✓ ${esc(f.category)}.jsonl (${f.count} cases) → ${esc(f.path)}</div>`)
      .join("");

    body.innerHTML = `
      <div class="export-box">
        <div style="color:#cbd5e1;line-height:1.45">
          Exports all <b>${resolvedCount}</b> resolved predictions using their immutable <b>t₀</b> <code>signal_snapshot</code> (zero future leakage) validated against <code>eval_case.schema.json</code>.
        </div>
        <div class="form-grid">
          <div class="form-row">
            <label>EXPORT DIRECTORY</label>
            <input id="export-dir-input" value="${esc(state.lastExport?.out_dir || defaultDir)}" />
          </div>
          <div class="form-row">
            <label>DATASET VERSION</label>
            <input id="export-ver-input" value="${esc(state.lastExport?.version || "0.4")}" />
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn-action amber" id="btn-run-export">Export Resolved Cases to JSONL</button>
          <button type="button" class="btn-action cyan" id="btn-set-ipxeval-path">Target IPX-Eval/datasets/v0.4-terminal</button>
        </div>
        ${filesHtml}
        <div class="code-preview">${esc(preview)}</div>
      </div>
    `;

    document.getElementById("btn-set-ipxeval-path").addEventListener("click", () => {
      document.getElementById("export-dir-input").value = "/Users/vieth/Documents/IPX/IPX-Eval/datasets/v0.4-terminal";
    });
    document.getElementById("btn-run-export").addEventListener("click", async () => {
      try {
        const out_dir = document.getElementById("export-dir-input").value.trim();
        const version = document.getElementById("export-ver-input").value.trim() || "0.4";
        state.lastExport = await api("/api/export", {
          method: "POST",
          body: JSON.stringify({ out_dir, version }),
        });
        setStatus(`Exported ${state.lastExport.total_exported} schema-valid IPX-Eval cases -> ${state.lastExport.out_dir}`);
        renderDesk();
      } catch (err) {
        setStatus(err.message, true);
      }
    });
  }
}

function renderPredictionCardHtml(p) {
  const isRes = p.status === "resolved";
  const badgeCls = isRes ? "badge-resolved" : "badge-pending";
  const statusTxt = isRes ? `RESOLVED (${p.outcome.prediction_correct ? "HIT" : "MISS"})` : p.overdue ? "PENDING · DUE NOW" : "PENDING";
  const gtLine = isRes
    ? `<div style="color:#34d399;font-family:monospace;font-size:11px;margin-top:4px">GT: <b>${esc(p.outcome.label)}</b> · ${esc(p.outcome.rationale)}</div>`
    : `<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px">
         <span style="font-family:monospace;font-size:10.5px;color:#8b9bb0">Window: ${p.outcome_window_hours ?? "N/A"}h · Due: ${esc((p.due_at || "N/A").slice(0, 16).replace("T", " "))}</span>
         <button type="button" class="btn-action green" data-resolve-pred="${p.id}">Resolve 48-72h Outcome</button>
       </div>`;
  const aiLine = p.ai_prediction
    ? `<div style="font-family:monospace;font-size:11px;color:#a78bfa;margin-top:2px">
         AI (${esc(p.ai_prediction.model || "model")}): <b>${esc(p.ai_prediction.label)}</b> (${Math.round((p.ai_prediction.confidence || 0) * 100)}%)
         ${p.ai_prediction.correct === true ? "· <span style='color:#34d399'>AI HIT</span>" : p.ai_prediction.correct === false ? "· <span style='color:#fb7185'>AI MISS</span>" : ""}
       </div>`
    : "";
  return `
    <div class="pred-card">
      <div class="pred-head">
        <span><b style="color:#22d3ee">${esc(p.case_code)}</b> · <b style="color:#f59e0b">${esc(p.ticker)}</b> · ${esc(p.category)}</span>
        <span class="pill ${badgeCls}">${statusTxt}</span>
      </div>
      <div style="font-weight:600;margin-bottom:3px">${esc(p.title)}</div>
      <div style="font-family:monospace;font-size:11px;color:#94a3b8">Human: <b>${esc(p.predicted_label)}</b> (${Math.round(p.confidence * 100)}%)</div>
      ${aiLine}
      ${gtLine}
    </div>
  `;
}

function wireResolveButtons(container) {
  container.querySelectorAll("[data-resolve-pred]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const pred = state.predictions.find((x) => x.id === Number(btn.dataset.resolvePred));
      if (pred) openResolveModal(pred);
    });
  });
}

/* ---------------- Modals ---------------- */
function openModal(title, html) {
  document.getElementById("modal-title").textContent = title;
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal-backdrop").classList.remove("hidden");
}
function closeModal() {
  document.getElementById("modal-backdrop").classList.add("hidden");
}

function openPasteUrlModal() {
  const sectors = (state.config?.sectors || []).map((s) => `<option value="${s}">${s}</option>`).join("");
  openModal(
    "PASTE URL — AUTO-INGEST t₀ SIGNAL",
    `
    <form id="form-paste-url">
      <div style="color:#94a3b8;font-size:12px;margin-bottom:10px">
        Paste any <b>YouTube / Shorts, TikTok, X, Instagram, or News URL</b>. IPX Terminal auto-extracts title, creator, description, and public view counts via oEmbed + OpenGraph.
      </div>
      <div class="form-grid">
        <div class="form-row full"><label>POST OR ARTICLE URL</label><input name="url" type="url" placeholder="https://www.youtube.com/shorts/... or https://www.tiktok.com/..." required /></div>
        <div class="form-row"><label>TICKER</label><input name="ticker" placeholder="e.g. FAOUZ.UN or NVDA.IP" required /></div>
        <div class="form-row"><label>SECTOR</label><select name="sector">${sectors}</select></div>
        <div class="form-row"><label>ENTITY NAME (OPTIONAL)</label><input name="entity_name" placeholder="Auto-filled if blank" /></div>
        <div class="form-row"><label>RIGHTS HOLDER (OPTIONAL)</label><input name="owner_holder" placeholder="e.g. Warner Music / Independent" /></div>
        <div class="form-row full"><label>ANALYST NOTE (OPTIONAL)</label><input name="notes" placeholder="e.g. 38 independent edit accounts using this sound in 6h" /></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action green">Auto-Ingest t₀ Signal</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-paste-url").addEventListener("submit", async (e) => {
    e.preventDefault();
    setStatus("Auto-ingesting URL metadata...");
    try {
      const res = await api("/api/ingest/url", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(e.target).entries())),
      });
      closeModal();
      state.activeTicker = res.signal.ticker;
      await loadBootstrap(true);
      setStatus(`Auto-ingested #${res.signal.id} [${res.signal.ticker}] -> ${res.signal.title}`);
    } catch (err) {
      setStatus(`URL ingest error: ${err.message}`, true);
    }
  });
}

function openAutoAbModal() {
  openModal(
    "1-CLICK CREATOR AUTO-PAIRER (SCRAPECREATORS → IPX-EVAL v0.5-creative)",
    `
    <form id="form-auto-ab">
      <div style="font-size:11.5px;color:#94a3b8;margin-bottom:10px">
        Enter any creator handle. ScrapeCreators pulls their recent posts, pairs their top breakout winners vs. bottom flops (50/50 balanced, metrics stripped), and saves directly into <code>IPX-Eval/datasets/v0.5-creative/</code>.
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label>PLATFORM</label>
          <select name="platform">
            <option>TikTok</option>
            <option>YouTube Shorts</option>
            <option>Instagram Reels</option>
            <option>X</option>
          </select>
        </div>
        <div class="form-row">
          <label>CREATOR HANDLE</label>
          <input name="handle" required placeholder="@handle (without URL)" />
        </div>
        <div class="form-row">
          <label>SECTOR</label>
          <select name="sector">
            <option>CREATORS</option><option>MUSIC</option><option>POP</option><option>FILM_TV</option><option>GAMING</option><option>SPORTS</option><option>DEALS</option>
          </select>
        </div>
        <div class="form-row">
          <label>MAX BLIND A/B PAIRS</label>
          <input name="max_pairs" type="number" min="1" max="15" value="5" />
        </div>
      </div>
      <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:12px">
        <button type="button" class="btn-action" id="cancel-auto-ab">Cancel</button>
        <button type="submit" class="btn-action cyan" id="submit-auto-ab">Fetch &amp; Build Blind A/B Pairs</button>
      </div>
    </form>
    `
  );
  document.getElementById("cancel-auto-ab").addEventListener("click", closeModal);
  document.getElementById("form-auto-ab").addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("submit-auto-ab");
    btn.disabled = true;
    btn.textContent = "Fetching via ScrapeCreators...";
    try {
      const fd = new FormData(e.target);
      const res = await api("/api/briefs/auto-ab", {
        method: "POST",
        body: JSON.stringify({
          platform: fd.get("platform"),
          handle: fd.get("handle"),
          sector: fd.get("sector"),
          max_pairs: Number(fd.get("max_pairs") || 5),
        }),
      });
      state.lastAutoAb = res;
      closeModal();
      setStatus(`Built ${res.pairs_created} blind A/B pairs from ${res.posts_fetched} posts for ${res.handle} (${res.platform})`);
      renderDesk();
    } catch (err) {
      btn.disabled = false;
      btn.textContent = "Fetch & Build Blind A/B Pairs";
      setStatus(err.message, true);
    }
  });
}

function openCreateBriefModal(signal) {
  const projOptions = [
    `<option value="NONE"${state.activeProjectId === "NONE" ? " selected" : ""}>None (General Format)</option>`,
    ...(state.projects || []).map(
      (p) =>
        `<option value="${esc(p.id)}"${state.activeProjectId === p.id ? " selected" : ""}>★ ${esc(p.name || p.id)}</option>`
    ),
  ].join("");
  openModal(
    `GENERATE CREATIVE BRIEF // ${signal.ticker} (SIGNAL #${signal.id})`,
    `
    <form id="form-brief">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <label style="font-family:monospace;font-size:10.5px;color:#8b9bb0">PLATFORM</label>
          <select name="target_platform" id="brief-platform" style="background:#070a0f;border:1px solid #2b384b;color:#e6edf5;padding:4px 8px;border-radius:3px">
            <option>TikTok</option><option>Instagram Reels</option><option>YouTube Shorts</option><option>X</option><option>Facebook Reels</option>
          </select>
          <label style="font-family:monospace;font-size:10.5px;color:#22d3ee">CLIENT</label>
          <select name="project_id" id="brief-project" style="background:#070a0f;border:1px solid rgba(34,211,238,0.45);color:#22d3ee;padding:4px 8px;border-radius:3px">
            ${projOptions}
          </select>
        </div>
        <button type="button" class="btn-action cyan" id="btn-gen-brief">Auto-Draft Brief</button>
      </div>
      <div id="brief-matched-track" style="display:none;margin-bottom:8px;padding:6px 10px;border-radius:4px;background:rgba(34,211,238,0.1);border:1px solid rgba(34,211,238,0.35);font-size:11.5px;color:#22d3ee"></div>
      <input type="hidden" name="model_used" id="brief-model" value="manual" />
      <div class="form-grid">
        <div class="form-row full"><label>CULTURAL ANGLE</label><input name="angle" id="brief-angle" required placeholder="What makes this native & shareable right now?" /></div>
        <div class="form-row full"><label>2-SECOND HOOK (VISUAL / AUDIO OPENER)</label><input name="hook_2s" id="brief-hook" required placeholder="First 2 seconds that stops the scroll..." /></div>
        <div class="form-row full"><label>ON-SCREEN TEXT (<=12 WORDS)</label><input name="on_screen_text" id="brief-ost" required placeholder="Exact overlay text..." /></div>
        <div class="form-row full"><label>NATIVE CAPTION</label><textarea name="caption" id="brief-caption" required placeholder="Punchy platform-native caption (no AI slop)..."></textarea></div>
        <div class="form-row full"><label>EDIT BEATS (ONE PER LINE)</label><textarea name="edit_beats" id="brief-beats" placeholder="0-2s: Hook...\n2-6s: Contrast...\n6-10s: Twist..."></textarea></div>
        <div class="form-row full"><label>AUDIO / FORMAT CUE</label><input name="audio_cue" id="brief-audio" placeholder="Trending sound, CapCut template, or deadpan VO..." /></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action amber">Save Creative Brief</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  const runAutoDraft = async () => {
    const plat = document.getElementById("brief-platform").value;
    const projId = document.getElementById("brief-project").value;
    setStatus(`Drafting ${plat} Creative Brief for ${signal.ticker}${projId !== "NONE" ? ` (${projId})` : ""}...`);
    try {
      const res = await api("/api/briefs/generate", {
        method: "POST",
        body: JSON.stringify({ signal_id: signal.id, target_platform: plat, project_id: projId }),
      });
      const d = res.draft;
      document.getElementById("brief-model").value = d.model_used || "template_draft";
      document.getElementById("brief-angle").value = d.angle || "";
      document.getElementById("brief-hook").value = d.hook_2s || "";
      document.getElementById("brief-ost").value = d.on_screen_text || "";
      document.getElementById("brief-caption").value = d.caption || "";
      document.getElementById("brief-beats").value = (d.edit_beats || []).join("\n");
      document.getElementById("brief-audio").value = d.audio_cue || "";
      const matchEl = document.getElementById("brief-matched-track");
      if (d.matched_track || d.production_format || d.asset_recipe) {
        matchEl.style.display = "block";
        const parts = [];
        if (d.matched_track) parts.push(`🎵 <b>Track:</b> ${esc(d.matched_track)}`);
        if (d.production_format) parts.push(`<span class="pill cyan" style="margin-left:4px">${esc(d.production_format)}</span>`);
        const recipeLine = d.asset_recipe ? `<div style="margin-top:4px;color:#cbd5e1">🎬 <b>Faceless Asset Recipe:</b> ${esc(d.asset_recipe)}</div>` : "";
        matchEl.innerHTML = `${parts.join(" ")}${recipeLine}`;
      } else {
        matchEl.style.display = "none";
      }
      setStatus(`Drafted brief (${d.model_used}) — tweak to taste and click Save.`);
    } catch (err) {
      setStatus(err.message, true);
    }
  };
  document.getElementById("btn-gen-brief").addEventListener("click", runAutoDraft);
  document.getElementById("brief-project").addEventListener("change", runAutoDraft);
  runAutoDraft();

  document.getElementById("form-brief").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = { ...Object.fromEntries(new FormData(e.target).entries()), signal_id: signal.id };
    try {
      await api("/api/briefs", { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      state.activeTab = "BRIEFS";
      await loadBootstrap(true);
      setStatus(`Saved Creative Brief for ${signal.ticker}. Post it and log the 48h outcome!`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

function openGradeBriefModal(brief) {
  openModal(
    `LOG 48H POST OUTCOME // ${brief.ticker} (CONTENT FACTORY FEEDBACK)`,
    `
    <form id="form-grade-brief">
      <div style="color:#94a3b8;font-size:12px;margin-bottom:10px"><b>${esc(brief.on_screen_text)}</b></div>
      <div class="form-grid">
        <div class="form-row">
          <label>VERDICT</label>
          <select name="verdict"><option value="winner">winner (outperformed)</option><option value="average">average (baseline)</option><option value="flop">flop (underperformed)</option></select>
        </div>
        <div class="form-row"><label>ACCOUNT HANDLE</label><input name="account_handle" placeholder="e.g. @yourpage" /></div>
        <div class="form-row full"><label>POSTED URL (OPTIONAL)</label><input name="posted_url" placeholder="https://..." /></div>
        <div class="form-row"><label>48H VIEWS</label><input name="views_48h" type="number" placeholder="e.g. 145000" /></div>
        <div class="form-row"><label>ACCOUNT FOLLOWERS</label><input name="follower_baseline" type="number" placeholder="e.g. 12000" /></div>
        <div class="form-row"><label>48H LIKES</label><input name="likes_48h" type="number" placeholder="e.g. 9200" /></div>
        <div class="form-row"><label>48H SHARES</label><input name="shares_48h" type="number" placeholder="e.g. 3100" /></div>
        <div class="form-row full"><label>WHY IT POPPED OR FLOPPED (FOR v0.5-CREATIVE &amp; DPO)</label><textarea name="outcome_notes" required placeholder="e.g. Hook held 62% past 3s and caption sparked 400+ debate comments..."></textarea></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action green">Save Post Outcome</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-grade-brief").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api(`/api/briefs/${brief.id}/grade`, {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(new FormData(e.target).entries())),
      });
      closeModal();
      state.activeTab = "BRIEFS";
      await loadBootstrap(true);
      setStatus(`Graded post outcome for ${brief.ticker}. Ready to export Winner/Flop A/B pairs!`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

function openCaptureSignalModal() {
  const sectors = (state.config?.sectors || []).map((s) => `<option value="${s}">${s}</option>`).join("");
  openModal(
    "CAPTURE t₀ SIGNAL SNAPSHOT",
    `
    <form id="form-capture">
      <div class="form-grid">
        <div class="form-row"><label>TICKER</label><input name="ticker" placeholder="e.g. NVDA.IP or KATT.FMT" required /></div>
        <div class="form-row"><label>SECTOR</label><select name="sector">${sectors}</select></div>
        <div class="form-row"><label>ENTITY NAME (IF NEW)</label><input name="entity_name" placeholder="e.g. Solo Leveling" /></div>
        <div class="form-row"><label>RIGHTS HOLDER</label><input name="owner_holder" placeholder="e.g. Sony / Crunchyroll" /></div>
        <div class="form-row full"><label>SIGNAL TITLE</label><input name="title" placeholder="Short headline of what spiked at t₀" required /></div>
        <div class="form-row full"><label>PLATFORMS (COMMA-SEPARATED)</label><input name="platforms" placeholder="TikTok, X, YouTube Shorts" required /></div>
        <div class="form-row full"><label>t₀ SUMMARY (NO FUTURE LEAKAGE)</label><textarea name="summary" required placeholder="Exact observations available at t₀..."></textarea></div>
        <div class="form-row full"><label>METRICS JSON</label><input name="metrics" value='{"views": 120000, "likes": 8500, "shares": 2400}' /></div>
        <div class="form-row full"><label>VERBATIM SAMPLES (ONE PER LINE)</label><textarea name="samples" placeholder="'Wait what song is this??'"></textarea></div>
        <div class="form-row full"><label>SOURCE URL (OPTIONAL)</label><input name="url" placeholder="https://..." /></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action amber">Save t₀ Signal</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-capture").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      const res = await api("/api/signals", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(fd.entries())),
      });
      closeModal();
      state.activeTicker = res.signal.ticker;
      await loadBootstrap(true);
      setStatus(`Captured signal #${res.signal.id} for ${res.signal.ticker} (CVS=${res.signal.cvs_score})`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

function openGdeltModal() {
  const sectors = (state.config?.sectors || []).map((s) => `<option value="${s}">${s}</option>`).join("");
  openModal(
    "LIVE GDELT DOC 2.0 NEWS SWEEP",
    `
    <form id="form-gdelt">
      <div class="form-grid">
        <div class="form-row"><label>TICKER</label><input name="ticker" value="${esc(state.activeTicker || "NVDA.IP")}" required /></div>
        <div class="form-row"><label>SECTOR</label><select name="sector">${sectors}</select></div>
        <div class="form-row full"><label>GDELT QUERY</label><input name="query" placeholder='e.g. "Jensen Huang" OR "GTA 6"' required /></div>
        <div class="form-row"><label>TIMESPAN</label><input name="timespan" value="24h" /></div>
        <div class="form-row"><label>MAX ARTICLES</label><input name="max_records" type="number" value="12" /></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action cyan">Run Live GDELT Sweep</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-gdelt").addEventListener("submit", async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    setStatus("Running live GDELT DOC 2.0 sweep...");
    try {
      const res = await api("/api/ingest/gdelt", {
        method: "POST",
        body: JSON.stringify(Object.fromEntries(fd.entries())),
      });
      closeModal();
      state.activeTicker = res.signal.ticker;
      await loadBootstrap(true);
      setStatus(`GDELT sweep ingested signal #${res.signal.id} -> ${res.signal.title}`);
    } catch (err) {
      setStatus(`GDELT error: ${err.message}`, true);
    }
  });
}

function openLogPredictionModal(signal) {
  const categories = state.config?.categories || [];
  const labelsMap = state.config?.category_labels || {};
  const defaultQs = state.config?.default_questions || {};
  const initCat = categories[0] || "breakout";

  openModal(
    `LOG PREDICTION // SIGNAL #${signal.id} (${signal.ticker})`,
    `
    <form id="form-log-pred">
      <div class="form-grid">
        <div class="form-row">
          <label>EVAL CATEGORY</label>
          <select name="category" id="log-cat">${categories.map((c) => `<option value="${c}">${c}</option>`).join("")}</select>
        </div>
        <div class="form-row">
          <label>PREDICTED LABEL</label>
          <select name="predicted_label" id="log-label">${(labelsMap[initCat] || []).map((l) => `<option value="${l}">${l}</option>`).join("")}</select>
        </div>
        <div class="form-row"><label>CONFIDENCE (0.0 - 1.0)</label><input name="confidence" type="number" step="0.05" min="0" max="1" value="0.80" /></div>
        <div class="form-row"><label>OUTCOME WINDOW (HOURS)</label><input name="outcome_window_hours" type="number" value="48" /></div>
        <div class="form-row">
          <label>DIFFICULTY</label>
          <select name="difficulty"><option value="easy">easy</option><option value="medium" selected>medium</option><option value="hard">hard</option></select>
        </div>
        <div class="form-row">
          <label>SOURCE TAG</label>
          <select name="source"><option value="ipx_terminal_export" selected>ipx_terminal_export</option><option value="ipx_live_prediction">ipx_live_prediction</option></select>
        </div>
        <div class="form-row full"><label>ANALYTICAL QUESTION</label><textarea name="question" id="log-question">${esc(defaultQs[initCat] || "")}</textarea></div>
        <div class="form-row full"><label>ANALYST NOTES</label><input name="analyst_notes" placeholder="Why you made this call at t₀..." /></div>
      </div>
      <div style="background:#0b1017;border:1px solid #2b384b;border-radius:4px;padding:8px 10px;margin:8px 0">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-family:monospace;font-size:11px;color:#a78bfa">HUMAN vs. AI DESK (OPTIONAL)</span>
          <div style="display:flex;gap:6px;align-items:center">
            <input id="ai-model-input" value="gemini-3.5-flash-lite" style="background:#070a0f;border:1px solid #2b384b;color:#cbd5e1;font-family:monospace;font-size:11px;padding:3px 6px;border-radius:3px;width:165px" />
            <button type="button" class="btn-action help-btn" id="btn-ask-ai">Ask AI at t₀</button>
          </div>
        </div>
        <div id="ai-score-output" style="font-family:monospace;font-size:11px;color:#8b9bb0;margin-top:6px">
          Click <b>Ask AI at t₀</b> to record the model's call alongside yours (uses GEMINI_API_KEY or DGX Spark IPX_AI_BASE_URL).
        </div>
      </div>
      <input type="hidden" name="ai_model" id="hd-ai-model" />
      <input type="hidden" name="ai_predicted_label" id="hd-ai-label" />
      <input type="hidden" name="ai_confidence" id="hd-ai-conf" />
      <input type="hidden" name="ai_reasoning" id="hd-ai-reason" />
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action amber">Freeze t₀ Snapshot &amp; Log</button>
      </div>
    </form>
  `
  );

  document.getElementById("btn-ask-ai").addEventListener("click", async () => {
    const out = document.getElementById("ai-score-output");
    const cat = document.getElementById("log-cat").value;
    const question = document.getElementById("log-question").value;
    const model = document.getElementById("ai-model-input").value.trim() || "gemini-3.5-flash-lite";
    out.textContent = `Querying ${model} on t₀ snapshot...`;
    try {
      const res = await api("/api/ai/score", {
        method: "POST",
        body: JSON.stringify({ signal_id: signal.id, category: cat, question, model }),
      });
      const ai = res.ai;
      document.getElementById("hd-ai-model").value = ai.model;
      document.getElementById("hd-ai-label").value = ai.label;
      document.getElementById("hd-ai-conf").value = ai.confidence;
      document.getElementById("hd-ai-reason").value = ai.reasoning;
      out.innerHTML = `<span style="color:#34d399">✓ ${esc(ai.model)}</span> → <b>${esc(ai.label)}</b> (${Math.round(ai.confidence * 100)}%)<br/><span style="color:#cbd5e1">${esc(ai.reasoning)}</span>`;
    } catch (err) {
      out.innerHTML = `<span style="color:#fb7185">${esc(err.message)}</span>`;
    }
  });

  document.getElementById("log-cat").addEventListener("change", (e) => {
    const cat = e.target.value;
    document.getElementById("log-label").innerHTML = (labelsMap[cat] || [])
      .map((l) => `<option value="${l}">${l}</option>`)
      .join("");
    document.getElementById("log-question").value = defaultQs[cat] || "";
  });
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-log-pred").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = { ...Object.fromEntries(new FormData(e.target).entries()), signal_id: signal.id };
    try {
      const res = await api("/api/predictions", { method: "POST", body: JSON.stringify(payload) });
      closeModal();
      state.activeTab = "LOG";
      await loadBootstrap(true);
      setStatus(`Logged ${res.prediction.case_code} (${res.prediction.predicted_label}) with frozen t₀ snapshot.`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

function openResolveModal(pred) {
  const validLabels = state.config?.category_labels?.[pred.category] || [];
  openModal(
    `RESOLVE 48-72H OUTCOME // ${pred.case_code}`,
    `
    <form id="form-resolve">
      <div style="margin-bottom:10px;color:#94a3b8;font-size:12px">
        <b>${esc(pred.title)}</b><br/>
        Frozen t₀ prediction: <b style="color:#f59e0b">${esc(pred.predicted_label)}</b> (${Math.round(pred.confidence * 100)}%)
      </div>
      <div class="form-grid">
        <div class="form-row">
          <label>VERIFIED GROUND-TRUTH LABEL</label>
          <select name="ground_truth_label">${validLabels.map((l) => `<option value="${l}" ${l === pred.predicted_label ? "selected" : ""}>${l}</option>`).join("")}</select>
        </div>
        <div class="form-row"><label>SECONDARY TAG (OPTIONAL)</label><input name="secondary_label" placeholder="e.g. organic_catalog_revival" /></div>
        <div class="form-row full">
          <label>REQUIRED CONCEPTS (SEMICOLON = GROUPS, COMMA = ALIASES)</label>
          <input name="required_concepts" required placeholder="e.g. 4.8x, subscriber baseline; kalshi, sponsor; nhl, maple leafs" />
        </div>
        <div class="form-row full">
          <label>AUTHORITATIVE RATIONALE (POST-WINDOW VERIFICATION)</label>
          <textarea name="rationale" required placeholder="Explain what actually happened after 48-72h and why this label is ground truth..."></textarea>
        </div>
        <div class="form-row"><label>OUTCOME WINDOW (HOURS)</label><input name="outcome_window_hours" type="number" value="${pred.outcome_window_hours ?? 48}" /></div>
        <div class="form-row"><label>POST-WINDOW METRICS JSON (KEPT OUT OF t₀)</label><input name="outcome_metrics" value="{}" /></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-action" id="cancel-modal">Cancel</button>
        <button type="submit" class="btn-action green">Save Verified Outcome</button>
      </div>
    </form>
  `
  );
  document.getElementById("cancel-modal").addEventListener("click", closeModal);
  document.getElementById("form-resolve").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(e.target).entries());
    try {
      const res = await api(`/api/predictions/${pred.id}/resolve`, {
        method: "POST",
        body: JSON.stringify(payload),
      });
      closeModal();
      state.activeTab = "LOG";
      await loadBootstrap(true);
      setStatus(`Resolved ${res.prediction.case_code} -> ${res.prediction.outcome.label}. Ready to export to IPX-Eval!`);
    } catch (err) {
      setStatus(err.message, true);
    }
  });
}

/* ---------------- Interactive HELP / Operator Key ---------------- */
function openHelpModal() {
  openModal(
    "IPX TERMINAL // OPERATOR'S KEY & BLOOMBERG GUIDE",
    `
    <div class="help-section">
      <h4>1. HOW THE COMMAND BAR WORKS (&lt;TICKER&gt; &lt;FUNCTION&gt; &lt;GO&gt;)</h4>
      <div class="help-card">
        Real Bloomberg terminals work like a sentence: <b>WHO</b> (a ticker or sector) + <b>WHAT VIEW</b> (a 2–4 letter function code) + <b>GO</b> (Enter).
        <div class="sub">Press <b>/</b> anywhere to jump to the command bar, or click any live example below to run it right now:</div>
        <div class="try-row">
          <button type="button" class="try-cmd" data-try-cmd="KATT.FMT GP">KATT.FMT GP</button>
          <button type="button" class="try-cmd" data-try-cmd="NVDA.IP DES">NVDA.IP DES</button>
          <button type="button" class="try-cmd" data-try-cmd="MUSIC TOP">MUSIC TOP</button>
          <button type="button" class="try-cmd" data-try-cmd="ALL">ALL</button>
          <button type="button" class="try-cmd" data-try-cmd="LOG">LOG</button>
          <button type="button" class="try-cmd" data-try-cmd="EXPORT">EXPORT</button>
        </div>
      </div>
    </div>

    <div class="help-section">
      <h4>2. FUNCTION CODES (WHAT THE 4 PANES MEAN)</h4>
      <div class="help-grid">
        <div class="help-card"><b>TOP</b> — Cultural Velocity Movers<div class="sub">Bloomberg's top-news/movers screen. Ranks every Content IP ticker by live momentum (CVS). Click any row to load it into GP &amp; DES.</div></div>
        <div class="help-card"><b>GP</b> — Graph Price (Velocity Chart)<div class="sub">Bloomberg's price chart, adapted for IP. Plots <b>CVS</b> (cyan line) and <b>Contagion Index</b> (amber dashed) across time-stamped t₀ snapshots.</div></div>
        <div class="help-card"><b>WIRE</b> — Live t₀ Signal Tape<div class="sub">Chronological stream of raw observations (TikTok, X, Reels, Shorts, GDELT news) before outcomes are known. Click <b>Log Prediction</b> on any card.</div></div>
        <div class="help-card"><b>DES</b> — Description (IP Profile)<div class="sub">Bloomberg's company tear-sheet. Shows who owns/monetizes the IP (studio, label, creator, brand), asset type, aliases, and linked predictions.</div></div>
        <div class="help-card"><b>LOG</b> — 48–72h Prediction Desk<div class="sub">Tracks open calls frozen at t₀. Once 48–72h passes, click <b>Resolve</b> to record what actually happened in the real world.</div></div>
        <div class="help-card"><b>EXPORT</b> — IPX-Eval Flywheel<div class="sub">Exports resolved outcomes as schema-validated JSONL (with zero future leakage) straight into your <b>IPX-Eval</b> benchmark.</div></div>
      </div>
    </div>

    <div class="help-section">
      <h4>3. SCORES &amp; BADGES (HOVER ANY COLUMN HEADER FOR QUICK HINTS)</h4>
      <div class="help-grid">
        <div class="help-card"><b>CVS (0–100) &amp; Δ</b><div class="sub"><b>Cultural Velocity Score</b>: time-decayed momentum combining views-to-followers breakout ratio, share/save intent, creator breadth, and cross-platform spread. <b>Δ</b> is the change since the prior snapshot.</div></div>
        <div class="help-card"><b>CONTAGION (0–100)</b><div class="sub">Measures whether a spike broke out of one platform/community into multiple platforms, search (Google Trends), or press (GDELT).</div></div>
        <div class="help-card"><b>STAGE BADGES</b><div class="sub"><span class="pill stage-echo_chamber">echo_chamber</span> Trapped in 1 bubble (&lt;38)<br/><span class="pill stage-emerging_contagion">emerging_contagion</span> Jumping platforms (38–67)<br/><span class="pill stage-mainstream_breakout">mainstream_breakout</span> Multi-surface breakout (68+)</div></div>
        <div class="help-card"><b>t₀ SNAPSHOT (ZERO LEAKAGE)</b><div class="sub">The exact facts visible at capture time. When you log a prediction, t₀ is <b>frozen</b> so future 48–72h results never contaminate the benchmark prompt.</div></div>
      </div>
    </div>

    <div class="help-section">
      <h4>4. THE DAILY 4-STEP OPERATOR WORKFLOW</h4>
      <div class="help-card">
        <b>1. Scan TOP &amp; WIRE</b> (or run <b>+ Capture t₀ Signal</b> / <b>GDELT Sweep</b>) →
        <b>2. Inspect GP &amp; DES</b> to separate real breakouts from echo chambers →
        <b>3. Log Prediction</b> to freeze t₀ and start the 48–72h clock →
        <b>4. Resolve &amp; Export</b> to turn real outcomes into live <b>IPX-Eval</b> test cases.
      </div>
    </div>

    <div style="font-family:monospace;font-size:11px;color:#8b9bb0;display:flex;justify-content:space-between">
      <span>Shortcuts: <b>/</b> Command Bar · <b>?</b> Help Key · <b>Esc</b> Close Modal</span>
      <span>Full doc: TERMINAL_GUIDE.md</span>
    </div>
    `
  );

  document.querySelectorAll("[data-try-cmd]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const cmd = btn.dataset.tryCmd;
      closeModal();
      await runCommandText(cmd);
    });
  });
}

async function runCommandText(cmd) {
  const input = document.getElementById("command-input");
  try {
    const res = await api("/api/command", { method: "POST", body: JSON.stringify({ command: cmd }) });
    if (res.action === "error") {
      setStatus(res.message, true);
      return;
    }
    if (res.action === "filter_sector") {
      state.sector = res.sector;
      document.getElementById("top-sector-label").textContent = `SECTOR: ${state.sector}`;
      await loadBootstrap(true);
    } else if (res.action === "select_ticker") {
      await selectTicker(res.ticker, false);
      if (["DES", "LOG", "BRIEFS", "MKTS", "MAP", "EXPORT"].includes(res.function)) {
        state.activeTab = res.function;
        renderDesk();
      }
    } else if (res.action === "focus_function") {
      if (res.function === "HELP") {
        openHelpModal();
      } else if (["DES", "LOG", "BRIEFS", "MKTS", "MAP", "EXPORT"].includes(res.function)) {
        state.activeTab = res.function;
        renderDesk();
      }
    } else if (res.action === "refresh") {
      await loadBootstrap(true);
    }
    setStatus(res.message);
    input.value = "";
  } catch (err) {
    setStatus(err.message, true);
  }
}

/* ---------------- Event Wiring ---------------- */
document.getElementById("command-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const cmd = document.getElementById("command-input").value.trim();
  if (!cmd) return;
  await runCommandText(cmd);
});

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    state.activeTab = btn.dataset.tab;
    renderDesk();
  });
});

document.getElementById("btn-open-url").addEventListener("click", openPasteUrlModal);
document.getElementById("btn-open-capture").addEventListener("click", openCaptureSignalModal);
document.getElementById("btn-open-gdelt").addEventListener("click", openGdeltModal);
document.getElementById("btn-quick-export").addEventListener("click", () => {
  state.activeTab = "EXPORT";
  renderDesk();
});
document.getElementById("btn-open-help").addEventListener("click", openHelpModal);
document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-backdrop").addEventListener("click", (e) => {
  if (e.target.id === "modal-backdrop") closeModal();
});

document.addEventListener("keydown", (e) => {
  const typing = document.activeElement.tagName === "INPUT" || document.activeElement.tagName === "TEXTAREA";
  if (e.key === "/" && !typing) {
    e.preventDefault();
    document.getElementById("command-input").focus();
  }
  if (e.key === "?" && !typing) {
    e.preventDefault();
    openHelpModal();
  }
  if (e.key === "Escape") closeModal();
});

loadBootstrap(false).catch((err) => setStatus(`Failed to load terminal: ${err.message}`, true));
