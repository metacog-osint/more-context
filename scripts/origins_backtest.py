"""Backtest independent origins on the archive (17-18 Nov 2026; free: GDELT downloads, local files, no bucket writes).

  python -I scripts/origins_backtest.py fetch --start 2026-09-19 --end 2026-11-17 --out data/origins
  python -I scripts/origins_backtest.py report --start 2026-10-17 --end 2026-11-17 --out data/origins \
      --stored data/origins/bucket

`fetch` re-reads each day's raw GDELT Events files (both streams, 192 a day, about 20 MB), because the stored
records keep counts, not links. Rows are filtered as `events.record` does (country code folded, events dated more
than two days before the file skipped). Per country it writes `days/YYYY-MM-DD.json`: articles (distinct URLs),
the stored-style count (distinct per file, summed), and `pipeline/origins.summarise` for all articles and for the
violent ones.

`report` reads those files and a local copy of the stored `countries.json` days (gcloud storage rsync of
stories/, read only) and answers: how often does a flagged country-day rest on one or two origins? Test A collapses
the day's largest one or two clusters to one article each and re-scores against the stored baseline. Test B scores
origins against origins (same estimator, robust-1, same Rising rule) and compares with articles against articles
from the same raw files.
"""
from __future__ import annotations

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipeline import countries, events, origins, sinks, zstats  # noqa: E402

TOP_KEPT_MIN = 15  # keep cluster samples for countries with at least this many articles


def _days(a: str, b: str):
    d, end = date.fromisoformat(a), date.fromisoformat(b)
    while d <= end:
        yield d
        d += timedelta(days=1)


def _file(stamp: str, stream: str):
    for attempt in range(3):
        try:
            data = events.download(stamp, stream)
            return stamp, stream, (events.parse_zip(data) if data else None)
        except Exception as e:  # noqa: BLE001 - retried, then reported as missing
            err = e
    print(f"  {stamp} {stream}: {err}", file=sys.stderr)
    return stamp, stream, None


def fetch_day(day: date, workers: int = 8) -> dict:
    stamps = [f"{day:%Y%m%d}{h:02d}{m:02d}00" for h in range(24) for m in (0, 15, 30, 45)]
    jobs = [(s, st) for s in stamps for st in ("english", "translation")]
    urls: dict[str, set] = {}
    violent: dict[str, set] = {}
    file_sum: dict[str, list[int]] = {}
    got = {"english": 0, "translation": 0}
    with ThreadPoolExecutor(workers) as pool:
        for stamp, stream, rows in pool.map(lambda j: _file(*j), jobs):
            if rows is None:
                continue
            got[stream] += 1
            oldest = (datetime.strptime(stamp[:8], "%Y%m%d") - timedelta(days=events.MAX_AGE_DAYS)).strftime("%Y%m%d")
            fu: dict[str, set] = {}
            fv: dict[str, set] = {}
            for r in rows:
                cc = events.canon(r[events.GCC])
                if not cc or r[events.DAY] < oldest:
                    continue
                fu.setdefault(cc, set()).add(r[events.URL])
                if r[events.ROOTCODE] in events.VIOLENT_ROOTS:
                    fv.setdefault(cc, set()).add(r[events.URL])
            for cc, s in fu.items():
                urls.setdefault(cc, set()).update(s)
                fs = file_sum.setdefault(cc, [0, 0])
                fs[0] += len(s)
                fs[1] += len(fv.get(cc, ()))
            for cc, s in fv.items():
                violent.setdefault(cc, set()).update(s)
    out = {}
    for cc, s in urls.items():
        u = origins.summarise(sorted(s))
        v = origins.summarise(sorted(violent.get(cc, ())))
        if u["articles"] < TOP_KEPT_MIN:
            u.pop("top")
        if v["articles"] < TOP_KEPT_MIN:
            v.pop("top")
        out[cc] = {"stored_urls": file_sum[cc][0], "stored_violent": file_sum[cc][1], "urls": u, "violent": v}
    return {"day": day.isoformat(), "files": got, "countries": out}


def cmd_fetch(a) -> None:
    root = Path(a.out) / "days"
    root.mkdir(parents=True, exist_ok=True)
    for d in _days(a.start, a.end):
        p = root / f"{d}.json"
        if p.exists() and not a.force:
            continue
        t0 = datetime.now()
        res = fetch_day(d, a.workers)
        p.write_text(json.dumps(res, separators=(",", ":")), encoding="utf-8")
        print(f"{d} files {res['files']} countries {len(res['countries'])} {(datetime.now() - t0).seconds}s", flush=True)


