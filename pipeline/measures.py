"""Measures computed from the daily story build. No model calls; all free.

- attention_anomaly: how unusual today's story count is against the entity's own last 28 complete days,
  adjusted for day of week. Counts are log-transformed (news volume is skewed). Since the z calibration (picked
  16 Nov 2026; docs/method/2026-11-16-z-calibration.md) z is normal-equivalent (pipeline/zstats.py, option B):
  residual SD on its real degrees of freedom, the weekday mean's own error, Student t. Before it, z ran about 1.3x
  too large (z >= 2.5 on about 3% of event-free days, against 0.62%).
- (removed 27 Oct 2026) casualty_share, the share of articles where GDELT extracted a KILL/WOUND count. It
  could not tell whose deaths, where or when: 20-26 Oct, Taiwan Strait ran 6-12% and raised two alarms, and a
  sanctions topic hit 50% from a story about Sudan. Planned replacement: violent events located inside the zone.

Thresholds for Watch / Warning / Crisis belong in each zone's indicator charter, not here.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, pstdev

from . import zstats

BASELINE_DAYS = 28
MIN_BASELINE_DAYS = 14
SD_FLOOR = zstats.SD_FLOOR  # log units; stops a very steady baseline from turning small changes into huge z
SHARE_SD_FLOOR = 0.02  # for shares (0-1)
# Alarm = a free signal that buys model coding for that entity-day (pipeline/ondemand.py). It is a spending
# trigger, not a warning level; Watch / Warning / Crisis come from the charters.
ALARM_Z = 2.0
ALARM_MIN_STORIES = 5
Z_METHOD = "pred-1"  # option B; countries use "robust-1" (option C, pipeline/countries.py)


def attention_anomaly(history: dict[date, float], day: date, count: float,
                      baseline_days: int = BASELINE_DAYS, min_days: int = MIN_BASELINE_DAYS) -> dict | None:
    """z-score of `count` on `day` against the previous `baseline_days` days in `history` (complete days only).

    Returns None until there are `min_days` baseline days. The weekday adjustment needs at least two
    baseline days on that weekday; otherwise it is skipped and `weekday_adjusted` is False.
    """
    start = day - timedelta(days=baseline_days)
    base = {d: c for d, c in history.items() if start <= d < day and c is not None}
    if len(base) < min_days:
        return None
    ds = sorted(base)
    r = zstats.predictive_z([math.log1p(base[d]) for d in ds], [d.weekday() for d in ds], math.log1p(count),
                            day.weekday())
    return scored(r["z"], r["expected"], count, len(base), r["weekday_adjusted"])


def scored(z: float, expected_log: float, count: float, baseline_days: int, weekday_adjusted: bool) -> dict:
    """The stored score: z, expected count, the rule's ratio (count / expected, for RISING_RATIO), the title's
    floored ratio (pipeline/zstats.floored_ratio) and the method."""
    expected = math.expm1(expected_log)
    return {
        "z": round(z, 2),
        "expected": round(expected, 1),
        "ratio": round(count / expected, 2) if expected > 0 else None,
        **zstats.floored_ratio(count, expected),
        "baseline_days": baseline_days,
        "weekday_adjusted": weekday_adjusted,
        "z_method": Z_METHOD,
    }


def share_anomaly(history: dict[date, float], day: date, value: float,
                  baseline_days: int = BASELINE_DAYS, min_days: int = MIN_BASELINE_DAYS) -> dict | None:
    """z of a share (0-1) against the previous `baseline_days` days."""
    start = day - timedelta(days=baseline_days)
    base = [v for d, v in history.items() if start <= d < day and v is not None]
    if len(base) < min_days:
        return None
    mu, sd = mean(base), max(pstdev(base), SHARE_SD_FLOOR)
    return {"z": round((value - mu) / sd, 2), "baseline": round(mu, 3), "baseline_days": len(base)}


def alarm_reasons(entity: dict) -> list[str]:
    """Why an entity-day should be coded by the model, from its free measures; [] when it should not."""
    if entity.get("filtered_stories", entity.get("stories", 0)) < ALARM_MIN_STORIES:
        return []
    out = []
    att = entity.get("attention")
    if att and att["z"] >= ALARM_Z:
        out.append(f"attention z {att['z']}")
    return out


def is_partial(summary: dict) -> bool:
    """A built day is partial when its first cycle file is later than 01:00 UTC on that day."""
    if "partial" in summary:
        return bool(summary["partial"])
    first = summary.get("first_cycle") or ""
    day = summary.get("day", "")
    expected_prefix = f"cycles/{day.replace('-', '/')}/"
    if not first.startswith(expected_prefix):
        return True
    return first[len(expected_prefix):len(expected_prefix) + 6] > "010000"
