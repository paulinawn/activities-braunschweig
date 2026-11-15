"use strict";

const CAT_ICONS = {
  "Tanz & Ballett": "💃",
  "Theater & Oper": "🎭",
  "Musik & Konzerte": "🎻",
  "Wandern & Natur": "🥾",
  "Rad & Bewegung": "🚲",
  "Ausstellungen & Kunst": "🖼️",
  "Führungen & Vorträge": "🏛️",
  "Kurse zum Mitmachen": "✋",
  "Feste & Märkte": "🎪",
  "Ausflüge & Reisen": "🧭",
  "Film": "🎬",
};
const MONTHS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const MON_SHORT = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"];
const DOW = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

const state = { month: null, cat: null, region: null, q: "", top: false, fresh: false };
let events = [];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const parseDate = (s) => { const [y, m, d] = s.split("-").map(Number); return new Date(y, m - 1, d); };
const monthKey = (s) => s.slice(0, 7);
const monthLabel = (key) => { const [y, m] = key.split("-").map(Number); return `${MONTHS[m - 1]} ${y}`; };
const fmtDate = (s) => { const d = parseDate(s); return `${DOW[d.getDay()]}, ${d.getDate()}. ${MONTHS[d.getMonth()]}`; };
const safeUrl = (u) => (/^https?:\/\//.test(u || "") ? u : "");
const daysAgo = (iso) => (Date.now() - parseDate(iso).getTime()) / 86400000;

function matches(ev, ignore) {
  if (ignore !== "month" && state.month && monthKey(ev.date_start) !== state.month) return false;
  if (ignore !== "cat" && state.cat && ev.category !== state.cat) return false;
  if (ignore !== "region" && state.region && ev.region !== state.region) return false;
  if (state.top && ev.relevance < 4) return false;
  if (state.fresh && !(ev.first_seen && daysAgo(ev.first_seen) <= 7)) return false;
  if (state.q) {
    const hay = [ev.title, ev.summary, ev.why, ev.venue, ev.city, ev.category, ev.region].join(" ").toLowerCase();
    if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function renderChips(containerId, key, values, labelFn) {
  const el = $(containerId);
  const counts = {};
  events.filter((e) => matches(e, key)).forEach((e) => {
    const v = key === "month" ? monthKey(e.date_start) : e[key === "cat" ? "category" : "region"];
    counts[v] = (counts[v] || 0) + 1;
  });
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const chip = (value, label, n) =>
    `<button type="button" class="chip" data-v="${esc(value ?? "")}" aria-pressed="${state[key] === value}">${label}<span class="n">${n}</span></button>`;
  el.innerHTML = chip(null, "Alle", total) + values.map((v) => chip(v, labelFn(v), counts[v] || 0)).join("");
  el.querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
    const v = b.dataset.v || null;
    state[key] = state[key] === v ? null : v;
    render();
  }));
}