# ---- report -------------------------------------------------------------------------------------------------------

def _complete(day_file: dict) -> bool:
    f = day_file["files"]
    need = countries.FILES_PER_STREAM * countries.MIN_FILE_SHARE
    return f["english"] >= need and f["translation"] >= need


def _rising(s: dict | None, n: int, metric: str) -> bool:
    """countries._listed's Rising rule for one country."""
    if not s or n < countries.MIN_ARTICLES[metric]:
        return False
    ratio_ok = (s.get("ratio") or 0) >= countries.RISING_RATIO or (s.get("expected") is not None and s["expected"] <= 1)
    return (s.get("z") or 0) >= countries.RISING_Z and ratio_ok


def own_history(days: dict[date, dict], key: str, metric: str) -> tuple[dict[str, dict[date, int]], list[date]]:
    """country -> day -> value from the fetched files; key 'articles' or 'origins'."""
    hist: dict[str, dict[date, int]] = {}
    complete = [d for d, f in days.items() if _complete(f)]
    for d in complete:
        for cc, c in days[d]["countries"].items():
            hist.setdefault(cc, {})[d] = c[metric][key]
    return hist, complete


def cmd_report(a) -> None:
    out = Path(a.out)
    days = {}
    for p in sorted((out / "days").glob("*.json")):
        days[date.fromisoformat(p.stem)] = json.loads(p.read_text(encoding="utf-8"))
    stored = sinks.LocalSink(Path(a.stored))
    known = countries.names()
    test_days = [d for d in _days(a.start, a.end) if d in days]
    res = {"A": [], "B": {}}
    for metric in countries.SCORED:
        own = {k: own_history(days, k, metric) for k in ("articles", "origins")}
        b_counts = {"articles_flags": 0, "origins_flags": 0, "both": 0, "articles_only": 0, "origins_only": 0}
        for d in test_days:
            cd = stored.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
            if not cd or cd.get("partial"):
                continue
            # Test A: the stored flags, re-scored with the largest one or two clusters collapsed.
            hist, complete = countries.history(stored, d)
            prof = countries.profile(hist[metric], complete, d)
            for cc in cd["lists"][metric]["rising"]:
                o = days[d]["countries"].get(cc, {}).get(metric)
                if not o:
                    continue
                n = cd["countries"][cc][metric]
                sizes = o["sizes"] + [1, 1]
                c1 = n - (sizes[0] - 1)
                c2 = c1 - (sizes[1] - 1)
                s0 = cd["countries"][cc][f"{metric}_score"]
                s1 = countries.score(hist[metric].get(cc, {}), complete, d, c1, prof)
                s2 = countries.score(hist[metric].get(cc, {}), complete, d, c2, prof)
                res["A"].append({
                    "day": d.isoformat(), "cc": cc, "name": known.get(cc, cc), "metric": metric, "count": n,
                    "z": s0.get("z"), "articles": o["articles"], "origins": o["origins"], "outlets": o["outlets"],
                    "no_text": o["no_text"], "top": o.get("top", [])[:3], "sizes": o["sizes"],
                    "z_top1": s1.get("z"), "z_top2": s2.get("z"),
                    "survives_top1": _rising(s1, c1, metric), "survives_top2": _rising(s2, c2, metric)})
            # Test B: own-file articles against articles, origins against origins.
            flags = {}
            for k in ("articles", "origins"):
                h, comp = own[k]
                pr = zstats.pooled_profile([countries.baseline(x, comp, d) for x in h.values()])
                flags[k] = set()
                for cc, c in days[d]["countries"].items():
                    if cc not in known or cc in countries.NOT_COUNTRIES:
                        continue
                    v = c[metric][k]
                    s = countries.score(h.get(cc, {}), comp, d, v, pr)
                    # The article minimum stays on articles, so origins are not held to a stricter floor.
                    if _rising(s, c[metric]["articles"], metric):
                        flags[k].add(cc)
            fa, fo = flags["articles"], flags["origins"]
            b_counts["articles_flags"] += len(fa)
            b_counts["origins_flags"] += len(fo)
            b_counts["both"] += len(fa & fo)
            b_counts["articles_only"] += len(fa - fo)
            b_counts["origins_only"] += len(fo - fa)
            res["B"].setdefault("days", {}).setdefault(d.isoformat(), {})[metric] = {
                "articles_only": sorted(fa - fo), "origins_only": sorted(fo - fa), "both": sorted(fa & fo)}
        res["B"][metric] = b_counts
    (out / "report.json").write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    for metric in countries.SCORED:
        rows = [r for r in res["A"] if r["metric"] == metric]
        n = len(rows)
        lost1 = sum(1 for r in rows if not r["survives_top1"])
        lost2 = sum(1 for r in rows if not r["survives_top2"])
        print(f"A {metric}: {n} stored Rising flags; rest on one origin {lost1} ({lost1 / max(n, 1):.0%}), "
              f"on one or two {lost2} ({lost2 / max(n, 1):.0%})")
        print(f"B {metric}: {res['B'][metric]}")


