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
  const res = await fetch("/api/devices");
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
  const res = await fetch("/api/events?limit=30");
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
  const res = await fetch(`/api/devices/${encodeURIComponent(deviceId)}/role`, {
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
  const res = await fetch("/api/spectrum");
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
  await fetch("/api/spectrum/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  await refreshSpectrum();
  await refreshEvents();
}

async function stopSpectrum() {
  await fetch("/api/spectrum/stop", { method: "POST" });
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
  await fetch("/api/spectrum/config", {
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
  const res = await fetch("/api/bands/classify", {
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
}, 3000);

async function refreshDecode() {
  const res = await fetch("/api/decode");
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
  await fetch("/api/decode/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await refreshDecode();
  await refreshEvents();
});
document.getElementById("decode-stop")?.addEventListener("click", async () => {
  await fetch("/api/decode/stop", { method: "POST" });
  await refreshDecode();
  await refreshEvents();
});
document.getElementById("decode-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await fetch("/api/decode/enqueue", {
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
  const statusRes = await fetch("/api/wireless");
  const status = await statusRes.json();
  const meta = document.getElementById("wireless-meta");
  const statusEl = document.getElementById("wireless-status");
  if (statusEl) statusEl.textContent = JSON.stringify(status, null, 2);
  if (meta) {
    meta.textContent = status.running
      ? `Running · wifi=${status.counts?.wifi || 0} bt=${status.counts?.bluetooth || 0} · last ${status.last_scan?.ts || "?"}`
      : `Idle${status.error ? " · " + status.error : ""}`;
  }
  const wifiRes = await fetch("/api/wireless/devices?kind=wifi&limit=50");
  const btRes = await fetch("/api/wireless/devices?kind=bluetooth&limit=50");
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
  const res = await fetch("/api/macs/known");
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
      await fetch("/api/macs/known/" + encodeURIComponent(btn.dataset.delMac), { method: "DELETE" });
      await refreshKnownMacs();
      await refreshWireless();
    };
  });
}

document.getElementById("wireless-start")?.addEventListener("click", async () => {
  await fetch("/api/wireless/start", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  await refreshWireless();
  await refreshEvents();
});
document.getElementById("wireless-stop")?.addEventListener("click", async () => {
  await fetch("/api/wireless/stop", { method: "POST" });
  await refreshWireless();
  await refreshEvents();
});
document.getElementById("known-mac-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  await fetch("/api/macs/known", {
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

async function refreshBalance() {
  const res = await fetch("/api/devices/balance");
  const data = await res.json();
  const scan = (data.scan && data.scan[0]) || null;
  const dec = (data.decode && data.decode[0]) || null;
  const sm = document.getElementById("slot-scan-meta");
  const dm = document.getElementById("slot-decode-meta");
  if (sm) {
    sm.textContent = scan
      ? scan.name + " (" + scan.id + ")" + (data.busy && data.busy.scan ? " · BUSY" : " · ready")
      : "Unassigned — pick role scan or auto-assign";
  }
  if (dm) {
    dm.textContent = dec
      ? dec.name + " (" + dec.id + ")" + (data.busy && data.busy.decode ? " · BUSY" : " · ready")
      : "Unassigned — pick role decode or auto-assign";
  }
}

document.getElementById("balance-apply")?.addEventListener("click", async () => {
  await fetch("/api/devices/balance", { method: "POST" });
  await refreshBalance();
  await refreshDevices();
  await refreshEvents();
});

refreshBalance().catch(console.error);


async function fillDecodeModes() {
  const sel = document.getElementById("dec-mode");
  if (!sel) return;
  try {
    const res = await fetch("/api/decode/modes");
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
