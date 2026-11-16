"""Tabulate real-data results from real.py's rows.

python -I scripts/zcal/report_real.py <real.jsonl> <fips_countries.json> <out.json>
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median, pstdev

MIN_ART = {"urls": 40, "violent": 15}
EST = ("A_cur", "B_pred", "C_robust", "D_nb", "E_robust_half")
THRESH = (2.0, 2.5, 3.0, 3.5, 4.0)


def main(rows_p: Path, names_p: Path, out: Path) -> None:
    names = json.loads(names_p.read_text(encoding="utf-8"))["names"]
    rows = [json.loads(l) for l in rows_p.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["live"] and r["live"].get("z") is not None]  # days the live build scored
    res = {"days": [min(r["day"] for r in rows), max(r["day"] for r in rows)],
           "n_days": len({r["day"] for r in rows})}
    listed = {}
    for m in ("urls", "violent"):
        R = [r for r in rows if r["m"] == m]
        res[m] = {}
        for e in EST:
            zs = sorted(r[e][0] for r in R)
            q = lambda p: zs[int(p * (len(zs) - 1))]  # noqa: E731
            big = [r[e][0] for r in R if r["base_mean"] >= 5]
            small = [r[e][0] for r in R if r["base_mean"] < 5]
            rising = set()
            for r in R:
                z, ex = r[e]
                ratio = r["n"] / ex if ex > 0 else 0
                if z >= 2.5 and ratio >= 1.5 and r["n"] >= MIN_ART[m] and r["cc"] in names:
                    rising.add((r["day"], r["cc"]))
            listed[(m, e)] = rising
            per_day = Counter(d for d, _ in rising)
            nd = res["n_days"]
            res[m][e] = {
                "n": len(zs), "sd_z": round(pstdev(zs), 3), "iqr_sd_z": round((q(.75) - q(.25)) / 1.349, 3),
                "median_z": round(q(.5), 3),
                "rate_pct": {str(t): round(sum(z >= t for z in zs) / len(zs) * 100, 2) for t in THRESH},
                "rate_pct_base_ge5": {str(t): round(sum(z >= t for z in big) / len(big) * 100, 2) for t in THRESH},
                "rate_pct_base_lt5": {str(t): round(sum(z >= t for z in small) / len(small) * 100, 2) for t in THRESH},
                "rising_total": len(rising),
                "rising_per_day_mean": round(len(rising) / nd, 2),
                "rising_per_day_range": [min(per_day.get(d, 0) for d in {r['day'] for r in R}), max(per_day.values() or [0])],
            }
        # live listing check (live caps at 15 per list)
        live = {(r["day"], r["cc"]) for r in R if r["live"].get("listed_rising")}
        res[m]["live_listed_total"] = len(live)
        res[m]["A_cur_vs_live_symdiff"] = len(live ^ listed[(m, "A_cur")])
        for e in EST[1:]:
            a, b = listed[(m, "A_cur")], listed[(m, e)]
            res[m][f"{e}_kept"] = len(a & b)
            res[m][f"{e}_dropped"] = len(a - b)
            res[m][f"{e}_gained"] = len(b - a)
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
