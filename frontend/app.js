const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let state = {
  journeyId: null,
  selectedOption: null, // {id, source_platform}
  preferredBerth: null,
  jobsCache: [], // last-loaded jobs, for the 1s local countdown ticker
  openConfirmJobId: null,
  openLaunchPadJobId: null,
  launchPadData: null,
};

let jobsRefreshTimer = null;

// ---------- tabs ----------
$$("nav button").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$("nav button").forEach((b) => b.classList.remove("active"));
    $$(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    $("#tab-" + btn.dataset.tab).classList.add("active");

    if (jobsRefreshTimer) { clearInterval(jobsRefreshTimer); jobsRefreshTimer = null; }
    if (btn.dataset.tab === "jobs") {
      loadJobs();
      jobsRefreshTimer = setInterval(loadJobs, 4000);
    }
    if (btn.dataset.tab === "passengers") loadPassengers();
    if (btn.dataset.tab === "audit") loadAudit();
  });
});

// 1s local ticker for countdown text - separate from the 4s network refresh
// so the numbers don't visibly freeze between polls.
setInterval(() => {
  const now = Date.now();
  state.jobsCache.forEach((j) => {
    const el = document.querySelector(`[data-countdown="${j.id}"]`);
    if (!el) return;
    if (j.booking_mode === "immediate" || j.status !== "pending") { el.textContent = "-"; return; }
    const triggerMs = new Date(j.window_open_time_ist).getTime() - j.lead_time_seconds * 1000;
    el.textContent = formatCountdown(triggerMs - now);
  });

  const tokenEl = $("#token-countdown");
  if (tokenEl && tokenEl.dataset.expiresAt) {
    tokenEl.textContent = formatCountdown(new Date(tokenEl.dataset.expiresAt).getTime() - now);
  }

  const lpEl = $("#lp-countdown");
  if (lpEl && lpEl.dataset.window) {
    lpEl.textContent = formatLongCountdown(new Date(lpEl.dataset.window).getTime() - now);
  }
}, 1000);