function card(ev) {
  const d = parseDate(ev.date_start);
  const isNew = ev.first_seen && daysAgo(ev.first_seen) <= 7;
  const stars = "★".repeat(ev.relevance) + "☆".repeat(5 - ev.relevance);
  const range = ev.date_end && ev.date_end !== ev.date_start ? ` bis ${fmtDate(ev.date_end)}` : "";
  const where = [ev.time && `${ev.time} Uhr`, ev.venue, ev.city].filter(Boolean).map(esc).join(" · ");
  const url = safeUrl(ev.url);
  const booking = safeUrl(ev.booking_url);
  const more = (ev.other_dates || []).length
    ? `<details class="more"><summary>Weitere Termine (${ev.other_dates.length})</summary>${ev.other_dates.map(fmtDate).join(" · ")}</details>`
    : "";
  return `<article class="card">
    <div class="date" aria-hidden="true"><span class="dow">${DOW[d.getDay()]}</span><span class="day">${d.getDate()}.</span><span class="mon">${MON_SHORT[d.getMonth()]}</span></div>
    <div>
      <div class="meta-top">
        <span class="tag">${CAT_ICONS[ev.category] || ""} ${esc(ev.category)}</span>
        <span>${esc(ev.region)}</span>
        <span class="stars" title="Empfehlung: ${ev.relevance} von 5">${stars}</span>
        ${isNew ? '<span class="badge-new">Neu</span>' : ""}
      </div>
      <h3>${esc(ev.title)}</h3>
      <p class="where">${esc(fmtDate(ev.date_start))}${esc(range)}${where ? " · " + where : ""}</p>
      <p class="summary">${esc(ev.summary)}</p>
      ${ev.why ? `<p class="why"><strong>Warum für euch:</strong> ${esc(ev.why)}</p>` : ""}
      <div class="actions">
        ${booking ? `<a class="btn primary" href="${esc(booking)}" target="_blank" rel="noopener">Tickets &amp; Anmeldung ↗</a>` : ""}
        ${url ? `<a class="btn${booking ? "" : " primary"}" href="${esc(url)}" target="_blank" rel="noopener">Mehr erfahren ↗</a>` : ""}
        ${ev.price ? `<span class="price">${esc(ev.price)}</span>` : ""}
      </div>
      ${more}
    </div>
  </article>`;
}

function render() {
  const months = [...new Set(events.map((e) => monthKey(e.date_start)))].sort();
  const cats = Object.keys(CAT_ICONS).filter((c) => events.some((e) => e.category === c));
  const regions = [...new Set(events.map((e) => e.region))].sort((a, b) => (a === "Braunschweig" ? -1 : b === "Braunschweig" ? 1 : a.localeCompare(b, "de")));

  renderChips("f-month", "month", months, monthLabel);
  renderChips("f-cat", "cat", cats, (c) => `${CAT_ICONS[c]} ${esc(c)}`);
  renderChips("f-region", "region", regions, esc);

  const shown = events.filter((e) => matches(e));
  $("count").textContent = `${shown.length} ${shown.length === 1 ? "Tipp" : "Tipps"}`;

  if (!shown.length) {
    $("list").innerHTML = events.length
      ? '<p class="empty">Keine Treffer für diese Auswahl. <br>Probiert einen anderen Filter oder setzt alle zurück.</p>'
      : '<p class="empty">Noch keine Tipps vorhanden – die erste Auswahl erscheint nach dem nächsten Freitags-Lauf.</p>';
    return;
  }
  let html = "";
  let current = "";
  for (const ev of shown) {
    const key = monthKey(ev.date_start);
    if (key !== current) {
      html += `<h2 class="month-title">${monthLabel(key)}</h2>`;
      current = key;
    }
    html += card(ev);
  }
  $("list").innerHTML = html;
}

function bind() {
  let t;
  $("q").addEventListener("input", (e) => { clearTimeout(t); t = setTimeout(() => { state.q = e.target.value.trim(); render(); }, 150); });
  $("f-top").addEventListener("change", (e) => { state.top = e.target.checked; render(); });
  $("f-new").addEventListener("change", (e) => { state.fresh = e.target.checked; render(); });
  $("reset").addEventListener("click", () => {
    Object.assign(state, { month: null, cat: null, region: null, q: "", top: false, fresh: false });
    $("q").value = ""; $("f-top").checked = false; $("f-new").checked = false;
    render();
  });
}

async function init() {
  bind();
  try {
    const res = await fetch(`data/events.json?v=${Date.now()}`);
    const data = await res.json();
    const today = new Date(); today.setHours(0, 0, 0, 0);
    events = (data.events || []).filter((e) => parseDate(e.date_end || e.date_start) >= today);
    if (data.updated) {
      const u = new Date(data.updated);
      $("updated").textContent = `Zuletzt aktualisiert: ${u.getDate()}. ${MONTHS[u.getMonth()]} ${u.getFullYear()}`;
    }
  } catch (err) {
    events = [];
  }
  render();
}

init();
