"""Per-country daily counts from GDELT Events records, each country against its own normal, and the Rising list.

So new crises surface without a catalog edit (Tom, 27 Oct 2026, after Ethiopia's renewed war was lost inside the
Horn of Africa zone). Every country is counted, not just the zones, from the per-file records `events.py` makes
(rows in each run's cycle file; `events/` files before 30 Oct 2026).

Two counts per country-day, both distinct articles with at least one event located in the country:
- attention (`urls`): any event;
- violence (`violent`): an assault, fight or mass-violence event (CAMEO 18-20).
Each is scored against the country's own previous 28 complete days (log z, weekday-adjusted, as for zones) and
against the median of its previous 90 complete days. The 90-day reference keeps a long crisis visible after its
peak has entered the 28-day baseline (Ethiopia & Eritrea, October 2026).

- Rising: z >= RISING_Z, at least MIN_ARTICLES that day, and at least RISING_RATIO times the 28-day expectation.
- Elevated: not rising, but at least ELEVATED_RATIO times the 90-day median (needs 60 such days).
Output: `stories/YYYY/MM/DD/countries.json`. A day missing more than a tenth of its files is partial: counted, not
scored. Violent events placed in a zone country go to `stories/YYYY/MM/DD/violent.jsonl` for the map.

Zone violence (replaces the casualty-reporting share removed on 27 Oct): per zone, distinct articles reporting a
violent event placed inside the zone (its `countries`, or `violence.countries` + `violence.adm1` where set) whose
headline names the zone (headline terms on the article link's words). The headline check matters: on 26 Oct only
about half of Israel's and a fifth of Venezuela's violent-event articles were about the zone, and Russia-NATO's
were nearly all noise (a Viking king placed in Oslo). Scored like attention, against the zone's last 28 days.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from statistics import median

from . import measures
from .events import METRICS, ROW_PREFIX, canon
from .press import ROW_PREFIX as PRESS_PREFIX
from .relevance import TermMatcher
from .stories import title_from_url

CATALOG = Path(__file__).resolve().parent.parent / "catalog"
FILES_PER_STREAM = 96
MIN_FILE_SHARE = 0.9
SCORED = ("urls", "violent")
RISING_Z = 2.5
RISING_RATIO = 1.5
MIN_ARTICLES = {"urls": 40, "violent": 15}
ELEVATED_RATIO = 2.0
REF_DAYS, MIN_REF_DAYS = 90, 60
MAX_LISTED = 15
SAMPLES_KEPT = 6
# GDELT codes that are not countries (GDELT's FIPS.country.txt: oceans, undersea features, undesignated
# sovereignty, no man's land): never listed, and not reported as missing from the catalog.
NOT_COUNTRIES = frozenset({"OS", "UF", "UU", "NM"})


@lru_cache(maxsize=1)
def names() -> dict[str, str]:
    p = CATALOG / "fips_countries.json"
    return json.loads(p.read_text(encoding="utf-8"))["names"] if p.exists() else {}


@lru_cache(maxsize=1)
def zone_countries() -> dict[str, list[str]]:
    """FIPS code -> zone ids that cover it (catalog/entities.json `countries`)."""
    cat = json.loads((CATALOG / "entities.json").read_text(encoding="utf-8"))
    out: dict[str, list[str]] = {}
    for z in cat["zones"]:
        for cc in z.get("countries", []):
            out.setdefault(cc, []).append(z["id"])
    return out


@lru_cache(maxsize=1)
def violence_scopes() -> dict[str, tuple[frozenset, frozenset]]:
    """zone id -> (countries, ADM1 codes) where its violence is counted."""
    cat = json.loads((CATALOG / "entities.json").read_text(encoding="utf-8"))
    out = {}
    for z in cat["zones"]:
        v = z.get("violence") or {}
        out[z["id"]] = (frozenset(v.get("countries", z.get("countries", []))), frozenset(v.get("adm1", [])))
    return out


def zone_violence(recs: list[dict], matcher: TermMatcher | None = None) -> dict[str, dict]:
    """Per zone: placed violent events inside it, their articles, and articles whose headline names the zone."""
    matcher = matcher or TermMatcher()
    scopes = violence_scopes()
    ev: dict[str, set] = {z: set() for z in scopes}
    urls: dict[str, set] = {z: set() for z in scopes}
    for r in recs:
        for v in r.get("violent", []):
            for zid, (ccs, adm1) in scopes.items():
                if canon(v["cc"]) in ccs or v.get("adm1") in adm1:
                    ev[zid].add(v["id"])
                    urls[zid].add(v["url"])
    out = {}
    for zid in scopes:
        named = sum(1 for u in urls[zid] if matcher.hit(zid, title_from_url(u)))
        out[zid] = {"events": len(ev[zid]), "articles": len(urls[zid]), "named": named}
    return out


def _keys_for(sink, day: date) -> list[str]:
    """Where `day`'s Events records can be: `events/` files (before 30 Oct 2026, and backfills) and cycle files."""
    nxt = day + timedelta(days=1)
    keys = []
    for prefix in ("events", "cycles"):
        keys += sink.list(f"{prefix}/{day:%Y/%m/%d}/")
        # A day's last files can be fetched by the next day's first runs (cloud files are named by run time).
        keys += [k for k in sink.list(f"{prefix}/{nxt:%Y/%m/%d}/") if _clock(k) < "040000"]
    return keys


