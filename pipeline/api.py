"""Public read API for Watchfloor (working name MORE CONTEXT), with on-view coding under the monthly AI cap.

    GET  /status                         AI on/off, this month's spend against the cap, last ingest run
    GET  /entities                       zones and topics: id, name, profile
    GET  /days                           built days, newest first
    GET  /summary?day=<date>             one built day's per-entity measures (newest built day by default)
    GET  /zone?entity=<id>&day=<date>&filter=terms|all
                                         top stories for one zone or topic and day, with any cached codings;
                                         filter=terms (default) keeps stories whose headline names the zone
    POST /code {"entity", "day", "filter"}  code the stories /zone shows that are not coded yet (anyone; capped)

Anyone may call it (Tom, 26 Oct 2026). Spending is bounded by the ledger (pipeline/budget.py): $5 a month,
on-view work at most $0.50 a day and never the last $1 (kept for alarms). A request codes at most 25 stories
that Watchfloor already stored; callers cannot send their own text to the model.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone

from . import ondemand
from .budget import BudgetExceeded, Ledger
from .match import load_catalog
from .relevance import TermMatcher

MAX_AGE_DAYS = 120
STORY_FIELDS = ("story_id", "title", "first_seen", "articles", "outlets", "languages", "groups", "killed_articles")
CODING_FIELDS = ("relevance", "belongs_to", "event_type", "quad", "direction", "source_actor", "target_actor",
                 "place", "country", "killed", "wounded", "casualty_source", "indicator_ids", "frame",
                 "confidence", "gist", "model", "coded_at", "source")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"}
_CACHE: dict[str, tuple[float, object]] = {}
_MATCHER: TermMatcher | None = None


class BadRequest(ValueError):
    pass


def _cached(key: str, ttl: float, fn):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _CACHE[key] = (time.time(), value)
    return value


def _matcher() -> TermMatcher:
    global _MATCHER
    if _MATCHER is None:
        _MATCHER = TermMatcher()
    return _MATCHER


def _entity(value, catalog) -> str:
    ids = {e["id"] for e in catalog["zones"] + catalog["topics"]}
    if value not in ids:
        raise BadRequest("unknown entity")
    return value


def _day(value, today: date) -> date:
    try:
        d = date.fromisoformat(value) if value else today
    except (TypeError, ValueError):
        raise BadRequest("day must be YYYY-MM-DD")
    if d > today or d < today - timedelta(days=MAX_AGE_DAYS):
        raise BadRequest(f"day must be within the last {MAX_AGE_DAYS} days")
    return d


def _filter(value) -> bool:
    if value in (None, "", "terms"):
        return True
    if value == "all":
        return False
    raise BadRequest("filter must be terms or all")


def _story(s: dict, coding: dict | None, passes: bool) -> dict:
    out = {k: s.get(k) for k in STORY_FIELDS}
    out["sample_urls"] = [u for u in (s.get("sample_urls") or [])[:3] if u.startswith(("http://", "https://"))]
    out["passes_filter"] = passes
    out["coding"] = {k: coding.get(k) for k in CODING_FIELDS} if coding else None
    return out


def built_days(sink) -> list[str]:
    keys = sink.list("stories/")
    days = {k[len("stories/"):len("stories/") + 10].replace("/", "-") for k in keys if k.endswith("/summary.json")}
    return sorted(days, reverse=True)


def zone_stories(sink, eid: str, d: date, filtered: bool) -> list[tuple[dict, bool]]:
    """The stories /zone shows and /code codes: up to 25, largest first, optionally headline-filtered."""
    m = _matcher()
    out = []
    for s in ondemand.day_stories(sink, eid, d):
        passes = m.hit(eid, s.get("title") or "")
        if passes or not filtered:
            out.append((s, passes))
        if len(out) == ondemand.MAX_STORIES:
            break
    return out


def _summary(sink, d: str, catalog) -> dict | None:
    s = sink.read_json(f"stories/{d[:4]}/{d[5:7]}/{d[8:10]}/summary.json")
    if not s:
        return None
    names = {e["id"]: e["name"] for e in catalog["zones"] + catalog["topics"]}
    ents = {}
    for eid, e in s.get("entities", {}).items():
        ents[eid] = {
            "name": names.get(eid, eid), "articles": e.get("articles"), "stories": e.get("stories"),
            "filtered_stories": e.get("filtered_stories"), "filtered_articles": e.get("filtered_articles"),
            "inflation": e.get("inflation"), "attention": e.get("attention"),
            "alarms": e.get("alarms") or [],
            "by_group": e.get("by_group"), "top": (e.get("top") or [])[:5],
        }
    return {"day": s["day"], "partial": s.get("partial"), "backfill": bool(s.get("backfill")),
            "built_at": s.get("built_at"), "gdelt_articles": s.get("gdelt_articles"), "rss_items": s.get("rss_items"),
            "entities": ents}


def _ingest_status(sink) -> dict:
    st = sink.read_json("state/state.json") or {}
    lr = st.get("last_run") or {}
    fh = st.get("feed_health") or {}
    counts: dict[str, int] = {}
    for p in fh.get("sources", []):
        counts[p.get("status", "?")] = counts.get(p.get("status", "?"), 0) + 1
    return {"last_run": lr.get("run_at"), "rows_written": (lr.get("written") or {}).get("rows"),
            "gdelt_through": {k: (v or {}).get("through") for k, v in (lr.get("gdelt") or {}).items()},
            "feeds": counts, "first_data_day": st.get("first_data_day"),
            "last_story_day": (st.get("stories") or {}).get("last_day")}


def handle(method: str, path: str, params: dict, body: dict | None, sink, *, ai_on: bool | None = None,
           ledger: Ledger | None = None, code=ondemand.code_entity_day, catalog: dict | None = None,
           today: date | None = None) -> tuple[int, dict]:
    """(HTTP status, JSON body). Pure function of its inputs, so it is tested without a server."""
    catalog = catalog or load_catalog()
    ledger = ledger or Ledger(sink)
    ai_on = ondemand.ai_enabled() if ai_on is None else ai_on
    today = today or datetime.now(timezone.utc).date()
    path = "/" + path.strip("/")
    try:
        if method == "GET" and path == "/status":
            return 200, {"ai": "on" if ai_on else "off", "budget": ledger.status(),
                         "ingest": _cached("ingest", 60, lambda: _ingest_status(sink))}
        if method == "GET" and path == "/entities":
            return 200, {k: [{"id": e["id"], "name": e["name"], "profile": e.get("profile", "")} for e in catalog[k]]
                         for k in ("zones", "topics")}
        if method == "GET" and path == "/days":
            return 200, {"days": _cached("days", 300, lambda: built_days(sink)), "today": today.isoformat()}
        if method == "GET" and path == "/summary":
            days = _cached("days", 300, lambda: built_days(sink))
            d = params.get("day") or (days[0] if days else None)
            if not d:
                return 404, {"error": "no day built yet"}
            d = _day(d, today).isoformat()
            out = _cached(f"summary:{d}", 3600, lambda: _summary(sink, d, catalog))
            return (200, out) if out else (404, {"error": f"no summary for {d}"})
        if method == "GET" and path == "/zone":
            eid, d = _entity(params.get("entity"), catalog), _day(params.get("day"), today)
            filtered = _filter(params.get("filter"))
            shown = zone_stories(sink, eid, d, filtered)
            cached = ondemand.load_codings(sink, eid, d)
            return 200, {"entity": eid, "day": d.isoformat(), "filter": "terms" if filtered else "all",
                         "stories": [_story(s, cached.get(s["story_id"]), p) for s, p in shown],
                         "coded": sum(1 for s, _ in shown if s["story_id"] in cached)}
        if method == "POST" and path == "/code":
            body = body or {}
            eid, d = _entity(body.get("entity"), catalog), _day(body.get("day"), today)
            filtered = _filter(body.get("filter"))
            if not ai_on:
                return 503, {"error": "AI coding is switched off", "budget": ledger.status()}
            ids = [s["story_id"] for s, _ in zone_stories(sink, eid, d, filtered)]
            try:
                r = code(sink, eid, d, "view", ledger=ledger, story_ids=ids)
            except BudgetExceeded:
                return 429, {"error": "AI budget for now is used up; stories stay readable without coding",
                             "budget": ledger.status()}
            return 200, {k: r[k] for k in ("entity", "day", "stories", "already_coded", "coded", "cost_usd")}
        return 404, {"error": "not found"}
    except BadRequest as e:
        return 400, {"error": str(e)}
