"""Zone and topic attention alarms (z >= 2 on >= 5 headline-filtered stories) under each estimator.

python -I scripts/zcal/zones.py <stories root with YYYY/MM/DD/summary.json> <first> <last> <out.json>
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
import estimators as E  # noqa: E402
from pipeline import measures  # noqa: E402

EST = ("A_cur", "B_pred", "C_robust", "E_robust_half")


def main(root: Path, first: date, last: date, out: Path) -> None:
    days, hist, live = [], {}, {}
    d = first
    while d <= last:
        p = root / f"{d:%Y/%m/%d}/summary.json"
        if p.exists():
            s = json.loads(p.read_text(encoding="utf-8"))
            if not measures.is_partial(s):
                days.append(d)
                for eid, e in (s.get("entities") or {}).items():
                    hist.setdefault(eid, {})[d] = e.get("filtered_stories", e.get("stories", 0))
                    if e.get("attention"):
                        live[(eid, d)] = (e["attention"]["z"], bool(e.get("alarms")))
        d += timedelta(days=1)
    res = {"days": [str(days[0]), str(days[-1]), len(days)], "entity_days": 0, "replica_mismatch": 0,
           "alarms": {k: 0 for k in ("live", *EST)}, "changes": {}}
    sets = {k: set() for k in EST}
    for d in days:
        bases = {eid: E.baseline(h, days, d) for eid, h in hist.items()}
        prof = E.pooled_profile(list(bases.values()))
        for eid, h in hist.items():
            if len(bases[eid]) < E.MIN_DAYS or (eid, d) not in live:
                continue
            x = h.get(d, 0)
            res["entity_days"] += 1
            res["alarms"]["live"] += live[(eid, d)][1]
            for k in EST:
                r = E.ESTIMATORS[k](bases[eid], d, x, profile=prof)
                if k == "A_cur" and abs(r["z"] - live[(eid, d)][0]) > 0.011:
                    res["replica_mismatch"] += 1
                if r["z"] >= measures.ALARM_Z and x >= measures.ALARM_MIN_STORIES:
                    res["alarms"][k] += 1
                    sets[k].add((str(d), eid, x, round(r["z"], 2)))
    a = {(d, e) for d, e, *_ in sets["A_cur"]}
    for k in EST[1:]:
        b = {(d, e) for d, e, *_ in sets[k]}
        res["changes"][k] = {"kept": len(a & b), "dropped": sorted(a - b), "gained": sorted(b - a)}
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "changes"}, indent=1))
    for k, v in res["changes"].items():
        print(k, "kept", v["kept"], "dropped", len(v["dropped"]), "gained", len(v["gained"]))


if __name__ == "__main__":
    main(Path(sys.argv[1]), date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]), Path(sys.argv[4]))