def cmd_zones(a) -> None:
    """Zone alarms (attention z >= 2 on headline-filtered stories) re-scored with the day's largest one or two
    clusters of filtered stories collapsed to one story each. Stories are already reprint-grouped (stories.py,
    title Jaccard >= 0.6); this regroups their titles at 80% overlap, group average, as for countries."""
    from pipeline import daily, measures
    from pipeline.relevance import TermMatcher
    stored = sinks.LocalSink(Path(a.stored))
    matcher = TermMatcher()
    rows = []
    for d in _days(a.start, a.end):
        sm = stored.read_json(f"stories/{d:%Y/%m/%d}/summary.json")
        if not sm or not sm.get("alarms"):
            continue
        key = f"stories/{d:%Y/%m/%d}/stories.jsonl"
        if not stored.exists(key):
            print(f"{d}: no stories file", file=sys.stderr)
            continue
        day_rows = stored.read_lines(key)
        hist = daily.history(stored, d)
        for eid in sm["alarms"]:
            kept = [s for s in day_rows if s.get("kind") == "gdelt" and s.get("entity") == eid
                    and matcher.hit(eid, s.get("title") or "")]
            items = [(s["story_id"], origins.text_tokens("", s.get("title") or "")) for s in kept]
            cl = origins.cluster(items)
            sizes = [len(c) for c in cl] + [1, 1]
            n = sm["entities"][eid]["filtered_stories"]
            c1 = n - (sizes[0] - 1)
            c2 = c1 - (sizes[1] - 1)
            z1 = measures.attention_anomaly(hist.get(eid, {}), d, c1)
            z2 = measures.attention_anomaly(hist.get(eid, {}), d, c2)
            outlets = {o for s in kept for o in s.get("outlet_names", [])}
            top = [{"stories": len(c), "title": kept[c[0]].get("title"),
                    "articles": sum(kept[i]["articles"] for i in c), "outlets": sum(kept[i]["outlets"] for i in c)}
                   for c in cl[:3]]
            rows.append({"day": d.isoformat(), "entity": eid, "filtered_stories": n, "recounted": len(kept),
                         "origins": len(cl), "z": sm["entities"][eid]["attention"]["z"],
                         "z_top1": z1 and z1["z"], "z_top2": z2 and z2["z"],
                         "survives_top1": bool(z1 and z1["z"] >= measures.ALARM_Z and c1 >= measures.ALARM_MIN_STORIES),
                         "survives_top2": bool(z2 and z2["z"] >= measures.ALARM_Z and c2 >= measures.ALARM_MIN_STORIES),
                         "top_story_outlets_shown": len(outlets), "top": top})
    out = Path(a.out)
    (out / "zones.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in rows:
        print(f"{r['day']} {r['entity']}: stories {r['filtered_stories']} (recount {r['recounted']}), origins "
              f"{r['origins']}, z {r['z']} -> top1 {r['z_top1']} / top2 {r['z_top2']}; largest {r['top'][0]['stories'] if r['top'] else 0}")
    n = len(rows)
    print(f"zones: {n} alarms; rest on one origin {sum(not r['survives_top1'] for r in rows)}, "
          f"on one or two {sum(not r['survives_top2'] for r in rows)}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--start", required=True)
    f.add_argument("--end", required=True)
    f.add_argument("--out", default="data/origins")
    f.add_argument("--workers", type=int, default=8)
    f.add_argument("--force", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--start", required=True)
    r.add_argument("--end", required=True)
    r.add_argument("--out", default="data/origins")
    r.add_argument("--stored", default="data/origins/bucket")
    z = sub.add_parser("zones")
    z.add_argument("--start", required=True)
    z.add_argument("--end", required=True)
    z.add_argument("--out", default="data/origins")
    z.add_argument("--stored", default="data/origins/bucket")
    a = p.parse_args()
    {"fetch": cmd_fetch, "report": cmd_report, "zones": cmd_zones}[a.cmd](a)


if __name__ == "__main__":
    main()
