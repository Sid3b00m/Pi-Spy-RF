async function apiFetch(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    window.location = "/login";
    throw new Error("auth required");
  }
  return res;
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function roleOptions(roles, selected) {
  return roles
    .map(
      (r) =>
        `<option value="${escapeHtml(r)}" ${r === selected ? "selected" : ""}>${escapeHtml(r)}</option>`
    )
    .join("");
}

async function refreshDevices() {
  const res = await apiFetch("/api/devices");
  const data = await res.json();
  const root = document.getElementById("device-list");
  if (!root) return;
  const roles = data.roles || ["scan", "decode", "wifi", "bluetooth", "idle"];
  if (!data.devices || data.devices.length === 0) {
    root.innerHTML = '<p class="empty">No SDR detected.</p>';
    return;
  }
  root.innerHTML = data.devices
    .map(
      (d) => `<article class="card" data-id="${escapeHtml(d.id)}">
      <h3>${escapeHtml(d.name)}</h3>
      <p class="meta">${escapeHtml(d.type)} · ${escapeHtml(d.status)}</p>
      <p class="meta">id: ${escapeHtml(d.id)}${d.serial ? " · SN: " + escapeHtml(d.serial) : ""}</p>
      <p>${escapeHtml(d.detail || "")}</p>
      <label class="role-row">Role
        <select class="role-select" data-device="${escapeHtml(d.id)}">
          ${roleOptions(roles, d.role)}
        </select>
      </label>
    </article>`
    )
    .join("");
  bindRoleSelects();
}

async function refreshEvents() {
  const res = await apiFetch("/api/events?limit=30");
  const data = await res.json();
  const list = document.getElementById("event-list");
  if (!list) return;
  if (!data.events || data.events.length === 0) {
    list.innerHTML = '<li class="empty">No events yet.</li>';
    return;
  }
  list.innerHTML = data.events
    .map(
      (e) => `<li>
        <span class="ts">${escapeHtml(e.ts)}</span>
        <strong>${escapeHtml(e.kind)}</strong>
        <span>${escapeHtml(e.summary)}</span>
      </li>`
    )
    .join("");
}

