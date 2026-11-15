"""Relations between countries for past days, from GDELT's public Events files (15 Nov 2026). Free.

Writes `stories/YYYY/MM/DD/relations.json` per day (the same table the daily build writes from the cycle's Events
records; pipeline/relations.py), then rebuilds `relations/series.json` from the stored days. Days already written are
skipped unless --force. About 20 MB of downloads and 10-25 s a day.

    python -I scripts/backfill_relations.py --start 2026-07-18 --end 2026-11-14 --root data/backfill/relations
    python -I scripts/backfill_relations.py --series-only --end 2026-11-14 --root data/backfill/relations

--bucket NAME writes to the Cloud Storage bucket instead of --root: one write per day plus one for the series
(Class A). That is a write to the live bucket: Tom's yes first.
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import events, relations  # noqa: E402
from pipeline.sinks import GCSSink, LocalSink  # noqa: E402

STREAMS = ("english", "translation")


def _file(stamp: str, stream: str) -> dict | None:
    for attempt in range(4):
        try:
            data = events.download(stamp, stream)
            break
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 + attempt * 4)
    if data is None:
        return None
    return {"stamp": stamp, "stream": stream, "pairs": relations.pair_table(events.parse_zip(data), stamp)}


def day_recs(ex: ThreadPoolExecutor, d: date, until: datetime) -> tuple[list[dict], int]:
    stamps, t = [], datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    while t.date() == d and t <= until:
        stamps.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    recs, failed = [], 0
    for fut in as_completed([ex.submit(_file, s, st) for s in stamps for st in STREAMS]):
        try:
            r = fut.result()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  failed: {str(e)[:100]}", flush=True)
            continue
        if r:
            recs.append(r)
    return recs, failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end", required=True)
    ap.add_argument("--root")
    ap.add_argument("--bucket", help="write to this bucket instead of --root (Tom's yes first)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--series-only", action="store_true", help="only rebuild relations/series.json")
    a = ap.parse_args()
    if bool(a.root) == bool(a.bucket):
        ap.error("give exactly one of --root and --bucket")
    sink = GCSSink(a.bucket) if a.bucket else LocalSink(Path(a.root))
    end = date.fromisoformat(a.end)
    if not a.series_only:
        if not a.start:
            ap.error("--start is required unless --series-only")
        until = datetime.now(timezone.utc) - timedelta(minutes=20)
        d = date.fromisoformat(a.start)
        with ThreadPoolExecutor(a.workers) as ex:
            while d <= end:
                key = f"stories/{d:%Y/%m/%d}/relations.json"
                if not a.force and sink.exists(key):
                    d += timedelta(days=1)
                    continue
                t0 = time.time()
                recs, failed = day_recs(ex, d, until)
                rec = relations.day_table(d, recs)
                sink.write_json(key, rec)
                print(f"{d}: {rec['files']} files, {failed} failed, {len(rec['pairs'])} pairs, "
                      f"{'partial' if rec['partial'] else 'complete'}, {time.time() - t0:.0f} s", flush=True)
                d += timedelta(days=1)
    s = relations.rebuild_series(sink, end)
    print(f"series: {len(s['days'])} days, {sum(len(v['pairs']) for v in s['days'].values())} pair-days", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
