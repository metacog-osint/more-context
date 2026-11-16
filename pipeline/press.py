"""Press tone by outlet country from GDELT GKG 2.1 (Tom approved the plan 15 Nov 2026; the build 16 Nov 2026).

Checks, Tom's outlet picks and the plan: `docs/relations/2026-11-15-press-outlets.md`.

Per GKG file (`FileTable`, fed by the cycle's existing GKG loop): for every article with a tone, the countries its
V2 enhanced locations mention (field 10, counted by mention) and the outlet's country (GDELT's 2018 domain table,
trimmed to the domains seen in a week, plus `catalog/press_outlets.json` overrides). For each subject country
(`subjects()`: every zone's countries plus the self-coverage ones), per outlet country "O>S": articles mentioning S
(n_any) and their summed tone, and articles where S is the single most-mentioned country (n_main) and their summed
tone. One `kind: "press"` row per GKG file rides in the run's cycle file; the daily build sums the day's rows into
the `press` section of `stories/YYYY/MM/DD/relations.json` and puts the zones' rows into `relations/series.json`
(pipeline/relations.py), so no new writes.

On read (`zone_view`): per row (outlet country > subject country), daily main-subject articles, the 7-day mean tone
and its z against the 7-day values of the four weeks before (as for the pairs; those windows overlap, so the z runs
large and the page shows the baseline mean). Each outlet country is read only against its own past: tone is a
dictionary score that differs by language and outlet mix. Display only: no flags, alarms or feed items until Tom
has read it for a month.
"""
from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent.parent / "catalog"
DOMAINS = CATALOG_DIR / "press_domains.tsv"
OUTLETS = CATALOG_DIR / "press_outlets.json"
VEC = ("n_any", "tone_any", "n_main", "tone_main")
ROW_PREFIX = '{"kind": "press"'
FILES_PER_STREAM, MIN_FILE_SHARE = 96, 0.9
DAILY_MIN = 8  # median main-subject articles a day to read a row daily (the plan: under 8 a day reads weekly)
WEEKLY_MIN = 14  # median 7-day total to read a row weekly; below that it is listed as too thin
TONE_MIN_7D = 10  # a 7-day tone needs at least this many articles
WINDOW, WINDOW_BASE = 7, 28
TONE_FLOOR = 0.3
UNKNOWN_TOP_FILE, UNKNOWN_TOP_DAY = 10, 50  # unknown-outlet domains kept per file and per day


# ---------------------------------------------------------------- catalog

@lru_cache(maxsize=1)
def outlets_catalog() -> dict:
    return json.loads(OUTLETS.read_text(encoding="utf-8")) if OUTLETS.exists() else {}


@lru_cache(maxsize=1)
def domain_table() -> dict[str, str | None]:
    """domain -> FIPS outlet country (None: deliberately unassigned)."""
    table: dict[str, str | None] = {}
    if DOMAINS.exists():
        for line in DOMAINS.read_text(encoding="utf-8").split("\n"):
            dom, _, cc = line.partition("\t")
            if dom and cc and not dom.startswith("#"):
                table[dom] = cc.strip()
    table.update(outlets_catalog().get("overrides") or {})
    return table


def outlet_country(domain: str, table: dict | None = None) -> str | None:
    """The outlet's FIPS country from its domain or the longest listed parent domain; None if unknown."""
    table = domain_table() if table is None else table
    host = domain.lower().strip()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    for i in range(len(parts) - 1):
        k = ".".join(parts[i:])
        if k in table:
            return table[k]
    return None


def zone_blocks(cat: dict | None = None) -> dict[str, dict]:
    if cat is None:
        from . import relations
        cat = relations.catalog()
    return {z: v["press"] for z, v in (cat.get("zones") or {}).items() if v.get("press")}


def subjects(cat: dict | None = None) -> frozenset[str]:
    """Every country a press row can be about: the zones' countries (catalog/entities.json) and the press blocks'."""
    out = set()
    ents = CATALOG_DIR / "entities.json"
    if ents.exists():
        for z in json.loads(ents.read_text(encoding="utf-8")).get("zones", []):
            out.update(z.get("countries") or [])
    for b in zone_blocks(cat).values():
        out.update(b.get("about") or [])
        out.update(b.get("self") or [])
    return frozenset(out)


def zone_rows(block: dict) -> list[tuple[str, str, str]]:
    """(outlet, subject, role) for a zone's press block: picked outside outlets and the zone's own countries
    ("home") on each subject other than themselves, and each self-coverage country on itself."""
    out, seen = [], set()
    for role, outlets in (("outside", block.get("outlets") or []), ("home", block.get("home") or [])):
        for o in outlets:
            for s in block.get("about") or []:
                if o != s and (o, s) not in seen:
                    seen.add((o, s))
                    out.append((o, s, role))
    for s in block.get("self") or []:
        if (s, s) not in seen:
            seen.add((s, s))
            out.append((s, s, "self"))
    return out


