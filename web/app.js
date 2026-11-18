// Watchfloor web app: a static page over the public API (pipeline/api.py). No build step, no dependencies.
// Every string from the API is inserted as text (never as HTML): headlines are third-party content.

// On localhost the site reads scripts/dev_server.py's local API instead of the cloud one.
const API = ["localhost", "127.0.0.1"].includes(location.hostname) ? `${location.origin}/api` : "https://mc-api-odg3xhcd4a-uc.a.run.app";
const COST_PER_STORY = 0.0002; // measured 26 Oct 2026: $0.0049 for 25 stories

const app = document.getElementById("app");
let ENTITIES = null;

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function call(path, opts) {
  const r = await fetch(API + path, opts);
  let body = {};
  try { body = await r.json(); } catch (_) { /* empty or not JSON */ }
  if (!r.ok) {
    const e = new Error(body.error || `HTTP ${r.status}`);
    e.status = r.status; e.body = body;
    throw e;
  }
  return body;
}
const get = (path) => call(path);
const post = (path, data) => call(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });

// Times follow the viewer's setting (tic-time.js: their own zone by default, or Zulu or any zone they pick).
const when = (iso) => (iso ? window.TicTime.format(iso) : "—");
const stampIso = (s) => (s ? `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T${s.slice(8, 10)}:${s.slice(10, 12)}:00Z` : null);
function dayLabel(d) {
  const [y, m, dd] = d.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, dd)).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
}
const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 100)}%`);
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//.test(u) ? u : null);

async function entities() {
  if (!ENTITIES) ENTITIES = await get("/entities");
  return ENTITIES;
}

function setNav(name) {
  for (const a of document.querySelectorAll("nav a")) a.classList.toggle("on", a.dataset.nav === name);
}

function show(...nodes) {
  app.replaceChildren(...nodes.flat(Infinity).filter((n) => n !== null && n !== undefined && n !== false));
  window.scrollTo(0, 0);
}

function fail(e) {
  show(h("h1", null, "Something went wrong"), h("p", { class: "err" }, e.message || String(e)),
    h("p", { class: "muted" }, "The data service may be waking up. Try again in a moment."));
}

// ---------- Zones (home) ----------
// Since the z calibration (16 Nov 2026) a score carries z_method and ratio_shown: count / max(expected, 90-day
// median, 3); `floored` means the floor of 3 bound, so the count is shown against "usually 3 or fewer". Every stored
// day was re-scored on 17 Nov 2026, so tooltips say plain "z" (they said "calibrated z" from 16 to 17 Nov).
function zLabel() { return "z"; }
function ratioText(s, count) {
  if (s.floored) return count !== undefined && count !== null ? `${count} (usually ≤3)` : "usually ≤3";
  const r = s.ratio_shown ?? s.ratio;
  return r === null || r === undefined ? "?" : `${r}×`;
}

function attentionBadge(att, partial) {
  if (partial) return h("span", { class: "badge cool", title: "Ingest covered only part of this UTC day, so it is not compared with full days" }, "partial day");
  if (!att) return h("span", { class: "badge cool", title: "Needs 14 complete days of history" }, "baseline building");
  const cls = att.z >= 2 ? "hot" : att.z >= 1 ? "warm" : "cool";
  const r = att.ratio_shown ?? att.ratio;
  const ratio = r === null || r === undefined ? "" : `${r}× `;
  return h("span", { class: `badge ${cls}`, title: `${zLabel(att)} ${att.z} against ${att.baseline_days} days, expected ${att.expected}` }, `${ratio}(z ${att.z})`);
}

function violenceCell(e, partial) {
  const v = e && e.violence;
  if (!v) return h("span", { class: "muted small" }, "—");
  const s = v.named_score;
  if (partial || !s || s.z === undefined || (s.ratio_shown ?? s.ratio) === null || (s.ratio_shown ?? s.ratio) === undefined) return h("span", { class: "muted small", title: "Articles reporting violence placed in the zone whose headline names it" }, `${v.named}`);
  const cls = s.z >= 2 ? "hot" : s.z >= 1 ? "warm" : "cool";
  return h("span", { class: `badge ${cls}`, title: `${v.named} articles reporting violence placed in the zone whose headline names it (of ${v.articles}); ${zLabel(s)} ${s.z} against the last 28 days, expected ${s.expected}` }, `${v.named} · ${ratioText(s)}`);
}

function zoneRows(list, sum, day) {
  return list.map((ent) => {
    const e = sum.entities[ent.id];
    const stories = e ? (e.filtered_stories ?? e.stories) : 0;
    const alarms = e && e.alarms && e.alarms.length;
    return h("tr", { class: alarms ? "alarm" : null },
      h("td", null, h("a", { class: "zone-link", href: `#/zone/${ent.id}?day=${day}` }, ent.name)),
      h("td", { class: "num" }, e ? stories.toLocaleString() : "—"),
      h("td", { class: "num hide-sm" }, e ? e.stories.toLocaleString() : "—"),
      h("td", null, e ? attentionBadge(e.attention, sum.partial) : "—"),
      h("td", { class: "hide-sm" }, violenceCell(e, sum.partial)),
      h("td", null, alarms ? h("span", { class: "badge hot", title: `Alarm: ${e.alarms.join("; ")}` }, "alarm") : ""));
  });
}

function zoneTable(title, list, sum, day) {
  return [
    h("h2", null, title),
    h("div", { class: "panel" }, h("table", null,
      h("thead", null, h("tr", null,
        h("th", null, "Name"),
        h("th", { class: "num", title: "Stories whose headline names the zone or topic" }, "Stories"),
        h("th", { class: "num hide-sm", title: "Every story v4.3's matching rules assign here" }, "All matches"),
        h("th", null, "Attention vs typical"),
        h("th", { class: "hide-sm", title: "GDELT events of assault, fighting or mass violence placed in the zone, in articles whose headline names it" }, "Violence"),
        h("th", null, h("span", { class: "sr-only" }, "Alarm")))),
      h("tbody", null, zoneRows(list, sum, day)))),
  ];
}

