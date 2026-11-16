"""Calibrated z-scores (method proposal docs/method/2026-11-16-z-calibration.md; Tom's picks, 16 Nov 2026).

Every z here is normal-equivalent: the standard-normal quantile of the estimator's predictive tail probability, so on
event-free data z >= 2.5 should come up about 0.62% of the time. The live estimator before this (in-sample weekday
means, population SD, read as normal) cleared 2.5 on about 3% of event-free country-days.

- predictive_z (option B): log counts, the entity's own weekday means; residual SD on its real degrees of freedom,
  predictive variance s^2 (1 + 1/n_weekday), Student t -> z. Zones, zone violence and relation-pair counts.
- robust_z (option C): log counts, one pooled weekday shape for every country that day (`pooled_profile`), median
  centre, MAD scale floored at the Poisson SD on the log scale and SD_FLOOR, predictive term (1 + pi/2n), t on the
  MAD's effective degrees of freedom -> z. Countries (Rising list, feed, COP).
- weighted_window_z (T2): this week's article-weighted mean of a daily value against the article-weighted mean of the
  21 days before it; scale = sample SD of the baseline days' values (floored), inflated for day-to-day
  autocorrelation; standard error from effective article counts; t -> z. Press tone and the pairs' 7-day values.
- floored_ratio: count / max(expected, 90-day median, 3), so a near-zero baseline no longer reads "79.3x normal".

Standard library only; float arithmetic (the statistics module's exact sums were too slow for the API, 15 Nov 2026).
"""
from __future__ import annotations

import math
from datetime import date
from statistics import NormalDist

ND = NormalDist()
SD_FLOOR = 0.15            # log units, as before
MIN_DAYS = 14
Z_CEILING = 37.5           # a tail below 1e-300
RATIO_FLOOR = 3.0          # articles: below this a ratio says more about the baseline than the day
PROFILE_MIN_MEAN = 5.0     # countries with fewer articles a day have too little weekday shape to pool
TONE_BASE_DAYS, TONE_MIN_BASE, TONE_MIN_WEEK = 21, 14, 10
WEEK = 7


# ---------------------------------------------------------------- Student t -> normal-equivalent z

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes, modified Lentz)."""
    tiny, eps = 1e-300, 3e-14
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def betainc(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1 - x) / b


def t_to_z(t: float, df: float) -> float:
    """Normal-equivalent of a Student t value on `df` degrees of freedom: the z with the same tail probability."""
    if df > 1e5:
        return t
    tail = 0.5 * betainc(df / 2, 0.5, df / (df + t * t))  # P(T > |t|)
    tail = min(tail, 0.5)
    z = -ND.inv_cdf(tail) if tail > 1e-300 else Z_CEILING
    return z if t >= 0 else -z


# ---------------------------------------------------------------- option B: own weekday means, predictive SD

def predictive_z(y: list[float], w: list[int], y0: float, wd0: int) -> dict | None:
    """Log counts `y` on weekdays `w` (the baseline days), today's log count `y0` on weekday `wd0`.
    Weekdays with two or more baseline days get their own mean; the rest share one. Returns
    {"z", "expected" (log), "weekday_adjusted"} or None before MIN_DAYS baseline days."""
    n = len(y)
    if n < MIN_DAYS:
        return None
    by: dict[int, list[float]] = {}
    for v, k in zip(y, w):
        by.setdefault(k, []).append(v)
    own = {k: vs for k, vs in by.items() if len(vs) >= 2}
    rest = [v for k, vs in by.items() if k not in own for v in vs]
    groups = list(own.values()) + ([rest] if rest else [])
    ss = 0.0
    for g in groups:
        m = math.fsum(g) / len(g)
        ss += math.fsum((v - m) ** 2 for v in g)
    df = n - len(groups)
    s = max(math.sqrt(ss / df) if df > 0 else 0.0, SD_FLOOR)
    g = own.get(wd0) or rest or y
    expected = math.fsum(g) / len(g)
    t = (y0 - expected) / (s * math.sqrt(1 + 1 / len(g)))
    return {"z": t_to_z(t, max(df, 1)), "expected": expected, "weekday_adjusted": wd0 in own}


# ---------------------------------------------------------------- option C: pooled weekday shape, robust scale

def pooled_profile(windows: list[dict[date, float]]) -> dict[int, float]:
    """One weekday shape for a day's countries: per weekday, the median over countries (baseline mean >=
    PROFILE_MIN_MEAN, MIN_DAYS or more days) of that weekday's mean log deviation from the country's level, centred
    to mean zero. `windows`: each country's baseline {date: count}. Weekday -> log offset (0 when unknown)."""
    devs: dict[int, list[float]] = {k: [] for k in range(7)}
    for base in windows:
        if len(base) < MIN_DAYS or math.fsum(base.values()) / len(base) < PROFILE_MIN_MEAN:
            continue
        y = {d: math.log1p(c) for d, c in base.items()}
        lvl = math.fsum(y.values()) / len(y)
        by: dict[int, list[float]] = {}
        for d, v in y.items():
            by.setdefault(d.weekday(), []).append(v - lvl)
        for k, vs in by.items():
            devs[k].append(math.fsum(vs) / len(vs))
    prof = {k: (_median(v) if v else 0.0) for k, v in devs.items()}
    m = math.fsum(prof.values()) / 7
    return {k: v - m for k, v in prof.items()}


