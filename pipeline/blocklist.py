"""Sites left out of Watchfloor's data: catalog/blocklist.json (Tom's yes, 31 Oct 2026), each entry with its reason.

GDELT rows are dropped by domain (subdomains included) or by URL pattern, at ingest and again when a day is built, so
a rebuilt or backfilled day leaves them out too. Google News search items are dropped by their " - Publisher" tail.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

BLOCKLIST = Path(__file__).resolve().parent.parent / "catalog" / "blocklist.json"


@lru_cache(maxsize=1)
def _rules() -> tuple[dict, list, dict]:
    cat = json.loads(BLOCKLIST.read_text(encoding="utf-8"))
    domains = {d["domain"].lower(): d["reason"] for d in cat.get("gdelt_domains", [])}
    patterns = [(re.compile(p["pattern"], re.I if p.get("ignore_case") else 0), p["reason"])
                for p in cat.get("gdelt_url_patterns", [])]
    publishers = {p["publisher"].lower(): p["reason"] for p in cat.get("search_publishers", [])}
    return domains, patterns, publishers


def gdelt_reason(domain: str | None, url: str | None) -> str | None:
    """Why a GDELT article is left out, or None to keep it. 'wjbo.iheart.com' matches the iheart.com entry."""
    domains, patterns, _ = _rules()
    d = (domain or "").lower().strip(".")
    while d:
        if d in domains:
            return domains[d]
        if "." not in d:
            break
        d = d.split(".", 1)[1]
    for rx, reason in patterns:
        if rx.search(url or ""):
            return reason
    return None


def blocked_row(row: dict) -> bool:
    return gdelt_reason(row.get("domain"), row.get("url")) is not None


def blocked_publisher(title: str | None) -> bool:
    """True for a Google News headline whose ' - Publisher' tail is on the list."""
    t = title or ""
    return " - " in t and t.rsplit(" - ", 1)[1].strip().lower() in _rules()[2]
