"""Code stories only when they are needed, and never twice.

Two callers: a person opening a zone (`source="view"`, through the public API or the CLI) and a free alarm
in the daily build (`source="alarm"`). Both code at most the top MAX_STORIES stories of one zone or topic
for one UTC day, in one Vertex request, after reserving the estimated cost in the monthly ledger.

Codings are cached at `codings/YYYY/MM/DD/<entity>.jsonl`; stories already there are never sent again.
Stories come from the daily build (`stories/YYYY/MM/DD/stories.jsonl`) or, for a day not built yet, from
that day's cycle files.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

from . import vertex
from .budget import Ledger
from .daily import load_day_rows
from .match import load_catalog
from .stories import build_stories

MAX_STORIES = 25
SAFETY = 1.5  # reservation = estimate x 1.5 (estimator is +-20%; thinking tokens are not estimated)
MODEL = os.environ.get("MC_AI_MODEL", vertex.DEFAULT_MODEL)


def codings_key(entity: str, day: date) -> str:
    return f"codings/{day:%Y/%m/%d}/{entity}.jsonl"


def ai_enabled() -> bool:
    """Cloud switch: Vertex calls from the deployed functions happen only with MC_AI=on."""
    return os.environ.get("MC_AI", "off").lower() == "on"


def load_codings(sink, entity: str, day: date) -> dict[str, dict]:
    key = codings_key(entity, day)
    if not sink.exists(key):
        return {}
    return {c["story_id"]: c for c in sink.read_lines(key)}


def day_stories(sink, entity: str, day: date) -> list[dict]:
    """The entity's stories for `day`, largest first: from the daily build, else built from cycle files."""
    key = f"stories/{day:%Y/%m/%d}/stories.jsonl"
    if sink.exists(key):
        return [r for r in sink.read_lines(key) if r.get("entity") == entity and r.get("kind") == "gdelt"]
    rows, _ = load_day_rows(sink, day)
    arts = [r for r in rows if r.get("kind") == "gdelt" and entity in r.get("labels", [])]
    return build_stories(arts)


def code_entity_day(sink, entity: str, day: date, source: str, ledger: Ledger | None = None,
                    coder_factory=vertex.Coder, top: int = MAX_STORIES, catalog: dict | None = None,
                    story_ids: list[str] | None = None) -> dict:
    """Code the top `top` uncached stories of one entity-day (or the given `story_ids` of that day, at most
    MAX_STORIES). Raises budget.BudgetExceeded when the cap says no."""
    catalog = catalog or load_catalog()
    if entity not in {e["id"] for e in catalog["zones"] + catalog["topics"]}:
        raise ValueError(f"unknown entity {entity}")
    ledger = ledger or Ledger(sink)
    stories = day_stories(sink, entity, day)
    if story_ids is not None:
        wanted = set(story_ids[:MAX_STORIES])
        stories = [s for s in stories if s["story_id"] in wanted]
    stories = stories[:min(top, MAX_STORIES)]
    cached = load_codings(sink, entity, day)
    todo = [s for s in stories if s["story_id"] not in cached]
    out = {"entity": entity, "day": day.isoformat(), "source": source, "stories": len(stories),
           "already_coded": len(stories) - len(todo), "coded": 0, "cost_usd": 0.0, "problems": []}
    if not todo:
        out["codings"] = [cached[s["story_id"]] for s in stories if s["story_id"] in cached]
        return out
    plan = vertex.plan_coding([{**s, "entity": entity} for s in todo], catalog, per_request=MAX_STORIES)
    tin, tout = plan.tokens()
    estimate = vertex.cost(tin, tout, MODEL) * SAFETY
    rid = ledger.reserve(estimate, source)
    coder = coder_factory(model=MODEL, spend_cap_usd=estimate)
    new: list[dict] = []
    try:
        for _req, codings, problems in coder.run(plan, pause_s=0):
            new += codings
            out["problems"] += problems
    finally:
        ledger.settle(rid, coder.spent)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for c in new:
        c.update(day=day.isoformat(), coded_at=stamp, source=source)
        cached[c["story_id"]] = c
    if new:
        sink.write_lines(codings_key(entity, day), list(cached.values()))
    out.update(coded=len(new), cost_usd=round(coder.spent, 6),
               codings=[cached[s["story_id"]] for s in stories if s["story_id"] in cached])
    return out
