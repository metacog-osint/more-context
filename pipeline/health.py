"""Feed health, after Vigil's feed_expectations pattern.

Each source has an expected interval between new items. Status compares the newest item's age with it:
fresh (<= 2x), late (<= 6x), stale (older), failing (3+ fetch errors in a row), never (no success yet).
A stale or failing critical source blocks any claim that the data is current.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "state" / "feeds.json"
SEEN_PER_SOURCE = 1000


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


def remember(entry: dict, urls: list[str]) -> list[str]:
    """Return the URLs not seen before for this source, and remember them (bounded list)."""
    seen = entry.setdefault("seen", [])
    seen_set = set(seen)
    new = [u for u in urls if u not in seen_set]
    seen.extend(new)
    if len(seen) > SEEN_PER_SOURCE:
        del seen[: len(seen) - SEEN_PER_SOURCE]
    return new
