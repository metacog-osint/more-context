"""Daily story build: group one UTC day's articles into stories, once per day.

Runs inside the 15-minute cycle. Day D is built on the first run after D+1 03:15 UTC, so files GDELT
posts late (the translated stream runs about an hour behind; retries last up to 3 h) are in. Articles are
assigned to D by publication time, so rows written just after midnight still count for the right day.

Writes `stories/YYYY/MM/DD/stories.jsonl` (one row per story: entity, ids, counts, source groups) and
`stories/YYYY/MM/DD/summary.json` (per-entity totals and reprint inflation).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

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


def build_day(sink, day: date) -> dict:
    rows, keys = load_day_rows(sink, day)
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
        }
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
    }
    base = f"stories/{day:%Y/%m/%d}/"
    sink.write_lines(base + "stories.jsonl", story_rows)
    sink.write_json(base + "summary.json", summary)
    return {"day": summary["day"], "gdelt_articles": summary["gdelt_articles"], "rss_items": summary["rss_items"],
            "stories": len(story_rows)}
