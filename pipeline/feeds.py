"""Poll the catalog's RSS sources once: fetch, parse, keep new items, update feed health in `state`."""
from __future__ import annotations

import json
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import health, rss, telegram

SOURCES = Path(__file__).resolve().parent.parent / "catalog" / "sources.json"


def load_sources(include_candidates: bool = False) -> list[dict]:
    """Feeds to poll (RSS, Atom, RDF, or Telegram previews): rss_status active, plus candidates when asked."""
    cat = json.loads(SOURCES.read_text(encoding="utf-8"))
    keep = {"active", "candidate"} if include_candidates else {"active"}
    return [s for s in cat["sources"] if s.get("url") and s.get("rss_status") in keep]


def is_due(src: dict, entry: dict | None, now: datetime) -> bool:
    """A source with poll_minutes (saved searches: hourly, to stay polite) waits that long after its last try."""
    every = src.get("poll_minutes")
    if not every or not entry:
        return True
    tried = [health.from_iso(entry.get(k)) for k in ("last_ok", "last_attempt_error_at")]
    last = max((t for t in tried if t), default=None)
    return last is None or (now - last).total_seconds() >= every * 60 - 30


def median_gap_minutes(items: list[dict]) -> float | None:
    times = sorted((i["published"] for i in items if i["published"]), reverse=True)
    gaps = [(a - b).total_seconds() / 60 for a, b in zip(times, times[1:])]
    return round(statistics.median(gaps), 1) if gaps else None


def _fetch_one(src: dict, entry: dict):
    res = rss.fetch(src["url"], entry.get("etag"), entry.get("last_modified"))
    items, err = None, res.error
    if res.ok:
        try:
            items = telegram.parse_preview(res.body) if src.get("format") == "telegram" else rss.parse_feed(res.body)
        except ValueError as e:
            err = str(e)[:200]
    if items:
        rss.correct_clock(items, src.get("clock_skew_hours", 0))
    return res, items, err


def poll(state: dict, now: datetime, include_candidates: bool = False, workers: int = 8,
         fetch_one=_fetch_one) -> tuple[list[dict], list[dict]]:
    """Returns (new item rows, per-source probe rows). Mutates state["rss"] (health, ETags, seen URLs)."""
    all_sources = load_sources(include_candidates)
    feeds = state.setdefault("rss", {})
    sources = [s for s in all_sources if is_due(s, feeds.get(s["id"]), now)]
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(lambda s: (s, *fetch_one(s, feeds.get(s["id"], {}))), sources))

    new_rows, probe = [], []
    for src in all_sources:
        if src in sources:
            continue
        entry = feeds.get(src["id"], {})  # not due yet (poll_minutes): keep its health, fetch nothing
        probe.append({"id": src["id"], "group": src["group"], "status": health.status(entry, src["expected_minutes"], now),
                      "http": None, "items": None, "new": 0, "newest_age_h": None, "median_gap_min": None,
                      "error": entry.get("last_error", ""), "skipped": True})
    for src, res, items, err in results:
        entry = feeds.setdefault(src["id"], {})
        new: list[dict] = []
        if res.not_modified:
            health.record_success(entry, now, entry.get("last_items", 0), None, None, None)
        elif items is not None:
            newest = max((i["published"] for i in items if i["published"]), default=None)
            health.record_success(entry, now, len(items), newest, res.etag, res.last_modified)
            new_urls = set(health.remember(entry, [i["url"] for i in items]))
            new = [i for i in items if i["url"] in new_urls]
            for i in new:
                new_rows.append({"source": src["id"], "group": src["group"], "owner": src["owner"],
                                 "lang": src["lang"], "title": i["title"], "url": i["url"],
                                 "published": health.iso(i["published"]), "summary": i["summary"],
                                 "fetched": health.iso(now)})
        else:
            health.record_failure(entry, now, err or f"HTTP {res.status}")
        newest_dt = health.from_iso(entry.get("newest_item"))
        future_h = rss.future_skew_hours(items or [], now)
        probe.append({
            "id": src["id"], "group": src["group"], "status": health.status(entry, src["expected_minutes"], now),
            "http": res.status, "items": len(items) if items is not None else None, "new": len(new),
            "newest_age_h": round((now - newest_dt).total_seconds() / 3600, 1) if newest_dt else None,
            "median_gap_min": median_gap_minutes(items) if items else None,
            "error": entry.get("last_error", "")
            or (f"items dated {future_h}h in the future: check clock_skew_hours" if future_h else ""),
        })
    return new_rows, probe
