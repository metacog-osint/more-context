"""Download GDELT Events files for past days and write one compact record per 15-minute slot (28 Oct 2026). Free.

Writes `events/YYYY/MM/DD/<stamp>.json` ({"files": [english record, translation record]}) under --root, the same
records the cloud cycle writes, then (unless --no-build) builds `stories/YYYY/MM/DD/countries.json` oldest first.
Re-running skips slots already written. Country names seen go to `events/names.json` (merged counts).

    python -I scripts/backfill_events.py --start 2026-07-29 --end 2026-10-28 --root data/backfill/baseline
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import countries, events  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402

STREAMS = ("english", "translation")


def slots(start: date, end: date, until: datetime) -> list[str]:
    t = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    stop = min(until, datetime(end.year, end.month, end.day, 23, 45, tzinfo=timezone.utc))
    out = []
    while t <= stop:
        out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    return out


def fetch_slot(stamp: str) -> tuple[str, list[dict], dict]:
    recs, names = [], {}
    for stream in STREAMS:
        for attempt in range(3):
            try:
                data = events.download(stamp, stream)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 + attempt * 3)
        if data is None:
            continue
        rows = events.parse_zip(data)
        recs.append(events.record(rows, stamp, stream))
        for cc, n in events.country_names(rows).items():
            names[(cc, n)] = names.get((cc, n), 0) + 1
    return stamp, recs, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--root", required=True)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    sink = LocalSink(Path(a.root))
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    # Only slots GDELT has had at least 20 minutes to publish.
    until = datetime.now(timezone.utc) - timedelta(minutes=20)
    todo = [s for s in slots(start, end, until) if not sink.exists(f"events/{s[:4]}/{s[4:6]}/{s[6:8]}/{s}.json")]
    print(f"{len(todo)} slots to fetch", flush=True)
    names_key = "events/names.json"
    names = {tuple(k.split("|", 1)): v for k, v in (sink.read_json(names_key) or {}).items()}
    done, missing, failed, t0 = 0, 0, 0, time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        for fut in [ex.submit(fetch_slot, s) for s in todo]:
            try:
                stamp, recs, got = fut.result()
            except Exception as e:
                failed += 1
                print("failed:", str(e)[:120], flush=True)
                continue
            if not recs:
                missing += 1
                continue
            sink.write_json(f"events/{stamp[:4]}/{stamp[4:6]}/{stamp[6:8]}/{stamp}.json", {"files": recs})
            for k, v in got.items():
                names[k] = names.get(k, 0) + v
            done += 1
            if done % 250 == 0:
                sink.write_json(names_key, {f"{cc}|{n}": v for (cc, n), v in names.items()})
                print(f"  {done}/{len(todo)} slots, {missing} missing, {failed} failed, {time.time() - t0:.0f} s", flush=True)
    sink.write_json(names_key, {f"{cc}|{n}": v for (cc, n), v in names.items()})
    print(f"fetched {done}, missing {missing}, failed {failed}, {time.time() - t0:.0f} s", flush=True)
    if not a.no_build:
        d = start
        while d <= end:
            out = countries.build_day(sink, d)
            print(d, "partial" if out["partial"] else "", f"{out['files']} files, {len(out['rising'])} rising", flush=True)
            d += timedelta(days=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