def robust_z(base: dict[date, float], day: date, count: float, profile: dict[int, float]) -> dict | None:
    """Option C. `base`: the baseline {date: count} (complete days; zeros included). Returns {"z", "expected" (log)}
    or None before MIN_DAYS baseline days."""
    n = len(base)
    if n < MIN_DAYS:
        return None
    r = [math.log1p(c) - profile.get(d.weekday(), 0.0) for d, c in base.items()]
    centre = _median(r)
    mad = _median([abs(v - centre) for v in r]) * 1.4826
    mu = max(math.expm1(centre), 0.0)
    poisson = math.sqrt(mu) / (1 + mu) if mu > 0 else 0.5  # Poisson SD on the log1p scale (delta method)
    s = max(mad, poisson, SD_FLOOR)
    sd = s * math.sqrt(1 + math.pi / (2 * n))  # the median's own sampling variance, about (pi/2) s^2 / n
    expected = centre + profile.get(day.weekday(), 0.0)
    df = max(3, round(0.37 * (n - 1)))  # the MAD is about 37% efficient: fewer effective degrees of freedom
    return {"z": t_to_z((math.log1p(count) - expected) / sd, df), "expected": expected}


# ---------------------------------------------------------------- T2: weighted 7-day means

def _acf_factor(xs: list[float]) -> float:
    """1 + 2 x (sum of the first three lag autocorrelations), when above 1 (Newey-West style inflation)."""
    m = math.fsum(xs) / len(xs)
    c0 = math.fsum((x - m) ** 2 for x in xs)
    if c0 <= 0:
        return 1.0
    rho = [math.fsum((xs[i] - m) * (xs[i - k] - m) for i in range(k, len(xs))) / c0 for k in (1, 2, 3)]
    return max(1.0, 1 + 2 * math.fsum(rho))


def weighted_window_z(week: list[tuple[float, float]], base: list[tuple[float, float]],
                      floor: float) -> dict | None:
    """T2. `week`: (articles, sum of the value) for each of the WEEK days ending today; `base`: the same for the
    TONE_BASE_DAYS days before the week, oldest first. Days with no articles are skipped. Needs TONE_MIN_BASE baseline
    days with articles and TONE_MIN_WEEK articles in the week. Returns {"z", "base"} (base: the baseline's weighted
    mean) or None."""
    wk = [(n, s / n) for n, s in week if n]
    b = [(n, s / n) for n, s in base if n]
    nwk = math.fsum(n for n, _ in wk)
    if nwk < TONE_MIN_WEEK or len(b) < TONE_MIN_BASE:
        return None
    nb = math.fsum(n for n, _ in b)
    xw = math.fsum(n * x for n, x in wk) / nwk
    xb = math.fsum(n * x for n, x in b) / nb
    vals = [x for _, x in b]
    m = math.fsum(vals) / len(vals)
    s = max(math.sqrt(math.fsum((x - m) ** 2 for x in vals) / (len(vals) - 1)), floor)
    s *= math.sqrt(_acf_factor(vals))
    neff = lambda ps: math.fsum(n for n, _ in ps) ** 2 / math.fsum(n * n for n, _ in ps)  # noqa: E731
    se = s * math.sqrt(1 / neff(wk) + 1 / neff(b))
    return {"z": t_to_z((xw - xb) / se, len(b) - 1), "base": xb}


# ---------------------------------------------------------------- ratio for titles

def floored_ratio(count: float, expected: float | None, median90: float | None = None) -> dict:
    """{"ratio_shown": count / max(expected, median90, RATIO_FLOOR), "floored": True when RATIO_FLOOR binds}."""
    ref = max(expected or 0.0, median90 or 0.0)
    floored = ref < RATIO_FLOOR
    return {"ratio_shown": round(count / max(ref, RATIO_FLOOR), 2), "floored": floored}


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    k = len(s)
    return (s[k // 2] if k % 2 else (s[k // 2 - 1] + s[k // 2]) / 2) if k else 0.0