// Elsewhere today: the other layers' findings in the zones' countries, strongest zone first (an alarm, then the
// attention z). Zones list GDELT FIPS codes; COP uses ISO, so the codes come from web/data/fips_iso.json
// (scripts/build_web.py). Shown for the newest day only, since the card is about the last 48 hours.
let FIPS_ISO = null;
async function related(box, ents, sum) {
  if (!window.TicRelated) return;
  try {
    if (!FIPS_ISO) FIPS_ISO = await fetch("data/fips_iso.json").then((r) => (r.ok ? r.json() : Promise.reject(r.status)));
  } catch (_) { return; }
  const score = (z) => {
    const e = sum.entities[z.id] || {};
    return [e.alarms && e.alarms.length ? 1 : 0, (e.attention && e.attention.z) || 0];
  };
  const zones = ents.zones.map((z, i) => ({ z, s: score(z), i }))
    .sort((a, b) => (b.s[0] - a.s[0]) || (b.s[1] - a.s[1]) || (a.i - b.i));
  const ccs = [];
  for (const { z } of zones) for (const f of z.countries || []) {
    const iso = FIPS_ISO[f];
    if (iso && !ccs.includes(iso)) ccs.push(iso);
  }
  if (ccs.length) window.TicRelated.render(box, { countries: ccs, here: "watchfloor", level: 2 });
}

async function viewHome(params) {
  setNav("home");
  const [ents, days] = await Promise.all([entities(), get("/days")]);
  if (!days.days.length) return show(h("h1", null, "Zones"), h("p", { class: "muted" }, "No complete day has been built yet."));
  const day = params.get("day") || days.days[0];
  const sum = await get(`/summary?day=${day}`);
  const picker = h("select", { "aria-label": "Day (UTC)", onchange: (ev) => { location.hash = `#/?day=${ev.target.value}`; } },
    days.days.map((d) => h("option", { value: d, selected: d === day }, dayLabel(d))));
  const notes = [];
  if (sum.partial) notes.push(h("p", { class: "note" }, "This day is incomplete: ingest started partway through it, so counts are low."));
  const filtered = Object.values(sum.entities).some((e) => e.filtered_stories !== null && e.filtered_stories !== undefined);
  if (!filtered) notes.push(h("p", { class: "note" }, "Headline-filtered counts are not available for this day; \"Stories\" shows every match."));
  const teaser = await risingTeaser(ents, day);
  const relBox = day === days.days[0] ? h("section", { class: "panel related", id: "tic-related", hidden: true }) : null;
  show(
    h("h1", null, "Conflict zones and watch topics"),
    h("p", { class: "lede" }, "Daily counts of stories whose headline names the zone (reprints merged), and how unusual each day is against the zone's own last 28 days. Open a zone for its stories."),
    h("div", { class: "bar" }, h("label", null, "UTC day ", picker),
      h("span", { class: "muted small" }, `${sum.gdelt_articles?.toLocaleString() ?? "—"} matched articles · built ${when(sum.built_at)}`)),
    notes,
    teaser,
    zoneTable("Conflict zones", ents.zones, sum, day),
    relBox,
    zoneTable("Watch topics", ents.topics, sum, day),
  );
  if (relBox) related(relBox, ents, sum);
}

// ---------- Rising (every country against its own normal) ----------
const MEASURES = {
  violent: { label: "Violence", noun: "articles reporting violence located there", short: "violence" },
  urls: { label: "Attention", noun: "articles reporting events located there", short: "attention" },
};
const MEASURE_ORDER = ["violent", "urls"];

function zoneLinks(c, ents, day) {
  const ids = c.zones || [];
  if (!ids.length) return h("span", { class: "badge warm", title: "No Watchfloor zone covers this country" }, "not watched");
  return ids.map((id) => {
    const z = ents.zones.find((e) => e.id === id);
    return h("a", { class: "zone-link small", href: `#/zone/${id}?day=${day}` }, z ? z.name : id);
  });
}

function scoreBadge(s, kind, count) {
  if (!s || s.z === undefined) return h("span", { class: "badge cool", title: "Needs 14 complete days of history" }, "—");
  if (kind === "elevated") {
    return h("span", { class: "badge warm", title: `${s.ratio90}× the median of the last 90 days (${s.median90})` }, `${s.ratio90}× 90-day`);
  }
  const cls = s.z >= 3 ? "hot" : s.z >= 2 ? "warm" : "cool";
  return h("span", { class: `badge ${cls}`, title: `${zLabel(s)} ${s.z} against the last 28 days (expected ${s.expected})` }, `${ratioText(s, count)} (z ${s.z})`);
}

function countryRows(ccs, data, metric, kind, ents) {
  return ccs.map((cc) => {
    const c = data.countries[cc] || {};
    const s = c[`${metric}_score`] || {};
    const heads = (data.samples[cc] || []).slice(0, 2);
    return h("tr", null,
      h("td", null, h("strong", null, c.name || cc), h("div", { class: "meta" }, zoneLinks(c, ents, data.day))),
      h("td", { class: "num" }, (c[metric] ?? 0).toLocaleString()),
      h("td", null, scoreBadge(s, kind), kind === "rising" && s.ratio90 ? h("div", { class: "meta" }, `${s.ratio90}× 90-day median`) : null),
      h("td", { class: "hide-sm" }, heads.length
        ? h("ul", { class: "heads" }, heads.map((x) => {
          const u = safeUrl(x.url);
          return h("li", null, u ? h("a", { href: u, target: "_blank", rel: "noopener noreferrer nofollow" }, x.title || new URL(u).hostname) : x.title);
        }))
        : h("span", { class: "muted small" }, "—")));
  });
}

function countryTable(title, sub, ccs, data, metric, kind, ents) {
  return [
    h("h2", null, title),
    h("p", { class: "muted small" }, sub),
    ccs.length
      ? h("div", { class: "panel" }, h("table", null,
        h("thead", null, h("tr", null, h("th", null, "Country"), h("th", { class: "num" }, "Articles"),
          h("th", null, kind === "rising" ? "Vs normal" : "Vs 90 days"), h("th", { class: "hide-sm" }, "Sample headlines"))),
        h("tbody", null, countryRows(ccs, data, metric, kind, ents))))
      : h("p", { class: "muted" }, "None today."),
  ];
}