async function setRole(deviceId, role) {
  const res = await apiFetch(`/api/devices/${encodeURIComponent(deviceId)}/role`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
  if (!res.ok) {
    alert("Failed to set role: " + (await res.text()));
    return;
  }
  await refreshEvents();
}

function bindRoleSelects() {
  document.querySelectorAll(".role-select").forEach((el) => {
    el.onchange = () => setRole(el.dataset.device, el.value).catch(console.error);
  });
}

const waterfallHistory = [];
const WATERFALL_ROWS = 80;

function heatColor(t) {
  const x = Math.max(0, Math.min(1, t));
  const r = Math.floor(20 + 200 * Math.max(0, x - 0.45) * 2);
  const g = Math.floor(40 + 180 * x);
  const b = Math.floor(90 + 80 * (1 - x));
  return "rgb(" + r + "," + g + "," + b + ")";
}

function drawWaterfall(latest) {
  const canvas = document.getElementById("waterfall-canvas");
  if (!canvas || !latest || !latest.bins || !latest.bins.length) return;
  waterfallHistory.unshift(latest.bins.slice());
  if (waterfallHistory.length > WATERFALL_ROWS) waterfallHistory.pop();
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#0a1016";
  ctx.fillRect(0, 0, w, h);
  const rows = waterfallHistory.length;
  const all = waterfallHistory.flat();
  const min = Math.min(...all);
  const max = Math.max(...all);
  const span = Math.max(1, max - min);
  const cols = waterfallHistory[0].length;
  const rw = w / cols;
  const rh = h / WATERFALL_ROWS;
  for (let y = 0; y < rows; y++) {
    const row = waterfallHistory[y];
    for (let x = 0; x < row.length; x++) {
      const t = (row[x] - min) / span;
      ctx.fillStyle = heatColor(t);
      ctx.fillRect(x * rw, y * rh, rw + 0.5, rh + 0.5);
    }
  }
}

function drawSpectrum(latest) {
  const canvas = document.getElementById("spectrum-canvas");
  if (!canvas || !latest || !latest.bins || latest.bins.length === 0) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = "#121a22";
  ctx.fillRect(0, 0, w, h);
  const bins = latest.bins;
  const min = Math.min(...bins);
  const max = Math.max(...bins);
  const span = Math.max(1, max - min);
  ctx.beginPath();
  ctx.strokeStyle = "#3ecf8e";
  ctx.lineWidth = 2;
  bins.forEach((v, i) => {
    const x = (i / (bins.length - 1)) * (w - 20) + 10;
    const y = h - 15 - ((v - min) / span) * (h - 30);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();
  ctx.fillStyle = "#93a4b5";
  ctx.font = "12px Consolas, monospace";
  const f0 = latest.freqs_mhz?.[0] ?? 0;
  const f1 = latest.freqs_mhz?.[latest.freqs_mhz.length - 1] ?? 0;
  ctx.fillText(`${f0.toFixed(2)} MHz`, 10, h - 4);
  ctx.fillText(`${f1.toFixed(2)} MHz`, w - 80, h - 4);
}

function renderPeaks(peaks) {
  const list = document.getElementById("peak-list");
  if (!list) return;
  if (!peaks || peaks.length === 0) {
    list.innerHTML = '<li class="empty">No peaks above threshold.</li>';
    return;
  }
  list.innerHTML = peaks
    .map(
      (p) => `<li>
        <strong>${escapeHtml(p.freq_mhz)} MHz</strong>
        <span>${escapeHtml(p.label)} · ${escapeHtml(p.mode_hint)} · ${escapeHtml(p.power_db)} dB</span>
      </li>`
    )
    .join("");
}

async function refreshSpectrum() {
  const res = await apiFetch("/api/spectrum");
  const data = await res.json();
  const meta = document.getElementById("spectrum-meta");
  const status = document.getElementById("spectrum-status");
  if (status) status.textContent = JSON.stringify(data, null, 2);
  if (meta) {
    meta.textContent = data.running
      ? `Running on ${data.device_id || "?"} · ${data.range_mhz?.[0]}–${data.range_mhz?.[1]} MHz · source ${data.latest?.source || "?"}${data.error ? " · ERROR: " + data.error : ""}`
      : `Idle${data.error ? " · " + data.error : ""}`;
  }
  if (data.latest) {
    drawSpectrum(data.latest);
    drawWaterfall(data.latest);
    renderPeaks(data.latest.peaks || []);
  }
}

async function startSpectrum() {
  const body = {
    start_mhz: Number(document.getElementById("spec-start").value),
    end_mhz: Number(document.getElementById("spec-end").value),
    threshold_db: Number(document.getElementById("spec-thresh").value),
  };
  await apiFetch("/api/spectrum/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await refreshSpectrum();
  await refreshEvents();
}

async function stopSpectrum() {
  await apiFetch("/api/spectrum/stop", { method: "POST" });
  await refreshSpectrum();
  await refreshEvents();
}

document.getElementById("refresh-devices")?.addEventListener("click", () => {
  refreshDevices().catch(console.error);
});
document.getElementById("refresh-events")?.addEventListener("click", () => {
  refreshEvents().catch(console.error);
});
document.getElementById("spectrum-start")?.addEventListener("click", () => {
  startSpectrum().catch(console.error);
});
document.getElementById("spectrum-stop")?.addEventListener("click", () => {
  stopSpectrum().catch(console.error);
});
document.getElementById("spectrum-config")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await apiFetch("/api/spectrum/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      start_mhz: Number(document.getElementById("spec-start").value),
      end_mhz: Number(document.getElementById("spec-end").value),
      threshold_db: Number(document.getElementById("spec-thresh").value),
    }),
  });
  await refreshSpectrum();
});

