"use strict";

// ---------- hulpjes ----------
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function hms(sec) {
  sec = Math.max(0, Math.floor(sec || 0));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: opts.body ? { "Content-Type": "application/json" } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* geen JSON */ }
  if (!res.ok) throw new Error((data && data.detail) || `Fout ${res.status}`);
  return data;
}

const STATUS = {
  queued: "In de wachtrij",
  downloading: "Downloaden",
  extracting: "Uitpakken",
  analyzing: "Analyseren",
  done: "Klaar",
  error: "Fout",
};
const ACTIVE = new Set(["queued", "downloading", "extracting", "analyzing"]);
const STAGES = [
  ["download", "Video downloaden"],
  ["extract", "Audio en beelden uitpakken"],
  ["transcript", "Spraak omzetten naar tekst"],
  ["audio", "Geluiden herkennen (lachen, schreeuwen, …)"],
  ["vision", "Beelden bekijken met AI"],
];
const EXAMPLES = [
  "Geef alle momenten waarop hij moet lachen",
  "Wanneer begint de eerste missie?",
  "Wanneer gaat hij dood of verliest hij?",
  "Geef een overzicht van de belangrijkste momenten",
  "Wanneer reageert hij geschrokken?",
];
const LAUGH = new Set(["Laughter", "Baby laughter", "Giggle", "Snicker", "Belly laugh", "Chuckle, chortle"]);
const SOUND_NL = {
  Laughter: "Lachen", Giggle: "Giechelen", Snicker: "Grinniken", "Belly laugh": "Bulderlach",
  "Chuckle, chortle": "Grinniken", Screaming: "Schreeuwen", Shout: "Roepen", Yell: "Schreeuwen",
  Applause: "Applaus", Cheering: "Gejuich", Music: "Muziek", Gunshot: "Schoten",
  "Gunshot, gunfire": "Schoten", Explosion: "Explosie", "Crying, sobbing": "Huilen", Singing: "Zingen",
  Whoop: "Joelen", Clapping: "Klappen", Sigh: "Zuchten", Gasp: "Naar adem happen", Cough: "Hoesten",
  Burping: "Boeren", "Burping, eructation": "Boeren", Dog: "Hond", Bark: "Blaffen", Cat: "Kat", Meow: "Miauw",
  "Video game music": "Gamemuziek", Speech: "Spraak", Whistling: "Fluiten", Siren: "Sirene", Thunder: "Onweer",
  "Glass": "Glas", Shatter: "Brekend glas", Bang: "Knal", Slam: "Klap", Knock: "Kloppen", Telephone: "Telefoon",
  Typing: "Typen", "Computer keyboard": "Toetsenbord", Engine: "Motor", Car: "Auto", Vehicle: "Voertuig",
};

// ---------- toestand ----------
const state = {
  status: null,
  videos: [],
  selected: null,
  player: null,
  timeline: {},       // id -> {transcript, audio_events, frames}
  timelineStamp: {},  // id -> status bij het ophalen
  pollTimer: null,
};

// ---------- start ----------
document.addEventListener("DOMContentLoaded", async () => {
  $("#add-form").addEventListener("submit", onAdd);
  window.addEventListener("hashchange", () => selectFromHash());
  try {
    state.status = await api("/api/status");
    renderWarnings();
  } catch (e) { console.error(e); }
  await refreshList();
  selectFromHash();
  schedulePoll();
});

function renderWarnings() {
  const box = $("#warnings");
  box.replaceChildren();
  const s = state.status;
  if (!s) return;
  if (!s.has_api_key) {
    box.append(el("div", { class: "warning" },
      el("strong", { text: "Geen API-sleutel ingesteld. " }),
      "Zonder sleutel kan de AI de beelden niet bekijken en kun je niet slim zoeken. Zet ",
      el("code", { text: "ANTHROPIC_API_KEY=…" }), " in het bestand ", el("code", { text: ".env" }),
      " en start de app opnieuw."));
  }
  if (!s.ffmpeg) {
    box.append(el("div", { class: "warning" },
      el("strong", { text: "ffmpeg ontbreekt. " }), "Installeer ffmpeg (zie de README) en start de app opnieuw."));
  }
}

