const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let state = {
  journeyId: null,
  selectedOption: null, // {id, source_platform}
  preferredBerth: null,
  jobsCache: [], // last-loaded jobs, for the 1s local countdown ticker
  openConfirmJobId: null,
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
    if (j.status !== "pending") { el.textContent = "-"; return; }
    const triggerMs = new Date(j.window_open_time_ist).getTime() - j.lead_time_seconds * 1000;
    el.textContent = formatCountdown(triggerMs - now);
  });

  const tokenEl = $("#token-countdown");
  if (tokenEl && tokenEl.dataset.expiresAt) {
    tokenEl.textContent = formatCountdown(new Date(tokenEl.dataset.expiresAt).getTime() - now);
  }
}, 1000);

function formatCountdown(msRemaining) {
  if (msRemaining <= 0) return "any moment now";
  const totalSeconds = Math.floor(msRemaining / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
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
      <td><button class="secondary" data-id="${o.id}" data-platform="${o.source_platform}">Schedule</button></td>
    `;
    tr.querySelector("button").addEventListener("click", () => {
      state.selectedOption = { id: o.id, source_platform: o.source_platform };
      $("#schedule-card").style.display = "block";
      $("#sched-time").value = defaultLocalDateTimeValue(3); // prefill: now + 3 min, edit from here
      $("#schedule-card").scrollIntoView({ behavior: "smooth" });
    });
    body.appendChild(tr);
  });
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
    tr.innerHTML = `
      <td>${j.target_platform}</td>
      <td>${new Date(j.window_open_time_ist).toLocaleString()}</td>
      <td><span class="badge ${statusCls}">${j.status}</span></td>
      <td class="muted" data-countdown="${j.id}">-</td>
      <td></td>
    `;
    if (j.status === "staged_and_waiting") {
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