document.getElementById("classify-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const mhz = Number(document.getElementById("freq-input").value);
  const res = await apiFetch("/api/bands/classify", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ freq_mhz: mhz }),
  });
  const data = await res.json();
  document.getElementById("classify-out").textContent = JSON.stringify(data, null, 2);
});

bindRoleSelects();
refreshSpectrum().catch(console.error);
setInterval(() => {
  refreshSpectrum().catch(() => {});
  refreshEvents().catch(() => {});
  refreshDecode().catch(() => {});
  refreshWireless().catch(() => {});
  refreshBalance().catch(() => {});
  refreshAudio().catch(() => {});
}, 3000);

async function refreshDecode() {
  const res = await apiFetch("/api/decode");
  const data = await res.json();
  const meta = document.getElementById("decode-meta");
  const status = document.getElementById("decode-status");
  const list = document.getElementById("decode-list");
  if (status) status.textContent = JSON.stringify(data, null, 2);
  if (meta) {
    meta.textContent = data.running
      ? `Running on ${data.device_id || "?"} · queue ${data.queue_len} · auto=${data.auto_from_spectrum}`
      : `Idle${data.error ? " · " + data.error : ""}`;
  }
  if (list) {
    const rows = data.recent || [];
    if (!rows.length) {
      list.innerHTML = '<li class="empty">No decode results yet.</li>';
    } else {
      list.innerHTML = rows
        .map((j) => {
          const r = j.result || {};
          let detail = r.text || j.error || j.status;
          if (r.mode === "dmr") {
            detail = `CC=${r.color_code} TS=${r.timeslot} TG=${r.talkgroup} RID=${r.radio_id}`;
          } else if (r.mode === "p25") {
            detail = `NAC=${r.nac} TG=${r.talkgroup} RID=${r.radio_id}`;
          }
          return `<li>
            <span class="ts">${escapeHtml(j.finished_at || j.created_at || "")}</span>
            <strong>${escapeHtml(j.mode)} @ ${escapeHtml(j.freq_mhz)} MHz</strong>
            <span>${escapeHtml(j.status)} · ${escapeHtml(detail || "")}</span>
          </li>`;
        })
        .join("");
    }
  }
}

document.getElementById("decode-start")?.addEventListener("click", async () => {
  await apiFetch("/api/decode/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await refreshDecode();
  await refreshEvents();
});
document.getElementById("decode-stop")?.addEventListener("click", async () => {
  await apiFetch("/api/decode/stop", { method: "POST" });
  await refreshDecode();
  await refreshEvents();
});
document.getElementById("decode-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await apiFetch("/api/decode/enqueue", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      freq_mhz: Number(document.getElementById("dec-freq").value),
      mode: document.getElementById("dec-mode").value,
      duration_s: 6,
    }),
  });
  await refreshDecode();
  await refreshEvents();
});

refreshDecode().catch(console.error);

