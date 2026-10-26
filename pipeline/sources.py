"""Source catalog lookups: which source group an outlet's domain belongs to.

GDELT articles carry only a domain, so the same groups used for RSS feeds (Western wires, Russian state,
Iranian state, regional press...) can be assigned to GDELT articles too. That is what makes framing
divergence possible for outlets with no usable feed.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SOURCES = Path(__file__).resolve().parent.parent / "catalog" / "sources.json"


@lru_cache(maxsize=1)
def _domain_index() -> dict[str, dict]:
    cat = json.loads(SOURCES.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    for s in cat["sources"]:
        for d in s.get("domains", []):
            index.setdefault(d.lower(), {"source": s["id"], "group": s["group"], "owner": s["owner"]})
    return index


def lookup_domain(domain: str) -> dict | None:
    """Source id, group and owner for a domain or any of its subdomains; None if not catalogued.

    'english.news.cn' -> the Xinhua entry; 'www.bbc.co.uk' -> BBC.
    """
    d = (domain or "").lower().strip(".")
    index = _domain_index()
    while d:
        if d in index:
            return index[d]
        if "." not in d:
            return None
        d = d.split(".", 1)[1]
    return None