def series_keys(cat: dict | None = None) -> set[str]:
    return {f"{o}>{s}" for b in zone_blocks(cat).values() for o, s, _ in zone_rows(b)}


# ---------------------------------------------------------------- per file

def location_counts(field: str, drop: frozenset[str] = frozenset()) -> dict[str, int]:
    """Country code -> mentions in a V2 enhanced locations field (TYPE#NAME#CC#...; entries ';'-separated)."""
    c: dict[str, int] = {}
    for loc in field.split(";"):
        p = loc.split("#", 3)
        if len(p) > 2 and p[2] and p[1] not in drop:
            c[p[2]] = c.get(p[2], 0) + 1
    return c


def main_country(c: dict[str, int]) -> str | None:
    """The single most-mentioned country; None on a tie or no locations."""
    if not c:
        return None
    top = max(c.values())
    m = [k for k, n in c.items() if n == top]
    return m[0] if len(m) == 1 else None


class FileTable:
    """One GKG file's press table, built article by article."""

    def __init__(self, subj: frozenset[str] | None = None, table: dict | None = None):
        self.subj = subjects() if subj is None else subj
        self.table = domain_table() if table is None else table
        self.drop = frozenset(outlets_catalog().get("drop_location_names") or [])
        self.t: dict[str, list] = {}
        self.articles = 0  # articles with a tone that mention a subject country
        self.unknown = 0  # of those, articles whose outlet country is unknown or unassigned
        self.unknown_domains: dict[str, int] = {}

    def add(self, domain: str, tone: float | None, v2_locations: str) -> None:
        if tone is None or not v2_locations:
            return
        c = location_counts(v2_locations, self.drop)
        hit = [s for s in c if s in self.subj]
        if not hit:
            return
        self.articles += 1
        o = outlet_country(domain, self.table)
        if not o:
            self.unknown += 1
            if o is None and domain not in self.table:  # not a deliberately unassigned one (null override)
                d = domain.lower()
                self.unknown_domains[d] = self.unknown_domains.get(d, 0) + 1
            return
        m = main_country(c)
        for s in hit:
            v = self.t.get(f"{o}>{s}")
            if v is None:
                v = self.t[f"{o}>{s}"] = [0, 0.0, 0, 0.0]
            v[0] += 1
            v[1] += tone
            if s == m:
                v[2] += 1
                v[3] += tone

    def add_zip(self, data: bytes, stream: str) -> "FileTable":
        """Every article of a zipped GKG file not left out by catalog/blocklist.json, as the cycle counts them."""
        from . import blocklist, gdelt
        for art in gdelt.parse_zip(data, stream):
            if not blocklist.gdelt_reason(art.domain, art.url):
                self.add(art.domain, art.tone, art.v2_locations)
        return self

    def row(self, stamp: str, stream: str) -> dict:
        """The cycle-file row; `kind` first so its line starts with ROW_PREFIX."""
        top = sorted(self.unknown_domains.items(), key=lambda kv: (-kv[1], kv[0]))[:UNKNOWN_TOP_FILE]
        return {"kind": "press", "stamp": stamp, "stream": stream, "articles": self.articles,
                "unknown": self.unknown, "unknown_top": [[d, n] for d, n in top],
                "t": {k: [v[0], round(v[1], 2), v[2], round(v[3], 2)] for k, v in sorted(self.t.items())}}


# ---------------------------------------------------------------- daily build

def is_partial(recs: list[dict]) -> bool:
    per: dict[str, int] = {}
    for r in recs:
        per[r["stream"]] = per.get(r["stream"], 0) + 1
    return any(per.get(s, 0) < FILES_PER_STREAM * MIN_FILE_SHARE for s in ("english", "translation"))


def day_table(recs: list[dict]) -> dict:
    total: dict[str, list] = {}
    for r in recs:
        for k, v in (r.get("t") or {}).items():
            t = total.get(k)
            if t is None:
                total[k] = list(v)
            else:
                for i, x in enumerate(v):
                    t[i] += x
    for v in total.values():
        v[1], v[3] = round(v[1], 2), round(v[3], 2)
    unk: dict[str, int] = {}
    for r in recs:
        for d, n in r.get("unknown_top") or []:
            unk[d] = unk.get(d, 0) + n
    top = sorted(unk.items(), key=lambda kv: (-kv[1], kv[0]))[:UNKNOWN_TOP_DAY]
    return {"partial": is_partial(recs), "files": len(recs), "vec": list(VEC),
            "articles": sum(r.get("articles", 0) for r in recs), "unknown": sum(r.get("unknown", 0) for r in recs),
            "unknown_top": [[d, n] for d, n in top],
            "t": dict(sorted(total.items()))}


# ---------------------------------------------------------------- read side

def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return 0.0 if not n else (s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2)