async function viewRising(params) {
  setNav("rising");
  const ents = await entities();
  const data = await get(`/countries${params.get("day") ? `?day=${params.get("day")}` : ""}`);
  const picker = h("select", { "aria-label": "Day (UTC)", onchange: (ev) => { location.hash = `#/rising?day=${ev.target.value}`; } },
    data.days.map((d) => h("option", { value: d, selected: d === data.day }, dayLabel(d))));
  const sections = [];
  if (data.partial) sections.push(h("p", { class: "note" }, "This day is incomplete (GDELT files missing), so it is counted but not compared with normal."));
  for (const m of MEASURE_ORDER) {
    const l = data.lists[m] || { rising: [], elevated: [] };
    const M = MEASURES[m];
    sections.push(countryTable(`${M.label} rising`, `Countries where ${M.noun} jumped against their own last 28 days (z 2.5 or more, at least 1.5× expected).`, l.rising, data, m, "rising", ents));
    sections.push(countryTable(`${M.label} elevated for weeks`, `Not a new jump, but at least twice the country's median of the last 90 days.`, l.elevated, data, m, "elevated", ents));
  }
  show(
    h("h1", null, "Rising"),
    h("p", { class: "lede" }, "Every country, not just the watched zones, compared with its own normal, so a new crisis shows up before anyone adds a zone. Counts are articles in GDELT's event data whose events are located in the country."),
    h("div", { class: "bar" }, h("label", null, "UTC day ", picker), h("a", { href: `#/map?day=${data.day}` }, "See it on the map")),
    sections,
    h("p", { class: "muted small" }, "Headlines are read from article links and may be shortened. GDELT's automated event coding is noisy: treat a row as a pointer to check, not a finding."),
  );
}

async function risingTeaser(ents, day) {
  let data;
  try { data = await get(`/countries?day=${day}`); } catch (_) { return null; }
  const pick = (m) => ((data.lists[m] || {}).rising || []).slice(0, 4);
  const items = MEASURE_ORDER.flatMap((m) => pick(m).map((cc) => ({ cc, m })));
  if (!items.length) return null;
  return h("div", { class: "panel teaser" },
    h("strong", null, "Rising today: "),
    items.flatMap(({ cc, m }, i) => {
      const c = data.countries[cc] || {};
      return [i ? " · " : "", h("a", { href: `#/rising?day=${data.day}` }, c.name || cc), h("span", { class: "muted small" }, ` ${MEASURES[m].short}${c.zones ? "" : ", not watched"}`)];
    }));
}

// ---------- Map ----------
let leafletLoading = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (!leafletLoading) {
    leafletLoading = new Promise((resolve, reject) => {
      const css = h("link", { rel: "stylesheet", href: "vendor/leaflet/leaflet.css" });
      const js = h("script", { src: "vendor/leaflet/leaflet.js" });
      js.addEventListener("load", () => resolve(window.L));
      js.addEventListener("error", () => reject(new Error("map library failed to load")));
      document.head.append(css, js);
    });
  }
  return leafletLoading;
}

let WORLD = null;
async function world() {
  if (!WORLD) WORLD = await (await fetch("geo/world.json")).json();
  return WORLD;
}

const zBucket = (z) => (z === undefined || z === null ? "nodata" : z >= 3 ? "z3" : z >= 2 ? "z2" : z >= 1 ? "z1" : z <= -1.5 ? "zlow" : "z0");

async function viewMap(params) {
  setNav("map");
  const metric = params.get("measure") === "urls" ? "urls" : "violent";
  const [L, ents, geo, data] = await Promise.all([loadLeaflet(), entities(), world(), get(`/countries${params.get("day") ? `?day=${params.get("day")}` : ""}`)]);
  const day = data.day;
  let sum = null;
  try { sum = await get(`/summary?day=${day}`); } catch (_) { /* zone markers then show without attention */ }
  const zoneSel = params.get("zone") || "";
  const go = (changes) => {
    const p = new URLSearchParams({ day, measure: metric, zone: zoneSel, ...changes });
    if (!p.get("zone")) p.delete("zone");
    location.hash = `#/map?${p}`;
  };
  const el = h("div", { id: "map", class: "map panel", role: "region", "aria-label": "World map" });
  const info = h("p", { class: "muted small" });
  show(
    h("h1", null, "Map"),
    h("p", { class: "lede" }, `Countries shaded by ${MEASURES[metric].short} against their own last 28 days; circles are Watchfloor's zones, coloured by attention on the zone's headline-filtered stories.`),
    h("div", { class: "bar" },
      h("label", null, "UTC day ", h("select", { onchange: (ev) => go({ day: ev.target.value }) }, data.days.map((d) => h("option", { value: d, selected: d === day }, dayLabel(d))))),
      h("label", null, "Shade by ", h("select", { onchange: (ev) => go({ measure: ev.target.value }) },
        MEASURE_ORDER.map((m) => h("option", { value: m, selected: m === metric }, MEASURES[m].label)))),
      h("label", null, "Violent events in ", h("select", { onchange: (ev) => go({ zone: ev.target.value }) },
        h("option", { value: "", selected: !zoneSel }, "no zone"),
        h("option", { value: "all", selected: zoneSel === "all" }, "all zones"),
        ents.zones.map((z) => h("option", { value: z.id, selected: z.id === zoneSel }, z.name))))),
    el,
    h("div", { class: "legend small" },
      ["z3", "z2", "z1", "z0", "zlow", "nodata"].map((b) => h("span", null, h("i", { class: `sw ${b}` }),
        { z3: "z 3+", z2: "z 2-3", z1: "z 1-2", z0: "typical", zlow: "well below", nodata: "no data or partial day" }[b])),
      h("span", null, h("i", { class: "sw dot" }), "violent event (GDELT, unverified)")),
    info,
  );
  const map = L.map(el, { worldCopyJump: true, minZoom: 1, maxZoom: 8, zoomSnap: 0.5 }).setView([20, 15], 2);
  map.attributionControl.setPrefix(false);
  map.attributionControl.addAttribution("Country outlines: Natural Earth · Events: The GDELT Project");
  const layer = L.geoJSON(geo, {
    style: (f) => {
      const c = data.countries[f.properties.cc];
      const s = c && !data.partial ? c[`${metric}_score`] : null;
      return { className: `land ${zBucket(s ? s.z : null)}`, weight: 0.6 };
    },
    onEachFeature: (f, lyr) => {
      const c = data.countries[f.properties.cc];
      const s = c ? c[`${metric}_score`] || {} : {};
      lyr.bindTooltip(h("span", null, c ? `${c.name || f.properties.name}: ${(c[metric] ?? 0).toLocaleString()} ${MEASURES[metric].short} articles${s.z !== undefined ? `, z ${s.z}` : ""}` : `${f.properties.name}: no data`), { sticky: true });
      lyr.on("click", () => { location.hash = `#/rising?day=${day}`; });
    },
  }).addTo(map);
  for (const z of ents.zones) {
    if (!z.map) continue;
    const e = sum && sum.entities[z.id];
    const att = e && !sum.partial ? e.attention : null;
    const m = L.circleMarker(z.map, { radius: 9, className: `zone-dot ${zBucket(att ? att.z : null)}`, weight: 2 }).addTo(map);
    m.bindTooltip(h("span", null, `${z.name}${att ? `: z ${att.z}` : ""}`));
    m.on("click", () => { location.hash = `#/zone/${z.id}?day=${day}`; });
  }
  layer.bringToBack();
  if (zoneSel) {
    try {
      const v = await get(`/violent?day=${day}&zone=${encodeURIComponent(zoneSel)}`);
      for (const ev of v.events) {
        const u = safeUrl(ev.url);
        const pt = L.circleMarker([ev.lat, ev.lon], { radius: 4, className: "event-dot", weight: 1 }).addTo(map);
        pt.bindPopup(() => h("div", null,
          h("strong", null, ev.place || "Unknown place"),
          h("div", null, `${ev.a1 || "?"} → ${ev.a2 || "?"} (CAMEO ${ev.code})`),
          h("div", { class: "muted small" }, `${ev.sources ?? "?"} source(s), ${ev.articles ?? "?"} article(s) when first seen`),
          u ? h("a", { href: u, target: "_blank", rel: "noopener noreferrer nofollow" }, "First report") : null));
      }
      info.textContent = `${v.events.length} violent events shown for ${zoneSel === "all" ? "all zones" : (ents.zones.find((z) => z.id === zoneSel) || {}).name}. GDELT codes events automatically and often wrongly; check the report.`;
    } catch (e) {
      info.textContent = `Violent events unavailable: ${e.message}`;
    }
  }
}

