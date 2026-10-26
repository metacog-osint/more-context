"""Public read API for MORE CONTEXT, with on-view coding under the monthly AI cap.

    GET  /status                      AI on/off and this month's spend against the cap
    GET  /zone?entity=<id>&day=<date> top stories for one zone or topic and day, with any cached codings
    POST /code {"entity": .., "day": ..}  code that entity-day's top uncached stories (anyone; budget-limited)

Anyone may call it (Tom, 26 Oct 2026). Spending is bounded by the ledger (pipeline/budget.py): $5 a month,
on-view work at most $0.50 a day and never the last $1 (kept for alarms). A request codes at most 25 stories
that MORE CONTEXT already stored; callers cannot send their own text to the model.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import ondemand
from .budget import BudgetExceeded, Ledger
from .match import load_catalog

MAX_AGE_DAYS = 90
STORY_FIELDS = ("story_id", "title", "first_seen", "articles", "outlets", "languages", "groups", "killed_articles")
CODING_FIELDS = ("relevance", "belongs_to", "event_type", "quad", "direction", "source_actor", "target_actor",
                 "place", "country", "killed", "wounded", "casualty_source", "indicator_ids", "frame",
                 "confidence", "gist", "model", "coded_at", "source")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "3600"}


class BadRequest(ValueError):
    pass


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


def _story(s: dict, coding: dict | None) -> dict:
    out = {k: s.get(k) for k in STORY_FIELDS}
    out["sample_urls"] = (s.get("sample_urls") or [])[:3]
    out["coding"] = {k: coding.get(k) for k in CODING_FIELDS} if coding else None
    return out


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
            return 200, {"ai": "on" if ai_on else "off", "budget": ledger.status()}
        if method == "GET" and path == "/zone":
            eid, d = _entity(params.get("entity"), catalog), _day(params.get("day"), today)
            stories = ondemand.day_stories(sink, eid, d)[:ondemand.MAX_STORIES]
            cached = ondemand.load_codings(sink, eid, d)
            return 200, {"entity": eid, "day": d.isoformat(), "stories": [_story(s, cached.get(s["story_id"])) for s in stories],
                         "coded": sum(1 for s in stories if s["story_id"] in cached)}
        if method == "POST" and path == "/code":
            body = body or {}
            eid, d = _entity(body.get("entity"), catalog), _day(body.get("day"), today)
            if not ai_on:
                return 503, {"error": "AI coding is switched off", "budget": ledger.status()}
            try:
                r = code(sink, eid, d, "view", ledger=ledger)
            except BudgetExceeded:
                return 429, {"error": "AI budget for now is used up; stories stay readable without coding",
                             "budget": ledger.status()}
            return 200, {k: r[k] for k in ("entity", "day", "stories", "already_coded", "coded", "cost_usd")}
        return 404, {"error": "not found"}
    except BadRequest as e:
        return 400, {"error": str(e)}