async function refreshWireless() {
  let banner = document.getElementById("demo-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "demo-banner";
    banner.style.cssText = "display:none;margin:0.5rem 0;padding:0.5rem 0.75rem;background:#3b2f1a;color:#f0d78c;border:1px solid #8a6d2f;";
    const main = document.querySelector("main") || document.body;
    main.prepend(banner);
  }

  const statusRes = await apiFetch("/api/wireless");
  const status = await statusRes.json();
  const bannerEl = document.getElementById("demo-banner");
  if (bannerEl) {
    if (status.demo) {
      bannerEl.style.display = "block";
      bannerEl.textContent = "Demo wireless data — nmcli/iw/bluetoothctl not available on this OS. Not live scan results.";
    } else {
      bannerEl.style.display = "none";
    }
  }

  const meta = document.getElementById("wireless-meta");
  const statusEl = document.getElementById("wireless-status");
  if (statusEl) statusEl.textContent = JSON.stringify(status, null, 2);
  if (meta) {
    meta.textContent = status.running
      ? `Running · wifi=${status.counts?.wifi || 0} bt=${status.counts?.bluetooth || 0} · last ${status.last_scan?.ts || "?"}`
      : `Idle${status.error ? " · " + status.error : ""}`;
  }
  const wifiRes = await apiFetch("/api/wireless/devices?kind=wifi&limit=50");
  const btRes = await apiFetch("/api/wireless/devices?kind=bluetooth&limit=50");
  const wifi = await wifiRes.json();
  const bt = await btRes.json();
  const wifiBody = document.getElementById("wifi-body");
  const btBody = document.getElementById("bt-body");
  if (wifiBody) {
    const rows = wifi.devices || [];
    wifiBody.innerHTML = rows.length
      ? rows.map((d) => `<tr>
          <td><code>${escapeHtml(d.mac)}</code></td>
          <td>${escapeHtml(d.ssid || d.name || "")}${d.known_name ? " <em>(" + escapeHtml(d.known_name) + ")</em>" : ""}</td>
          <td>${escapeHtml(d.rssi ?? "")}</td>
          <td>${escapeHtml(d.channel ?? "")}</td>
          <td>${escapeHtml(d.vendor || "")}</td>
        </tr>`).join("")
      : '<tr><td colspan="5" class="empty">No WiFi devices yet.</td></tr>';
  }
  if (btBody) {
    const rows = bt.devices || [];
    btBody.innerHTML = rows.length
      ? rows.map((d) => `<tr>
          <td><code>${escapeHtml(d.mac)}</code></td>
          <td>${escapeHtml(d.name || "")}${d.known_name ? " <em>(" + escapeHtml(d.known_name) + ")</em>" : ""}</td>
          <td>${escapeHtml(d.rssi ?? "")}</td>
          <td>${escapeHtml(d.vendor || "")}</td>
        </tr>`).join("")
      : '<tr><td colspan="4" class="empty">No Bluetooth devices yet.</td></tr>';
  }
}

async function refreshKnownMacs() {
  const res = await apiFetch("/api/macs/known");
  const data = await res.json();
  const body = document.getElementById("mac-body");
  if (!body) return;
  const rows = data.devices || [];
  body.innerHTML = rows
    .map(
      (d) => `<tr>
      <td><code>${escapeHtml(d.mac)}</code></td>
      <td>${escapeHtml(d.name)}</td>
      <td>${escapeHtml(d.type)}</td>
      <td>${escapeHtml(d.notes || "")} <button type="button" data-del-mac="${escapeHtml(d.mac)}" class="linkish">delete</button></td>
    </tr>`
    )
    .join("");
  body.querySelectorAll("[data-del-mac]").forEach((btn) => {
    btn.onclick = async () => {
      await apiFetch("/api/macs/known/" + encodeURIComponent(btn.dataset.delMac), { method: "DELETE" });
      await refreshKnownMacs();
      await refreshWireless();
    };
  });
}

document.getElementById("wireless-start")?.addEventListener("click", async () => {
  await apiFetch("/api/wireless/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await refreshWireless();
  await refreshEvents();
});
document.getElementById("wireless-stop")?.addEventListener("click", async () => {
  await apiFetch("/api/wireless/stop", { method: "POST" });
  await refreshWireless();
  await refreshEvents();
});
document.getElementById("known-mac-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await apiFetch("/api/macs/known", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      mac: document.getElementById("km-mac").value,
      name: document.getElementById("km-name").value,
      type: document.getElementById("km-type").value,
      notes: document.getElementById("km-notes").value,
    }),
  });
  await refreshKnownMacs();
  await refreshWireless();
});

refreshWireless().catch(console.error);
refreshKnownMacs().catch(console.error);