def _week(daily: dict[date, list], d: date, complete: set[date]) -> tuple[int, float] | None:
    win = [d - timedelta(days=k) for k in range(WINDOW)]
    if not all(w in complete for w in win):
        return None
    n = sum(daily[w][2] for w in win)
    return n, sum(daily[w][3] for w in win)


def row_view(daily: dict[date, list], complete: set[date], dates: list[date], shown: list[date]) -> dict:
    """Daily main-subject articles and tone over `shown`, the 7-day tone at the last shown day with its z and
    baseline mean, and the row's cadence (daily, weekly or thin) from its last 28 complete days."""
    from .relations import _mean, _pstdev
    end = shown[-1]
    recent = [d for d in dates if d in complete and end - timedelta(days=WINDOW_BASE) < d <= end]
    med_day = _median([daily[d][2] for d in recent])
    weeks = [w[0] for d in recent if (w := _week(daily, d, complete))]
    med_week = _median(weeks)
    cadence = "daily" if recent and med_day >= DAILY_MIN else "weekly" if weeks and med_week >= WEEKLY_MIN else "thin"
    w7: dict[date, float] = {}
    for d in dates:
        w = _week(daily, d, complete)
        if w and w[0] >= TONE_MIN_7D:
            w7[d] = w[1] / w[0]
    wd = sorted(w7)
    tone_7d = z = base = None
    last = _week(daily, end, complete)
    if end in w7:
        tone_7d = round(w7[end], 2)
        lo = bisect_left(wd, end - timedelta(days=WINDOW + WINDOW_BASE - 1))
        hi = bisect_right(wd, end - timedelta(days=WINDOW))
        b = [w7[x] for x in wd[lo:hi]]
        if len(b) >= WINDOW_BASE // 2:
            base = round(_mean(b), 2)
            z = round((w7[end] - _mean(b)) / max(_pstdev(b), TONE_FLOOR), 2)
    return {"cadence": cadence, "median_day": round(med_day, 1), "median_week": round(med_week, 1),
            "articles": [daily[d][2] for d in shown],
            "tone": [round(daily[d][3] / daily[d][2], 2) if daily[d][2] else None for d in shown],
            "articles_7d": last[0] if last else None, "tone_7d": tone_7d, "z_tone_7d": z, "base_tone_7d": base}


def zone_view(series: dict, zone_id: str, end: date, days: int, cat: dict | None = None,
              names: dict | None = None) -> dict | None:
    """The zone's press rows from the series' `press` sections, or None if the zone has no press block."""
    block = zone_blocks(cat).get(zone_id)
    if not block:
        return None
    sdays = series.get("days") or {}
    dates = sorted(date.fromisoformat(d) for d, v in sdays.items() if "press" in v and date.fromisoformat(d) <= end)
    names = names if names is not None else fips_names()
    out = {"about": [{"cc": s, "name": names.get(s, s)} for s in block.get("about") or []],
           "days": [], "complete": [], "rows": [], "method": method()}
    if not dates:
        return out
    complete = {d for d in dates if not sdays[d.isoformat()]["press"].get("partial")}
    shown = [d for d in dates if d > dates[-1] - timedelta(days=days)]
    out["days"] = [d.isoformat() for d in shown]
    out["complete"] = [d in complete for d in shown]
    out["end"] = dates[-1].isoformat()
    zero = [0, 0.0, 0, 0.0]
    for o, s, role in zone_rows(block):
        key = f"{o}>{s}"
        daily = {d: (sdays[d.isoformat()]["press"].get("t") or {}).get(key) or zero for d in dates}
        out["rows"].append({"outlet": o, "outlet_name": names.get(o, o), "about": s, "about_name": names.get(s, s),
                            "role": role, **row_view(daily, complete, dates, shown)})
    return out


@lru_cache(maxsize=1)
def fips_names() -> dict:
    p = CATALOG_DIR / "fips_countries.json"
    return json.loads(p.read_text(encoding="utf-8")).get("names", {}) if p.exists() else {}


def method() -> dict:
    return {
        "source": "GDELT Project GKG 2.1 (gdeltproject.org), English and translation streams",
        "unit": "articles whose most-mentioned country (GKG V2 enhanced locations, by mention) is the subject, by "
                "the outlet's country (GDELT's 2018 domain table, with fixes in catalog/press_outlets.json)",
        "tone": "mean per article of GDELT's document tone (dictionary score of the article text); it differs by "
                "language and outlet mix, so each outlet country is read only against its own past",
        "z": "7-day mean tone against the 7-day values of the four weeks before (base: their mean; those windows "
             "overlap, so this z runs large)",
        "cadence": f"daily when the median is at least {DAILY_MIN} articles a day over the last 28 complete days, "
                   f"weekly when the median 7-day total is at least {WEEKLY_MIN}, otherwise too thin to read",
        "limits": "GDELT carries no wire services, samples non-English press and geocodes place names (it can "
                  "misplace them); outlet countries come from a 2018 table; display only, not a warning",
    }
