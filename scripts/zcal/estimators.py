"""Prototype z estimators for Watchfloor's country Rising list (method proposal, 16 Nov 2026; not live).

Every estimator takes the baseline {date: count} (complete days in the 28 before `day`), the day and its count,
plus a pooled weekday profile, and returns {"z", "expected"} or None. z is a normal-equivalent score: the
standard-normal quantile of the estimator's predictive tail probability, so z 2.5 should be cleared about 0.62%
of the time on event-free data if the estimator is calibrated.

  A  cur     measures.attention_anomaly as live (in-sample weekday means, population SD, SD floor 0.15).
  B  pred    same log model, residual SD on its real degrees of freedom, predictive term for the estimated
             weekday mean, Student t -> normal-equivalent z.
  C  robust  log model, pooled weekday profile (one shape for every country), median centre, MAD scale with a
             Poisson floor, predictive term, t on the MAD's effective degrees of freedom -> z.
  E  robust_half  as C, weekday profile half the country's own and half pooled.
  D  nb      negative-binomial count model: pooled multiplicative weekday factors, centre = mean after capping
             baseline days above median + 4 NB SDs, dispersion by moments shrunk to the pooled value, predictive variance
             (1 + 1/n), mid-p tail -> z.
Standard library only.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import NormalDist, mean, median, pstdev

ND = NormalDist()
SD_FLOOR = 0.15
BASELINE_DAYS, MIN_DAYS = 28, 14


# ---------------------------------------------------------------- special functions

def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta (Numerical Recipes, modified Lentz)."""
    tiny, eps = 1e-300, 3e-14
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 20000):
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
    """Normal-equivalent of a Student t value: same tail probability."""
    if df > 1e5:
        return t
    tail = 0.5 * betainc(df / 2, 0.5, df / (df + t * t))  # P(T > |t|)
    tail = min(max(tail, 1e-300), 0.5)
    z = -ND.inv_cdf(tail) if tail > 1e-300 else 37.5
    return z if t >= 0 else -z


def nb_cdf(k: int, mu: float, alpha: float) -> float:
    """P(X <= k) for a negative binomial with mean mu and variance mu + alpha mu^2."""
    if k < 0:
        return 0.0
    if mu <= 0:
        return 1.0
    r = 1.0 / max(alpha, 1e-4)
    return betainc(r, k + 1, r / (r + mu))


def nb_z(x: int, mu: float, alpha: float) -> float:
    """Mid-p normal-equivalent z of count x."""
    lo = nb_cdf(x - 1, mu, alpha)
    hi = nb_cdf(x, mu, alpha)
    upper = (1 - hi) + 0.5 * (hi - lo)  # P(X > x) + P(X = x) / 2
    upper = min(max(upper, 1e-300), 1 - 1e-16)
    return -ND.inv_cdf(upper) if upper > 1e-300 else 37.5


# ---------------------------------------------------------------- pooled weekday profile

def pooled_profile(windows: list[dict[date, float]], min_mean: float = 5.0) -> dict[int, float]:
    """Median over countries (baseline mean >= min_mean) of each weekday's log deviation from the country's level.
    `windows`: each country's baseline {date: count}. Returns weekday -> log offset (0 when unknown)."""
    devs: dict[int, list[float]] = {wd: [] for wd in range(7)}
    for base in windows:
        if len(base) < MIN_DAYS or mean(base.values()) < min_mean:
            continue
        y = {d: math.log1p(c) for d, c in base.items()}
        lvl = mean(y.values())
        by: dict[int, list[float]] = {}
        for d, v in y.items():
            by.setdefault(d.weekday(), []).append(v - lvl)
        for wd, vs in by.items():
            devs[wd].append(mean(vs))
    prof = {wd: (median(v) if v else 0.0) for wd, v in devs.items()}
    m = mean(prof.values())
    return {wd: v - m for wd, v in prof.items()}


# ---------------------------------------------------------------- estimators

def est_cur(base: dict[date, float], day: date, count: float, **_) -> dict | None:
    if len(base) < MIN_DAYS:
        return None
    y = {d: math.log1p(c) for d, c in base.items()}
    level = mean(y.values())
    by: dict[int, list[float]] = {}
    for d, v in y.items():
        by.setdefault(d.weekday(), []).append(v)
    adjust = {wd: mean(vs) - level for wd, vs in by.items() if len(vs) >= 2}
    resid = [v - level - adjust.get(d.weekday(), 0.0) for d, v in y.items()]
    sd = max(pstdev(resid), SD_FLOOR)
    expected = level + adjust.get(day.weekday(), 0.0)
    return {"z": (math.log1p(count) - expected) / sd, "expected": math.expm1(expected)}