// ---------- One zone ----------
function codingView(c) {
  if (!c) return null;
  const dir = c.direction === "escalating" ? "esc" : c.direction === "de-escalating" ? "deesc" : "";
  return h("div", { class: "coding" },
    h("span", { class: `chip ${c.relevance}` }, c.relevance === "on" ? "on topic" : c.relevance === "off" ? "off topic" : "unclear"),
    c.event_type && c.event_type !== "NONE" ? h("span", { class: "chip" }, c.event_type.toLowerCase()) : null,
    c.direction && c.direction !== "neutral" ? h("span", { class: `chip ${dir}` }, c.direction) : null,
    c.killed ? h("span", { class: "chip esc" }, `${c.killed} killed (as reported)`) : null,
    c.gist ? h("span", { class: "gist" }, c.gist) : null);
}

function storyItem(s) {
  const url = safeUrl((s.sample_urls || [])[0]);
  const title = s.title || "(no headline)";
  const groups = Object.keys(s.groups || {});
  return h("li", { class: "story" },
    url ? h("a", { class: "story-title", href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, title) : h("span", { class: "story-title" }, title),
    h("div", { class: "meta" },
      `${s.articles} article${s.articles === 1 ? "" : "s"} · ${s.outlets} outlet${s.outlets === 1 ? "" : "s"} · ${(s.languages || []).join(", ")}`,
      groups.length ? ` · ${groups.join(", ")}` : "",
      s.passes_filter ? "" : " · headline does not name the zone"),
    codingView(s.coding));
}

function feedItem(s) {
  const url = safeUrl((s.sample_urls || [])[0]);
  const title = s.title || "(no headline)";
  const names = (s.outlet_names || []).join(", ");
  return h("li", { class: "story" },
    url ? h("a", { class: "story-title", href: url, target: "_blank", rel: "noopener noreferrer nofollow" }, title) : h("span", { class: "story-title" }, title),
    h("div", { class: "meta" },
      names || `${s.outlets} outlet${s.outlets === 1 ? "" : "s"}`,
      s.articles > 1 ? ` · ${s.articles} items` : "",
      s.first_seen ? ` · ${when(s.first_seen)}` : ""));
}

// "From the suite": what The Intelligence Company's other programs report now (GET /suite; pipeline/suite.py).
function suiteItem(t) {
  const url = safeUrl(t.link);
  const site = safeUrl(t.site);
  const flagged = t.tier === "anomaly" || t.tier === "warning";
  return h("li", { class: t.stale ? "story stale" : "story", title: t.why || null },
    url ? h("a", { class: "story-title", href: url, target: "_blank", rel: "noopener noreferrer" }, t.title) : h("span", { class: "story-title" }, t.title),
    h("div", { class: "meta" },
      site ? h("a", { href: site, target: "_blank", rel: "noopener noreferrer" }, t.program_name) : t.program_name,
      flagged ? [" ", h("span", { class: "badge warm" }, t.tier === "warning" ? "warning" : "anomaly")] : "",
      // with the year: standing notices can be months or years old
      t.data_as_of || t.published_at ? ` · ${window.TicTime.format(t.data_as_of || t.published_at, { year: true })}` : "",
      t.stale ? ` · ${t.program_name}'s feed is behind; shown in grey` : ""));
}

function suitePanel(s, pastDay) {
  const more = Object.entries(s.more || {}).map(([p, n]) => `${n} more from ${p.charAt(0).toUpperCase()}${p.slice(1)}`);
  return [
    pastDay ? h("p", { class: "muted small" }, "These are current reports, not the chosen day's.") : null,
    (s.missing || []).length
      ? h("p", { class: "note" }, `Could not read ${s.missing.join(", ")} just now. Its reports are missing here, not absent.`)
      : null,
    (s.tips || []).length
      ? h("ul", { class: "stories panel" }, s.tips.map(suiteItem))
      : h("p", { class: "muted" }, (s.missing || []).length ? "No reports could be read." : "Nothing from the other programs for this right now."),
    more.length ? h("p", { class: "muted small" }, `Also: ${more.join(", ")}.`) : null,
  ];
}

// ---------- Relations between countries (GET /relations; pipeline/relations.py) ----------
const SVGNS = "http://www.w3.org/2000/svg";
function svg(tag, attrs, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) if (v !== null && v !== undefined) el.setAttribute(k, v);
  for (const kid of kids.flat(Infinity)) if (kid !== null && kid !== undefined) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return el;
}
const COUNT_LABEL = { articles: "articles", verbal_conflict: "verbal-conflict articles", material_conflict: "material-conflict articles" };
const shortDay = (d) => dayLabel(d).replace(/ \d{4}$/, "");
const signed = (x) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(1)}`);
// A 7-day value far from its four weeks before (|z| >= 2) shows that baseline beside it.
function baseNote(z, base, fmt) {
  return z !== null && z !== undefined && Math.abs(z) >= 2 && base !== null && base !== undefined
    ? h("span", { class: "badge warm", title: "Article-weighted average of the 21 days before this week" }, `3-wk avg ${fmt(base)}`) : null;
}

// Daily articles both ways; flagged days in amber, the chosen day outlined. Hover a bar for its numbers.
function relSpark(p, r, day) {
  const W = 600, H = 48, n = r.days.length;
  const max = Math.max(1, ...p.articles);
  const bw = W / n;
  const flagged = new Set(p.flagged);
  return svg("svg", { class: "spark", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Articles a day between ${p.a_name} and ${p.b_name}, highest ${max}` },
  r.days.map((d, i) => {
    const hgt = Math.max(1, (p.articles[i] / max) * (H - 2));
    const cls = flagged.has(d) ? "f" : r.complete[i] ? "b" : "p";
    const z = p.z_articles[i];
    return svg("rect", { class: d === day ? `${cls} sel` : cls, x: (i * bw + 0.5).toFixed(1), y: (H - hgt).toFixed(1),
      width: Math.max(1, bw - 1).toFixed(1), height: hgt.toFixed(1) },
    svg("title", null, `${dayLabel(d)}: ${p.articles[i]} articles both ways (${p.a_name} → ${p.b_name} ${p.articles_ab[i]}, ${p.b_name} → ${p.a_name} ${p.articles_ba[i]})${z !== null && z !== undefined ? `, z ${signed(z)}` : ""}${r.complete[i] ? "" : ", incomplete day"}${flagged.has(d) ? ", flagged" : ""}`));
  }));
}

