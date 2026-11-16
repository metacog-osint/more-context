"""Relations between countries for past days, from GDELT's public Events files (15 Nov 2026). Free.

Writes `stories/YYYY/MM/DD/relations.json` per day (the same table the daily build writes from the cycle's Events
records; pipeline/relations.py), then rebuilds `relations/series.json` from the stored days. Days already written are
skipped unless --force. About 20 MB of downloads and 10-25 s a day.

    python -I scripts/backfill_relations.py --start 2026-07-18 --end 2026-11-14 --root data/backfill/relations
    python -I scripts/backfill_relations.py --series-only --end 2026-11-14 --root data/backfill/relations

--bucket NAME reads and writes the Cloud Storage bucket instead of --root, through the storage JSON API with the
gcloud user's token (`gcloud auth print-access-token`; never printed), so it runs on Tom's laptop without the
google-cloud-storage package: one write per day plus one for the series (Class A), and up to 120 reads to rebuild
the series. Objects are gzip with Content-Encoding gzip, like pipeline/sinks.py. Writes to the live bucket: Tom's
yes first.

    python -I scripts/backfill_relations.py --bucket more-context-484804 --start 2026-11-15 --end 2026-11-15 --force

That example re-does 15 Nov 2026, built as partial because the ingest only began writing pair tables at 18:07 UTC
(mc-ingest-00022-zul); run it after that day's build (after 03:20 UTC 16 Nov).

--press does the press-tone section instead (pipeline/press.py): every GKG 2.1 file of each day, both streams (about
1.3 GB of downloads and 5 minutes a day on Tom's connection), summed into the day's `press` section; the rest of an
existing relations.json is kept. A pairs run keeps an existing `press` section the same way. Days that already have
a press section are skipped unless --force. Run it from C: when D: may sleep (data stays in memory; nothing is saved
but the day files).

    python -I scripts/backfill_relations.py --press --bucket more-context-484804 --start 2026-10-19 --end 2026-11-15
"""
from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import events, gdelt, press, relations  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402

STREAMS = ("english", "translation")
API = "https://storage.googleapis.com"
GZIP_MAGIC = bytes([0x1F, 0x8B])


class TokenSink:
    """The few sink calls the backfill needs, over the storage JSON API with the gcloud user's token."""

    def __init__(self, bucket: str):
        self.bucket = bucket
        gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        self.token = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True,
                                    text=True).stdout.strip() if gcloud else ""
        if not self.token:
            sys.exit("gcloud auth print-access-token gave nothing: run gcloud auth login")

    def _obj(self, key: str) -> str:
        return f"{API}/storage/v1/b/{self.bucket}/o/" + urllib.parse.quote(key, safe="")

    def _open(self, req: urllib.request.Request):
        req.add_header("Authorization", "Bearer " + self.token)
        return urllib.request.urlopen(req, timeout=120)

    def exists(self, key: str) -> bool:
        try:
            with self._open(urllib.request.Request(self._obj(key))):
                return True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise

    def read_json(self, key: str) -> dict | None:
        try:  # gzip objects come back zipped when stored with no-transform (gcloud storage cp -Z): unzip either way
            with self._open(urllib.request.Request(self._obj(key) + "?alt=media")) as r:
                data = r.read()
            return json.loads((gzip.decompress(data) if data[:2] == GZIP_MAGIC else data).decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise

    def write_json(self, key: str, obj: dict) -> None:
        body = gzip.compress(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        q = urllib.parse.urlencode({"uploadType": "media", "name": key, "contentEncoding": "gzip"})
        req = urllib.request.Request(f"{API}/upload/storage/v1/b/{self.bucket}/o?{q}", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        with self._open(req):
            pass


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


def _press_file(stamp: str, stream: str) -> dict | None:
    for attempt in range(4):
        try:
            data = gdelt.download(stamp, stream)
            break
        except Exception:  # noqa: BLE001
            if attempt == 3:
                raise
            time.sleep(2 + attempt * 4)
    if data is None:
        return None
    return press.FileTable().add_zip(data, stream).row(stamp, stream)


def day_recs(ex: ThreadPoolExecutor, d: date, until: datetime, fn=_file) -> tuple[list[dict], int]:
    stamps, t = [], datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    while t.date() == d and t <= until:
        stamps.append(t.strftime("%Y%m%d%H%M%S"))
        t += timedelta(minutes=15)
    recs, failed = [], 0
    for fut in as_completed([ex.submit(fn, s, st) for s in stamps for st in STREAMS]):
        try:
            r = fut.result()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"  failed: {str(e)[:100]}", flush=True)
            continue
        if r:
            recs.append(r)
    return recs, failed


def merge_press(d: date, old: dict | None, press_recs: list[dict]) -> dict:
    """The day's relations.json with a new press section: the stored pairs kept, or an empty partial pairs part
    when the day has none."""
    rec = dict(old) if old else relations.day_table(d, [])
    rec["press"] = press.day_table(press_recs)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end", required=True)
    ap.add_argument("--root")
    ap.add_argument("--bucket", help="write to this bucket instead of --root (Tom's yes first)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--series-only", action="store_true", help="only rebuild relations/series.json")
    ap.add_argument("--press", action="store_true", help="the press section from GKG files instead of the pairs")
    a = ap.parse_args()
    if bool(a.root) == bool(a.bucket):
        ap.error("give exactly one of --root and --bucket")
    sink = TokenSink(a.bucket) if a.bucket else LocalSink(Path(a.root))
    end = date.fromisoformat(a.end)
    if not a.series_only:
        if not a.start:
            ap.error("--start is required unless --series-only")
        until = datetime.now(timezone.utc) - timedelta(minutes=20)
        d = date.fromisoformat(a.start)
        with ThreadPoolExecutor(a.workers) as ex:
            while d <= end:
                key = f"stories/{d:%Y/%m/%d}/relations.json"
                old = None
                if a.press:
                    old = sink.read_json(key)
                    if not a.force and old and "press" in old:
                        d += timedelta(days=1)
                        continue
                elif not a.force and sink.exists(key):
                    d += timedelta(days=1)
                    continue
                else:
                    old = sink.read_json(key)
                t0 = time.time()
                if a.press:
                    recs, failed = day_recs(ex, d, until, _press_file)
                    rec = merge_press(d, old, recs)
                    p = rec["press"]
                    print(f"{d}: press {p['files']} files, {failed} failed, {len(p['t'])} rows, {p['articles']} "
                          f"articles ({p['unknown']} unknown outlet), {'partial' if p['partial'] else 'complete'}, "
                          f"{time.time() - t0:.0f} s", flush=True)
                else:
                    recs, failed = day_recs(ex, d, until)
                    rec = relations.day_table(d, recs)
                    if old and "press" in old:  # a pairs re-run keeps the day's press section
                        rec["press"] = old["press"]
                    print(f"{d}: {rec['files']} files, {failed} failed, {len(rec['pairs'])} pairs, "
                          f"{'partial' if rec['partial'] else 'complete'}, {time.time() - t0:.0f} s", flush=True)
                sink.write_json(key, rec)
                d += timedelta(days=1)
    s = relations.rebuild_series(sink, end)
    print(f"series: {len(s['days'])} days, {sum(len(v['pairs']) for v in s['days'].values())} pair-days", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
