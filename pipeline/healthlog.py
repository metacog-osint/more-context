"""The per-run health record, kept for good (retention M1, 18 Nov 2026).

The live state document (`mc_state/ingest`, the bucket's `state/state.json`) holds only the latest run's summary and
feed probe: every 15 minutes it is replaced. Feed health is what CLAUDE.md says to judge a feed on (its new rows per
day against its own weekdays), and that history was lost. This module keeps one line per run,
`{"run_at", "summary", "feed_health"}` (the run's summary as `state["last_run"]` and the per-source probe as
`state["feed_health"]`), appended to a day file in the bucket: `health/YYYY-MM-DD.jsonl` (UTC day of `run_at`).

Cost: every bucket write is a Class A operation and 5,000 a month are free (statestore.py). A write per run would add
~2,900 a month, so the lines wait in the state (`state["health_pending"]`, Firestore, free) and go to the bucket
together every FLUSH_RUNS runs (hourly: ~720 a month); a closed UTC day goes out at the first run of the next. An append is read-modify-write
with the object's generation as precondition (a concurrent writer makes it retry), lines already in the file (same
`run_at`) are not added twice, and a failed append never fails the run: the lines stay pending (up to PENDING_CAP)
and go with the next one. The live state document is unchanged except for the pending lines.

Size: ~30-40 KB a line raw (the probe lists every source), 96 lines a day, gzip about 10x: ~0.4 MB a day in the bucket.
"""
from __future__ import annotations

import copy

FLUSH_RUNS = 4
PENDING_CAP = 400  # about four days of runs: never grows without bound if the bucket stays unreachable
TRIES = 3


def key_for(day: str) -> str:
    return f"health/{day}.jsonl"


def make_line(state: dict, summary: dict) -> dict:
    """A deep copy, so later changes to the live summary never touch it."""
    return copy.deepcopy({"run_at": summary.get("run_at"), "summary": summary, "feed_health": state.get("feed_health")})


def append_day(sink, day: str, lines: list[dict], tries: int = TRIES) -> bool:
    """Add `lines` to health/<day>.jsonl, skipping run_at values already there. True when they are all stored."""
    key = key_for(day)
    for _ in range(tries):
        rows, version = sink.read_lines_versioned(key)
        have = {r.get("run_at") for r in rows}
        new = [ln for ln in lines if ln["run_at"] not in have]
        if not new:
            return True
        if sink.write_lines_if(key, rows + new, version):
            return True
    return False


def flush(sink, pending: list[dict]) -> tuple[list[dict], str | None]:
    """Append every pending line to its day file. Returns (lines still pending, error text or None)."""
    by_day: dict[str, list[dict]] = {}
    for ln in pending:
        by_day.setdefault(ln["run_at"][:10], []).append(ln)
    left, error = [], None
    for day, lines in sorted(by_day.items()):
        try:
            ok = append_day(sink, day, lines)
        except Exception as e:  # noqa: BLE001 - the health record must never stop an ingest run
            ok, error = False, f"{day}: {e}"[:200]
        if not ok:
            error = error or f"{day}: append kept losing the race"
            left += lines
    return sorted(left, key=lambda ln: ln["run_at"]), error


def record(sink, state: dict, summary: dict) -> None:
    """Add this run's line to the pending list and flush when it is due. Never raises."""
    try:
        pending = state.setdefault("health_pending", [])
        if summary.get("run_at"):
            pending.append(make_line(state, summary))
        newest = max(ln["run_at"][:10] for ln in pending) if pending else None
        if len(pending) >= FLUSH_RUNS:
            due, keep = pending, []
        else:  # a closed UTC day goes out at once; the new day's first lines wait for company
            due = [ln for ln in pending if ln["run_at"][:10] != newest]
            keep = [ln for ln in pending if ln["run_at"][:10] == newest]
        if due:
            left, error = flush(sink, due)
            state["health_pending"] = sorted(left + keep, key=lambda ln: ln["run_at"])[-PENDING_CAP:]
            if error:
                summary["health_log_error"] = error
    except Exception as e:  # noqa: BLE001
        summary["health_log_error"] = f"{e}"[:200]
