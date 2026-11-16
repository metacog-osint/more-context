"""Rising listings and feed country items per option, with the listings each option drops or adds.

python -I scripts/zcal/listings.py <real.jsonl> <countries folder> <fips_countries.json> <out.json>
Rising: z >= 2.5, ratio >= 1.5 (count / the option's expected), >= 40 / 15 articles, a named country, top 15 by z.
Elevated (unchanged rule): not Rising, >= 2x the 90-day median, same article minimum, top 15 by ratio90.
Feed country items a day = violence Rising + violence Elevated + attention Rising (pipeline/feed_v2.py:187-196).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

MIN_ART = {"urls": 40, "violent": 15}
EST = ("A_cur", "B_pred", "C_robust", "D_nb", "E_robust_half")


def main(rows_p: Path, cdir: Path, names_p: Path, out: Path) -> None:
    names = json.loads(names_p.read_text(encoding="utf-8"))["names"]
    rows = [json.loads(l) for l in rows_p.read_text(encoding="utf-8").splitlines()]
    rows = [r for r in rows if r["live"] and r["live"].get("z") is not None]
    days = sorted({r["day"] for r in rows})
    by = defaultdict(list)
    for r in rows:
        by[(r["m"], r["day"])].append(r)
    res = {"days": [days[0], days[-1], len(days)], "options": {}}
    lists = {}
    for e in EST:
        feed, rising_all = [], {}
        for d in days:
            n_items = 0
            for m in ("urls", "violent"):
                cand = []
                for r in by[(m, d)]:
                    z, ex = r[e]
                    if r["cc"] not in names or r["n"] < MIN_ART[m]:
                        continue
                    if z >= 2.5 and (r["n"] / ex if ex > 0 else 0) >= 1.5:
                        cand.append((z, r))
                cand.sort(key=lambda t: -t[0])
                ris = [r for _, r in cand[:15]]
                for r in ris:
                    rising_all[(m, d, r["cc"])] = {"z": round(r[e][0], 2), "n": r["n"], "expected": r[e][1],
                                                   "live_z": r["live"]["z"], "live_expected": r["live"]["expected"],
                                                   "median90": r["live"].get("median90")}
                rs = {r["cc"] for r in ris}
                n_items += len(ris) if m == "violent" else len(ris)
                if m == "violent":
                    el = [r for r in by[(m, d)] if r["cc"] in names and r["cc"] not in rs and r["n"] >= MIN_ART[m]
                          and (r["live"].get("ratio90") or 0) >= 2.0]
                    n_items += min(15, len(el))
            feed.append(n_items)
        lists[e] = rising_all
        res["options"][e] = {"feed_items_per_day_mean": round(sum(feed) / len(feed), 1),
                             "feed_items_per_day_range": [min(feed), max(feed)],
                             "rising_urls": sum(1 for k in rising_all if k[0] == "urls"),
                             "rising_violent": sum(1 for k in rising_all if k[0] == "violent")}
    base = lists["A_cur"]
    for e in EST[1:]:
        cur = lists[e]
        dropped = sorted((k for k in base if k not in cur), key=lambda k: -base[k]["live_z"])
        gained = sorted((k for k in cur if k not in base), key=lambda k: -cur[k]["z"])
        res["options"][e]["dropped"] = len(dropped)
        res["options"][e]["gained"] = len(gained)
        res["options"][e]["dropped_top"] = [[*k, base[k]["n"], base[k]["live_z"], base[k]["live_expected"],
                                             cur.get(k, {}).get("z")] for k in dropped[:25]]
        res["options"][e]["gained_top"] = [[*k, cur[k]["n"], cur[k]["z"], cur[k]["live_z"]] for k in gained[:25]]
    out.write_text(json.dumps({**res, "lists": {e: {"|".join(k): v for k, v in l.items()} for e, l in lists.items()}},
                              indent=1), encoding="utf-8")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if not kk.endswith("_top")} for k, v in res["options"].items()},
                     indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