function formatCountdown(msRemaining) {
  if (msRemaining <= 0) return "any moment now";
  const totalSeconds = Math.floor(msRemaining / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// A Tatkal window is often scheduled a day or more out, where formatCountdown's
// bare minutes ("2346:12") is unreadable. Days/hours until the last hour, then
// hand off to precise m:ss for the part that actually needs second-accuracy.
function formatLongCountdown(msRemaining) {
  if (msRemaining <= 0) return "OPEN NOW";
  const totalSeconds = Math.floor(msRemaining / 1000);
  if (totalSeconds < 3600) return formatCountdown(msRemaining);
  const d = Math.floor(totalSeconds / 86400);
  const h = Math.floor((totalSeconds % 86400) / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  return d > 0 ? `${d}d ${h}h ${m}m` : `${h}h ${m}m`;
}

// Format a Date as the "YYYY-MM-DDTHH:mm" string <input type="datetime-local">
// expects, `minutesFromNow` in the future - used to prefill the schedule
// field so testing doesn't require hand-typing every digit.
function defaultLocalDateTimeValue(minutesFromNow) {
  const d = new Date(Date.now() + minutesFromNow * 60000);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || res.statusText);
  }
  return res.json();
}

// ---------- search flow ----------
$("#parse-btn").addEventListener("click", async () => {
  const text = $("#journey-text").value.trim();
  if (!text) return;
  $("#parse-btn").textContent = "Parsing...";
  try {
    const jr = await api("/api/journey", { method: "POST", body: JSON.stringify({ text }) });
    state.journeyId = jr.id;
    $("#f-origin").value = jr.origin || "";
    $("#f-destination").value = jr.destination || "";
    $("#f-date").value = jr.travel_date || "";
    $("#f-class").value = jr.travel_class || "";
    $("#f-quota").value = jr.quota || "";
    $("#f-passengers").value = jr.passenger_count || 1;
    $("#clarification-note").textContent = jr.needs_clarification
      ? "⚠ " + (jr.clarification_note || "Please check/fill the fields below.")
      : "Parsed - review and confirm below.";
    $("#confirm-card").style.display = "block";
    $("#results-card").style.display = "none";
    $("#schedule-card").style.display = "none";
  } catch (e) {
    alert("Parse failed: " + e.message);
  } finally {
    $("#parse-btn").textContent = "Parse request";
  }
});

$("#search-btn").addEventListener("click", async () => {
  const payload = {
    origin: $("#f-origin").value || null,
    destination: $("#f-destination").value || null,
    travel_date: $("#f-date").value || null,
    travel_class: $("#f-class").value || null,
    quota: $("#f-quota").value || null,
    passenger_count: parseInt($("#f-passengers").value || "1", 10),
    preferred_berth: $("#f-pref-berth").value || null,
  };
  state.preferredBerth = payload.preferred_berth;
  $("#search-btn").textContent = "Searching...";
  $("#results-card").style.display = "block";
  $("#summary-text").textContent = "Searching...";
  $("#results-body").innerHTML = "";
  renderPlatformStatus({});

  const progressTimer = setInterval(async () => {
    try {
      const p = await api(`/api/journey/${state.journeyId}/progress`);
      renderPlatformStatus(p.platform_status);
    } catch (e) { /* ignore transient poll errors */ }
  }, 400);

  try {
    const results = await api(`/api/journey/${state.journeyId}/confirm`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResults(results);
  } catch (e) {
    alert("Search failed: " + e.message);
  } finally {
    clearInterval(progressTimer);
    $("#search-btn").textContent = "Confirm & search";
  }
});

function renderPlatformStatus(platformStatus) {
  const statusBoard = $("#platform-status");
  statusBoard.innerHTML = "";
  const known = ["IRCTC", "ixigo", "ConfirmTkt"];
  known.forEach((platform) => {
    const status = (platformStatus || {})[platform];
    const label = status || "searching...";
    const cls = status === "done" ? "good" : !status ? "warn" : status === "timeout" ? "warn" : "bad";
    statusBoard.innerHTML += `<span class="status-pill">${platform}: <span class="badge ${cls}">${label}</span></span>`;
  });
}

function badgeForAvailability(status) {
  if (status === "AVAILABLE") return `<span class="badge good">${status}</span>`;
  if (status.startsWith("RAC")) return `<span class="badge warn">${status}</span>`;
  if (status.startsWith("WL")) return `<span class="badge bad">${status}</span>`;
  return `<span class="badge neutral">${status}</span>`;
}

const BERTH_LABELS = { LOWER: "L", MIDDLE: "M", UPPER: "U", SIDE_LOWER: "SL", SIDE_UPPER: "SU" };

function formatBerths(availableBerths, preferredBerth) {
  const berths = availableBerths || {};
  return Object.entries(BERTH_LABELS)
    .map(([key, label]) => {
      const count = berths[key] || 0;
      const isPreferred = key === preferredBerth;
      const cls = count === 0 ? "neutral" : isPreferred ? "good" : "neutral";
      return `<span class="badge ${cls}" title="${key}">${label}:${count}</span>`;
    })
    .join(" ");
}

function renderResults(results) {
  $("#results-card").style.display = "block";
  $("#summary-text").textContent = results.summary || "";
  renderPlatformStatus(results.platform_status);

  const body = $("#results-body");
  body.innerHTML = "";
  results.options.forEach((o) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${o.source_platform}</td>
      <td>${o.train_no} ${o.train_name}</td>
      <td>${o.travel_class}</td>
      <td>${o.departure_time}</td>
      <td>${o.arrival_time}</td>
      <td>₹${o.fare.toFixed(0)}</td>
      <td>${badgeForAvailability(o.availability_status)}</td>
      <td>${formatBerths(o.available_berths, state.preferredBerth)}</td>
      <td class="nowrap">
        <button class="primary" data-act="now">Book now</button>
        <button class="secondary" data-act="tatkal">Schedule Tatkal</button>
      </td>
    `;

    // Book now: the common case. No window to wait for, so skip scheduling
    // entirely and go straight to the Launch Pad.
    tr.querySelector('[data-act="now"]').addEventListener("click", async () => {
      try {
        const job = await api("/api/jobs/immediate", {
          method: "POST",
          body: JSON.stringify({
            journey_request_id: state.journeyId,
            train_option_id: o.id,
            target_platform: o.source_platform,
          }),
        });
        goToJobsTab();
        await loadJobs();
        openLaunchPad(job);
      } catch (e) {
        alert("Could not start booking: " + e.message);
      }
    });

    // Schedule Tatkal: only meaningful for a timed quota window.
    tr.querySelector('[data-act="tatkal"]').addEventListener("click", () => {
      state.selectedOption = { id: o.id, source_platform: o.source_platform };
      $("#schedule-card").style.display = "block";
      $("#sched-time").value = suggestedTatkalWindow(o.travel_class);
      $("#schedule-card").scrollIntoView({ behavior: "smooth" });
    });
    body.appendChild(tr);
  });
}

function goToJobsTab() {
  $$("nav button").forEach((b) => b.classList.remove("active"));
  $$(".tab").forEach((t) => t.classList.remove("active"));
  document.querySelector('nav button[data-tab="jobs"]').classList.add("active");
  $("#tab-jobs").classList.add("active");
  if (jobsRefreshTimer) clearInterval(jobsRefreshTimer);
  jobsRefreshTimer = setInterval(loadJobs, 4000);
}

// Tatkal opens the day BEFORE travel: 10:00 IST for AC classes, 11:00 non-AC.
// Prefilling the real instant beats the old "now + 3 minutes" placeholder,
// which was only ever useful for testing and looked like a real suggestion.
function suggestedTatkalWindow(travelClass) {
  const AC = ["1A", "2A", "3A", "CC", "EC", "3E"];
  const dateStr = $("#f-date").value;
  if (!dateStr) return defaultLocalDateTimeValue(3);
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() - 1);
  d.setHours(AC.includes((travelClass || "").toUpperCase()) ? 10 : 11, 0, 0, 0);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

$("#sched-btn").addEventListener("click", async () => {
  if (!state.selectedOption) return;
  const timeVal = $("#sched-time").value;
  if (!timeVal) { alert("Pick a window open time."); return; }
  const payload = {
    journey_request_id: state.journeyId,
    train_option_id: state.selectedOption.id,
    target_platform: state.selectedOption.source_platform,
    window_open_time_ist: new Date(timeVal).toISOString(),
    lead_time_seconds: parseInt($("#sched-lead").value || "120", 10),
  };
  try {
    await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
    alert("Scheduled. Check the 'Scheduled Jobs' tab for status.");
    $("#schedule-card").style.display = "none";
  } catch (e) {
    alert("Schedule failed: " + e.message);
  }
});

// ---------- jobs ----------
$("#refresh-jobs").addEventListener("click", loadJobs);

async function loadJobs() {
  const jobs = await api("/api/jobs");
  state.jobsCache = jobs;
  const body = $("#jobs-body");
  body.innerHTML = "";
  jobs.forEach((j) => {
    const tr = document.createElement("tr");
    const statusCls = { confirmed: "good", staged_and_waiting: "warn", failed: "bad", expired: "bad" }[j.status] || "neutral";
    const immediate = j.booking_mode === "immediate";
    tr.innerHTML = `
      <td>${j.target_platform}</td>
      <td>${immediate ? '<span class="badge neutral">book now</span>' : '<span class="badge warn">Tatkal</span>'}</td>
      <td>${immediate ? '<span class="muted">-</span>' : new Date(j.window_open_time_ist).toLocaleString()}</td>
      <td><span class="badge ${statusCls}">${j.status}</span></td>
      <td class="muted" data-countdown="${j.id}">-</td>
      <td>${j.pnr ? `<span class="badge good">${j.pnr}</span>` : '<span class="muted">-</span>'}</td>
      <td></td>
    `;
    // Launch Pad is offered for every live job, not just staged ones - its
    // whole value is the prep that has to happen BEFORE the window opens.
    if (!["failed", "expired"].includes(j.status)) {
      const lp = document.createElement("button");
      lp.className = "primary";
      lp.textContent = "Launch Pad";
      lp.addEventListener("click", () => openLaunchPad(j));
      tr.lastElementChild.appendChild(lp);
    }
    // "Confirm booking" drives this app's internal mock staging flow, which a
    // book-now job never goes through - it's created already staged. Offering
    // it there just invites a click that appears to confirm a real booking and
    // doesn't.
    if (j.status === "staged_and_waiting" && !immediate) {
      const btn = document.createElement("button");
      btn.className = "secondary";
      btn.textContent = "Confirm booking";
      btn.addEventListener("click", () => openConfirmPanel(j));
      tr.lastElementChild.appendChild(btn);
    }
    body.appendChild(tr);
  });

  // keep the open confirm panel in sync if its job's status changed underneath it
  if (state.openConfirmJobId) {
    const stillStaged = jobs.find((j) => j.id === state.openConfirmJobId && j.status === "staged_and_waiting");
    if (!stillStaged) closeConfirmPanel();
  }
}

// ---------- launch pad ----------
// Everything the user needs at the window, on one screen, so nothing has to be
// looked up or decided while the clock is running. See
// backend/app/agents/handoff_agent.py for why this is as far as automation goes.

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Renders the guided step list. One step is expanded at a time - the current
// one by default - but ANY step can be reopened by clicking its header,
// including finished ones, so the details of a step you've already done stay
// available instead of disappearing the moment you tick it.
function renderChecklist(h, jobId) {
  const container = $("#lp-checklist");
  if (!container) return;

  if (state.lpExpandedStep === null || state.lpExpandedStep === undefined) {
    const cur = h.checklist.find((s) => s.current);
    state.lpExpandedStep = cur ? cur.key : null;
  }

  const prog = $("#lp-progress");
  if (prog) {
    prog.textContent = h.all_steps_done
      ? `— all ${h.steps_total} done`
      : `— ${h.steps_done} of ${h.steps_total} done`;
  }

  container.innerHTML = h.checklist.map((s, i) => {
    const expanded = state.lpExpandedStep === s.key;
    const cls = [
      "lp-step",
      s.done ? "lp-done" : "",
      s.current && !s.done ? "lp-current" : "",
      s.overdue ? "lp-overdue" : "",
      expanded ? "lp-expanded" : "",
    ].filter(Boolean).join(" ");

    let tag = "";
    if (s.done) {
      tag = `<span class="badge good">done${s.done_at ? " " + new Date(s.done_at).toLocaleTimeString() : ""}</span>`;
    } else if (s.overdue) {
      tag = '<span class="badge bad">overdue</span>';
    } else if (s.due_at) {
      tag = `<span class="badge neutral">by ${new Date(s.due_at).toLocaleTimeString()}</span>`;
    }

    const marker = s.done ? "&#10003;" : String(i + 1);

    const body = !expanded ? "" : `
      <div class="lp-step-body">
        <p>${escapeHtml(s.detail)}</p>
        ${s.why ? `<p class="muted"><em>${escapeHtml(s.why)}</em></p>` : ""}
        ${s.nav_path ? `<p class="lp-nav">Where: <code>${escapeHtml(s.nav_path)}</code></p>` : ""}
        ${s.links.length ? `<p>${s.links.map((l) =>
            `<a class="lp-link" href="${escapeHtml(l.url)}" target="_blank" rel="noopener">${escapeHtml(l.label)} &#8599;</a>`
          ).join(" ")}</p>` : ""}
        ${s.help.length ? `<ul class="lp-help">${s.help.map((t) => `<li>${escapeHtml(t)}</li>`).join("")}</ul>` : ""}
        <button class="${s.done ? "secondary" : "primary"}" data-step="${s.key}" data-done="${s.done ? "0" : "1"}">
          ${s.done ? "Mark not done" : "Mark done &amp; continue"}
        </button>
      </div>`;

    return `
      <div class="${cls}">
        <div class="lp-step-head" data-toggle="${s.key}">
          <span class="lp-marker">${marker}</span>
          <strong>${escapeHtml(s.title)}</strong> ${tag}
        </div>
        ${body}
      </div>`;
  }).join("");

  container.querySelectorAll("[data-toggle]").forEach((el) => {
    el.addEventListener("click", () => {
      const key = el.dataset.toggle;
      state.lpExpandedStep = state.lpExpandedStep === key ? null : key;
      renderChecklist(state.launchPadData, jobId);
    });
  });

  container.querySelectorAll("[data-step]").forEach((btn) => {
    btn.addEventListener("click", async (ev) => {
      ev.stopPropagation();
      const key = btn.dataset.step;
      const done = btn.dataset.done === "1";
      btn.disabled = true;
      try {
        const fresh = await api(`/api/jobs/${jobId}/checklist`, {
          method: "POST",
          body: JSON.stringify({ step_key: key, done }),
        });
        state.launchPadData = fresh;
        // Advance to whatever is now current; if everything's done, collapse.
        const next = fresh.checklist.find((s) => s.current);
        state.lpExpandedStep = done ? (next ? next.key : null) : key;
        renderChecklist(fresh, jobId);
      } catch (e) {
        btn.disabled = false;
        alert("Could not update step: " + e.message);
      }
    });
  });
}

