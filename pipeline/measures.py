"""Measures computed from the daily story build. No model calls; all free.

- attention_anomaly: how unusual today's story count is against the entity's own last 28 complete days,
  adjusted for day of week. Counts are log-transformed (news volume is skewed), so z is in log units:
  z = 2 means about two typical day-to-day swings above the expected level for that weekday.
- (removed 27 Oct 2026) casualty_share, the share of articles where GDELT extracted a KILL/WOUND count. It
  could not tell whose deaths, where or when: 20-26 Oct, Taiwan Strait ran 6-12% and raised two alarms, and a
  sanctions topic hit 50% from a story about Sudan. Planned replacement: violent events located inside the zone.

Thresholds for Watch / Warning / Crisis belong in each zone's indicator charter, not here.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from statistics import mean, pstdev

BASELINE_DAYS = 28
MIN_BASELINE_DAYS = 14
SD_FLOOR = 0.15  # log units; stops a very steady baseline from turning small changes into huge z
SHARE_SD_FLOOR = 0.02  # for shares (0-1)
# Alarm = a free signal that buys model coding for that entity-day (pipeline/ondemand.py). It is a spending
# trigger, not a warning level; Watch / Warning / Crisis come from the charters.
ALARM_Z = 2.0
ALARM_MIN_STORIES = 5


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
    y = {d: math.log1p(c) for d, c in base.items()}
    level = mean(y.values())
    by_wd: dict[int, list[float]] = {}
    for d, v in y.items():
        by_wd.setdefault(d.weekday(), []).append(v)
    adjust = {wd: mean(vs) - level for wd, vs in by_wd.items() if len(vs) >= 2}
    weekday_adjusted = day.weekday() in adjust
    resid = [v - level - adjust.get(d.weekday(), 0.0) for d, v in y.items()]
    sd = max(pstdev(resid), SD_FLOOR)
    expected = level + adjust.get(day.weekday(), 0.0)
    z = (math.log1p(count) - expected) / sd
    return {
        "z": round(z, 2),
        "expected": round(math.expm1(expected), 1),
        "ratio": round(count / math.expm1(expected), 2) if math.expm1(expected) > 0 else None,
        "baseline_days": len(base),
        "weekday_adjusted": weekday_adjusted,
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
