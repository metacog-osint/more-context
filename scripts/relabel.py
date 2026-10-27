"""Apply a catalog change to rows already stored, then rebuild the affected days. Free: no downloads, no models.

Use it when a zone is split, merged or retired (catalog/entities.json "retired"). Every stored GDELT row whose
labels include a retired id is matched again with the current catalog; topic labels are recomputed the same way.
This only works when the new zones' rules are a subset of what the old zone stored (same themes, places within
the old place list): rows the old zone never matched were not kept. A wider rule needs a re-download
(scripts/backfill.py) instead.

    python -I scripts/relabel.py --root data/backfill/baseline --start 2026-09-28 --end 2026-10-26 --dry-run
    python -I scripts/relabel.py --root data/relabel/all --start 2026-09-28 --end 2026-10-26

Cycle files are rewritten in place under --root (copy the originals first if you want them), then every day from
--start to --end is rebuilt oldest first, so each day's attention baseline uses the rebuilt days before it.
A summary that was a backfill keeps its backfill mark.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import daily  # noqa: E402
from pipeline.match import Matcher, load_catalog  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402


def relabel_rows(rows: list[dict], retired: set[str], matcher: Matcher) -> tuple[list[dict], Counter]:
    """Rows with a retired label get fresh labels from `matcher`; returns (rows, counts of new labels)."""
    moved: Counter = Counter()
    for r in rows:
        if r.get("kind") != "gdelt" or not retired & set(r.get("labels") or []):
            continue
        art = SimpleNamespace(locations=r.get("locations", ""), themes=r.get("themes", ""), url=r.get("url", ""))
        r["labels"] = matcher.labels(art)
        moved.update(r["labels"] or ["(none)"])
    return rows, moved


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true", help="count what would move; write nothing")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    sink = LocalSink(Path(a.root))
    catalog = load_catalog()
    retired = {r["id"] for r in catalog.get("retired", [])}
    if not retired:
        print("catalog has no retired ids; nothing to relabel")
        return 0
    matcher = Matcher(catalog)
    start, end = date.fromisoformat(a.start), date.fromisoformat(a.end)

    total, files = Counter(), 0
    d = start
    while d <= end + timedelta(days=1):  # rows published late on `end` can sit in the next day's first files
        for key in sink.list(f"cycles/{d:%Y/%m/%d}"):
            rows = sink.read_lines(key)
            rows, moved = relabel_rows(rows, retired, matcher)
            if moved:
                total += moved
                files += 1
                if not a.dry_run:
                    sink.write_lines(key, rows)
        d += timedelta(days=1)
    print(f"{'would relabel' if a.dry_run else 'relabelled'} rows in {files} cycle files: {dict(total)}")

    if a.dry_run or a.no_build:
        return 0
    d = start
    while d <= end:
        key = f"stories/{d:%Y/%m/%d}/summary.json"
        old = sink.read_json(key) if sink.exists(key) else None
        r = daily.build_day(sink, d)
        if old and old.get("backfill"):
            s = sink.read_json(key)
            s["backfill"] = {**old["backfill"], "relabelled": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
            sink.write_json(key, s)
        print(f"  rebuilt {r['day']}: {r['gdelt_articles']:,} articles, alarms {list(r['alarms'])}")
        d += timedelta(days=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
