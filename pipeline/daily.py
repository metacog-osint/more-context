"""Daily story build: group one UTC day's articles into stories, once per day.

Runs inside the 15-minute cycle. Day D is built on the first run after D+1 03:15 UTC, so files GDELT
posts late (the translated stream runs about an hour behind; retries last up to 3 h) are in. Articles are
assigned to D by publication time, so rows written just after midnight still count for the right day.

Writes `stories/YYYY/MM/DD/stories.jsonl` (one row per story: entity, ids, counts, source groups) and
`stories/YYYY/MM/DD/summary.json` (per-entity totals, reprint inflation and
attention anomaly against the entity's previous 28 complete days; see pipeline/measures.py).
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

from . import feedlabels, measures
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


# Only what a build or a zone page needs. GDELT's theme and location strings are most of a row's size; a full day
# kept whole peaked near 475 MiB of Python objects, and the 512 MiB cloud function died on 28 Oct 2026.
BUILD_FIELDS = ("kind", "url", "title", "published", "fetched", "lang", "domain", "group", "owner", "source",
                "labels", "killed", "wounded", "stream")


def load_day_rows(sink, day: date) -> tuple[list[dict], list[str]]:
    """Rows published on `day` (from that day's cycle files and the next day's first hours), and the keys read.
    Each row keeps only BUILD_FIELDS."""
    nxt = day + timedelta(days=1)
    keys = sink.list(f"cycles/{day:%Y/%m/%d}/")
    keys += [k for k in sink.list(f"cycles/{nxt:%Y/%m/%d}/") if k.rsplit("/", 1)[-1] < "040000"]
    want = day.isoformat()
    rows, seen = [], set()
    for k in keys:
        for r in sink.read_lines(k):
            if _row_day(r) != want:
                continue
            # The same row can sit in several cycle files: on 28 Oct 2026 runs that died re-read the same slots
            # for 16 hours (266,950 rows for 41,208 distinct; loading all of them peaked at 518 MiB, over the
            # function's 512). Keep the first copy. The link is part of the key because GDELT reused 89
            # translation record ids for other articles that day.
            key = (r.get("record_id"), r.get("kind"), r.get("source"), r.get("url"))
            if key in seen:
                continue
            seen.add(key)
            rows.append({f: r[f] for f in BUILD_FIELDS if f in r})
    return rows, keys


def history(sink, day: date, days: int = measures.BASELINE_DAYS) -> dict:
    """From earlier complete days' summaries: headline-filtered stories per entity-day (days built before the
    filter count existed are skipped)."""
    stories: dict[str, dict[date, int]] = defaultdict(dict)
    for i in range(1, days + 1):
        d = day - timedelta(days=i)
        s = sink.read_json(f"stories/{d:%Y/%m/%d}/summary.json")
        if not s or measures.is_partial(s):
            continue
        for eid, e in s.get("entities", {}).items():
            if e.get("filtered_stories") is not None:
                stories[eid][d] = e["filtered_stories"]
    return stories


def build_day(sink, day: date) -> dict:
    rows, keys = load_day_rows(sink, day)
    story_hist = history(sink, day)
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
        # Attention and alarms count stories whose headline names the zone: on the 26 Oct labelled set that is
        # 82% on topic against 42% for every v4.3 match (scripts/eval_location.py; Tom, 27 Oct 2026).
        kept = [s for s in stories if matcher.hit(eid, s.get("title") or "")]
        entities[eid] = {
            "articles": len(urls),
            "stories": len(stories),
            "inflation": round(len(urls) / len(stories), 2) if stories else None,
            "by_group": dict(Counter(a["group"] for a in arts if a.get("group"))),
            "languages": dict(Counter(a.get("lang", "eng") for a in arts).most_common(8)),
            "top": [{k: s[k] for k in ("story_id", "title", "articles", "outlets", "groups")}
                    for s in stories[:TOP_PER_ENTITY]],
            "attention": measures.attention_anomaly(story_hist.get(eid, {}), day, len(kept)),
        }
        entities[eid]["filtered_stories"] = len(kept)  # headline names the zone (catalog/title_terms.json)
        entities[eid]["filtered_articles"] = sum(s["articles"] for s in kept)
        entities[eid]["alarms"] = measures.alarm_reasons(entities[eid])
        story_rows += [{"day": day.isoformat(), "entity": eid, "kind": "gdelt", **s} for s in stories]

    rss_stories = build_stories(rss)
    story_rows += [{"day": day.isoformat(), "entity": None, "kind": "rss", **s} for s in rss_stories]

    # Feed and saved-search items per zone (pipeline/feedlabels.py); kept out of the GDELT counts above.
    feed_counts = {}
    for eid, items in sorted(feedlabels.prepared(rss).items()):
        fstories = build_stories(items)
        feed_counts[eid] = len(fstories)
        story_rows += [{"day": day.isoformat(), "entity": eid, "kind": "feed", **s} for s in fstories]

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
        "feed_stories": feed_counts,
        "alarms": {eid: e["alarms"] for eid, e in entities.items() if e["alarms"]},
    }
    summary["partial"] = measures.is_partial(summary)
    if summary["partial"]:
        # Part of a day against whole-day baselines reads as a collapse (26 Oct 2026 showed z -4.4): no z, no alarm.
        for e in entities.values():
            e["attention"], e["alarms"] = None, []
        summary["alarms"] = {}
    base = f"stories/{day:%Y/%m/%d}/"
    sink.write_lines(base + "stories.jsonl", story_rows)
    sink.write_json(base + "summary.json", summary)
    return {"day": summary["day"], "gdelt_articles": summary["gdelt_articles"], "rss_items": summary["rss_items"],
            "stories": len(story_rows), "alarms": summary["alarms"]}
