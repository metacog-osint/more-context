"""Calibrated z (pipeline/zstats.py; docs/method/2026-11-16-z-calibration.md). The calibration tests draw event-free
data on fixed seeds and check that z >= 2.5 stays rare (normal: 0.62%); the live estimator before 16 Nov 2026 gave
about 3% on the same kind of data."""
import math
import random
import unittest
from datetime import date, timedelta
from statistics import NormalDist

from pipeline import countries, measures, zstats

START = date(2026, 1, 5)  # a Monday
SHAPE = [0.10, 0.12, 0.10, 0.08, 0.02, -0.20, -0.22]  # GDELT-like weekday shape in log units, Monday first


def nb_draw(rng: random.Random, mu: float, alpha: float) -> int:
    """Negative binomial (mean mu, variance mu + alpha mu^2) as a gamma-Poisson mixture."""
    lam = rng.gammavariate(1 / alpha, mu * alpha) if alpha > 0 else mu
    # Poisson by inversion for small lam, normal approximation above 50
    if lam > 50:
        return max(0, round(rng.gauss(lam, math.sqrt(lam))))
    k, p, u = 0, math.exp(-lam), rng.random()
    s = p
    while u > s:
        k += 1
        p *= lam / k
        s += p
    return k


def simulate(seed: int, n_series: int = 160, n_days: int = 70) -> list[dict[date, int]]:
    rng = random.Random(seed)
    out = []
    for _ in range(n_series):
        mu = math.exp(rng.uniform(math.log(0.5), math.log(400)))
        alpha = math.exp(rng.uniform(math.log(0.02), math.log(0.6)))
        out.append({START + timedelta(days=i): nb_draw(rng, mu * math.exp(SHAPE[(START + timedelta(days=i)).weekday()]),
                                                       alpha) for i in range(n_days)})
    return out


class TtoZ(unittest.TestCase):
    def test_matches_known_quantiles(self):
        # t 2.0 on 10 df: upper tail 0.03669 -> z 1.791
        self.assertAlmostEqual(zstats.t_to_z(2.0, 10), -NormalDist().inv_cdf(0.036694), places=3)
        self.assertAlmostEqual(zstats.t_to_z(-2.0, 10), -zstats.t_to_z(2.0, 10), places=9)
        self.assertEqual(zstats.t_to_z(0.0, 7), 0.0)
        self.assertAlmostEqual(zstats.t_to_z(2.5, 1e6), 2.5)

    def test_huge_t_hits_the_ceiling_not_an_error(self):
        self.assertGreater(zstats.t_to_z(1e9, 20), 20)
        self.assertEqual(zstats.t_to_z(1e12, 200), zstats.Z_CEILING)


class Calibration(unittest.TestCase):
    def rate(self, zs):
        return sum(z >= 2.5 for z in zs) / len(zs)

    def test_event_free_countries_option_c(self):
        series = simulate(7)
        zs = []
        for i in range(28, 70):
            day = START + timedelta(days=i)
            complete = [START + timedelta(days=k) for k in range(i)]
            hist = {str(j): s for j, s in enumerate(series)}
            prof = countries.profile(hist, complete, day)
            for s in series:
                r = zstats.robust_z(countries.baseline(s, complete, day), day, s[day], prof)
                zs.append(r["z"])
        self.assertGreater(len(zs), 6000)
        self.assertLess(self.rate(zs), 0.01)

    def test_event_free_zones_option_b(self):
        series = simulate(8)
        zs = []
        for s in series:
            for i in range(28, 70):
                day = START + timedelta(days=i)
                r = measures.attention_anomaly({d: c for d, c in s.items() if d < day}, day, s[day])
                zs.append(r["z"])
        self.assertLess(self.rate(zs), 0.01)

    def test_event_free_weekly_tone_t2(self):
        rng = random.Random(11)
        zs = []
        for _ in range(300):
            med = math.exp(rng.uniform(math.log(8), math.log(300)))
            days = []
            for _ in range(28):
                n = max(0, round(med * math.exp(rng.gauss(0, 0.6))))
                x = rng.gauss(0, 1.0) + (rng.gauss(0, 3.5 / math.sqrt(n)) if n else 0.0)
                days.append((n, x * n))
            r = zstats.weighted_window_z(days[21:], days[:21], 0.3)
            if r:
                zs.append(abs(r["z"]))
        self.assertGreater(len(zs), 250)
        self.assertLess(self.rate(zs), 0.03)  # two-sided; normal gives 1.2%


class Behaviour(unittest.TestCase):
    def test_a_spike_still_scores_high(self):
        series = simulate(9, n_series=40, n_days=29)
        day = START + timedelta(days=28)
        complete = [START + timedelta(days=k) for k in range(28)]
        prof = countries.profile({str(j): s for j, s in enumerate(series)}, complete, day)
        steady = {d: 100 for d in complete}
        self.assertGreater(zstats.robust_z(steady, day, 400, prof)["z"], 4)
        self.assertLess(zstats.robust_z(steady, day, 110, prof)["z"], 2)

    def test_small_baseline_is_held_down_by_the_poisson_floor(self):
        """Guinea, 13 Nov 2026: 15 violent-event articles against a baseline of mostly zeros read z 6.7 live."""
        day = date(2026, 11, 13)
        base = {day - timedelta(days=k): (1 if k % 9 == 0 else 0) for k in range(1, 29)}
        r = zstats.robust_z(base, day, 15, {k: 0.0 for k in range(7)})
        self.assertLess(r["z"], 5)
        self.assertGreater(r["z"], 2.5)

    def test_floored_ratio(self):
        self.assertEqual(zstats.floored_ratio(15, 0.19, 0), {"ratio_shown": 5.0, "floored": True})
        self.assertEqual(zstats.floored_ratio(84, 2.7, 4), {"ratio_shown": 21.0, "floored": False})
        self.assertEqual(zstats.floored_ratio(300, 100.0), {"ratio_shown": 3.0, "floored": False})

    def test_country_score_carries_method_and_floored_ratio(self):
        day = date(2026, 11, 13)
        complete = [day - timedelta(days=k) for k in range(1, 91)]
        hist = {d: (1 if d.toordinal() % 9 == 0 else 0) for d in complete}
        s = countries.score(hist, complete, day, 15, {k: 0.0 for k in range(7)})
        self.assertEqual(s["z_method"], countries.Z_METHOD)
        self.assertTrue(s["floored"])
        self.assertEqual(s["ratio_shown"], 5.0)
        self.assertIsNone(s["ratio"])  # the median of a mostly-zero baseline is 0: no ratio to expected
        rising, _ = countries._listed({"GV": {"violent": 15, "violent_score": s}}, "violent")
        self.assertEqual(rising, ["GV"])  # Guinea is still listed
        zone = countries.score(hist, complete, day, 15)  # no profile: a zone, option B
        self.assertEqual(zone["z_method"], measures.Z_METHOD)


if __name__ == "__main__":
    unittest.main()
