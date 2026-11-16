"""Relations between countries from GDELT Events (Tom, 15 Nov 2026: "Yes, build it").

Design and the Korean Peninsula probe it rests on: `docs/relations/2026-11-15-relations-tone.md`.

Per Events file, `pair_table` counts each directed pair of actors (Actor1 > Actor2) by their CAMEO country codes
(PRK|KOR; the UN and NATO by GDELT's known-group codes UNO and NAT). The unit is the article (distinct source URL):
GDELT codes several events from one article, sometimes both ways, so summing events or NumArticles multiplies one
story. Per pair: VEC = articles; articles carrying an event in QuadClass 1 (verbal cooperation), 2 (material
cooperation), 3 (verbal conflict), 4 (material conflict); articles with any conflict event (3 or 4); the sum over
articles of each article's mean GoldsteinScale and mean AvgTone; articles with a lead-paragraph event. The table
rides in the file's Events record (`pairs`), so the cycle writes nothing new.

Daily (`build_day`, after the country counts): the day's records are summed into
`stories/YYYY/MM/DD/relations.json` (every pair seen), and the pairs named in `catalog/relations.json` go into the
rolling `relations/series.json` (SERIES_DAYS days, one object), which is all the API reads. A day missing a tenth of
its files, or whose records mostly predate pair tables, is partial: kept, never scored and never a baseline.
Since 16 Nov 2026 the same files carry `press` (pipeline/press.py: GKG articles and tone by outlet country, summed
from the cycle's kind=press rows); the series keeps the zones' press rows beside their pairs.

On read (`zone_view`), per pair and direction: daily articles, verbal and material conflict articles, conflict
share, mean Goldstein and tone; z of the daily counts against the series' own previous 28 complete days
(`measures.attention_anomaly`, log and weekday-adjusted, as for zone attention); 7-day conflict share, Goldstein
and tone with z against the four weeks before. A pair-day is flagged when a count's z >= FLAG_Z on at least
FLAG_MIN articles (probe: 20 of 26 dated Korean events caught, 18 of 20 unlisted flags real news). Display only:
no alarm, no feed item, until Tom sets thresholds after a month of reading.

GDELT's limits (probe, 15 Nov 2026): direction and partner are often wrong, so a pair is read both ways together;
small pairs (Japan-North Korea, a median of 1-2 articles a day each way) are too thin to read daily; GDELT carries
no wires and samples non-English press.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from . import measures, press as press_mod

CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "relations.json"
VEC = ("urls", "u1", "u2", "u3", "u4", "uconf", "gold", "tone", "uroot")
# Events 2.0 columns (pipeline/events.py names the shared ones; kept here so events.py can import this module)
_DAY, _A1CC, _A1KG, _A2CC, _A2KG, _ROOT, _QUAD, _GOLD, _TONE, _URL = 1, 7, 8, 17, 18, 25, 29, 30, 34, 60
_FIELDS = 61
MAX_AGE_DAYS = 2  # as pipeline/events.py: older events are references to the past
KNOWN_GROUPS = frozenset({"UNO", "NAT"})  # the UN (no country code in GDELT) and NATO (coded "WST", the West)
SERIES_KEY = "relations/series.json"
SERIES_DAYS = 120
FILES_PER_STREAM, MIN_FILE_SHARE = 96, 0.9
FLAG_Z, FLAG_MIN = 2.5, 5
WINDOW, WINDOW_BASE = 7, 28
FLOORS = {"conflict_share_7d": 0.03, "goldstein_7d": 0.3, "tone_7d": 0.3}


# ---------------------------------------------------------------- per file

def actor_code(country: str, known_group: str) -> str:
    if known_group in KNOWN_GROUPS and (not country or known_group == "NAT"):
        return known_group
    return country


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def pair_table(rows: list[list[str]], stamp: str) -> dict[str, list]:
    """One Events file's rows -> {"A|B": VEC values} for every directed pair of two different actor codes."""
    oldest = (datetime.strptime(stamp[:8], "%Y%m%d") - timedelta(days=MAX_AGE_DAYS)).strftime("%Y%m%d")
    per: dict[str, dict[str, list]] = {}  # key -> url -> [quad bitmask, gold sum, gold n, tone sum, tone n, root]
    for r in rows:
        if len(r) < _FIELDS or r[_DAY] < oldest:
            continue
        a1, a2 = actor_code(r[_A1CC], r[_A1KG]), actor_code(r[_A2CC], r[_A2KG])
        if not a1 or not a2 or a1 == a2:
            continue
        try:
            quad = int(r[_QUAD])
        except ValueError:
            continue
        u = per.setdefault(f"{a1}|{a2}", {}).setdefault(r[_URL], [0, 0.0, 0, 0.0, 0, 0])
        if 1 <= quad <= 4:
            u[0] |= 1 << quad
        g, t = _num(r[_GOLD]), _num(r[_TONE])
        if g is not None:
            u[1] += g
            u[2] += 1
        if t is not None:
            u[3] += t
            u[4] += 1
        if r[_ROOT] == "1":
            u[5] = 1
    out = {}
    for key, urls in per.items():
        v = [0, 0, 0, 0, 0, 0, 0.0, 0.0, 0]
        for mask, gs, gn, ts, tn, root in urls.values():
            v[0] += 1
            for q in (1, 2, 3, 4):
                if mask & (1 << q):
                    v[q] += 1
            if mask & 0b11000:
                v[5] += 1
            if gn:
                v[6] += gs / gn
            if tn:
                v[7] += ts / tn
            v[8] += root
        v[6], v[7] = round(v[6], 2), round(v[7], 2)
        out[key] = v
    return out