def _clock(key: str) -> str:
    """HHMMSS of a file name: live runs write HHMMSS, Events backfills the full stamp, GKG backfills HHMMSSt."""
    return "".join(c for c in Path(key).stem if c.isdigit())[-6:]


def _records_in(sink, key: str, press: bool = False) -> list[dict]:
    if key.startswith("cycles/"):
        kinds = ("events", "press") if press else ("events",)
        prefix = (ROW_PREFIX, PRESS_PREFIX) if press else ROW_PREFIX
        return [r for r in sink.read_lines(key, prefix) if r.get("kind") in kinds]
    return (sink.read_json(key) or {}).get("files", [])


def day_records_and_press(sink, day: date) -> tuple[list[dict], list[dict]]:
    """The day's Events records and its GKG press rows (pipeline/press.py), first copy of each file, read in one
    pass over the same objects."""
    want = f"{day:%Y%m%d}"
    recs, press, seen = [], [], set()
    for k in _keys_for(sink, day):
        for r in _records_in(sink, k, press=True):
            kind = r.get("kind", "events")
            key = (kind, r["stamp"], r["stream"])
            if r["stamp"][:8] == want and key not in seen:
                seen.add(key)
                (press if kind == "press" else recs).append(r)
    return recs, press


def day_records(sink, day: date) -> list[dict]:
    want = f"{day:%Y%m%d}"
    recs, seen = [], set()
    for k in _keys_for(sink, day):
        for r in _records_in(sink, k):
            key = (r["stamp"], r["stream"])
            if r["stamp"][:8] == want and key not in seen:
                seen.add(key)
                recs.append(r)
    return recs


def totals(recs: list[dict]) -> dict[str, dict[str, int]]:
    """Per country, the day's counts summed over its files. Records stored before the RB fold keep RB apart; it is
    added to RI here (an article placed under both codes in one such file counts twice; new records count it once)."""
    out: dict[str, dict[str, int]] = {}
    for r in recs:
        for cc, vals in r["countries"].items():
            t = out.setdefault(canon(cc), dict.fromkeys(METRICS, 0))
            for m, v in zip(METRICS, vals):
                t[m] += v
    return out


def is_partial(recs: list[dict]) -> bool:
    per_stream: dict[str, int] = {}
    for r in recs:
        per_stream[r["stream"]] = per_stream.get(r["stream"], 0) + 1
    return any(per_stream.get(s, 0) < FILES_PER_STREAM * MIN_FILE_SHARE for s in ("english", "translation"))


def history(sink, day: date, days: int = REF_DAYS) -> tuple[dict[str, dict[str, dict[date, int]]], list[date]]:
    """(metric -> country -> day -> count, the complete days read), from earlier days' countries.json.
    A country absent from a complete day had zero articles that day."""
    out: dict[str, dict[str, dict[date, int]]] = {m: {} for m in SCORED}
    out["zone_named"] = {}
    complete = []
    for i in range(1, days + 1):
        d = day - timedelta(days=i)
        s = sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
        if not s or s.get("partial"):
            continue
        complete.append(d)
        for cc, c in s["countries"].items():
            for m in SCORED:
                h = out[m].setdefault(canon(cc), {})  # days stored before the fold hold RB apart: add it to RI
                h[d] = h.get(d, 0) + c.get(m, 0)
        for zid, zv in (s.get("zones") or {}).items():
            out["zone_named"].setdefault(zid, {})[d] = zv.get("named", 0)
    return out, complete


