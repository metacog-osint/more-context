"""Event-free simulation: false-alarm rate of each estimator.

python -I scripts/zcal/sim.py <folder of YYYY-MM-DD.json> <out.json> [seed]
Each country-metric keeps its own measured level and dispersion (last 90 stored days, weekday-adjusted, moments,
clipped to [0.01, 3]) and the pooled weekday shape. Two worlds:
  S1 stationary negative binomial (no events, no drift);
  S2 the same with a slow AR(1) drift of the log level (phi 0.95, stationary SD 0.2): no events, but news volume
     wanders, as real coverage does.
70 scored days per country after a 28-day warm-up. Scores use the same rules as live: 28-day baseline, Rising needs
z >= 2.5, ratio >= 1.5 and 40 (attention) / 15 (violence) articles.
"""
from __future__ import annotations

import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
import estimators as E  # noqa: E402
from real import load  # noqa: E402

MIN_ART = {"urls": 40, "violent": 15}
THRESH = (2.0, 2.5, 3.0, 3.5, 4.0)


def nb_draw(rng: random.Random, mu: float, alpha: float) -> int:
    lam = rng.gammavariate(1 / alpha, mu * alpha) if alpha > 0 else mu
    # Poisson by inversion for small lam, normal approximation above 500
    if lam > 500:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def main(folder: Path, out: Path, seed: int = 7) -> None:
    rng = random.Random(seed)
    days, complete, counts, _ = load(folder)
    end = complete[-1]
    params = {}
    for m in counts:
        bases = {cc: {d: h.get(d, 0) for d in complete if end - timedelta(days=90) <= d} for cc, h in counts[m].items()}
        prof = E.pooled_profile([{d: c for d, c in b.items() if d > end - timedelta(days=28)} for b in bases.values()])
        fac = {wd: math.exp(v) for wd, v in prof.items()}
        fm = mean(fac.values())
        fac = {wd: v / fm for wd, v in fac.items()}
        for cc, b in bases.items():
            adj = [c / fac[d.weekday()] for d, c in b.items()]
            mu = mean(adj)
            if mu < 0.2:
                continue
            var = sum((a - mu) ** 2 for a in adj) / (len(adj) - 1)
            alpha = min(3.0, max(0.01, (var - mu) / mu ** 2))
            params[(m, cc)] = (mu, alpha, fac)
    print("country-metrics", len(params), file=sys.stderr)
    start = date(2026, 1, 5)
    res = {}
    for world in ("S1", "S2"):
        tally = {name: {"n": 0, "zs": [], "rising": 0, "by_level": {}} for name in E.ESTIMATORS}
        for (m, cc), (mu, alpha, fac) in params.items():
            prof = {wd: math.log(f) for wd, f in fac.items()}
            series, lvl = {}, 0.0
            sd_eps = 0.2 * math.sqrt(1 - 0.95 ** 2)
            for i in range(98):
                d = start + timedelta(days=i)
                if world == "S2":
                    lvl = 0.95 * lvl + rng.gauss(0, sd_eps)
                series[d] = nb_draw(rng, mu * fac[d.weekday()] * math.exp(lvl - (0.02 if world == "S2" else 0)), alpha)
            dlist = sorted(series)
            for i in range(28, 98):
                d = dlist[i]
                base = {x: series[x] for x in dlist[i - 28:i]}
                x = series[d]
                band = "lt5" if mu < 5 else "5-40" if mu < 40 else "ge40"
                for name, f in E.ESTIMATORS.items():
                    r = f(base, d, x, profile=prof, factors=fac, alpha_pool=0.1)
                    if r is None:
                        continue
                    t = tally[name]
                    t["n"] += 1
                    t["zs"].append(r["z"])
                    bl = t["by_level"].setdefault(band, {"n": 0, "ge25": 0})
                    bl["n"] += 1
                    bl["ge25"] += r["z"] >= 2.5
                    ratio = x / r["expected"] if r["expected"] > 0 else 0
                    if r["z"] >= 2.5 and ratio >= 1.5 and x >= MIN_ART[m]:
                        t["rising"] += 1
        res[world] = {}
        for name, t in tally.items():
            zs = sorted(t["zs"])
            q = lambda p: zs[int(p * (len(zs) - 1))]  # noqa: E731
            res[world][name] = {
                "n": t["n"], "sd_z": round(pstdev(zs), 3), "iqr_sd_z": round((q(0.75) - q(0.25)) / 1.349, 3),
                "median_z": round(median(zs), 3),
                "rate": {f"{th}": round(sum(z >= th for z in zs) / len(zs) * 100, 3) for th in THRESH},
                "rising_rate_pct": round(t["rising"] / t["n"] * 100, 3),
                "rising_per_day": round(t["rising"] / 70, 2),
                "by_level_ge25_pct": {k: [v["n"], round(v["ge25"] / v["n"] * 100, 3)] for k, v in t["by_level"].items()},
            }
        print(world, json.dumps(res[world], indent=1), file=sys.stderr)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 7)