def add(total: dict[str, list], table: dict[str, list]) -> None:
    for k, v in table.items():
        t = total.get(k)
        if t is None:
            total[k] = list(v)
        else:
            for i, x in enumerate(v):
                t[i] += x


# ---------------------------------------------------------------- catalog

@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() else {"zones": {}, "names": {}}


def series_keys(cat: dict | None = None) -> set[str]:
    """Directed keys of every pair a zone names, both ways."""
    cat = cat or catalog()
    return {k for z in cat.get("zones", {}).values() for a, b in z.get("pairs", []) for k in (f"{a}|{b}", f"{b}|{a}")}


# ---------------------------------------------------------------- daily build

def is_partial(recs: list[dict]) -> bool:
    per_stream: dict[str, int] = {}
    for r in recs:
        per_stream[r["stream"]] = per_stream.get(r["stream"], 0) + 1
    short = any(per_stream.get(s, 0) < FILES_PER_STREAM * MIN_FILE_SHARE for s in ("english", "translation"))
    with_pairs = sum(1 for r in recs if "pairs" in r)
    return short or with_pairs < MIN_FILE_SHARE * max(1, len(recs))


def day_table(day: date, recs: list[dict], press_recs: list[dict] | None = None) -> dict:
    """The day's pairs from its Events records and, given its GKG press rows (even none), its `press` section."""
    total: dict[str, list] = {}
    for r in recs:
        add(total, r.get("pairs") or {})
    for v in total.values():
        v[6], v[7] = round(v[6], 2), round(v[7], 2)
    out = {"day": day.isoformat(), "partial": is_partial(recs), "files": len(recs),
           "files_with_pairs": sum(1 for r in recs if "pairs" in r), "vec": list(VEC),
           "pairs": dict(sorted(total.items()))}
    if press_recs is not None:
        out["press"] = press_mod.day_table(press_recs)
    return out