async function onAdd(ev) {
  ev.preventDefault();
  const input = $("#url"), btn = $("#add-btn"), msg = $("#add-msg");
  const url = input.value.trim();
  if (!url) return;
  btn.disabled = true;
  msg.className = "hint";
  msg.textContent = "Link controleren…";
  try {
    const meta = await api("/api/videos", { method: "POST", body: { url } });
    input.value = "";
    msg.textContent = "Toegevoegd! De analyse loopt op de achtergrond.";
    await refreshList();
    location.hash = `#/v/${meta.id}`;
  } catch (e) {
    msg.className = "hint error";
    msg.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

// ---------- lijst ----------
async function refreshList() {
  try {
    state.videos = await api("/api/videos");
  } catch (e) {
    console.error(e);
    return;
  }
  renderList();
  if (state.selected) {
    const meta = state.videos.find((v) => v.id === state.selected);
    if (meta) updateDetail(meta);
    else { state.selected = null; location.hash = ""; resetDetail(); }
  }
}

function schedulePoll() {
  clearTimeout(state.pollTimer);
  const busy = state.videos.some((v) => ACTIVE.has(v.status));
  state.pollTimer = setTimeout(async () => { await refreshList(); schedulePoll(); }, busy ? 2000 : 10000);
}

function overallProgress(v) {
  const p = v.progress || {};
  const parts = STAGES.map(([k]) => p[k] || 0);
  return parts.reduce((a, b) => a + b, 0) / parts.length;
}

function renderList() {
  const list = $("#video-list");
  list.replaceChildren();
  $("#empty-list").hidden = state.videos.length > 0;
  for (const v of state.videos) {
    const active = ACTIVE.has(v.status);
    const item = el("li", { class: `video-item ${v.id === state.selected ? "selected" : ""}` },
      el("a", { href: `#/v/${v.id}` },
        v.thumbnail ? el("img", { src: v.thumbnail, alt: "", loading: "lazy", referrerpolicy: "no-referrer" })
          : el("div", { class: "thumb-placeholder" }),
        el("div", { class: "vi-text" },
          el("span", { class: "vi-title", text: v.title }),
          el("span", { class: "vi-meta" },
            el("span", { class: `pill ${v.status}`, text: STATUS[v.status] || v.status }),
            el("span", { class: "muted", text: `${platformName(v.platform)} · ${hms(v.duration)}` })),
          active ? el("div", { class: "bar thin" }, el("span", { style: `width:${Math.round(overallProgress(v) * 100)}%` })) : null)));
    list.append(item);
  }
}

function platformName(p) {
  return { youtube: "YouTube", twitch: "Twitch" }[p] || "Video";
}

// ---------- detail ----------
function selectFromHash() {
  const m = location.hash.match(/^#\/v\/([A-Za-z0-9_-]+)/);
  const id = m ? m[1] : null;
  if (id === state.selected) return;
  state.selected = id;
  renderList();
  if (!id) { resetDetail(); return; }
  const meta = state.videos.find((v) => v.id === id);
  if (!meta) { resetDetail(); return; }
  mountDetail(meta);
  if (window.matchMedia("(max-width: 900px)").matches) $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

let welcomeHTML = null;
function resetDetail() {
  const d = $("#detail");
  if (welcomeHTML === null) welcomeHTML = d.innerHTML;
  d.innerHTML = welcomeHTML;
  state.player = null;
}

function mountDetail(meta) {
  const d = $("#detail");
  if (welcomeHTML === null) welcomeHTML = d.innerHTML;
  d.replaceChildren($("#detail-tpl").content.cloneNode(true));
  d.dataset.id = meta.id;

  $(".v-retry", d).addEventListener("click", async () => {
    try { await api(`/api/videos/${meta.id}/retry`, { method: "POST" }); await refreshList(); schedulePoll(); }
    catch (e) { alert(e.message); }
  });
  $(".v-delete", d).addEventListener("click", async () => {
    if (!confirm(`“${meta.title}” en alle zoekresultaten verwijderen?`)) return;
    try { await api(`/api/videos/${meta.id}`, { method: "DELETE" }); location.hash = ""; await refreshList(); }
    catch (e) { alert(e.message); }
  });

  // tabbladen
  for (const tab of $$(".tabs button", d)) {
    tab.addEventListener("click", () => {
      $$(".tabs button", d).forEach((b) => b.classList.toggle("active", b === tab));
      $$(".tab-panel", d).forEach((p) => { p.hidden = p.dataset.panel !== tab.dataset.tab; });
      if (tab.dataset.tab !== "search") ensureTimeline(meta.id, true);
    });
  }

  // zoeken
  const form = $(".search-form", d);
  form.addEventListener("submit", (ev) => { ev.preventDefault(); runSearch(meta.id, $(".q", d).value); });
  const ex = $(".examples", d);
  for (const q of EXAMPLES) {
    ex.append(el("button", { class: "chip", type: "button", text: q, onclick: () => { $(".q", d).value = q; runSearch(meta.id, q); } }));
  }

  $(".filter", d).addEventListener("input", debounce(() => renderTranscript(meta.id), 200));
  for (const chip of $$(".timeline-filter .chip", d)) {
    chip.addEventListener("click", () => {
      $$(".timeline-filter .chip", d).forEach((c) => c.classList.toggle("active", c === chip));
      renderTimeline(meta.id);
    });
  }

  state.player = createPlayer($("#player", d), meta);
  updateDetail(meta);
  loadHistory(meta.id);
}

function updateDetail(meta) {
  const d = $("#detail");
  if (d.dataset.id !== meta.id) return;
  $(".v-title", d).textContent = meta.title;
  const bits = [platformName(meta.platform)];
  if (meta.uploader) bits.push(meta.uploader);
  if (meta.duration) bits.push(hms(meta.duration));
  if (meta.cost_estimate != null) bits.push(`AI-kosten ≈ $${meta.cost_estimate.toFixed(2)}`);
  $(".v-sub", d).textContent = bits.join(" · ");
  const open = $(".v-open", d);
  open.href = meta.url;
  open.textContent = meta.platform === "other" ? "Origineel openen" : `Openen op ${platformName(meta.platform)}`;
  $(".v-retry", d).hidden = meta.status !== "error";

  renderProgress(meta);

  // Tijdlijn verversen als er nieuwe resultaten zijn.
  const stamp = `${meta.status}:${Math.round(overallProgress(meta) * 20)}`;
  if (state.timeline[meta.id] && state.timelineStamp[meta.id] !== stamp && (meta.status === "done" || meta.status === "error")) {
    ensureTimeline(meta.id, true);
  } else if (!state.timeline[meta.id]) {
    ensureTimeline(meta.id, false);
  }
}

function renderProgress(meta) {
  const box = $(".v-progress");
  box.replaceChildren();
  const p = meta.progress || {}, notes = meta.notes || {};
  if (meta.status === "done") {
    box.classList.add("compact");
    box.append(el("p", { class: "done-line" },
      el("span", { class: "pill done", text: "Klaar" }),
      " De video is geanalyseerd. Stel hieronder je vraag.",
      notes.transcript ? el("span", { class: "muted", text: ` Spraak: ${notes.transcript}.` }) : null,
      notes.audio ? el("span", { class: "muted", text: ` Geluid: ${notes.audio}.` }) : null,
      notes.vision ? el("span", { class: "muted", text: ` Beeld: ${notes.vision}.` }) : null));
    return;
  }
  box.classList.remove("compact");
  box.append(el("div", { class: "progress-head" },
    el("span", { class: `pill ${meta.status}`, text: STATUS[meta.status] || meta.status }),
    meta.status === "queued" ? el("span", { class: "muted", text: "Wacht tot de vorige video klaar is…" }) : null));
  if (meta.status === "error" && meta.error) {
    box.append(el("p", { class: "error-box", text: meta.error }));
  }
  for (const [key, label] of STAGES) {
    const v = p[key] || 0;
    box.append(el("div", { class: "stage" },
      el("div", { class: "stage-label" }, el("span", { text: label }), el("span", { class: "muted", text: `${Math.round(v * 100)}%` })),
      el("div", { class: "bar" }, el("span", { style: `width:${Math.round(v * 100)}%` })),
      notes[key] ? el("div", { class: "stage-note muted", text: notes[key] }) : null));
  }
  if (ACTIVE.has(meta.status)) {
    box.append(el("p", { class: "muted small", text: "Je kunt al zoeken in wat er tot nu toe is geanalyseerd. Lange streams kunnen een tijd duren, vooral het omzetten van spraak zonder grafische kaart." }));
  }
}

// ---------- speler ----------
let ytReady = null;
function loadYouTubeAPI() {
  if (!ytReady) {
    ytReady = new Promise((resolve) => {
      window.onYouTubeIframeAPIReady = () => resolve(window.YT);
      document.head.append(el("script", { src: "https://www.youtube.com/iframe_api" }));
    });
  }
  return ytReady;
}

let twitchReady = null;
function loadTwitchAPI() {
  if (!twitchReady) {
    twitchReady = new Promise((resolve, reject) => {
      const s = el("script", { src: "https://player.twitch.tv/js/embed/v1.js" });
      s.onload = () => resolve(window.Twitch);
      s.onerror = reject;
      document.head.append(s);
    });
  }
  return twitchReady;
}

function createPlayer(container, meta) {
  const player = { seek: () => {}, ready: false };
  const pending = { t: null };

  if (meta.platform === "youtube" && meta.platform_id) {
    const target = el("div");
    container.append(target);
    loadYouTubeAPI().then((YT) => {
      const yt = new YT.Player(target, {
        videoId: meta.platform_id,
        playerVars: { rel: 0, playsinline: 1, origin: location.origin },
        events: {
          onReady: () => {
            player.ready = true;
            if (pending.t !== null) { yt.seekTo(pending.t, true); yt.playVideo(); }
          },
        },
      });
      player.seek = (t) => {
        if (!player.ready) { pending.t = t; return; }
        yt.seekTo(t, true); yt.playVideo();
      };
    });
    player.seek = (t) => { pending.t = t; };
  } else if (meta.platform === "twitch" && meta.platform_id) {
    const target = el("div", { id: `tw-${meta.id}` });
    container.append(target);
    const vid = meta.platform_id.startsWith("v") ? meta.platform_id : `v${meta.platform_id}`;
    player.seek = (t) => { pending.t = t; };
    loadTwitchAPI().then((Twitch) => {
      const tw = new Twitch.Player(target.id, { video: vid, parent: [location.hostname], autoplay: false, width: "100%", height: "100%" });
      tw.addEventListener(Twitch.Player.READY, () => {
        player.ready = true;
        if (pending.t !== null) { tw.seek(pending.t); tw.play(); }
      });
      player.seek = (t) => {
        if (!player.ready) { pending.t = t; return; }
        tw.seek(t); tw.play();
      };
    }).catch(() => {
      container.replaceChildren(el("p", { class: "muted pad", text: "De Twitch-speler kon niet laden. Gebruik de links bij de resultaten." }));
    });
  } else if (meta.has_file) {
    const video = el("video", { src: `/api/videos/${meta.id}/file`, controls: true, preload: "metadata" });
    container.append(video);
    player.seek = (t) => { video.currentTime = t; video.play().catch(() => {}); };
  } else {
    container.classList.add("no-player");
    container.append(el("p", { class: "muted pad", text: "Voor deze video is er geen ingebouwde speler. Gebruik de links bij de resultaten." }));
  }
  return player;
}

function seekTo(t) {
  if (state.player) state.player.seek(t);
  const wrap = $(".player-wrap");
  if (wrap && wrap.getBoundingClientRect().top < 0) wrap.scrollIntoView({ behavior: "smooth", block: "start" });
}

function externalLink(meta, t) {
  t = Math.max(0, Math.floor(t));
  if (meta.platform === "youtube") return `https://www.youtube.com/watch?v=${encodeURIComponent(meta.platform_id)}&t=${t}s`;
  if (meta.platform === "twitch") {
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    return `https://www.twitch.tv/videos/${meta.platform_id.replace(/^v/, "")}?t=${h}h${m}m${s}s`;
  }
  return meta.url;
}

function timeButton(start, end) {
  const label = end && end - start >= 2 ? `${hms(start)} – ${hms(end)}` : hms(start);
  return el("button", { class: "time", type: "button", title: "Spring naar dit moment", onclick: () => seekTo(Math.max(0, start - 1)) },
    el("span", { class: "play", "aria-hidden": "true" }), label);
}

// ---------- slim zoeken ----------
async function runSearch(id, query) {
  query = (query || "").trim();
  if (!query) return;
  const d = $("#detail");
  const results = $(".results", d);
  const btn = $(".search-form button", d);
  btn.disabled = true;
  results.replaceChildren(el("div", { class: "card searching" },
    el("span", { class: "spinner", "aria-hidden": "true" }),
    el("div", {}, el("strong", { text: "Claude doorzoekt de video…" }),
      el("p", { class: "muted small", text: "Bij lange streams kan dit tot een minuut duren. Volgende vragen over dezelfde video gaan sneller." }))));
  try {
    const record = await api(`/api/videos/${id}/search`, { method: "POST", body: { query } });
    if (d.dataset.id !== id) return;
    renderResults(id, record);
    loadHistory(id);
    refreshList();
  } catch (e) {
    if (d.dataset.id === id) results.replaceChildren(el("p", { class: "error-box", text: e.message }));
  } finally {
    btn.disabled = false;
  }
}

function confidenceLabel(c) {
  return { high: "zeker", medium: "waarschijnlijk", low: "misschien" }[c] || c;
}

function renderResults(id, record) {
  const meta = state.videos.find((v) => v.id === id) || {};
  const box = $("#detail .results");
  box.replaceChildren();
  box.append(el("div", { class: "answer card" },
    el("p", { class: "q-echo muted small", text: `“${record.query}”` }),
    el("p", { class: "answer-text", text: record.answer || "" }),
    el("p", { class: "muted small", text: `${record.results.length} ${record.results.length === 1 ? "moment" : "momenten"} gevonden${record.seconds ? ` in ${record.seconds} s` : ""}.` })));
  const list = el("ol", { class: "result-list" });
  for (const r of record.results) {
    list.append(el("li", { class: "result card" },
      r.frame ? el("button", { class: "thumb", type: "button", onclick: () => seekTo(Math.max(0, r.start - 1)), "aria-label": "Spring naar dit moment" },
        el("img", { src: `/api/videos/${id}/frames/${r.frame}`, alt: "", loading: "lazy" })) : null,
      el("div", { class: "r-body" },
        el("div", { class: "r-top" },
          timeButton(r.start, r.end),
          el("span", { class: `conf ${r.confidence}`, text: confidenceLabel(r.confidence) })),
        el("h4", { text: r.title }),
        el("p", { text: r.explanation }),
        meta.platform !== "other" ? el("a", { class: "small", href: externalLink(meta, r.start), target: "_blank", rel: "noopener", text: `Open op ${platformName(meta.platform)} bij ${hms(r.start)}` }) : null)));
  }
  box.append(list);
}

async function loadHistory(id) {
  let items = [];
  try { items = await api(`/api/videos/${id}/searches`); } catch { return; }
  const d = $("#detail");
  if (d.dataset.id !== id) return;
  const box = $(".history", d);
  box.replaceChildren();
  if (!items.length) return;
  box.append(el("h3", { class: "mini-title", text: "Eerdere zoekvragen" }));
  const ul = el("ul", { class: "history-list" });
  for (const rec of items.slice(0, 30)) {
    ul.append(el("li", {}, el("button", { type: "button", class: "link", onclick: () => { $(".q", d).value = rec.query; renderResults(id, rec); window.scrollTo({ top: $(".results", d).offsetTop - 80, behavior: "smooth" }); } },
      rec.query), el("span", { class: "muted small", text: ` · ${rec.results.length} momenten` })));
  }
  box.append(ul);
}

// ---------- tijdlijn, transcript, geluiden ----------
async function ensureTimeline(id, force) {
  if (state.timeline[id] && !force) { renderLocal(id); return; }
  try {
    state.timeline[id] = await api(`/api/videos/${id}/timeline`);
    const meta = state.videos.find((v) => v.id === id);
    if (meta) state.timelineStamp[id] = `${meta.status}:${Math.round(overallProgress(meta) * 20)}`;
  } catch (e) { console.error(e); return; }
  renderLocal(id);
}

function renderLocal(id) {
  if ($("#detail").dataset.id !== id) return;
  renderSoundChips(id);
  renderTranscript(id);
  renderTimeline(id);
}

function renderSoundChips(id) {
  const data = state.timeline[id];
  const box = $("#detail .sounds");
  if (!box) return;
  box.replaceChildren();
  const events = (data && data.audio_events) || [];
  const quick = $("#detail .quick");
  if (!events.length) {
    quick.hidden = !data || !data.transcript.length;
    box.append(el("span", { class: "muted small", text: "Nog geen geluiden herkend." }));
    return;
  }
  quick.hidden = false;
  const laughs = events.filter((e) => LAUGH.has(e.label));
  const groups = new Map();
  for (const e of events) {
    if (LAUGH.has(e.label)) continue;
    if (!groups.has(e.label)) groups.set(e.label, []);
    groups.get(e.label).push(e);
  }
  const chips = [];
  if (laughs.length) chips.push(["😂 Lachen", laughs]);
  [...groups.entries()].sort((a, b) => b[1].length - a[1].length).slice(0, 14)
    .forEach(([label, evs]) => chips.push([SOUND_NL[label] ? `${SOUND_NL[label]} (${label})` : label, evs]));
  for (const [label, evs] of chips) {
    box.append(el("button", { class: "chip", type: "button", onclick: () => showSoundResults(id, label, evs) },
      label, el("span", { class: "count", text: evs.length })));
  }
}

function showSoundResults(id, label, events) {
  const meta = state.videos.find((v) => v.id === id) || {};
  const merged = [];
  for (const e of [...events].sort((a, b) => a.start - b.start)) {
    const last = merged[merged.length - 1];
    const kinds = (e.kinds && e.kinds.length ? e.kinds : [e.label]).map((k) => SOUND_NL[k] || k);
    if (last && e.start <= last.end + 2) { last.end = Math.max(last.end, e.end); last.score = Math.max(last.score, e.score); kinds.forEach((k) => last.labels.add(k)); }
    else merged.push({ start: e.start, end: e.end, score: e.score, labels: new Set(kinds) });
  }
  const box = $("#detail .results");
  box.replaceChildren(el("div", { class: "answer card" },
    el("p", { class: "answer-text", text: `${label}: ${merged.length} ${merged.length === 1 ? "moment" : "momenten"} gevonden door de geluidsherkenning.` }),
    el("p", { class: "muted small", text: "Dit komt rechtstreeks uit het geluidsmodel. Wil je het preciezer (bijv. alleen de maker zelf)? Vraag het dan via slim zoeken." })));
  const list = el("ol", { class: "result-list compact" });
  for (const m of merged) {
    list.append(el("li", { class: "result card" },
      el("div", { class: "r-body" },
        el("div", { class: "r-top" }, timeButton(m.start, m.end),
          el("span", { class: "conf", text: `${Math.round(m.score * 100)}%` }),
          el("span", { class: "muted small", text: [...m.labels].join(", ") })),
        meta.platform !== "other" ? el("a", { class: "small", href: externalLink(meta, m.start), target: "_blank", rel: "noopener", text: `Open op ${platformName(meta.platform)}` }) : null)));
  }
  box.append(list);
}

function renderTranscript(id) {
  const data = state.timeline[id];
  const d = $("#detail");
  const ul = $(".transcript-lines", d);
  if (!ul) return;
  const q = $(".filter", d).value.trim().toLowerCase();
  const segs = (data && data.transcript) || [];
  const matches = q ? segs.filter((s) => s.text.toLowerCase().includes(q)) : segs;
  $(".t-count", d).textContent = !segs.length ? "Nog geen transcript."
    : q ? `${matches.length} van ${segs.length} zinnen bevatten “${q}”.` : `${segs.length} zinnen.`;
  ul.replaceChildren();
  for (const s of matches.slice(0, 3000)) {
    ul.append(el("li", {}, timeButton(s.start), el("span", { class: "line-text" }, highlight(s.text, q))));
  }
  if (matches.length > 3000) ul.append(el("li", { class: "muted small", text: "… gebruik het zoekveld om de rest te vinden." }));
}

function highlight(text, q) {
  if (!q) return text;
  const out = [];
  const lower = text.toLowerCase();
  let i = 0;
  while (true) {
    const j = lower.indexOf(q, i);
    if (j < 0) { out.push(text.slice(i)); break; }
    out.push(text.slice(i, j), el("mark", { text: text.slice(j, j + q.length) }));
    i = j + q.length;
  }
  return out;
}

function renderTimeline(id) {
  const data = state.timeline[id];
  const d = $("#detail");
  const ul = $(".timeline-lines", d);
  if (!ul || !data) return;
  const kind = ($(".timeline-filter .chip.active", d) || {}).dataset?.kind || "all";
  const items = [];
  if (kind === "all" || kind === "say") data.transcript.forEach((s) => items.push({ t: s.start, kind: "say", text: s.text }));
  if (kind === "all" || kind === "sound") data.audio_events.forEach((e) => items.push({ t: e.start, end: e.end, kind: "sound", text: `${SOUND_NL[e.label] || e.label} (${Math.round(e.score * 100)}%)` }));
  if (kind === "all" || kind === "see") data.frames.forEach((f) => items.push({ t: f.t, kind: "see", text: f.description + (f.text ? ` — tekst in beeld: “${f.text}”` : ""), frame: f.file }));
  items.sort((a, b) => a.t - b.t);
  ul.replaceChildren();
  const label = { say: "spraak", sound: "geluid", see: "beeld" };
  for (const it of items.slice(0, 4000)) {
    ul.append(el("li", { class: `k-${it.kind}` }, timeButton(it.t, it.end), el("span", { class: `kind ${it.kind}`, text: label[it.kind] }), el("span", { class: "line-text", text: it.text })));
  }
  if (!items.length) ul.append(el("li", { class: "muted small", text: "Nog niets geanalyseerd." }));
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}