function relDirRow(label, short, last, week) {
  return h("tr", null,
    h("td", null, h("span", { class: "hide-sm" }, label), h("span", { class: "show-sm", title: label }, short)),
    h("td", null, String(week)),
    h("td", null, pct(last.conflict_share_7d), " ", baseNote(last.z_conflict_share_7d, last.base_conflict_share_7d, pct)),
    h("td", null, signed(last.goldstein_7d), " ", baseNote(last.z_goldstein_7d, last.base_goldstein_7d, signed)),
    h("td", { class: "hide-sm" }, signed(last.tone_7d), " ", baseNote(last.z_tone_7d, last.base_tone_7d, signed)));
}

function relPair(p, r) {
  const last = p.latest;
  const week = (xs) => xs.slice(-7).reduce((t, x) => t + x, 0);
  const recent = p.flagged[p.flagged.length - 1];
  return h("div", { class: "rel-pair" },
    h("div", { class: "rel-head" }, h("strong", null, `${p.a_name} – ${p.b_name}`),
      recent ? h("span", { class: "badge warm" }, `flagged ${shortDay(recent)}`) : null,
      h("span", { class: "muted small" }, ` ${dayLabel(r.days[0])} to ${dayLabel(r.days[r.days.length - 1])}`)),
    relSpark(p, r, last.day),
    h("table", { class: "rel-table" },
      h("thead", null, h("tr", null, h("th", null, `To ${dayLabel(last.day)}`), h("th", null, "Articles, 7 days"),
        h("th", null, "Conflict share"), h("th", null, "Goldstein"), h("th", { class: "hide-sm" }, "Tone"))),
      h("tbody", null,
        relDirRow(`${p.a_name} → ${p.b_name}`, `${p.a} → ${p.b}`, last.ab, week(p.articles_ab)),
        relDirRow(`${p.b_name} → ${p.a_name}`, `${p.b} → ${p.a}`, last.ba, week(p.articles_ba)))));
}

function relationsPanel(r) {
  if (!r.pairs.length || !r.days.length) return [h("p", { class: "muted" }, "No relations built for this zone yet.")];
  const flags = r.flags.slice(0, 8);
  const names = Object.fromEntries(r.pairs.flatMap((p) => [[p.a, p.a_name], [p.b, p.b_name]]));
  const flagText = (f) => f.why.map((w) => {
    const dir = w.direction === "both" ? `${names[f.a]} and ${names[f.b]}` : w.direction === "ab" ? `${names[f.a]} → ${names[f.b]}` : `${names[f.b]} → ${names[f.a]}`;
    return `${dir}: ${w.n} ${COUNT_LABEL[w.count]} (z ${signed(w.z)})`;
  }).join("; ");
  return [
    r.end !== r.asked ? h("p", { class: "muted small" }, `Relations are built through ${dayLabel(r.end)}.`) : null,
    h("div", { class: "panel" }, r.pairs.map((p) => relPair(p, r))),
    flags.length
      ? h("div", null, h("h3", null, "Flagged days"),
        h("ul", { class: "stories panel" }, flags.map((f) => h("li", { class: "story" },
          h("span", { class: "story-title" }, dayLabel(f.day)), h("div", { class: "meta" }, flagText(f))))))
      : h("p", { class: "muted small" }, "No flagged days in this window."),
  ];
}