def build_day(sink, day: date, recs: list[dict] | None = None, press_recs: list[dict] | None = None) -> dict:
    """Write the day's relations.json and put its configured pairs and press rows into the rolling series."""
    if recs is None:
        from . import countries  # imported here: countries -> events -> relations
        recs, press_recs = countries.day_records_and_press(sink, day)
    rec = day_table(day, recs, press_recs)
    sink.write_json(f"stories/{day:%Y/%m/%d}/relations.json", rec)
    update_series(sink, [rec])
    out = {"day": rec["day"], "partial": rec["partial"], "pairs": len(rec["pairs"])}
    if "press" in rec:
        out["press"] = {"files": rec["press"]["files"], "partial": rec["press"]["partial"],
                        "rows": len(rec["press"]["t"])}
    return out


def update_series(sink, recs: list[dict], keys: set[str] | None = None, series: dict | None = None,
                  press_keys: set[str] | None = None) -> dict:
    """Merge day tables into relations/series.json (read once, written once), keeping the newest SERIES_DAYS."""
    keys = keys if keys is not None else series_keys()
    pkeys = press_keys if press_keys is not None else press_mod.series_keys()
    s = series if series is not None else (sink.read_json(SERIES_KEY) or {})
    days = dict(s.get("days") or {})
    for rec in recs:
        days[rec["day"]] = {"partial": rec["partial"], "pairs": {k: v for k, v in rec["pairs"].items() if k in keys}}
        if "press" in rec:
            p = rec["press"]
            days[rec["day"]]["press"] = {"partial": p["partial"],
                                         "t": {k: v for k, v in p["t"].items() if k in pkeys}}
    keep = sorted(days)[-SERIES_DAYS:]
    out = {"vec": list(VEC), "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "catalog_version": catalog().get("version"), "days": {d: days[d] for d in keep}}
    sink.write_json(SERIES_KEY, out)
    return out


def rebuild_series(sink, end: date, days: int = SERIES_DAYS) -> dict:
    """The series from stored relations.json files (after a catalog change or a backfill): up to `days` reads."""
    recs = []
    for i in range(days):
        d = end - timedelta(days=i)
        r = sink.read_json(f"stories/{d:%Y/%m/%d}/relations.json")
        if r:
            recs.append(r)
    return update_series(sink, recs, series={})


# ---------------------------------------------------------------- read side

def _derive(v: list | None) -> dict:
    v = v or [0] * len(VEC)
    n = v[0]
    return {"articles": n, "verbal_conflict": v[3], "material_conflict": v[4],
            "conflict_share": round(v[5] / n, 3) if n else None,
            "goldstein": round(v[6] / n, 2) if n else None, "tone": round(v[7] / n, 2) if n else None}


def _sum(vs: list) -> list:
    out = [0] * len(VEC)
    for v in vs:
        if v:
            for i, x in enumerate(v):
                out[i] += x
    return out


def _mean(xs: list[float]) -> float:
    return math.fsum(xs) / len(xs)


def _pstdev(xs: list[float]) -> float:
    m = _mean(xs)
    return math.sqrt(math.fsum((x - m) ** 2 for x in xs) / len(xs))


def _z_logs(y: list[float], w: list[int], y0: float, wd0: int) -> float | None:
    """The z of measures.attention_anomaly from log counts `y` on weekdays `w` (the baseline days) and today's log
    count `y0` on weekday `wd0`."""
    n = len(y)
    if n < measures.MIN_BASELINE_DAYS:
        return None
    level = math.fsum(y) / n
    sums, cnt = [0.0] * 7, [0] * 7
    for v, k in zip(y, w):
        sums[k] += v
        cnt[k] += 1
    adj = [sums[k] / cnt[k] - level if cnt[k] >= 2 else 0.0 for k in range(7)]
    resid = [v - level - adj[k] for v, k in zip(y, w)]
    sd = max(_pstdev(resid), measures.SD_FLOOR)
    return round((y0 - level - adj[wd0]) / sd, 2)


def anomaly_z(history: dict[date, float], day: date, count: float) -> float | None:
    """measures.attention_anomaly's z (log counts, weekday-adjusted, against the previous 28 complete days) in
    float arithmetic: the statistics module's exact sums took 2.7 s for one pair's 90 days (15 Nov 2026), too slow
    for an API call. tests/test_relations.py checks it gives the same z."""
    start = day - timedelta(days=measures.BASELINE_DAYS)
    base = [(d, c) for d, c in history.items() if start <= d < day and c is not None]
    return _z_logs([math.log1p(c) for _, c in base], [d.weekday() for d, _ in base], math.log1p(count),
                   day.weekday())


def _window_z(dates: list[date], vals: list[float], x: float | None, day: date,
              floor: float) -> tuple[float, float] | None:
    """(z, baseline mean) of the 7-day value `x` ending `day` against the 7-day values ending 7-34 days before
    (none overlaps this week); `dates` sorted, `vals` alongside. Those baseline windows overlap each other, so their
    spread understates week-to-week change and the z runs large: the page shows the baseline mean, not the z."""
    if x is None:
        return None
    lo = bisect_left(dates, day - timedelta(days=WINDOW + WINDOW_BASE - 1))
    hi = bisect_right(dates, day - timedelta(days=WINDOW))
    base = vals[lo:hi]
    if len(base) < WINDOW_BASE // 2:
        return None
    m = _mean(base)
    return round((x - m) / max(_pstdev(base), floor), 2), round(m, 3)


def direction_rows(daily: dict[date, list], complete: set[date], dates: list[date],
                   shown: list[date] | None = None) -> dict[date, dict]:
    """Per shown day: the derived values, z of the daily counts and the 7-day values with their z."""
    comp = [d for d in dates if d in complete]  # sorted
    counts = {m: [daily[d][i] for d in comp] for m, i in (("articles", 0), ("verbal_conflict", 3),
                                                          ("material_conflict", 4))}
    w7: dict[date, dict] = {}
    for d in dates:
        win = [d - timedelta(days=k) for k in range(WINDOW)]
        if all(w in complete for w in win):
            w = _derive(_sum([daily[x] for x in win]))
            w7[d] = {"conflict_share_7d": w["conflict_share"], "goldstein_7d": w["goldstein"], "tone_7d": w["tone"]}
    wins = {}
    for m in FLOORS:
        ds = [d for d in sorted(w7) if w7[d][m] is not None]
        wins[m] = (ds, [w7[d][m] for d in ds])
    logs = {m: [math.log1p(x) for x in vs] for m, vs in counts.items()}
    wds = [d.weekday() for d in comp]
    out = {}
    for d in (shown if shown is not None else dates):
        row = _derive(daily[d])
        if d in complete:
            # only the 28 days before reach anomaly_z (bisect on the sorted complete days)
            lo, hi = bisect_left(comp, d - timedelta(days=measures.BASELINE_DAYS)), bisect_left(comp, d)
            for m, ys in logs.items():
                row[f"z_{m}"] = _z_logs(ys[lo:hi], wds[lo:hi], ys[hi], wds[hi])
        if d in w7:
            row.update(w7[d])
            for m in FLOORS:
                zb = _window_z(*wins[m], w7[d][m], d, FLOORS[m])
                row[f"z_{m}"], row[f"base_{m}"] = zb if zb else (None, None)
        out[d] = row
    return out


def _flag(row: dict, count: str) -> bool:
    z = row.get(f"z_{count}")
    return z is not None and z >= FLAG_Z and (row.get(count) or 0) >= FLAG_MIN


def zone_view(series: dict, zone_id: str, end: date | None = None, days: int = 90, cat: dict | None = None,
              detail: bool = False) -> dict | None:
    """The zone's pairs over `days` days ending `end` (default: the newest in the series), or None if the zone
    names no pairs. Per pair: daily article counts (both ways and each way) and their z as lists aligned with
    `days`, and every measure for the last day (`latest`); `detail` adds every measure for every day (`rows`,
    about 600 KB for six pairs, against about 20 KB without)."""
    cat = cat or catalog()
    zone = (cat.get("zones") or {}).get(zone_id)
    if not zone or not zone.get("pairs"):
        return None
    sdays = series.get("days") or {}
    dates = sorted(date.fromisoformat(d) for d in sdays)
    if not dates:
        return {"zone": zone_id, "pairs": [], "flags": [], "days": [], "complete": [], "method": method()}
    end = min(end, dates[-1]) if end else dates[-1]
    dates = [d for d in dates if d <= end]
    complete = {d for d in dates if not sdays[d.isoformat()]["partial"]}
    shown = [d for d in dates if d > end - timedelta(days=days)]
    names = cat.get("names") or {}
    pairs_out, flags = [], []
    for a, b in zone["pairs"]:
        ab = {d: sdays[d.isoformat()]["pairs"].get(f"{a}|{b}") or [0] * len(VEC) for d in dates}
        ba = {d: sdays[d.isoformat()]["pairs"].get(f"{b}|{a}") or [0] * len(VEC) for d in dates}
        both = {d: _sum([ab[d], ba[d]]) for d in dates}
        rows = {k: direction_rows(v, complete, dates, shown) for k, v in (("ab", ab), ("ba", ba), ("both", both))}
        out_days = []
        for d in shown:
            item = {"day": d.isoformat(), "complete": d in complete,
                    "both": rows["both"][d], "ab": rows["ab"][d], "ba": rows["ba"][d]}
            why = []
            if _flag(rows["both"][d], "articles"):
                why.append({"direction": "both", "count": "articles"})
            for k in ("ab", "ba"):
                for c in ("verbal_conflict", "material_conflict"):
                    if _flag(rows[k][d], c):
                        why.append({"direction": k, "count": c})
            if why and d in complete:
                item["flag"] = why
                flags.append({"day": d.isoformat(), "a": a, "b": b, "why": [
                    {**w, "n": rows[w["direction"]][d][w["count"]], "z": rows[w["direction"]][d][f"z_{w['count']}"]}
                    for w in why]})
            out_days.append(item)
        pair = {"a": a, "b": b, "a_name": names.get(a, a), "b_name": names.get(b, b),
                "articles": [rows["both"][d]["articles"] for d in shown],
                "articles_ab": [rows["ab"][d]["articles"] for d in shown],
                "articles_ba": [rows["ba"][d]["articles"] for d in shown],
                "z_articles": [rows["both"][d].get("z_articles") for d in shown],
                "flagged": [x["day"] for x in out_days if x.get("flag")],
                "latest": out_days[-1] if out_days else None}
        if detail:
            pair["rows"] = out_days
        pairs_out.append(pair)
    flags.sort(key=lambda f: f["day"], reverse=True)
    return {"zone": zone_id, "end": end.isoformat(), "days": [d.isoformat() for d in shown],
            "complete": [d in complete for d in shown], "pairs": pairs_out, "flags": flags, "method": method(),
            "press": press_mod.zone_view(series, zone_id, end, days, cat), "catalog_version": cat.get("version")}


def method() -> dict:
    return {
        "source": "GDELT Project Events 2.0 (gdeltproject.org), English and translation streams",
        "unit": "articles (distinct source URLs) with a coded event between the two, by direction (actor > target)",
        "conflict": "QuadClass 3 (verbal conflict: accuse, demand, reject, threaten) and 4 (material conflict)",
        "goldstein": "mean per article of GDELT's GoldsteinScale, -10 (most conflictual) to +10",
        "tone": "mean per article of GDELT's AvgTone (dictionary score of the article text)",
        "z": "daily counts against the pair's own previous 28 complete days (log, weekday-adjusted); 7-day values "
             "against the 7-day values of the four weeks before (base_*: their mean; those windows overlap, so this "
             "z runs large)",
        "flag": f"z >= {FLAG_Z} on at least {FLAG_MIN} articles (daily articles both ways, or either direction's "
                "verbal or material conflict articles); display only, not a warning",
        "limits": "GDELT often gets direction and partner wrong (read both ways together), carries no wire "
                  "services and samples non-English press; small pairs are noisy",
    }
