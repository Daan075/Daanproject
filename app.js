// Temperatuurvergelijking Uitgeest: dit jaar vs. vorig jaar
const LAT = 52.529, LON = 4.709, TZ = "Europe/Amsterdam";
const ARCHIVE = "https://archive-api.open-meteo.com/v1/archive";
const FORECAST = "https://api.open-meteo.com/v1/forecast";
const ARCHIVE_DELAY = 3;   // archief loopt een paar dagen achter
const RECENT_DAYS = 14;    // recente dagen aanvullen uit KNMI-model

const $ = (s) => document.querySelector(s);
const fmtT = (t) => (t == null ? "–" : `${t.toFixed(1)}°`);
let hourlyNow = {}, hourlyPrev = {}, provisional = new Set(), chart;

// ---------- datumhulpjes (werken met "YYYY-MM-DD" strings) ----------
function todayLocal() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: TZ, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
}
function addDays(iso, n) {
  const d = new Date(iso + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
function minusYear(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  if (m === 2 && d === 29) return null; // geen 29 februari vorig jaar
  return `${y - 1}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
}
function niceDate(iso, opts) {
  return new Date(iso + "T12:00:00Z").toLocaleDateString("nl-NL", { timeZone: "UTC", ...opts });
}

// ---------- data ophalen ----------
async function getJSON(url, params) {
  const q = new URLSearchParams({ latitude: LAT, longitude: LON, timezone: TZ, hourly: "temperature_2m", ...params });
  const res = await fetch(`${url}?${q}`);
  const data = await res.json();
  if (!res.ok || data.error) throw new Error(data.reason || `HTTP ${res.status}`);
  return data;
}
// Zet hourly-respons om naar { "YYYY-MM-DD": [24 waarden] }
function toDays(data, target = {}, onlyMissing = false, markSet = null) {
  const times = data.hourly.time;
  const key = Object.keys(data.hourly).find((k) => k.startsWith("temperature_2m"));
  const temps = data.hourly[key];
  times.forEach((t, i) => {
    const day = t.slice(0, 10), h = Number(t.slice(11, 13));
    if (temps[i] == null) return;
    if (onlyMissing && target[day] && target[day][h] != null) return;
    (target[day] ||= Array(24).fill(null))[h] = temps[i];
    if (markSet) markSet.add(day);
  });
  return target;
}

async function load(nDays) {
  const status = $("#status");
  status.className = "status";
  status.textContent = "Gegevens laden…";
  $("#days").innerHTML = "";

  const today = todayLocal();
  const start = addDays(today, -(nDays - 1));
  const archiveEnd = addDays(today, -ARCHIVE_DELAY);
  const prevStart = minusYear(start) || minusYear(addDays(start, 1));
  const prevEnd = minusYear(today) || minusYear(addDays(today, -1));

  try {
    const [arcNow, arcPrev, recent] = await Promise.all([
      archiveEnd >= start ? getJSON(ARCHIVE, { start_date: start, end_date: archiveEnd }) : null,
      getJSON(ARCHIVE, { start_date: prevStart, end_date: prevEnd }),
      getJSON(FORECAST, { past_days: RECENT_DAYS, forecast_days: 1, models: "knmi_seamless" }).catch(() => null),
    ]);
    hourlyNow = arcNow ? toDays(arcNow) : {};
    hourlyPrev = toDays(arcPrev);
    provisional = new Set();
    if (recent) toDays(recent, hourlyNow, true, provisional);
    render(start, today);
    status.textContent = "";
  } catch (e) {
    status.className = "status error";
    status.textContent = `Kon de gegevens niet laden: ${e.message}`;
  }
}

// ---------- weergave ----------
const max = (a) => { const v = (a || []).filter((x) => x != null); return v.length ? Math.max(...v) : null; };
const min = (a) => { const v = (a || []).filter((x) => x != null); return v.length ? Math.min(...v) : null; };

function diffHTML(a, b) {
  if (a == null || b == null) return `<span class="diff eq">&nbsp;</span>`;
  const d = a - b;
  const cls = Math.abs(d) < 0.05 ? "eq" : d > 0 ? "up" : "down";
  const sign = d > 0 ? "+" : d < 0 ? "−" : "±";
  return `<span class="diff ${cls}">${sign}${Math.abs(d).toFixed(1)}° t.o.v. vorig jaar</span>`;
}

function render(start, today) {
  const y = Number(today.slice(0, 4));
  $("#lbl-now").textContent = `Dit jaar (${y})`;
  $("#lbl-prev").textContent = `Vorig jaar (${y - 1})`;
  const ul = $("#days");
  ul.innerHTML = "";
  for (let d = today; d >= start; d = addDays(d, -1)) {
    const prevKey = minusYear(d);
    const now = hourlyNow[d], prev = prevKey ? hourlyPrev[prevKey] : null;
    const isToday = d === today;
    const dayNow = max(now), nightNow = min(now), dayPrev = max(prev), nightPrev = min(prev);
    const li = document.createElement("li");
    li.className = "day";
    li.tabIndex = 0;
    li.innerHTML = `
      <div class="date">${niceDate(d, { weekday: "long", day: "numeric", month: "long" })}
        ${isToday ? '<span class="badge">vandaag, deels verwacht</span>' : provisional.has(d) ? '<span class="badge">voorlopig</span>' : ""}
        <small>vergeleken met ${prevKey ? niceDate(prevKey, { weekday: "short", day: "numeric", month: "short", year: "numeric" }) : "– (schrikkeldag)"}</small>
      </div>
      <div class="col"><div class="lbl">☀️ Dag (max)</div>
        <div class="vals"><span class="v-now">${fmtT(dayNow)}</span> / <span class="v-prev">${fmtT(dayPrev)}</span></div>
        ${diffHTML(dayNow, dayPrev)}</div>
      <div class="col"><div class="lbl">🌙 Nacht (min)</div>
        <div class="vals"><span class="v-now">${fmtT(nightNow)}</span> / <span class="v-prev">${fmtT(nightPrev)}</span></div>
        ${diffHTML(nightNow, nightPrev)}</div>`;
    const open = () => showDetail(d, prevKey, isToday);
    li.addEventListener("click", open);
    li.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    ul.appendChild(li);
  }
}

function showDetail(day, prevKey, isToday) {
  const now = hourlyNow[day] || Array(24).fill(null);
  const prev = (prevKey && hourlyPrev[prevKey]) || Array(24).fill(null);
  const css = getComputedStyle(document.documentElement);
  const cNow = css.getPropertyValue("--now").trim(), cPrev = css.getPropertyValue("--prev").trim();
  const cText = css.getPropertyValue("--muted").trim(), cGrid = css.getPropertyValue("--border").trim();

  $("#detail-title").textContent = niceDate(day, { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#detail-summary").innerHTML = `
    <span><b style="color:${cNow}">${day.slice(0, 4)}</b>: max ${fmtT(max(now))}, min ${fmtT(min(now))}</span>
    <span><b style="color:${cPrev}">${prevKey ? prevKey.slice(0, 4) : "–"}</b>: max ${fmtT(max(prev))}, min ${fmtT(min(prev))}</span>`;
  $("#detail-note").textContent = isToday
    ? "Vandaag: de rest van de dag is een verwachting van het KNMI-model."
    : provisional.has(day) ? "Voorlopige waarden (KNMI HARMONIE-model); het definitieve archief volgt na enkele dagen." : "";

  chart?.destroy();
  chart = new Chart($("#chart"), {
    type: "line",
    data: {
      labels: Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`),
      datasets: [
        { label: day.slice(0, 4), data: now, borderColor: cNow, backgroundColor: cNow, tension: 0.35, pointRadius: 2, borderWidth: 2.5 },
        { label: prevKey ? prevKey.slice(0, 4) : "vorig jaar", data: prev, borderColor: cPrev, backgroundColor: cPrev, tension: 0.35, pointRadius: 2, borderWidth: 2, borderDash: [6, 4] },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: cText, usePointStyle: true, pointStyle: "line" } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${fmtT(c.parsed.y)}` } },
      },
      scales: {
        x: { ticks: { color: cText, maxTicksLimit: 12 }, grid: { color: cGrid } },
        y: { ticks: { color: cText, callback: (v) => `${v}°` }, grid: { color: cGrid }, title: { display: true, text: "°C", color: cText } },
      },
    },
  });
  $("#detail").showModal();
}

$("#close").addEventListener("click", () => $("#detail").close());
$("#detail").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });
$("#range").addEventListener("change", (e) => load(Number(e.target.value)));
load(Number($("#range").value));

// ---------- installeerbare app (PWA) ----------
if ("serviceWorker" in navigator && location.protocol !== "file:") {
  navigator.serviceWorker.register("sw.js");
}
let installPrompt;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  $("#install").hidden = false;
});
$("#install").addEventListener("click", async () => {
  if (!installPrompt) return;
  installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  $("#install").hidden = true;
});