def est_pred(base: dict[date, float], day: date, count: float, **_) -> dict | None:
    """Same model as cur; SD on n - k degrees of freedom; predictive variance s^2 (1 + 1/n_g); t -> z."""
    n = len(base)
    if n < MIN_DAYS:
        return None
    y = {d: math.log1p(c) for d, c in base.items()}
    by: dict[int, list[float]] = {}
    for d, v in y.items():
        by.setdefault(d.weekday(), []).append(v)
    own = {wd: vs for wd, vs in by.items() if len(vs) >= 2}
    rest = [v for wd, vs in by.items() if wd not in own for v in vs]
    groups = list(own.values()) + ([rest] if rest else [])
    k = len(groups)
    ss = sum((v - mean(g)) ** 2 for g in groups for v in g)
    df = n - k
    s = max(math.sqrt(ss / df) if df > 0 else 0.0, SD_FLOOR)
    g = own.get(day.weekday())
    if g is None:  # weekday without its own mean: level of the pooled remainder or the whole baseline
        g = rest if rest else list(y.values())
    expected = mean(g)
    sd = s * math.sqrt(1 + 1 / len(g))
    t = (math.log1p(count) - expected) / sd
    return {"z": t_to_z(t, df), "expected": math.expm1(expected)}


def est_robust(base: dict[date, float], day: date, count: float, profile: dict[int, float], **_) -> dict | None:
    """Pooled weekday profile, median centre, MAD scale (floor), predictive term, t on n - 1 -> z."""
    n = len(base)
    if n < MIN_DAYS:
        return None
    r = [math.log1p(c) - profile.get(d.weekday(), 0.0) for d, c in base.items()]
    centre = median(r)
    mad = median(abs(v - centre) for v in r) * 1.4826
    mu = max(math.expm1(centre), 0.0)
    count_floor = math.sqrt(mu) / (1 + mu) if mu > 0 else 0.5  # Poisson SD on the log1p scale (delta method)
    s = max(mad, count_floor, SD_FLOOR)
    # the median's sampling variance is about (pi/2) s^2 / n for normal data
    sd = s * math.sqrt(1 + math.pi / (2 * n))
    expected = centre + profile.get(day.weekday(), 0.0)
    t = (math.log1p(count) - expected) / sd
    df = max(3, round(0.37 * (n - 1)))  # the MAD has about 37% efficiency: fewer effective degrees of freedom
    return {"z": t_to_z(t, df), "expected": math.expm1(expected)}


def est_nb(base: dict[date, float], day: date, count: float, factors: dict[int, float],
           alpha_pool: float = 0.1, n0: float = 10.0, **_) -> dict | None:
    """Negative-binomial predictive tail. `factors`: multiplicative weekday factors (mean 1)."""
    n = len(base)
    if n < MIN_DAYS:
        return None
    raw = [c / factors.get(d.weekday(), 1.0) for d, c in base.items()]
    # robust centre: cap baseline days above median + 4 NB standard deviations (a past spike), then the mean
    m0 = median(raw)
    cap = m0 + 4 * math.sqrt(m0 + alpha_pool * m0 * m0) + 1
    adj = [min(x, cap) for x in raw]
    m_c = mean(adj)
    m, v = m_c, (sum((x - m_c) ** 2 for x in adj) / (n - 1))
    a_hat = max(0.0, (v - m) / (m * m)) if m > 0 else alpha_pool
    alpha = (n * a_hat + n0 * alpha_pool) / (n + n0)
    mu = max(m_c * factors.get(day.weekday(), 1.0), 0.05)
    var = (mu + alpha * mu * mu) * (1 + 1 / n)  # predictive: add the centre's own variance
    alpha_p = max((var - mu) / (mu * mu), 1e-4)
    return {"z": nb_z(int(round(count)), mu, alpha_p), "expected": mu}


def est_robust_half(base: dict[date, float], day: date, count: float, profile: dict[int, float], **_) -> dict | None:
    """As est_robust, but the weekday profile is half the country's own weekday deviations (weekdays with two or
    more baseline days) and half the pooled profile, with the own half's sampling variance in the predictive term."""
    n = len(base)
    if n < MIN_DAYS:
        return None
    y = {d: math.log1p(c) for d, c in base.items()}
    lvl = mean(y.values())
    by: dict[int, list[float]] = {}
    for d, v in y.items():
        by.setdefault(d.weekday(), []).append(v - lvl)
    own = {wd: mean(vs) for wd, vs in by.items() if len(vs) >= 2}
    prof = {wd: 0.5 * own.get(wd, profile.get(wd, 0.0)) + 0.5 * profile.get(wd, 0.0) for wd in range(7)}
    r = [v - prof[d.weekday()] for d, v in y.items()]
    centre = median(r)
    mad = median(abs(v - centre) for v in r) * 1.4826
    mu = max(math.expm1(centre), 0.0)
    count_floor = math.sqrt(mu) / (1 + mu) if mu > 0 else 0.5
    s = max(mad, count_floor, SD_FLOOR)
    n_wd = len(by.get(day.weekday(), [])) or n
    sd = s * math.sqrt(1 + math.pi / (2 * n) + 0.25 / n_wd)
    expected = centre + prof[day.weekday()]
    t = (math.log1p(count) - expected) / sd
    df = max(3, round(0.37 * (n - 1)))
    return {"z": t_to_z(t, df), "expected": math.expm1(expected)}


ESTIMATORS = {"A_cur": est_cur, "B_pred": est_pred, "C_robust": est_robust, "D_nb": est_nb,
              "E_robust_half": est_robust_half}


def baseline(hist: dict[date, float], complete: list[date], day: date) -> dict[date, float]:
    start = day - timedelta(days=BASELINE_DAYS)
    return {d: hist.get(d, 0) for d in complete if start <= d < day}