// ---------- Press tone by outlet country (the `press` part of GET /relations; pipeline/press.py) ----------
const tone2 = (x) => (x === null || x === undefined ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(2)}`);
const CADENCE = { daily: "daily", weekly: "weekly" };

// Main-subject articles a day; incomplete days pale. Hover a bar for its numbers.
function pressSpark(row, p) {
  const W = 160, H = 22, n = p.days.length;
  const max = Math.max(1, ...row.articles);
  const bw = W / n;
  return svg("svg", { class: "spark mini", viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", role: "img",
    "aria-label": `Articles a day by ${row.outlet_name} outlets mainly about ${row.about_name}, highest ${max}` },
  p.days.map((d, i) => {
    const hgt = Math.max(1, (row.articles[i] / max) * (H - 2));
    const t = row.tone[i];
    return svg("rect", { class: p.complete[i] ? "b" : "p", x: (i * bw).toFixed(1), y: (H - hgt).toFixed(1),
      width: Math.max(0.6, bw - 0.4).toFixed(1), height: hgt.toFixed(1) },
    svg("title", null, `${dayLabel(d)}: ${row.articles[i]} articles${t !== null && t !== undefined ? `, tone ${tone2(t)}` : ""}${p.complete[i] ? "" : ", incomplete day"}`));
  }));
}

function pressRowLabel(r) {
  return r.role === "self" ? `${r.outlet_name} (its own press)` : r.outlet_name;
}

function pressGroup(p, cc, name) {
  const rows = p.rows.filter((r) => r.about === cc);
  const read = rows.filter((r) => r.cadence !== "thin").sort((a, b) => b.median_day - a.median_day);
  const thin = rows.filter((r) => r.cadence === "thin").sort((a, b) => b.median_week - a.median_week);
  if (!read.length && !thin.length) return null;
  return h("div", { class: "rel-pair" },
    h("div", { class: "rel-head" }, h("strong", null, read.some((r) => r.role === "self") && read.length === 1 ? `${name} on itself` : `On ${name}`)),
    read.length
      ? h("table", { class: "rel-table" },
        h("thead", null, h("tr", null, h("th", null, "Outlets in"), h("th", null, "A day"), h("th", null, "Tone, 7 days"),
          h("th", { class: "hide-sm" }, "Read"), h("th", { class: "hide-sm" }, "Articles a day"))),
        h("tbody", null, read.map((r) => h("tr", null,
          h("td", null, pressRowLabel(r)),
          r.cadence === "daily"
            ? h("td", { title: "Median articles a day over the last 28 complete days" }, String(Math.round(r.median_day)))
            : h("td", { title: "Median 7-day total over the last 28 complete days, divided by 7" }, (r.median_week / 7).toFixed(1)),
          h("td", null, tone2(r.tone_7d), " ", baseNote(r.z_tone_7d, r.base_tone_7d, tone2)),
          h("td", { class: "hide-sm" }, CADENCE[r.cadence]),
          h("td", { class: "hide-sm spark-cell" }, pressSpark(r, p))))))
      : null,
    thin.length
      ? h("p", { class: "muted small" }, "Too few to read: ",
        thin.map((r) => `${pressRowLabel(r)} (${(r.median_week / 7).toFixed(1)} a day)`).join(", "), ".")
      : null);
}

function pressPanel(p) {
  if (!p) return [h("p", { class: "muted" }, "No press rows for this zone: no outside outlet country reaches 8 articles a day on it.")];
  if (!p.days.length) return [h("p", { class: "muted" }, "No press tone built for this zone yet.")];
  const groups = [...p.about.map((a) => [a.cc, a.name])];
  for (const r of p.rows) if (!groups.some(([cc]) => cc === r.about)) groups.push([r.about, r.about_name]);
  return [
    h("p", { class: "muted small" }, `${dayLabel(p.days[0])} to ${dayLabel(p.end)}. Tone is the latest 7 complete days; a "4-wk avg" badge marks a week far from that outlet country's own four weeks before.`),
    h("div", { class: "panel" }, groups.map(([cc, name]) => pressGroup(p, cc, name))),
  ];
}

async function viewZone(id, params) {
  setNav("home");
  const ents = await entities();
  const ent = [...ents.zones, ...ents.topics].find((e) => e.id === id);
  if (!ent) return show(h("h1", null, "Not found"), h("p", null, "No such zone or topic."));
  const days = await get("/days");
  const day = params.get("day") || days.today;
  const filter = params.get("filter") === "all" ? "all" : "terms";
  const [z, st] = await Promise.all([get(`/zone?entity=${id}&day=${day}&filter=${filter}`), get("/status")]);
  const uncoded = z.stories.filter((s) => !s.coding).length;
  const go = (d, f) => { location.hash = `#/zone/${id}?day=${d}&filter=${f}`; };
  const dayOpts = [...new Set([days.today, day, ...days.days])].sort().reverse();
  const msg = h("span", { class: "muted small" });
  const left = st.budget ? st.budget.view_left_today_usd : 0;
  const canCode = st.ai === "on" && uncoded > 0 && left >= uncoded * COST_PER_STORY;
  const btn = h("button", {
    class: "primary", disabled: !canCode,
    onclick: async () => {
      btn.disabled = true; msg.textContent = "Coding with Gemini…";
      try {
        const r = await post("/code", { entity: id, day, filter });
        msg.textContent = `Coded ${r.coded} stories for $${r.cost_usd.toFixed(4)}.`;
        setTimeout(() => render(), 600);
      } catch (e) {
        msg.textContent = e.status === 429 ? "The AI budget for now is used up. Stories stay readable." : `Failed: ${e.message}`;
      }
    },
  }, uncoded ? `Code ${uncoded} stor${uncoded === 1 ? "y" : "ies"} with Gemini (about $${Math.max(uncoded * COST_PER_STORY, 0.001).toFixed(3)})` : "All shown stories are coded");
  // Loaded after the page so a slow program feed never holds up the stories.
  const suiteBox = h("div", null, h("p", { class: "muted small" }, "Loading reports from the other programs…"));
  const isZone = ents.zones.some((e) => e.id === id);
  const relBox = isZone ? h("div", null, h("p", { class: "muted small" }, "Loading relations…")) : null;
  const pressBox = isZone ? h("div", null, h("p", { class: "muted small" }, "Loading press tone…")) : null;
  show(
    h("p", { class: "small" }, h("a", { href: `#/?day=${days.days.includes(day) ? day : days.days[0] || ""}` }, "← All zones")),
    h("h1", null, ent.name),
    h("p", { class: "lede" }, ent.profile),
    h("div", { class: "bar" },
      h("label", null, "UTC day ", h("select", { onchange: (ev) => go(ev.target.value, filter) },
        dayOpts.map((d) => h("option", { value: d, selected: d === day }, d === days.today ? `${dayLabel(d)} (so far)` : dayLabel(d))))),
      h("label", null, h("input", { type: "checkbox", checked: filter === "terms", onchange: (ev) => go(day, ev.target.checked ? "terms" : "all") }),
        " Only headlines that name the zone")),
    h("div", { class: "bar" }, btn, msg),
    st.ai !== "on" ? h("p", { class: "note" }, "AI coding is switched off.") : null,
    z.stories.length
      ? h("ul", { class: "stories panel" }, z.stories.map(storyItem))
      : h("p", { class: "muted" }, filter === "terms" ? "No headline names this zone for that day. Untick the filter to see every match." : "No stories for that day."),
    h("p", { class: "muted small" }, `Showing up to 25 stories, largest first. ${z.coded} coded. Coding is capped at $5 a month for the whole site; this page has $${left.toFixed(2)} left today.`),
    h("h2", null, "From news feeds and searches"),
    h("p", { class: "muted small" }, "A saved Google News search for this zone, plus items whose headlines name it from Watchfloor's own feeds, outlet searches and Telegram channels. Kept apart from the counts above, which use GDELT only."),
    (z.feeds || []).length
      ? h("ul", { class: "stories panel" }, z.feeds.map(feedItem))
      : h("p", { class: "muted" }, "No feed items for that day yet."),
    isZone ? [
      h("h2", null, "Relations between countries"),
      h("p", { class: "muted small" }, "Articles in which GDELT coded an event between the two, counted once per article, by who acts on whom. ",
        "Conflict share is the share carrying a verbal (accuse, demand, reject, threaten) or material conflict event; Goldstein runs from −10 (most conflictual) to +10; tone is GDELT's score of the article text. ",
        "A day is flagged when a count is far above its own previous four weeks (z ≥ 2.5, at least 5 articles). GDELT often gets direction and partner wrong, so read each pair both ways; it carries no wire services. Display only, not a warning."),
      relBox,
      h("h2", null, `How other countries' press covers ${ent.name}`),
      h("p", { class: "muted small" }, "GDELT articles whose most-mentioned country is one of this zone's, by the country of the outlet (GDELT's 2018 outlet table, with fixes). ",
        "Tone is GDELT's dictionary score of the article text. It runs differently by language and outlet, so read each outlet country only against its own past, never one country against another. ",
        "Rows under 8 articles a day are read by the week; GDELT carries no wire services and samples non-English press. Display only, not a warning."),
      pressBox,
    ] : null,
    h("h2", null, "From the suite"),
    h("p", { class: "muted small" }, "What The Intelligence Company's other programs report now for this zone's countries or this topic: travel advisories, embassy posture, airspace and navigational warnings (",
      h("a", { href: "https://cordon.theintelligence.company/", target: "_blank", rel: "noopener noreferrer" }, "Cordon"), "), GPS interference (",
      h("a", { href: "https://noisefloor.theintelligence.company", target: "_blank", rel: "noopener noreferrer" }, "Noisefloor"), "), fire detections and natural hazards (",
      h("a", { href: "https://elements.theintelligence.company/", target: "_blank", rel: "noopener noreferrer" }, "Elements"), "), cyber activity (",
      h("a", { href: "https://vigil.theintelligence.company", target: "_blank", rel: "noopener noreferrer" }, "Vigil"), ") and dated events (",
      h("a", { href: "https://metacog-osint.github.io/verdict/", target: "_blank", rel: "noopener noreferrer" }, "Verdict"),
      "). Each program collects its own data; Watchfloor links to it and does not count it above."),
    suiteBox,
  );
  if (relBox) {
    get(`/relations?zone=${encodeURIComponent(id)}&day=${encodeURIComponent(day)}`)
      .then((r) => {
        relBox.replaceChildren(...relationsPanel({ ...r, asked: day }).filter(Boolean));
        pressBox.replaceChildren(...pressPanel(r.press).filter(Boolean));
      })
      .catch((e) => {
        relBox.replaceChildren(h("p", { class: "muted" }, e.status === 404 ? "No relations built for this zone yet." : "Relations could not be loaded just now."));
        pressBox.replaceChildren(h("p", { class: "muted" }, e.status === 404 ? "No press tone built for this zone yet." : "Press tone could not be loaded just now."));
      });
  }
  get(`/suite?entity=${encodeURIComponent(id)}`)
    .then((s) => suiteBox.replaceChildren(...suitePanel(s, day !== days.today).filter(Boolean)))
    .catch(() => suiteBox.replaceChildren(h("p", { class: "note" }, "The other programs could not be reached just now. Their reports are missing here, not absent.")));
}

