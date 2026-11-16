"""7-day tone z: the live estimator (pipeline/press.py row_view, pipeline/relations.py _window_z) against a proposed
one, on the press series, on the 120-day pair series (Events tone, same estimator) and on event-free simulation.

python -I scripts/zcal/tone.py <series.json> <out.json>

  T0 live: 7-day value against the 7-day values ending 7-34 days before (overlapping windows), population SD,
     floor 0.3, at least 14 baseline windows.
  T1 proposed: daily mean tones; this week's article-weighted mean against the article-weighted mean of the 21 days
     before it; SD of daily tone (sample SD of the baseline days' tones, ddof 1, with a floor of 0.3 on the daily
     SD); standard error s * sqrt(1/neff_week + 1/neff_base) with neff = (sum n)^2 / sum n^2; t on (days - 1)
     degrees of freedom -> normal-equivalent z. At least 14 baseline days with articles and 10 articles in the week.
  T2 = T1 with the SD inflated by sqrt(1 + 2 * sum of the first 3 lag autocorrelations) measured on the baseline
     (Newey-West style), when that factor is above 1.
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
from estimators import t_to_z  # noqa: E402

WINDOW, BASE_DAYS, FLOOR, MIN_BASE, MIN_WEEK = 7, 21, 0.3, 14, 10


def t0(daily: dict[date, tuple[int, float]], end: date) -> float | None:
    def w7(d):
        win = [d - timedelta(days=k) for k in range(WINDOW)]
        if not all(w in daily for w in win):
            return None
        n = sum(daily[w][0] for w in win)
        return sum(daily[w][1] for w in win) / n if n >= MIN_WEEK else None
    x = w7(end)
    if x is None:
        return None
    base = [v for k in range(7, 35) if (v := w7(end - timedelta(days=k))) is not None]
    if len(base) < 14:
        return None
    return (x - mean(base)) / max(pstdev(base), FLOOR)


def _acf_factor(xs: list[float]) -> float:
    m = mean(xs)
    c0 = sum((x - m) ** 2 for x in xs)
    if c0 <= 0:
        return 1.0
    rho = [sum((xs[i] - m) * (xs[i - k] - m) for i in range(k, len(xs))) / c0 for k in (1, 2, 3)]
    return max(1.0, 1 + 2 * sum(rho))


def t1(daily: dict[date, tuple[int, float]], end: date, nw: bool = False) -> float | None:
    week = [end - timedelta(days=k) for k in range(WINDOW)]
    if not all(w in daily for w in week):
        return None
    wk = [(daily[w][0], daily[w][1] / daily[w][0]) for w in week if daily[w][0]]
    nwk = sum(n for n, _ in wk)
    if nwk < MIN_WEEK:
        return None
    bdays = [end - timedelta(days=k) for k in range(WINDOW, WINDOW + BASE_DAYS)]
    b = [(daily[d][0], daily[d][1] / daily[d][0]) for d in sorted(bdays) if d in daily and daily[d][0]]
    if len(b) < MIN_BASE:
        return None
    xw = sum(n * x for n, x in wk) / nwk
    nb = sum(n for n, _ in b)
    xb = sum(n * x for n, x in b) / nb
    tones = [x for _, x in b]
    s = max(math.sqrt(sum((x - mean(tones)) ** 2 for x in tones) / (len(tones) - 1)), FLOOR)
    if nw:
        s *= math.sqrt(_acf_factor(tones))
    neff = lambda ps: sum(n for n, _ in ps) ** 2 / sum(n * n for n, _ in ps)  # noqa: E731
    se = s * math.sqrt(1 / neff(wk) + 1 / neff(b))
    return t_to_z((xw - xb) / se, len(b) - 1)


def summary(zs: list[float]) -> dict:
    zs = sorted(zs)
    if not zs:
        return {"n": 0}
    q = lambda p: zs[int(p * (len(zs) - 1))]  # noqa: E731
    return {"n": len(zs), "sd": round(pstdev(zs), 2), "iqr_sd": round((q(.75) - q(.25)) / 1.349, 2),
            "abs_ge_2_5_pct": round(sum(abs(z) >= 2.5 for z in zs) / len(zs) * 100, 1),
            "abs_ge_4_pct": round(sum(abs(z) >= 4 for z in zs) / len(zs) * 100, 1)}


def series_rows(series: dict, part: str) -> dict[str, dict[date, tuple[int, float]]]:
    out: dict[str, dict] = {}
    for d, v in series["days"].items():
        if part == "press":
            p = v.get("press")
            if not p or "t" not in p or p.get("partial"):
                continue
            for k, t in p["t"].items():
                out.setdefault(k, {})[date.fromisoformat(d)] = (t[2], t[3])
        else:
            if v.get("partial"):
                continue
            for k, t in (v.get("pairs") or {}).items():
                out.setdefault(k, {})[date.fromisoformat(d)] = (t[0], t[7])
    # complete days with no row are zero-article days
    alld = sorted({date.fromisoformat(d) for d, v in series["days"].items()
                   if (v.get("press") and "t" in v["press"] and not v["press"].get("partial")) or
                   (part == "pairs" and not v.get("partial"))})
    for k, rows in out.items():
        for d in alld:
            rows.setdefault(d, (0, 0.0))
    return out


def run_real(series: dict, part: str, keys: set | None, min_median: float) -> dict:
    rows = series_rows(series, part)
    res = {"T0": [], "T1": [], "T2": []}
    for k, daily in rows.items():
        if keys is not None and k not in keys:
            continue
        if median(n for n, _ in daily.values()) < min_median:
            continue
        for end in sorted(daily):
            a, b, c = t0(daily, end), t1(daily, end), t1(daily, end, nw=True)
            if a is not None and b is not None:
                res["T0"].append(a)
                res["T1"].append(b)
                res["T2"].append(c)
    return {k: summary(v) for k, v in res.items()}


def run_sim(rng: random.Random, n_rows: int = 400, ar: float = 0.0) -> dict:
    """Event-free daily tone: mean 0, day-level SD 1.0 (AR(1) with coefficient `ar`), plus article noise SD 3.5 /
    sqrt(n); daily article counts lognormal around a row median drawn from 8-300."""
    res = {"T0": [], "T1": [], "T2": []}
    start = date(2026, 1, 1)
    for _ in range(n_rows):
        med = math.exp(rng.uniform(math.log(8), math.log(300)))
        daily, e = {}, 0.0
        for i in range(90):
            n = max(0, int(round(med * math.exp(rng.gauss(0, 0.6)))))
            e = ar * e + math.sqrt(1 - ar * ar) * rng.gauss(0, 1.0)
            x = e + (rng.gauss(0, 3.5 / math.sqrt(n)) if n else 0)
            daily[start + timedelta(days=i)] = (n, x * n)
        for i in range(40, 90):
            end = start + timedelta(days=i)
            a, b, c = t0(daily, end), t1(daily, end), t1(daily, end, nw=True)
            if a is not None and b is not None:
                res["T0"].append(a)
                res["T1"].append(b)
                res["T2"].append(c)
    return {k: summary(v) for k, v in res.items()}


def main(series_p: Path, out: Path) -> None:
    series = json.loads(series_p.read_text(encoding="utf-8"))
    res = {
        "press_rows_median_ge_8": run_real(series, "press", None, 8),
        "press_rows_all_median_ge_2": run_real(series, "press", None, 2),
        "pairs_median_ge_8": run_real(series, "pairs", None, 8),
        "sim_iid": run_sim(random.Random(11), ar=0.0),
        "sim_ar_0_5": run_sim(random.Random(12), ar=0.5),
    }
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