function closeLaunchPad() {
  state.openLaunchPadJobId = null;
  state.lpExpandedStep = null;
  const panel = $("#launchpad-panel");
  panel.style.display = "none";
  panel.innerHTML = "";
}

async function openLaunchPad(job) {
  state.openLaunchPadJobId = job.id;
  state.lpExpandedStep = null; // let the current step decide what's open
  const panel = $("#launchpad-panel");
  panel.style.display = "block";
  panel.innerHTML = `<p class="muted">Loading launch pad...</p>`;
  panel.scrollIntoView({ behavior: "smooth" });

  let h;
  try {
    h = await api(`/api/jobs/${job.id}/handoff`);
  } catch (e) {
    panel.innerHTML = `<p class="muted">Could not load launch pad: ${escapeHtml(e.message)}</p>`;
    return;
  }
  state.launchPadData = h;

  // The single most important thing on this screen when adapters are mocked:
  // the train/fare/availability below are generated, so anyone acting on them
  // as if they were a real quote will be misled. Say so above the spec, not in
  // a footnote.
  const simWarning = h.data_source && h.data_source.any_simulated
    ? `<p class="lp-simulated"><strong>Simulated data.</strong>
         ${escapeHtml(h.data_source.simulated_platforms.join(", "))}
         ${h.data_source.simulated_platforms.length > 1 ? "are" : "is"} returning generated results -
         the train, fare and availability below are placeholders and may not match this route at all.
         Verify everything on IRCTC before booking. See docs/AUTOMATION_LIMITS.md.</p>`
    : "";

  const spec = h.selection_spec;
  const specRows = [
    ["From", spec.from_station], ["To", spec.to_station], ["Date", spec.journey_date],
    ["Train", spec.train], ["Class", spec.travel_class], ["Quota", spec.quota],
    ["Passengers", spec.passenger_count], ["Expected fare", spec.expected_fare ? `Rs ${spec.expected_fare}` : null],
  ].filter(([, v]) => v !== null && v !== undefined);


  const pax = h.passengers;
  const paxWarning = pax.shortfall > 0
    ? `<span class="badge bad">${pax.shortfall} passenger profile(s) missing</span>`
    : `<span class="badge good">all ${pax.needed} on file</span>`;

  const headerHtml = h.is_immediate
    ? `<p class="muted">Booking now - no Tatkal window to wait for. Work down this page and you're done.</p>`
    : `<p>Window opens in <strong id="lp-countdown" data-window="${h.window_open_time_ist}">...</strong>
         <span class="muted">(${new Date(h.window_open_time_ist).toLocaleString()})</span></p>`;

  panel.innerHTML = `
    <h3 style="margin-top:0">Launch Pad - ${escapeHtml(h.platform)}${h.is_immediate ? " (book now)" : ""}</h3>
    ${h.window_warning ? `<p class="badge bad">${escapeHtml(h.window_warning)}</p>` : ""}
    ${headerHtml}

    <h4>1. ${h.is_immediate ? "Before you click through" : "Prep checklist"}
        <span class="muted" id="lp-progress"></span></h4>
    <div id="lp-checklist"></div>

    <h4>2. Exactly what to enter</h4>
    ${simWarning}
    <table class="lp-spec">
      ${specRows.map(([k, v]) => `<tr><td class="muted">${k}</td><td><strong>${escapeHtml(v)}</strong></td></tr>`).join("")}
    </table>
    <button class="secondary" id="lp-copy-spec">Copy journey details</button>

    <h4>3. Passengers ${paxWarning}</h4>
    <p class="muted">Fastest path is IRCTC's own Master List (step 1). This block is the fallback if you haven't set that up yet.</p>
    <pre class="lp-pre">${escapeHtml(pax.clipboard_text || "(no passenger profiles saved yet)")}</pre>
    <button class="secondary" id="lp-copy-pax" ${pax.clipboard_text ? "" : "disabled"}>Copy passengers</button>

    <h4>4. Go</h4>
    <p class="muted">You do these yourself, in your own browser session: ${h.manual_steps_remaining.map(escapeHtml).join(" &rarr; ")}.</p>
    <button class="primary" id="lp-open-irctc">Open IRCTC booking page</button>

    <h4>5. After booking</h4>
    ${h.pnr
      ? `<p>Recorded PNR: <span class="badge good">${escapeHtml(h.pnr)}</span>
           <a class="lp-link" href="${escapeHtml(h.pnr_enquiry_url)}" target="_blank" rel="noopener">Check status &#8599;</a></p>`
      : `<p class="muted">Paste the PNR here once booked - it gets logged and emailed to you.</p>
         <input id="lp-pnr" placeholder="10-digit PNR" maxlength="10" />
         <button class="secondary" id="lp-save-pnr">Save PNR</button>`}

    <p><button class="secondary" id="lp-close">Close</button></p>
  `;

  renderChecklist(h, job.id);

  const copyTo = async (btn, text, label) => {
    try {
      await navigator.clipboard.writeText(text);
      btn.textContent = "Copied";
      setTimeout(() => { btn.textContent = label; }, 1500);
    } catch {
      alert("Clipboard blocked by the browser - select and copy manually.");
    }
  };

  $("#lp-copy-spec").addEventListener("click", (e) =>
    copyTo(e.target, specRows.map(([k, v]) => `${k}: ${v}`).join("\n"), "Copy journey details"));

  const copyPaxBtn = $("#lp-copy-pax");
  if (pax.clipboard_text) {
    copyPaxBtn.addEventListener("click", (e) => copyTo(e.target, pax.clipboard_text, "Copy passengers"));
  }

  $("#lp-open-irctc").addEventListener("click", () => {
    window.open(h.booking_url, "_blank", "noopener");
  });

  const savePnrBtn = $("#lp-save-pnr");
  if (savePnrBtn) {
    savePnrBtn.addEventListener("click", async () => {
      const pnr = $("#lp-pnr").value.trim();
      try {
        await api(`/api/jobs/${job.id}/pnr`, { method: "POST", body: JSON.stringify({ pnr }) });
        loadJobs();
        openLaunchPad(job);
      } catch (e) {
        alert("Could not save PNR: " + e.message);
      }
    });
  }

  $("#lp-close").addEventListener("click", closeLaunchPad);
}

function closeConfirmPanel() {
  state.openConfirmJobId = null;
  const panel = $("#confirm-panel");
  panel.style.display = "none";
  panel.innerHTML = "";
}

async function openConfirmPanel(job) {
  state.openConfirmJobId = job.id;
  const panel = $("#confirm-panel");
  panel.style.display = "block";
  panel.innerHTML = `<p class="muted">Requesting confirmation token...</p>`;
  panel.scrollIntoView({ behavior: "smooth" });

  let token;
  try {
    token = await api(`/api/jobs/${job.id}/request-token`, { method: "POST" });
  } catch (e) {
    panel.innerHTML = `<p class="muted">Could not get a confirmation token: ${e.message}</p>`;
    return;
  }

  panel.innerHTML = `
    <h3 style="margin-top:0">Confirm booking on ${job.target_platform}</h3>
    <p class="muted">Real staging/CAPTCHA/payment is a stub in this build (see docs/AUTOMATION_LIMITS.md) - you solve the actual CAPTCHA and pay yourself, in your own browser, on the platform's site. This panel only issues/consumes the single-use confirmation token that unlocks the mock "confirmed" status.</p>
    <div class="captcha-box">[ CAPTCHA placeholder - solve the real one on the platform's page yourself ]</div>
    <p>Token expires in <strong id="token-countdown" data-expires-at="${token.expires_at}">...</strong></p>
    <button class="primary" id="confirm-pay-btn">Confirm &amp; Pay</button>
    <button class="secondary" id="confirm-cancel-btn">Cancel</button>
  `;

  $("#confirm-pay-btn").addEventListener("click", async () => {
    try {
      await api(`/api/jobs/${job.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({ token_id: token.id }),
      });
      panel.innerHTML = `<p class="muted">Confirmed.</p>`;
      closeConfirmPanel();
      loadJobs();
    } catch (e) {
      alert("Confirm failed: " + e.message);
    }
  });
  $("#confirm-cancel-btn").addEventListener("click", closeConfirmPanel);
}

