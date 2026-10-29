"""Feed health, after Vigil's feed_expectations pattern.

Each source has an expected interval between new items. Status compares the newest item's age with it:
fresh (<= 2x), late (<= 6x), stale (older), failing (3+ fetch errors in a row), never (no success yet).
A stale or failing critical source blocks any claim that the data is current.
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state" / "feeds.json"

# Each feed remembers short fingerprints of the links it has already given us, so an item is stored once. The list is
# kept in the order items were last listed and trimmed from the other end, so an item still in the feed is never
# dropped (sticky items stay listed for months: on 29 Oct 2026 tribune_pk listed one 238 days old, jpost one 49 days).
# The size, 3 x the most items the feed has returned (200-2,000), only has to cover items that leave the feed and come
# back. A link forgotten and seen again costs one extra cycle row, not a double count: the daily build keeps one copy
# per source and link, and skips rows dated before the day it builds (all ~98,000 feed rows read 26-29 Oct 2026 had a
# date). Until 29 Oct 2026 the lists held 1,000 full links a feed in first-seen order: 99% of state.json, which is
# rewritten every run and kept a week by the bucket's soft delete (cost audit in CLAUDE.md).
SEEN_MIN, SEEN_PER_ITEM, SEEN_MAX = 200, 3, 2000


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(d: datetime | None) -> str | None:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ") if d else None


def from_iso(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def load_state(path: Path = STATE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def record_success(entry: dict, now: datetime, items: int, newest: datetime | None,
                   etag: str | None, last_modified: str | None) -> None:
    entry["last_ok"] = iso(now)
    entry["last_items"] = items
    entry["consecutive_failures"] = 0
    entry["last_error"] = ""
    if newest and (not entry.get("newest_item") or newest > from_iso(entry["newest_item"])):
        entry["newest_item"] = iso(newest)
    if etag:
        entry["etag"] = etag
    if last_modified:
        entry["last_modified"] = last_modified


def record_failure(entry: dict, now: datetime, error: str) -> None:
    entry["last_attempt_error_at"] = iso(now)
    entry["last_error"] = error
    entry["consecutive_failures"] = entry.get("consecutive_failures", 0) + 1


def status(entry: dict | None, expected_minutes: float, now: datetime) -> str:
    if not entry or not entry.get("last_ok"):
        return "failing" if entry and entry.get("consecutive_failures", 0) >= 3 else "never"
    if entry.get("consecutive_failures", 0) >= 3:
        return "failing"
    newest = from_iso(entry.get("newest_item")) or from_iso(entry["last_ok"])
    age = (now - newest).total_seconds() / 60
    if age <= 2 * expected_minutes:
        return "fresh"
    if age <= 6 * expected_minutes:
        return "late"
    return "stale"


def fingerprint(url: str) -> str:
    """8 characters, 48 bits of SHA-1: a new link matches one of 2,000 remembered about once in 100 billion."""
    return base64.urlsafe_b64encode(hashlib.sha1(url.encode("utf-8")).digest()[:6]).decode("ascii")


def seen_cap(entry: dict) -> int:
    return min(SEEN_MAX, max(SEEN_MIN, SEEN_PER_ITEM * entry.get("max_items", 0)))


def upgrade_seen(entry: dict) -> None:
    """Turn a pre-29 Oct 2026 list of full links into fingerprints. Not trimmed here: that list is in first-seen
    order, and trimming it would drop sticky items; the feed's next fetch trims it (remember)."""
    if "seen" not in entry:
        return
    entry.setdefault("max_items", entry.get("last_items") or 0)
    entry["seen_fp"] = [fingerprint(u) for u in entry.pop("seen")]


def remember(entry: dict, urls: list[str]) -> list[str]:
    """Return the URLs not seen before for this source (each once, in feed order). Every listed item moves to the
    recent end of the fingerprint list; the list is trimmed from the other end."""
    upgrade_seen(entry)
    listed: dict[str, str] = {}
    for u in urls:
        listed.setdefault(fingerprint(u), u)
    old = entry.get("seen_fp", [])
    known = set(old)
    new = [u for f, u in listed.items() if f not in known]
    entry["max_items"] = max(entry.get("max_items", 0), len(listed))
    cap = max(seen_cap(entry), len(listed))
    entry["seen_fp"] = ([f for f in old if f not in listed] + list(listed))[-cap:]
    return new
