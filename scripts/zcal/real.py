"""Run the prototype estimators over stored countries.json days (read-only copies on C:).

python -I scripts/zcal/real.py <folder of YYYY-MM-DD.json> <out.json>
Writes per country-day rows: metric, cc, day, count, live z/ratio/expected/median90, and each estimator's z/expected.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimators as E  # noqa: E402

SCORED = ("urls", "violent")


def load(folder: Path):
    days, counts, live, complete = [], {m: {} for m in SCORED}, {}, []
    for p in sorted(folder.glob("*.json")):
        s = json.loads(p.read_text(encoding="utf-8"))
        d = date.fromisoformat(s["day"])
        days.append(d)
        if s.get("partial"):
            continue
        complete.append(d)
        for cc, c in s["countries"].items():
            for m in SCORED:
                counts[m].setdefault(cc, {})[d] = c.get(m, 0)
                sc = c.get(f"{m}_score") or {}
                if sc.get("z") is not None:
                    live[(m, cc, d)] = {"z": sc["z"], "ratio": sc.get("ratio"), "expected": sc.get("expected"),
                                        "median90": sc.get("median90"), "ratio90": sc.get("ratio90")}
        for m in SCORED:
            for k, v in (s.get("lists", {}).get(m) or {}).items():
                for cc in v:
                    live.setdefault((m, cc, d), {})[f"listed_{k}"] = True
    return days, complete, counts, live


def run(folder: Path, out: Path) -> None:
    days, complete, counts, live = load(folder)
    rows = []
    for m in SCORED:
        ccs = list(counts[m])
        for d in complete:
            bases = {cc: E.baseline(counts[m][cc], complete, d) for cc in ccs}
            if sum(1 for b in bases.values() if len(b) >= E.MIN_DAYS) == 0:
                continue
            prof = E.pooled_profile(list(bases.values()))
            fac = {wd: math.exp(v) for wd, v in prof.items()}
            fm = mean(fac.values())
            fac = {wd: v / fm for wd, v in fac.items()}
            ahat = []
            for b in bases.values():
                if len(b) >= E.MIN_DAYS and mean(b.values()) >= 5:
                    adj = [c / fac[x.weekday()] for x, c in b.items()]
                    mu = mean(adj)
                    var = sum((a - mu) ** 2 for a in adj) / (len(adj) - 1)
                    ahat.append(max(0.0, (var - mu) / mu ** 2))
            apool = median(ahat) if ahat else 0.1
            for cc in ccs:
                b = bases[cc]
                if len(b) < E.MIN_DAYS:
                    continue
                x = counts[m][cc].get(d, 0)
                row = {"m": m, "cc": cc, "day": d.isoformat(), "n": x, "base_mean": round(mean(b.values()), 2),
                       "live": live.get((m, cc, d))}
                for name, f in E.ESTIMATORS.items():
                    r = f(b, d, x, profile=prof, factors=fac, alpha_pool=apool)
                    row[name] = None if r is None else [round(r["z"], 3), round(r["expected"], 2)]
                rows.append(row)
        print(m, "done", len(rows), file=sys.stderr)
    out.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


if __name__ == "__main__":
    run(Path(sys.argv[1]), Path(sys.argv[2]))