function renderSlot(id, device, busy, role) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = device
    ? `${device.name} (${device.id})${busy ? " · BUSY" : " · ready"}`
    : `Unassigned — pick role ${role} or auto-assign`;
}

async function refreshBalance() {
  const res = await apiFetch("/api/devices/balance");
  const data = await res.json();
  const busy = data.busy || {};
  renderSlot("slot-scan-meta", (data.scan || [])[0], busy.scan, "scan");
  renderSlot("slot-decode-meta", (data.decode || [])[0], busy.decode, "decode");
  renderSlot("slot-audio-meta", (data.audio || [])[0], busy.audio, "audio");
}

document.getElementById("balance-apply")?.addEventListener("click", async () => {
  await apiFetch("/api/devices/balance", { method: "POST" });
  await refreshBalance();
  await refreshDevices();
  await refreshEvents();
});

refreshBalance().catch(console.error);


let websdrReceivers = [];
let websdrStatus = null;

/** Third-party directory data, so never trust the scheme it hands us. */
function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || ""));
}

function websdrAge(seconds) {
  if (!Number.isFinite(seconds)) return "";
  const mins = Math.round(seconds / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function websdrLabel(r) {
  const bits = [r.label || r.name || r.id];
  if (r.type) bits.push(r.type);
  if (r.users_max) bits.push(`${r.users || 0}/${r.users_max} users`);
  else if (r.bands) bits.push(r.bands);
  return bits.join(" · ");
}

function fillWebsdrTypes(byType) {
  const sel = document.getElementById("websdr-type");
  if (!sel) return;
  const current = sel.value;
  const total = Object.values(byType || {}).reduce((a, b) => a + b, 0);
  sel.innerHTML =
    `<option value="">All types (${total})</option>` +
    Object.entries(byType || {})
      .map(
        ([kind, n]) =>
          `<option value="${escapeHtml(kind)}">${escapeHtml(kind)} (${n})</option>`
      )
      .join("");
  if ([...sel.options].some((o) => o.value === current)) sel.value = current;
}

function renderWebsdrDetail() {
  const box = document.getElementById("websdr-detail");
  const sel = document.getElementById("websdr-select");
  if (!box || !sel) return;
  const r = websdrReceivers.find((x) => x.id === sel.value);
  if (!r) {
    box.className = "card websdr-detail empty";
    box.textContent = "Pick a receiver to see its details.";
    return;
  }
  const rows = [
    ["Site", r.label],
    ["Listing", r.name !== r.label ? r.name : null],
    ["Type", r.version ? `${r.type} ${r.version}` : r.type],
    ["Coverage", r.bands],
    ["Users", r.users_max ? `${r.users || 0} of ${r.users_max}` : null],
    ["SNR", r.snr],
    ["Antenna", r.antenna],
    ["Grid", r.grid],
    ["Position", `${r.lat.toFixed(3)}, ${r.lon.toFixed(3)}`],
    ["Listed by", r.source],
  ].filter(([, v]) => v);
  box.className = "card websdr-detail";
  box.innerHTML =
    `<p class="websdr-url"><code>${escapeHtml(r.tune_url || r.url)}</code></p>` +
    rows
      .map(
        ([k, v]) =>
          `<p class="meta"><span>${escapeHtml(k)}</span>${escapeHtml(v)}</p>`
      )
      .join("");
}

function renderWebsdrOptions() {
  const sel = document.getElementById("websdr-select");
  const meta = document.getElementById("websdr-meta");
  if (!sel) return;
  const kind = document.getElementById("websdr-type")?.value || "";
  const needle = (document.getElementById("websdr-search")?.value || "")
    .trim()
    .toLowerCase();
  const rows = websdrReceivers.filter((r) => {
    if (kind && r.type !== kind) return false;
    if (needle) {
      const hay = `${r.label || ""} ${r.name || ""}`.toLowerCase();
      if (!hay.includes(needle)) return false;
    }
    return true;
  });

  const current = sel.value;
  sel.innerHTML = rows.length
    ? rows
        .map(
          (r) =>
            `<option value="${escapeHtml(r.id)}">${escapeHtml(websdrLabel(r))}</option>`
        )
        .join("")
    : '<option value="">No receiver matches that filter</option>';
  if (rows.some((r) => r.id === current)) sel.value = current;

  if (meta && websdrStatus) {
    const parts = [`${rows.length} of ${websdrStatus.total} receivers`];
    const byType = Object.entries(websdrStatus.by_type || {})
      .map(([k, n]) => `${k} ${n}`)
      .join(", ");
    if (byType) parts.push(byType);
    if (websdrStatus.unknown_coverage) {
      parts.push(`${websdrStatus.unknown_coverage} hidden with no published coverage`);
    }
    parts.push(`updated ${websdrAge(websdrStatus.age_s)}`);
    if (websdrStatus.stale) {
      parts.push(`cached copy — ${websdrStatus.degraded_reason || "directory unreachable"}`);
    }
    const failed = Object.entries(websdrStatus.errors || {})
      .map(([k, v]) => `${k}: ${v}`)
      .join("; ");
    if (failed) parts.push(failed);
    meta.textContent = parts.join(" · ");
  }
  renderWebsdrDetail();
}

/** Coverage lives server-side, so a frequency filter means a refetch. */
function websdrQuery() {
  const params = new URLSearchParams({ limit: "2000" });
  const freq = Number(document.getElementById("websdr-freq")?.value);
  if (Number.isFinite(freq) && freq > 0) {
    params.set("freq_mhz", String(freq));
    const mode = document.getElementById("websdr-mode")?.value || "";
    if (mode) params.set("mode", mode);
  }
  return params.toString();
}

async function refreshWebsdr() {
  const panel = document.getElementById("websdr-panel");
  if (!panel) return;
  const meta = document.getElementById("websdr-meta");
  try {
    const res = await apiFetch(`/api/websdr/receivers?${websdrQuery()}`);
    if (res.status === 404) {
      panel.remove();
      return;
    }
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    websdrReceivers = data.receivers || [];
    websdrStatus = data;
    fillWebsdrTypes(data.by_type);
    renderWebsdrOptions();
  } catch (e) {
    if (meta) meta.textContent = `Directory unavailable — ${e.message}`;
  }
}

document.getElementById("websdr-type")?.addEventListener("change", renderWebsdrOptions);
document.getElementById("websdr-search")?.addEventListener("input", renderWebsdrOptions);
document.getElementById("websdr-select")?.addEventListener("change", renderWebsdrDetail);

let websdrRefetch = null;
function scheduleWebsdrRefetch() {
  clearTimeout(websdrRefetch);
  websdrRefetch = setTimeout(() => refreshWebsdr().catch(console.error), 350);
}
document.getElementById("websdr-freq")?.addEventListener("input", scheduleWebsdrRefetch);
document.getElementById("websdr-mode")?.addEventListener("change", scheduleWebsdrRefetch);

document.getElementById("websdr-form")?.addEventListener("submit", (ev) => {
  ev.preventDefault();
  const sel = document.getElementById("websdr-select");
  const r = websdrReceivers.find((x) => x.id === sel?.value);
  if (!r) return;
  const target = r.tune_url || r.url;
  if (!isHttpUrl(target)) return;
  window.open(target, "_blank", "noopener,noreferrer");
});

document.getElementById("websdr-refresh")?.addEventListener("click", async () => {
  const meta = document.getElementById("websdr-meta");
  if (meta) meta.textContent = "Refreshing directory…";
  try {
    const res = await apiFetch("/api/websdr/refresh", { method: "POST" });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }
  } catch (e) {
    if (meta) meta.textContent = `Refresh failed — ${e.message}`;
  }
  await refreshWebsdr();
  await refreshEvents();
});

refreshWebsdr().catch(console.error);

let audioModesFilled = false;

function audioFields() {
  return {
    freq_mhz: Number(document.getElementById("audio-freq").value),
    mode: document.getElementById("audio-mode").value,
    gain: Number(document.getElementById("audio-gain").value),
    squelch: Number(document.getElementById("audio-squelch").value),
  };
}

/** A fresh URL each time, so the element never replays a cached stream. */
function attachAudioPlayer() {
  const player = document.getElementById("audio-player");
  if (!player) return;
  player.src = `/api/audio/stream?t=${Date.now()}`;
  player.load();
  const started = player.play();
  if (started) started.catch(() => {});
}

function detachAudioPlayer() {
  const player = document.getElementById("audio-player");
  if (!player) return;
  player.pause();
  player.removeAttribute("src");
  player.load();
}

function fillAudioModes(modes) {
  const sel = document.getElementById("audio-mode");
  if (!sel || audioModesFilled || !modes || !modes.length) return;
  const current = sel.value;
  sel.innerHTML = modes
    .map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`)
    .join("");
  if (modes.includes(current)) sel.value = current;
  audioModesFilled = true;
}

function audioSummary(data) {
  if (!data.running) return `Idle${data.error ? " · " + data.error : ""}`;
  const bits = [
    `${data.freq_mhz} MHz ${data.mode}`,
    `${data.backend} (${data.backend_reason})`,
    `${data.audio_rate} Hz`,
    `${data.listeners}/${data.max_listeners} listening`,
  ];
  if (data.squelched) bits.push("squelched");
  if (data.dropped_chunks) bits.push(`${data.dropped_chunks} chunks dropped`);
  if (data.error) bits.push("ERROR: " + data.error);
  return bits.join(" · ");
}

async function refreshAudio() {
  const panel = document.getElementById("audio-panel");
  if (!panel) return;
  const res = await apiFetch("/api/audio");
  const data = await res.json();
  fillAudioModes(data.modes);
  const meta = document.getElementById("audio-meta");
  const status = document.getElementById("audio-status");
  if (status) status.textContent = JSON.stringify(data, null, 2);
  if (meta) meta.textContent = audioSummary(data);
}

async function postAudio(path, body) {
  const meta = document.getElementById("audio-meta");
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const payload = await res.json().catch(() => ({}));
    if (meta) meta.textContent = `Failed — ${payload.detail || "HTTP " + res.status}`;
    return null;
  }
  return res.json();
}

document.getElementById("audio-start")?.addEventListener("click", async () => {
  const data = await postAudio("/api/audio/start", audioFields());
  if (data && data.running) attachAudioPlayer();
  await refreshAudio();
  await refreshEvents();
});

document.getElementById("audio-stop")?.addEventListener("click", async () => {
  detachAudioPlayer();
  await postAudio("/api/audio/stop", {});
  await refreshAudio();
  await refreshEvents();
});

document.getElementById("audio-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  // Retuning restarts the radio, which ends the stream the player is holding.
  detachAudioPlayer();
  const data = await postAudio("/api/audio/config", audioFields());
  if (data && data.running) attachAudioPlayer();
  await refreshAudio();
  await refreshEvents();
});

refreshAudio().catch(console.error);

async function fillDecodeModes() {
  const sel = document.getElementById("dec-mode");
  if (!sel) return;
  try {
    const res = await apiFetch("/api/decode/modes");
    const data = await res.json();
    const current = sel.value;
    sel.innerHTML = (data.modes || [])
      .map((m) => `<option value="${escapeHtml(m.id)}">${escapeHtml(m.label)}</option>`)
      .join("");
    if ([...sel.options].some((o) => o.value === current)) sel.value = current;
    else sel.value = "dmr";
  } catch (e) {
    console.error(e);
  }
}
fillDecodeModes().catch(console.error);
