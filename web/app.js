// Watchfloor web app: a static page over the public API (pipeline/api.py). No build step, no dependencies.
// Every string from the API is inserted as text (never as HTML): headlines are third-party content.

const API = "https://mc-api-odg3xhcd4a-uc.a.run.app";
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
  for (const kid of kids.flat()) {
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
  app.replaceChildren(...nodes.flat().filter((n) => n !== null && n !== undefined && n !== false));
  window.scrollTo(0, 0);
}

function fail(e) {
  show(h("h1", null, "Something went wrong"), h("p", { class: "err" }, e.message || String(e)),
    h("p", { class: "muted" }, "The data service may be waking up. Try again in a moment."));
}

// ---------- Zones (home) ----------
function attentionBadge(att, partial) {
  if (partial) return h("span", { class: "badge cool", title: "Ingest covered only part of this UTC day, so it is not compared with full days" }, "partial day");
  if (!att) return h("span", { class: "badge cool", title: "Needs 14 complete days of history" }, "baseline building");
  const cls = att.z >= 2 ? "hot" : att.z >= 1 ? "warm" : "cool";
  const ratio = att.ratio === null || att.ratio === undefined ? "" : `${att.ratio}× `;
  return h("span", { class: `badge ${cls}`, title: `z ${att.z} against ${att.baseline_days} days, expected ${att.expected}` }, `${ratio}(z ${att.z})`);
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
        h("th", null, ""))),
      h("tbody", null, zoneRows(list, sum, day)))),
  ];
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
  show(
    h("h1", null, "Conflict zones and watch topics"),
    h("p", { class: "lede" }, "Daily counts of stories whose headline names the zone (reprints merged), and how unusual each day is against the zone's own last 28 days. Open a zone for its stories."),
    h("div", { class: "bar" }, h("label", null, "UTC day ", picker),
      h("span", { class: "muted small" }, `${sum.gdelt_articles?.toLocaleString() ?? "—"} matched articles · built ${when(sum.built_at)}`)),
    notes,
    zoneTable("Conflict zones", ents.zones, sum, day),
    zoneTable("Watch topics", ents.topics, sum, day),
  );
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
    h("p", { class: "muted small" }, "A saved Google News search for this zone, plus items from Watchfloor's own feeds and Telegram channels whose headlines name it. Kept apart from the counts above."),
    (z.feeds || []).length
      ? h("ul", { class: "stories panel" }, z.feeds.map(feedItem))
      : h("p", { class: "muted" }, "No feed items for that day yet."),
  );
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
    h("p", { class: "lede" }, "Watchfloor turns publicly available news into a daily picture of 15 conflict zones and 5 strategic topics, built to answer two questions: did something change, and how is each side telling it?"),
    h("h2", null, "How it works"),
    h("ul", null,
      li("Every 15 minutes it reads GDELT's article files (English and machine-translated) and more than 50 news feeds."),
      li("Articles become stories: reprints and near-identical headlines are merged, so one wire story is counted once."),
      li("A free headline filter keeps stories that name the zone. In a first test on 278 stories it raised the on-topic share from 42% (the matching rules alone) to about 82%; the test set will grow."),
      li("Free measures run on everything: attention, the day's count of stories whose headline names the zone, against the zone's own last 28 days (adjusted for the day of the week). On a labelled test, 82% of those stories were on topic, against 42% of everything the matching rules catch."),
      li("Google Gemini codes a story only when someone opens a zone or a free alarm fires: relevance, event type (PLOVER), direction, and a plain-English gist. Every coding is cached, and spending is capped at $5 a month."),
      li("Warning ladders (Watch, Warning, Crisis) with headline-observable indicators are being written for each zone and will be backtested against known onsets.")),
    h("h2", null, "Two-source rule"),
    h("p", null, "An indicator counts once two independent sources report it: different outlets, not both from the same government. An official claim counts once an outlet outside that government reports it too."),
    h("h2", null, "Limits"),
    h("ul", null,
      li("Watchfloor sees headlines, languages, outlets and source groups, not full article text."),
      li("Codings are machine-generated and can be wrong; counts come from automated matching."),
      li("Coverage reflects what outlets publish, not what happens. A spike in reporting is not a measured change on the ground.")),
    h("p", null, h("a", { href: "#/sources" }, "Sources and their terms"), " · ", h("a", { href: "#/terms" }, "Terms of use")),
  ));
}

async function viewSources() {
  setNav("about");
  const cat = await (await fetch("data/sources.json")).json();
  const kind = (s) => (s.format === "telegram" ? "Telegram channel" : s.rss_status === "active" ? "News feed" : "GDELT only");
  const rows = cat.sources.map((s) => h("tr", null,
    h("td", null, s.name), h("td", { class: "hide-sm" }, cat.groups[s.group] || s.group), h("td", null, kind(s)), h("td", { class: "hide-sm" }, s.lang)));
  show(h("h1", null, "Sources"),
    h("div", { class: "prose" },
      h("p", null, h("strong", null, "The GDELT Project. "), "GDELT's datasets are free for any academic, commercial or governmental use, with a citation and a link: ",
        h("a", { href: "https://www.gdeltproject.org/" }, "gdeltproject.org"), ". Watchfloor uses GDELT's 15-minute Global Knowledge Graph files."),
      h("p", null, h("strong", null, "News feeds and public channels. "), "Headlines, short excerpts and links belong to their publishers, under each publisher's terms. Watchfloor shows a headline and links to the original; read the full article at the source."),
      h("p", null, h("strong", null, "Story codings. "), "Generated by Google Gemini on Vertex AI from headlines only. Machine-generated and sometimes wrong.")),
    h("h2", null, `Catalogue (${cat.sources.length} sources)`),
    h("div", { class: "panel" }, h("table", null,
      h("thead", null, h("tr", null, h("th", null, "Source"), h("th", { class: "hide-sm" }, "Perspective"), h("th", null, "How it is read"), h("th", { class: "hide-sm" }, "Language"))),
      h("tbody", null, rows))));
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
      li("Headlines, excerpts and links belong to their publishers. Follow the link to read an article at its source."),
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
