"""Which zones and topics a feed item belongs to: news feeds, Telegram channels and saved news searches.

Labels are given when a day is built, not at ingest, so a change to a zone's headline terms applies to earlier
items too. A saved search (a source with "entity") belongs to its own zone. Any other item counts for each zone
or topic whose headline terms (catalog/title_terms.json) it contains, limited to the source's "focus" when that
lists zones. Feed stories are kept apart from GDELT's: attention baselines stay GDELT-only, so history compares.
"""
from __future__ import annotations

import json
from collections import defaultdict
from functools import lru_cache

from .feeds import SOURCES
from .match import load_catalog
from .relevance import TermMatcher

SEARCH_GROUP = "search"


@lru_cache(maxsize=1)
def _sources() -> dict[str, dict]:
    cat = json.loads(SOURCES.read_text(encoding="utf-8"))
    return {s["id"]: s for s in cat["sources"]}


def entity_ids(catalog: dict | None = None) -> list[str]:
    catalog = catalog or load_catalog()
    return [e["id"] for e in catalog["zones"] + catalog["topics"]]


def split_publisher(title: str) -> tuple[str, str | None]:
    """Google News headlines end with " - Publisher"; return (headline, publisher)."""
    if " - " in title:
        head, pub = title.rsplit(" - ", 1)
        if head.strip() and 0 < len(pub.strip()) <= 80:
            return head.strip(), pub.strip()
    return title, None


def labels(row: dict, matcher: TermMatcher, ids: list[str], sources: dict[str, dict] | None = None) -> list[str]:
    sources = _sources() if sources is None else sources
    src = sources.get(row.get("source") or "") or {}
    if src.get("entity"):
        return [src["entity"]] if src["entity"] in ids else []
    focus = [f for f in src.get("focus") or [] if f in ids]
    title = row.get("title") or ""
    return [eid for eid in (focus or ids) if matcher.hit(eid, title)]


def prepared(rows: list[dict], catalog: dict | None = None, matcher: TermMatcher | None = None,
             sources: dict[str, dict] | None = None) -> dict[str, list[dict]]:
    """Feed rows grouped by entity, ready for build_stories. Search headlines lose their " - Publisher" tail, which
    becomes the outlet; other feeds count each source as one outlet."""
    sources = _sources() if sources is None else sources
    ids = entity_ids(catalog)
    matcher = matcher or TermMatcher()
    out: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        item = dict(r)
        src = sources.get(item.get("source") or "") or {}
        if item.get("group") == SEARCH_GROUP:
            head, pub = split_publisher(item.get("title") or "")
            item["title"] = head
            item["domain"] = pub or "news.google.com"
        else:
            item["domain"] = src.get("name") or item.get("source") or ""
        for eid in labels(item, matcher, ids, sources):
            out[eid].append(item)
    return out
