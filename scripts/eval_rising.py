"""Compare country counts for the Rising list on backfilled GDELT Events records (28 Oct 2026). Free, local.

For each count (events, articles, lead-paragraph articles, placed articles, violent articles): how many countries
are flagged per day, how named countries read on named days, and the top risers on chosen days with the
headlines (URL slugs) that explain them.

    python -I scripts/eval_rising.py --root data/backfill/baseline --check ET:2026-09-20:2026-09-30 --show 2026-09-23,2026-10-27
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import countries, measures  # noqa: E402
from pipeline.events import METRICS  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402
from pipeline.stories import title_from_url  # noqa: E402

MIN = {"ev": 80, "urls": 40, "root": 30, "place": 30, "violent": 15}


def load(sink, start: date, end: date):
    days, samples, partial = {}, {}, set()
    d = start
    # Reads built days (countries.json: every country's counts; samples for listed and zone countries).
    while d <= end:
        c = sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
        if c:
            days[d] = {cc: {m: v.get(m, 0) for m in METRICS} for cc, v in c["countries"].items()}
            if c.get("partial"):
                partial.add(d)
            samples[d] = c.get("samples", {})
        d += timedelta(days=1)
    return days, samples, partial


def zs(days, partial, metric, day):
    complete = [d for d in days if d < day and d >= day - timedelta(days=28) and d not in partial]
    out = {}
    for cc, t in days[day].items():
        att = measures.attention_anomaly({d: days[d].get(cc, {}).get(metric, 0) for d in complete}, day, t[metric])
        if att:
            out[cc] = (att["z"], att["ratio"], t[metric])
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # headlines in every script; Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--start", default="2026-07-29")
    ap.add_argument("--end", default="2026-10-27")
    ap.add_argument("--check", action="append", default=[], help="CC:first:last")
    ap.add_argument("--show", default="")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    sink = LocalSink(Path(a.root))
    days, samples, partial = load(sink, date.fromisoformat(a.start), date.fromisoformat(a.end))
    nm = countries.names()
    scored_days = [d for d in sorted(days) if d not in partial and d >= min(days) + timedelta(days=28)]
    print(f"{len(days)} days loaded, {len(partial)} partial, {len(scored_days)} scored")
    for metric in METRICS:
        flagged = []
        for d in scored_days:
            z = zs(days, partial, metric, d)
            flagged.append(sum(1 for cc, (zz, r, n) in z.items()
                               if zz >= countries.RISING_Z and (r or 0) >= countries.RISING_RATIO and n >= MIN[metric]))
        print(f"\n== {metric}: flagged per day mean {sum(flagged) / max(len(flagged), 1):.1f}, max {max(flagged or [0])}")
        for chk in a.check:
            cc, f, l = chk.split(":")
            line = []
            d = date.fromisoformat(f)
            while d <= date.fromisoformat(l):
                if d in scored_days:
                    z = zs(days, partial, metric, d).get(cc)
                    line.append(f"{d:%d %b} {z[2]}/z{z[0]}" if z else f"{d:%d %b} -")
                d += timedelta(days=1)
            print(f"  {cc}: " + "  ".join(line))
        for s in filter(None, a.show.split(",")):
            d = date.fromisoformat(s)
            if d not in scored_days:
                continue
            z = zs(days, partial, metric, d)
            top = sorted(((cc, v) for cc, v in z.items() if v[2] >= MIN[metric]), key=lambda kv: -kv[1][0])[:a.top]
            print(f"  {d}:")
            for cc, (zz, r, n) in top:
                heads = [title_from_url(u)[:60] or urlparse(u).netloc for u in samples[d].get(cc, [])[:3]]
                print(f"    {nm.get(cc, cc)[:18]:18} z{zz:>5} x{r} n{n:>5}  | " + " | ".join(heads))
    return 0


if __name__ == "__main__":
    sys.exit(main())