def score(hist: dict[date, int], complete: list[date], day: date, count: int) -> dict:
    """28-day z (measures.attention_anomaly) and the ratio to the 90-day median, over complete days only."""
    out: dict = {}
    start28 = day - timedelta(days=measures.BASELINE_DAYS)
    att = measures.attention_anomaly({d: hist.get(d, 0) for d in complete if d >= start28}, day, count)
    if att:
        out.update(z=att["z"], expected=att["expected"], ratio=att["ratio"])
    ref = [hist.get(d, 0) for d in complete if d >= day - timedelta(days=REF_DAYS)]
    if len(ref) >= MIN_REF_DAYS:
        med = median(ref)
        out.update(median90=med, ratio90=round(count / med, 2) if med > 0 else None)
    return out


def uncatalogued(tot: dict[str, dict[str, int]]) -> dict[str, int]:
    """Codes with enough articles to be listed but no name in catalog/fips_countries.json, so never listed, fed or
    mapped (Serbia's RB until 16 Nov 2026). Written to countries.json so a gap shows in the data."""
    known = names()
    return {cc: t["urls"] for cc, t in sorted(tot.items())
            if known and cc not in known and cc not in NOT_COUNTRIES and t["urls"] >= min(MIN_ARTICLES.values())}


def _listed(scored: dict[str, dict], metric: str) -> tuple[list[str], list[str]]:
    rising, elevated = [], []
    known = names()
    for cc, c in scored.items():
        s = c.get(f"{metric}_score") or {}
        n = c.get(metric, 0)
        # GDELT also uses codes that are not countries ("OS", oceans); only named countries are listed.
        if n < MIN_ARTICLES[metric] or (known and cc not in known):
            continue
        if (s.get("z") or 0) >= RISING_Z and (s.get("ratio") or 0) >= RISING_RATIO:
            rising.append(cc)
        elif (s.get("ratio90") or 0) >= ELEVATED_RATIO:
            elevated.append(cc)
    rising.sort(key=lambda cc: -scored[cc][f"{metric}_score"]["z"])
    elevated.sort(key=lambda cc: -scored[cc][f"{metric}_score"]["ratio90"])
    return rising[:MAX_LISTED], elevated[:MAX_LISTED]


def build_day(sink, day: date, recs: list[dict] | None = None) -> dict:
    """`recs`: the day's Events records when the caller already read them (the cycle passes them on to
    relations.build_day too, so the day's cycle files are read once)."""
    recs = day_records(sink, day) if recs is None else recs
    partial = is_partial(recs)
    tot = totals(recs)
    hist, complete = history(sink, day) if not partial else ({m: {} for m in (*SCORED, "zone_named")}, [])
    zc, nm = zone_countries(), names()
    scored = {}
    for cc, t in tot.items():
        c = {"name": nm.get(cc, cc), **t}
        if cc in zc:
            c["zones"] = zc[cc]
        if not partial:
            for m in SCORED:
                c[f"{m}_score"] = score(hist[m].get(cc, {}), complete, day, t[m])
        scored[cc] = c
    lists = {}
    if not partial:
        for m in SCORED:
            r, e = _listed(scored, m)
            lists[m] = {"rising": r, "elevated": e}
    shown = {cc for l in lists.values() for v in l.values() for cc in v} | set(zc)
    samples: dict[str, list[str]] = {}
    for r in recs:
        for cc, urls in r.get("samples", {}).items():
            cc = canon(cc)
            if cc in shown:
                s = samples.setdefault(cc, [])
                s.extend(u for u in urls if u not in s and len(s) < SAMPLES_KEPT)
    violent, seen = [], set()
    for r in recs:
        for v in r.get("violent", []):
            cc = canon(v["cc"])
            if (cc in zc or cc in shown) and v["id"] not in seen:
                seen.add(v["id"])
                violent.append({**v, "cc": cc, "stream": r["stream"], "file": r["stamp"]})
    zones = zone_violence(recs)
    if not partial:
        for zid, zv in zones.items():
            # A zone is scored on the complete days that recorded it (a new zone waits for 14 of them).
            zh = hist["zone_named"].get(zid, {})
            zv["named_score"] = score(zh, [d for d in complete if d in zh], day, zv["named"])
    out = {"day": day.isoformat(), "partial": partial, "files": len(recs), "scored": list(SCORED),
           "lists": lists, "countries": scored, "samples": samples, "zones": zones, "uncatalogued": uncatalogued(tot)}
    sink.write_json(f"stories/{day:%Y/%m/%d}/countries.json", out)
    sink.write_lines(f"stories/{day:%Y/%m/%d}/violent.jsonl", violent)
    return {"day": out["day"], "partial": partial, "files": len(recs),
            "rising": lists.get("urls", {}).get("rising", []), "violent_rising": lists.get("violent", {}).get("rising", [])}