// ---------- Status ----------
async function viewStatus() {
  setNav("status");
  const st = await get("/status");
  const b = st.budget, ing = st.ingest || {};
  const feeds = Object.entries(ing.feeds || {}).map(([k, v]) => `${v} ${k}`).join(", ") || "—";
  const stat = (k, v, sub) => h("div", { class: "panel stat" }, h("div", { class: "k" }, k), h("div", { class: "v" }, v), sub ? h("div", { class: "muted small" }, sub) : null);
  show(
    h("h1", null, "Status"),
    h("p", { class: "lede" }, "What the pipeline did last and what the AI budget has left."),
    h("div", { class: "grid" },
      stat("AI coding", st.ai === "on" ? "On" : "Off", `${b.month}: $${b.spent_usd.toFixed(b.spent_usd < 1 ? 3 : 2)} of $${b.cap_usd.toFixed(2)} spent`),
      stat("Left this month", `$${b.left_usd.toFixed(2)}`, `$${b.view_left_today_usd.toFixed(2)} left today for on-view coding`),
      stat("Last ingest run", when(ing.last_run), `${ing.rows_written ?? "—"} rows written`),
      stat("GDELT files through", when(stampIso((ing.gdelt_through || {}).english)), `translated stream: ${when(stampIso((ing.gdelt_through || {}).translation))}`),
      stat("Feeds", feeds, "fresh / late / stale / failing, by expected interval"),
      stat("Latest built day", ing.last_story_day ? dayLabel(ing.last_story_day) : "—", ing.first_data_day ? `live ingest since ${dayLabel(ing.first_data_day)}; earlier days from GDELT's archive` : null)),
  );
}

// ---------- Static pages ----------
function viewAbout() {
  setNav("about");
  const li = (...t) => h("li", null, ...t);
  show(h("div", { class: "prose" },
    h("h1", null, "About Watchfloor"),
    h("p", { class: "lede" }, "Watchfloor turns publicly available news into a daily picture of the conflict zones and strategic topics on its watch list, built to answer two questions: did something change, and how is each side telling it?"),
    h("h2", null, "How it works"),
    h("ul", null,
      li("Every 15 minutes it reads GDELT's article files (English and machine-translated), its main source."),
      li("GDELT does not carry many major outlets, among them Reuters, AP, AFP, Bloomberg, CNN, NHK and several regional ones (measured October 2026). So Watchfloor also reads publishers' own feeds, public Telegram channels and Google News searches: one for each zone and topic, and others limited to one outlet's website, for outlets GDELT misses or whose feeds turn away automated readers. The ",
        h("a", { href: "#/sources" }, "Sources"), " page lists every source and how it is read."),
      li("Some websites are left out of GDELT's articles because they are not news or only copy it: a court-records database, press-release wires, a network of about 100 look-alike reprint sites, and radio-station copies. The list and the reasons are on the Sources page."),
      li("Articles become stories: reprints and near-identical headlines are merged, so one wire story is counted once."),
      li("A free headline filter keeps stories that name the zone. In a first test on 278 stories it raised the on-topic share from 42% (the matching rules alone) to about 82%; the test set will grow."),
      li("Free measures run on GDELT's stories: attention, the day's count of stories whose headline names the zone, against the zone's own last 28 days (adjusted for the day of the week). Counting one source keeps each day comparable with the zone's history. On a labelled test, 82% of those stories were on topic, against 42% of everything the matching rules catch."),
      li("Stories from the feeds, searches and Telegram channels appear on each zone page, apart from those counts."),
      li("Each zone and topic page also shows what The Intelligence Company's other programs report there now: travel advisories, embassy posture, airspace and navigational warnings (Cordon), GPS interference (Noisefloor), fire detections and natural hazards (Elements), cyber activity (Vigil) and dated events (Verdict). Each program collects its own data; Watchfloor links to it and does not count it."),
      li("Google Gemini codes a story only when someone opens a zone or a free alarm fires: relevance, event type (PLOVER), direction, and a plain-English gist. Every coding is cached, and spending is capped at $5 a month."),
      li("Warning ladders (Watch, Warning, Crisis) with headline-observable indicators are being written for each zone and will be backtested against known onsets.")),
    h("h2", null, "Two-source rule"),
    h("p", null, "An indicator counts once two independent sources report it: different outlets, not both from the same government. An official claim counts once an outlet outside that government reports it too."),
    h("h2", null, "Limits"),
    h("ul", null,
      li("Watchfloor sees headlines, languages, outlets and source groups, not full article text."),
      li("Codings are machine-generated and can be wrong; counts come from automated matching."),
      li("Coverage reflects what outlets publish, not what happens. A spike in reporting is not a measured change on the ground."),
      li("Attention counts follow GDELT's coverage, which leaves out several major outlets. Watchfloor's own feeds and searches fill part of that gap on the zone pages, but are not counted.")),
    h("p", null, h("a", { href: "#/sources" }, "Sources and their terms"), " · ", h("a", { href: "#/terms" }, "Terms of use")),
  ));
}

