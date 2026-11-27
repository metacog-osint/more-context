"""Replay GDELT's raw archive through the live pipeline code, for days before ingest began. Free: GDELT's files
cost nothing to download; nothing here calls Vertex or BigQuery.

Each 15-minute GKG file becomes one cycle file, `cycles/YYYY/MM/DD/HHMMSS.jsonl` (named by GDELT stamp), with
the same rows the cloud cycle writes (v4.3 labels, source groups, casualty counts). Days are then built oldest
first with the daily builder, so each day's attention baseline uses the days before it.

    python -I scripts/backfill.py --start 2026-09-28 --end 2026-10-25 --root data/backfill/baseline
    python -I scripts/backfill.py --start 2025-12-01 --end 2026-03-15 --every 4 --root data/backfill/iran-runup

--every 4 keeps one file per hour (counts are then a quarter of full volume: fine for a separate run-up profile,
never for the live baselines). Re-running skips files already written. Upload afterwards (needs approval):
    gcloud storage rsync data/backfill/baseline/stories gs://more-context-484804/stories --recursive
rsync stores the files plain; compress them after (dry run first, each rewrite is one Class A write):
    python -I scripts/recompress.py --bucket more-context-484804 --prefix stories/
"""
from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import daily, gdelt  # noqa: E402
from pipeline.cycle import gdelt_rows  # noqa: E402
from pipeline.match import Matcher  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402
from scripts.rescore_archive import ArchiveError, archive_local, stamp_now  # noqa: E402

STREAMS = ("english", "translation")


def stamps(start: date, end: date, every: int, until: datetime | None) -> list[str]:
    t = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    stop = until or datetime(end.year, end.month, end.day, 23, 45, tzinfo=timezone.utc)
    out = []
    i = 0
    while t <= stop:
        if i % every == 0:
            out.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
        i += 1
    return out


def key_for(stamp: str, stream: str) -> str:
    # One cycle file per GDELT file; the stream suffix keeps English and translated rows apart.
    return f"cycles/{stamp[:4]}/{stamp[4:6]}/{stamp[6:8]}/{stamp[8:14]}{'' if stream == 'english' else 't'}.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--until", help="last stamp to fetch, YYYYmmddHHMM (UTC), e.g. to stop where live ingest began")
    ap.add_argument("--every", type=int, default=1)
    ap.add_argument("--root", required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)
    until = datetime.strptime(a.until, "%Y%m%d%H%M").replace(tzinfo=timezone.utc) if a.until else None
    sink = LocalSink(Path(a.root))
    matcher = Matcher()
    jobs = [(s, st) for s in stamps(start, end, a.every, until) for st in STREAMS if not sink.exists(key_for(s, st))]
    print(f"{len(jobs)} files to fetch ({a.start} to {a.end}, every {a.every}); root {a.root}", flush=True)

    def work(job):
        stamp, stream = job
        for attempt in range(3):
            try:
                data = gdelt.download(stamp, stream)
                break
            except Exception as e:
                if attempt == 2:
                    return job, f"failed: {e}", 0, 0
                time.sleep(5 * (attempt + 1))
        if data is None:
            sink.write_lines(key_for(stamp, stream), [])  # GDELT has no file for this slot; remember it
            return job, "missing", 0, 0
        rows = gdelt_rows(stamp, stream, data, matcher)
        sink.write_lines(key_for(stamp, stream), rows)
        return job, "ok", len(data), len(rows)

    started, done, mb, matched, problems = time.time(), 0, 0.0, 0, []
    with ThreadPoolExecutor(a.workers) as ex:
        for fut in as_completed([ex.submit(work, j) for j in jobs]):
            job, status, size, n = fut.result()
            done += 1
            mb += size / 1e6
            matched += n
            if status != "ok":
                problems.append(f"{job[1]}:{job[0]} {status}")
            if done % 50 == 0 or done == len(jobs):
                rate = done / max(time.time() - started, 1)
                print(f"  {done}/{len(jobs)} files, {mb:,.0f} MB, {matched:,} rows, "
                      f"~{(len(jobs) - done) / rate / 60:.0f} min left", flush=True)
    if problems:
        print(f"{len(problems)} files missing or failed, e.g. {problems[:3]}")
    if not a.no_build:
        d = start
        stamp = stamp_now()
        while d <= end:
            try:  # the build replaces the day's story files: keep the originals first (retention M4)
                archive_local(Path(a.root), sink.list(f"stories/{d:%Y/%m/%d}/"), stamp)
            except ArchiveError as e:
                sys.exit(f"REFUSING to build {d}: {e}")
            r = daily.build_day(sink, d)
            s = sink.read_json(f"stories/{d:%Y/%m/%d}/summary.json")
            s["backfill"] = {"every": a.every, "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            sink.write_json(f"stories/{d:%Y/%m/%d}/summary.json", s)
            print(f"  built {r['day']}: {r['gdelt_articles']:,} articles, {r['stories']:,} stories, alarms {list(r['alarms'])}")
            d += timedelta(days=1)
    print(f"done in {(time.time() - started) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