// ---------- passengers ----------
$("#add-passenger-btn").addEventListener("click", async () => {
  const payload = {
    name: $("#p-name").value,
    age: parseInt($("#p-age").value || "0", 10),
    gender: $("#p-gender").value,
    berth_preference: $("#p-berth").value || null,
  };
  if (!payload.name || !payload.age) { alert("Name and age required."); return; }
  await api("/api/passengers", { method: "POST", body: JSON.stringify(payload) });
  $("#p-name").value = "";
  $("#p-age").value = "";
  loadPassengers();
});

async function loadPassengers() {
  const rows = await api("/api/passengers");
  const body = $("#passengers-body");
  body.innerHTML = "";
  rows.forEach((p) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.name}</td><td>${p.age}</td><td>${p.gender}</td><td>${p.berth_preference || "-"}</td><td></td>`;
    const del = document.createElement("button");
    del.className = "secondary";
    del.textContent = "Remove";
    del.addEventListener("click", async () => {
      await api(`/api/passengers/${p.id}`, { method: "DELETE" });
      loadPassengers();
    });
    tr.lastElementChild.appendChild(del);
    body.appendChild(tr);
  });
}

// ---------- audit ----------
$("#refresh-audit").addEventListener("click", loadAudit);

async function loadAudit() {
  const rows = await api("/api/audit");
  const body = $("#audit-body");
  body.innerHTML = "";
  rows.forEach((a) => {
    const cls = a.outcome === "success" ? "good" : a.outcome === "rejected" ? "warn" : "bad";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(a.timestamp).toLocaleString()}</td>
      <td>${a.agent}</td>
      <td>${a.action}</td>
      <td><span class="badge ${cls}">${a.outcome}</span></td>
      <td>${a.target || "-"}</td>
    `;
    body.appendChild(tr);
  });
}

// ---------- notifications (polling) ----------
const seenIds = new Set();
async function pollNotifications() {
  try {
    const notes = await api("/api/notifications");
    const area = $("#notif-area");
    area.innerHTML = "";
    notes.filter((n) => !n.seen).slice(0, 5).forEach((n) => {
      const div = document.createElement("div");
      div.className = "notif-banner " + n.level;
      div.textContent = n.message;
      area.appendChild(div);
    });
  } catch (e) {
    // backend not up yet - ignore
  }
}
setInterval(pollNotifications, 5000);
pollNotifications();