async function viewSources() {
  setNav("about");
  const cat = await (await fetch("data/sources.json")).json();
  // `read` comes from scripts/build_web.py; the fallback serves a sources.json built before it.
  const kind = (s) => s.read || (s.format === "telegram" ? "Telegram channel" : s.rss_status === "active" ? "News feed" : "GDELT only");
  const count = (k) => cat.sources.filter((s) => kind(s) === k).length;
  const rows = cat.sources.map((s) => h("tr", null,
    h("td", null, s.name), h("td", { class: "hide-sm" }, cat.groups[s.group] || s.group), h("td", null, kind(s)), h("td", { class: "hide-sm" }, s.lang)));
  const leftOut = (cat.left_out || []).map((b) => h("li", null, b.what ? h("strong", null, `${b.what}: `) : null, b.why));
  show(h("h1", null, "Sources"),
    h("div", { class: "prose" },
      h("p", null, h("strong", null, "The GDELT Project. "), "GDELT's datasets are free for any academic, commercial or governmental use, with a citation and a link: ",
        h("a", { href: "https://www.gdeltproject.org/" }, "gdeltproject.org"), ". Watchfloor uses GDELT's 15-minute Global Knowledge Graph and Event files. They are its main source and the only one its attention counts and alarms use."),
      h("p", null, h("strong", null, "What Watchfloor reads itself. "), "GDELT does not carry many major outlets, among them Reuters, AP, AFP, Bloomberg, CNN, NHK and several regional ones (measured October 2026). Watchfloor reads ",
        `${count("News feed")} publishers' feeds, ${count("Telegram channel")} public Telegram channels, ${count("Google News search")} Google News searches (one for each zone and topic) and ${count("Google News site search")} Google News searches limited to one outlet's website, `,
        "for outlets GDELT misses or whose own feeds turn away automated readers. These appear on the zone pages, apart from the counts."),
      h("p", null, h("strong", null, "Map. "), "Drawn with ", h("a", { href: "https://leafletjs.com/" }, "Leaflet"),
        " (BSD 2-Clause licence) over country outlines from ", h("a", { href: "https://www.naturalearthdata.com/" }, "Natural Earth"),
        " (public domain), both served from this site."),
      h("p", null, h("strong", null, "News feeds and public channels. "), "Headlines, short excerpts and links belong to their publishers, under each publisher's terms. Watchfloor shows a headline and links to the original; read the full article at the source."),
      h("p", null, h("strong", null, "Google News. "), "Saved searches read through Google News's public search feed, hourly. Each result keeps its publisher's headline and links to the publisher; an outlet found this way is counted as that outlet, not as Google News."),
      h("p", null, h("strong", null, "Story codings. "), "Generated by Google Gemini on Vertex AI from headlines only. Machine-generated and sometimes wrong.")),
    h("h2", null, `Catalogue (${cat.sources.length} sources)`),
    h("div", { class: "panel" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Source"), h("th", { class: "hide-sm" }, "Perspective"), h("th", null, "How it is read"), h("th", { class: "hide-sm" }, "Language"))),
      h("tbody", null, rows))),
    leftOut.length ? h("div", { class: "prose" },
      h("h2", null, "Left out"),
      h("p", null, "These are dropped from GDELT's articles (and the last ones from Google News results) because they are not news or only copy other outlets. Removing them changed the attention counts by 3% or less when measured, but keeps story cards and outlet counts honest."),
      h("ul", null, leftOut)) : null);
}

function viewTerms() {
  setNav("about");
  const li = (t) => h("li", null, t);
  show(h("div", { class: "prose" },
    h("h1", null, "Terms of use"),
    h("p", { class: "muted small" }, "Draft, 27 October 2026."),
    h("ul", null,
      li("Watchfloor is provided as is, for information and research. It is not advice, and nothing on it is guaranteed accurate, complete or current."),
      li("It is built only from publicly available information. It is a private project of The Intelligence Company and is not affiliated with any government."),
      li("Headlines, excerpts and links belong to their publishers. Follow the link to read an article at its source. Some headlines are found through Google News search results; they too belong to their publishers."),
      li("Story codings are machine-generated and can be wrong. Counts and alarms come from automated matching and describe coverage, not events."),
      li("Do not use Watchfloor to identify, track, harass or target individuals."),
      li("News data from The GDELT Project (gdeltproject.org), used under its terms, which require this citation.")),
  ));
}

// ---------- Router ----------
async function render() {
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query || "");
  try {
    if (path.startsWith("/zone/")) await viewZone(decodeURIComponent(path.slice(6)), params);
    else if (path === "/status") await viewStatus();
    else if (path === "/rising") await viewRising(params);
    else if (path === "/map") await viewMap(params);
    else if (path === "/about") viewAbout();
    else if (path === "/sources") await viewSources();
    else if (path === "/terms") viewTerms();
    else await viewHome(params);
  } catch (e) {
    fail(e);
  }
}

window.addEventListener("hashchange", render);
window.TicTime.mountSettings(document.getElementById("time-settings"));
window.TicTime.onChange(() => render());
fetch("build.json").then((r) => r.json()).then((b) => {
  document.getElementById("updated").textContent = new Date(b.updated).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: window.TicTime.zone() });
}).catch(() => {});
render();
