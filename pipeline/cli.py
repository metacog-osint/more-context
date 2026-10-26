"""Command line for MORE CONTEXT pipeline steps.

    python -I run.py measure-reprints --hours 6
    python -I run.py measure-reprints --from-jsonl data/raw/matched-<stamp>.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import gdelt
from .match import Matcher
from .stories import build_stories

DATA = Path(__file__).resolve().parent.parent / "data"


def collect(hours: float, streams: list[str], workers: int = 4) -> tuple[list[dict], dict]:
    """Download the window, keep articles that match a zone or topic. Returns (rows, stats)."""
    matcher = Matcher()
    jobs, ends = [], {}
    for stream in streams:
        ends[stream] = gdelt.latest_stamp(stream)
        jobs += [(s, stream) for s in gdelt.window_stamps(ends[stream], hours)]

    def work(job):
        stamp, stream = job
        data = None
        for attempt in range(2):
            try:
                data = gdelt.download(stamp, stream)
                break
            except Exception as e:  # network hiccup: one retry, then record the failure
                if attempt == 1:
                    return job, "failed", 0, 0, [], str(e)
                time.sleep(3)
        if data is None:
            return job, "missing", 0, 0, [], ""
        rows, scanned = [], 0
        for art in gdelt.parse_zip(data, stream):
            scanned += 1
            labels = matcher.labels(art)
            if labels:
                d = art.to_dict()
                d["labels"] = labels
                rows.append(d)
        return job, "ok", len(data), scanned, rows, ""

    stats = {"window_hours": hours, "streams": streams, "end_stamps": ends, "files_ok": 0,
             "files_missing": [], "files_failed": [], "bytes_downloaded": 0, "articles_scanned": 0}
    rows: list[dict] = []
    started = time.time()
    with ThreadPoolExecutor(workers) as ex:
        futures = [ex.submit(work, j) for j in jobs]
        for n, fut in enumerate(as_completed(futures), 1):
            job, status, size, scanned, got, err = fut.result()
            if status == "ok":
                stats["files_ok"] += 1
                stats["bytes_downloaded"] += size
                stats["articles_scanned"] += scanned
                rows += got
            elif status == "missing":
                stats["files_missing"].append(f"{job[1]}:{job[0]}")
            else:
                stats["files_failed"].append(f"{job[1]}:{job[0]} {err}")
            if n % 8 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)} files, {stats['articles_scanned']:,} scanned, "
                      f"{len(rows):,} matched, {time.time() - started:.0f}s", flush=True)
    stats["elapsed_s"] = round(time.time() - started, 1)
    return rows, stats


def reprint_report(rows: list[dict], names: dict) -> list[dict]:
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        for label in r["labels"]:
            by_entity[label].append(r)
    report = []
    for eid in sorted(by_entity):
        arts = by_entity[eid]
        urls = {a["url"] for a in arts}
        stories = build_stories(arts)
        multi = sum(s["articles"] for s in stories if s["articles"] > 1)
        report.append({
            "entity": eid,
            "name": names.get(eid, eid),
            "articles": len(urls),
            "stories": len(stories),
            "inflation": round(len(urls) / len(stories), 2) if stories else None,
            "share_in_multi_article_stories": round(multi / len(urls), 3) if urls else None,
            "top_stories": [{k: s[k] for k in ("title", "articles", "outlets", "languages", "sample_urls")}
                            for s in stories[:5]],
        })
    report.sort(key=lambda e: -e["articles"])
    return report


def cmd_measure_reprints(args) -> int:
    matcher = Matcher()
    if args.from_jsonl:
        path = Path(args.from_jsonl)
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        stats = {"source": str(path)}
        tag = path.stem.replace("matched-", "")
    else:
        streams = [s.strip() for s in args.streams.split(",") if s.strip()]
        print(f"Downloading {args.hours} h of GKG files ({', '.join(streams)})...", flush=True)
        rows, stats = collect(args.hours, streams, args.workers)
        tag = f"{stats['end_stamps'][streams[0]]}-{args.hours:g}h"
        raw = DATA / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        with (raw / f"matched-{tag}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    report = reprint_report(rows, matcher.names)
    total_articles = sum(e["articles"] for e in report)
    total_stories = sum(e["stories"] for e in report)
    out = {"stats": stats, "totals": {"articles": total_articles, "stories": total_stories,
           "inflation": round(total_articles / total_stories, 2) if total_stories else None},
           "entities": report}
    reports = DATA / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    dest = reports / f"reprints-{tag}.json"
    dest.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n{'entity':<28}{'articles':>9}{'stories':>9}{'ratio':>7}{'in multi':>10}")
    for e in report:
        print(f"{e['entity']:<28}{e['articles']:>9,}{e['stories']:>9,}{e['inflation']:>7.2f}"
              f"{e['share_in_multi_article_stories']:>10.0%}")
    print(f"{'ALL (zone+topic labels)':<28}{total_articles:>9,}{total_stories:>9,}"
          f"{out['totals']['inflation'] or 0:>7.2f}")
    if "files_ok" in stats:
        print(f"\nfiles ok {stats['files_ok']}, missing {len(stats['files_missing'])}, failed "
              f"{len(stats['files_failed'])}; {stats['bytes_downloaded'] / 1e6:,.0f} MB; "
              f"{stats['articles_scanned']:,} articles scanned in {stats['elapsed_s']}s")
    print(f"report: {dest}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("measure-reprints", help="how much reprints inflate article counts")
    m.add_argument("--hours", type=float, default=6)
    m.add_argument("--streams", default="english,translation")
    m.add_argument("--workers", type=int, default=4)
    m.add_argument("--from-jsonl", help="re-run grouping on a saved matched-*.jsonl file")
    m.set_defaults(func=cmd_measure_reprints)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
