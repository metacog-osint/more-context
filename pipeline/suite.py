"""What The Intelligence Company's other programs report for a zone or topic: the zone page's "From the suite" panel
(Tom, 1 Nov 2026: leverage the other programs' data instead of recreating it).

Watchfloor's interests (doctrine/interests.json, written by scripts/build_interests.py) are matched by the doctrine
kit (tips.py) against COP's bus plus any wanted feed the bus does not carry. A zone gets the tips whose areas include
its warning problem; a topic gets the tips of interests that name it in `warning_problems`. Nothing here is counted in
Watchfloor's measures; the panel links to the program that collected each item.

The whole set is computed at most once per TTL in a process (the bus refreshes every two hours) and sooner after a
failure, so a source that could not be read is retried and is shown as missing, never as quiet.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import tips as kittips  # noqa: E402

TTL = 1800             # seconds; the bus itself refreshes every two hours
TTL_AFTER_FAILURE = 300
FETCH_TIMEOUT = 20     # seconds per source, inside the API's 120 s request limit
MAX_PER_PROGRAM = 12
ORDER = ["cordon", "noisefloor", "elements", "vigil", "verdict", "context"]
TIER_RANK = {"warning": 0, "anomaly": 1, "routine": 2}
_CACHE: dict = {"at": 0.0, "value": None, "ttl": TTL}


@lru_cache(maxsize=1)
def interests() -> dict:
    return json.loads((ROOT / "doctrine" / "interests.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def warning_problem_of() -> dict[str, str]:
    """Catalog entity id (01_Ukraine_Conflict, T4_GNSS_Counterspace) -> its warning problem (WF-WP-Z01, WF-WP-T4)."""
    ind = json.loads((ROOT / "doctrine" / "indicators.json").read_text(encoding="utf-8"))
    return {w["entity"]: w["id"] for w in ind["warning_problems"] if w.get("entity")}


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(src: str):
    return kittips.load(src, timeout=FETCH_TIMEOUT)


def snapshot(now: datetime | None = None, gather=None, clock=time.time) -> dict:
    """Every tip for Watchfloor's interests, cached for TTL seconds (TTL_AFTER_FAILURE after a failed source)."""
    t = clock()
    if _CACHE["value"] is not None and t - _CACHE["at"] < _CACHE["ttl"]:
        return _CACHE["value"]
    now = now or datetime.now(timezone.utc)
    doc = interests()
    items, problems = (gather or (lambda d: kittips.gather(d, fetch=_fetch)))(doc)
    value = {"as_of": _iso(now), "items": len(items), "tips": kittips.tips(items, doc, now=now), "problems": problems}
    _CACHE.update(at=t, value=value, ttl=TTL_AFTER_FAILURE if problems else TTL)
    return value


def _safe_link(url) -> str | None:
    return url if isinstance(url, str) and url.startswith(("https://", "http://")) else None


def for_entity(entity_id: str, snap: dict) -> dict:
    """The panel for one zone or topic: tips first by tier (warnings, anomalies, then standing items), then by program,
    newest first, at most MAX_PER_PROGRAM per program (the rest counted in `more`)."""
    wp = warning_problem_of().get(entity_id)
    doc = interests()
    serves = {i["id"]: set(i.get("warning_problems", [])) for i in doc["interests"]}
    about = {i["id"]: i.get("about", "") for i in doc["interests"]}
    picked, seen = [], set()
    for t in snap.get("tips", []):
        if not wp or not (wp in (t.get("areas") or []) or wp in serves.get(t["interest_id"], set())):
            continue
        key = (t["program"], t.get("item_id"))
        if key in seen:
            continue
        seen.add(key)
        picked.append(t)
    rank = {p: i for i, p in enumerate(ORDER)}

    def newest_first(t):
        d = kittips._parse(t.get("data_as_of")) or kittips._parse(t.get("published_at"))
        return -d.timestamp() if d else 0.0

    picked.sort(key=lambda t: (TIER_RANK.get(t.get("tier"), 3), rank.get(t["program"], 99), newest_first(t),
                               t.get("title") or ""))
    out, per, more = [], {}, {}
    for t in picked:
        per[t["program"]] = per.get(t["program"], 0) + 1
        if per[t["program"]] > MAX_PER_PROGRAM:
            more[t["program"]] = more.get(t["program"], 0) + 1
            continue
        entry = kittips.program_entry(t["program"])
        out.append({
            "program": t["program"], "program_name": entry.get("name") or t["program"], "site": entry.get("site"),
            "title": t.get("title") or "", "tier": t.get("tier"), "kind": t.get("kind"),
            "status_class": t.get("status_class"), "response_stage": t.get("response_stage"),
            "countries": t.get("countries") or [], "link": _safe_link(t.get("link")) or _safe_link(entry.get("site")),
            "data_as_of": t.get("data_as_of"), "published_at": t.get("published_at"), "stale": bool(t.get("stale")),
            "why": about.get(t["interest_id"], ""),
        })
    names = {p["id"]: p["name"] for p in kittips.registry()["programs"]}
    return {"entity": entity_id, "warning_problem": wp, "as_of": snap.get("as_of"), "tips": out, "more": more,
            "missing": [names.get(p["source"], "COP's combined feed" if p["source"] == "bus" else p["source"])
                        for p in snap.get("problems", [])]}
