"""Daily story build: group one UTC day's articles into stories, once per day.

Runs inside the 15-minute cycle. Day D is built on the first run after D+1 03:15 UTC, so files GDELT
posts late (the translated stream runs about an hour behind; retries last up to 3 h) are in. Articles are
assigned to D by publication time, so rows written just after midnight still count for the right day.

Writes `stories/YYYY/MM/DD/stories.jsonl` (one row per story: entity, ids, counts, source groups) and
`stories/YYYY/MM/DD/summary.json` (per-entity totals, reprint inflation, casualty-reporting share, and
attention anomaly against the entity's previous 28 complete days; see pipeline/measures.py).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import measures
from .relevance import TermMatcher
from .stories import build_stories

BUILD_DELAY = timedelta(hours=3, minutes=15)
MAX_DAYS_PER_RUN = 2
TOP_PER_ENTITY = 10


def days_to_build(last_day: str | None, now: datetime, first_data_day: date | None) -> list[date]:
    """Completed days not yet built, oldest first. Without history, start with the first day of data."""
    newest = (now - BUILD_DELAY).date() - timedelta(days=1)
    if last_day:
        start = date.fromisoformat(last_day) + timedelta(days=1)
    elif first_data_day:
        start = first_data_day
    else:
        return []
    out, d = [], start
    while d <= newest and len(out) < MAX_DAYS_PER_RUN:
        out.append(d)
        d += timedelta(days=1)
    return out


def _row_day(r: dict) -> str:
    return (r.get("published") or r.get("fetched") or "")[:10]


def load_day_rows(sink, day: date) -> tuple[list[dict], list[str]]:
    """Rows published on `day` (from that day's cycle files and the next day's first hours), and the keys read."""
    nxt = day + timedelta(days=1)
    keys = sink.list(f"cycles/{day:%Y/%m/%d}/")
    keys += [k for k in sink.list(f"cycles/{nxt:%Y/%m/%d}/") if k.rsplit("/", 1)[-1] < "040000"]
    want = day.isoformat()
    return [r for k in keys for r in sink.read_lines(k) if _row_day(r) == want], keys


def history(sink, day: date, days: int = measures.BASELINE_DAYS) -> tuple[dict, dict]:
    """From earlier complete days' summaries: stories per entity-day, and killed-share per entity-day
    (only days where every row carried the casualty fields)."""
    stories: dict[str, dict[date, int]] = defaultdict(dict)
    killed: dict[str, dict[date, float]] = defaultdict(dict)
    for i in range(1, days + 1):
        d = day - timedelta(days=i)
        s = sink.read_json(f"stories/{d:%Y/%m/%d}/summary.json")
        if not s or measures.is_partial(s):
            continue
        for eid, e in s.get("entities", {}).items():
            stories[eid][d] = e.get("stories", 0)
            c = e.get("casualty")
            if c and c.get("articles_counted") == c.get("articles_total"):
                killed[eid][d] = c["killed_share"]
    return stories, killed


def build_day(sink, day: date) -> dict:
    rows, keys = load_day_rows(sink, day)
    story_hist, killed_hist = history(sink, day)
    matcher = TermMatcher()
    gdelt = [r for r in rows if r.get("kind") == "gdelt"]
    rss = [r for r in rows if r.get("kind") == "rss"]

    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in gdelt:
        for label in r.get("labels", []):
            by_entity[label].append(r)

    story_rows, entities = [], {}
    for eid, arts in sorted(by_entity.items()):
        stories = build_stories(arts)
        urls = {a["url"] for a in arts}
        entities[eid] = {
            "articles": len(urls),
            "stories": len(stories),
            "inflation": round(len(urls) / len(stories), 2) if stories else None,
            "by_group": dict(Counter(a["group"] for a in arts if a.get("group"))),
            "languages": dict(Counter(a.get("lang", "eng") for a in arts).most_common(8)),
            "top": [{k: s[k] for k in ("story_id", "title", "articles", "outlets", "groups")}
                    for s in stories[:TOP_PER_ENTITY]],
            "casualty": measures.casualty_share(arts, stories),
            "attention": measures.attention_anomaly(story_hist.get(eid, {}), day, len(stories)),
        }
        cas = entities[eid]["casualty"]
        if cas and cas["articles_counted"] == cas["articles_total"]:
            cas["anomaly"] = measures.share_anomaly(killed_hist.get(eid, {}), day, cas["killed_share"])
        kept = [s for s in stories if matcher.hit(eid, s.get("title") or "")]
        entities[eid]["filtered_stories"] = len(kept)  # headline names the zone (catalog/title_terms.json)
        entities[eid]["filtered_articles"] = sum(s["articles"] for s in kept)
        entities[eid]["alarms"] = measures.alarm_reasons(entities[eid])
        story_rows += [{"day": day.isoformat(), "entity": eid, "kind": "gdelt", **s} for s in stories]

    rss_stories = build_stories(rss)
    story_rows += [{"day": day.isoformat(), "entity": None, "kind": "rss", **s} for s in rss_stories]

    summary = {
        "day": day.isoformat(),
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "gdelt_articles": len({r["url"] for r in gdelt}),
        "rss_items": len({r["url"] for r in rss}),
        "rss_stories": len(rss_stories),
        "rss_by_group": dict(Counter(r["group"] for r in rss if r.get("group"))),
        "cycle_files": len(keys),
        "first_cycle": keys[0] if keys else None,  # later than about 00:15 on the day means a partial day
        "entities": entities,
        "alarms": {eid: e["alarms"] for eid, e in entities.items() if e["alarms"]},
    }
    summary["partial"] = measures.is_partial(summary)
    base = f"stories/{day:%Y/%m/%d}/"
    sink.write_lines(base + "stories.jsonl", story_rows)
    sink.write_json(base + "summary.json", summary)
    return {"day": summary["day"], "gdelt_articles": summary["gdelt_articles"], "rss_items": summary["rss_items"],
            "stories": len(story_rows), "alarms": summary["alarms"]}
