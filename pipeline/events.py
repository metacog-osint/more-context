"""GDELT Events 2.0: what happened where, from the same 15-minute processing as the GKG (28 Oct 2026).

Why Events and not GKG for country-wide counts: an Events file is ~100 KB per stream per 15 minutes against
~20 MB for GKG (90 days: ~1.7 GB against ~173 GB), so every country can be counted, live and back in time, for
free. Each row is one event first seen in that window: actors, a CAMEO code, where it happened (ActionGeo, FIPS
10-4 country codes as in GKG) and the first article that reported it (SOURCEURL).

One file becomes one compact record:
- `countries`: per country, distinct articles (`urls`) with at least one event located there; of those, with a
  lead-paragraph event (`root`), with an event placed below country level (`place`), and with a violent event
  (`violent`); plus the event count (`ev`).
- `samples`: up to two article URLs per country (lead-paragraph events first), for headlines on the Rising list.
- `violent`: assault, fight and mass-violence events (CAMEO roots 18-20) placed below country level, for the map
  and the in-zone violence measure. GDELT's coding is noisy (28 Oct sample: a Seville traffic report and an
  Italian strike notice coded as fights), so consumers filter them further.
- `pairs` (since 15 Nov 2026): per directed pair of actor countries, articles and the kinds of events they carry
  (`pipeline/relations.py`), for the relations layer.
- `texts`, `vtexts` (since 18 Nov 2026): per country, the file's articles (all, and violent) counted by exact text
  key (`origins.text_key`, "" for links with no text), so the daily build can count independent origins beside the
  article counts (Tom, 18 Nov 2026: z stays on articles). About 1.4 KiB gzip a file.
Events dated more than two days before the file are references to the past ("a year ago...") and are skipped.

Since 30 Oct 2026 the records ride in the run's cycle file as rows with `"kind": "events"` first (`as_row`), so a
run makes one data write, not two. Older records stay in `events/YYYY/MM/DD/HHMMSS.json` (`{"files": [...]}`),
where `scripts/backfill_events.py` still writes; `countries.py` reads both.
"""
from __future__ import annotations

import io
import urllib.error
import zipfile
from datetime import datetime, timedelta

from . import gdelt, origins
from .relations import pair_table

FILE_NAMES = {"english": "{stamp}.export.CSV.zip", "translation": "{stamp}.translation.export.CSV.zip"}
FIELDS = 61
VIOLENT_ROOTS = frozenset({"18", "19", "20"})  # CAMEO: assault, fight, unconventional mass violence
COUNTRY_LEVEL = frozenset({"", "0", "1"})  # no location, or the country's centroid
MAX_AGE_DAYS = 2
SAMPLES_PER_COUNTRY = 2
METRICS = ("ev", "urls", "root", "place", "violent")
# How an Events row's line starts in a cycle file, so a reader can skip the article rows unparsed.
ROW_PREFIX = '{"kind": "events"'
# GDELT codes one country under two FIPS codes: Serbia is RI, but Belgrade is placed as "Belgrade, Serbia
# (general)" with ADM1 RB00 under RB, a code missing from GDELT's own country list (checked 16 Nov 2026: RB
# rivalled RI, 400 against 444 articles on 28 Oct). RB is counted as RI here and again on read
# (`countries.totals`, `countries.history`), so records and days stored before the fold count too.
FOLD = {"RB": "RI"}


def canon(cc: str) -> str:
    """The FIPS code a country is counted under."""
    return FOLD.get(cc, cc)


def as_row(rec: dict) -> dict:
    """A record as a cycle-file row; `kind` comes first so its line starts with ROW_PREFIX."""
    return {"kind": "events", **rec}

# Field positions in the Events 2.0 export.
ID, DAY, A1NAME, A2NAME, ROOT, CODE, BASE, ROOTCODE, QUAD = 0, 1, 6, 16, 25, 26, 27, 28, 29
NUM_SOURCES, NUM_ARTICLES = 32, 33
GTYPE, GNAME, GCC, GADM1, GLAT, GLON = 51, 52, 53, 54, 56, 57
ADDED, URL = 59, 60


def file_url(stamp: str, stream: str) -> str:
    return gdelt.BASE + FILE_NAMES[stream].format(stamp=stamp)


def download(stamp: str, stream: str) -> bytes | None:
    """Zipped bytes, or None when GDELT has no file for that slot (yet). Same CDN cache-busting as GKG."""
    import time
    try:
        return gdelt.fetch(f"{file_url(stamp, stream)}?mc={int(time.time() // 60)}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def parse_zip(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        body = z.read(z.namelist()[0])
    rows = []
    for line in body.split(b"\n"):
        f = line.rstrip(b"\r").split(b"\t")
        if len(f) >= FIELDS:
            rows.append([gdelt._decode(x) for x in f[:FIELDS]])
    return rows


def _num(s: str, cast=int):
    try:
        return cast(s)
    except ValueError:
        return None


def record(rows: list[list[str]], stamp: str, stream: str) -> dict:
    """One file's compact record (see the module docstring)."""
    oldest = (datetime.strptime(stamp[:8], "%Y%m%d") - timedelta(days=MAX_AGE_DAYS)).strftime("%Y%m%d")
    ev: dict[str, int] = {}
    sets: dict[str, dict[str, set]] = {m: {} for m in ("urls", "root", "place", "violent")}
    best: dict[str, dict[str, int]] = {}  # cc -> url -> sample score
    violent = []
    seen_violent = set()
    keys: dict[str, str] = {}
    for r in rows:
        cc = canon(r[GCC])
        if not cc or r[DAY] < oldest:
            continue
        url = r[URL]
        ev[cc] = ev.get(cc, 0) + 1
        sets["urls"].setdefault(cc, set()).add(url)
        is_root = r[ROOT] == "1"
        placed = r[GTYPE] not in COUNTRY_LEVEL
        if is_root:
            sets["root"].setdefault(cc, set()).add(url)
        if placed:
            sets["place"].setdefault(cc, set()).add(url)
        score = (2 if is_root else 0) + (1 if placed else 0)
        b = best.setdefault(cc, {})
        b[url] = max(b.get(url, -1), score)
        if r[ROOTCODE] in VIOLENT_ROOTS:
            sets["violent"].setdefault(cc, set()).add(url)
            if placed and r[ID] not in seen_violent:
                seen_violent.add(r[ID])
                violent.append({
                    "id": r[ID], "day": r[DAY], "code": r[CODE], "a1": r[A1NAME], "a2": r[A2NAME],
                    "place": r[GNAME], "cc": cc, "adm1": r[GADM1], "lat": _num(r[GLAT], float),
                    "lon": _num(r[GLON], float), "gtype": r[GTYPE], "root": is_root,
                    "sources": _num(r[NUM_SOURCES]), "articles": _num(r[NUM_ARTICLES]), "url": url,
                })
    countries = {}
    for cc, n in ev.items():
        countries[cc] = [n] + [len(sets[m].get(cc, ())) for m in ("urls", "root", "place", "violent")]
    texts, vtexts = {}, {}
    for out, m in ((texts, "urls"), (vtexts, "violent")):
        for cc, urls in sets[m].items():
            t = out[cc] = {}
            for u in urls:
                k = keys.get(u)
                if k is None:
                    k = keys[u] = origins.text_key(u)
                t[k] = t.get(k, 0) + 1
    samples = {cc: [u for u, _ in sorted(b.items(), key=lambda kv: -kv[1])[:SAMPLES_PER_COUNTRY]]
               for cc, b in best.items()}
    return {"stamp": stamp, "stream": stream, "rows": len(rows), "countries": countries,
            "samples": samples, "violent": violent, "pairs": pair_table(rows, stamp),
            "texts": texts, "vtexts": vtexts}


def country_names(rows: list[list[str]]) -> dict[str, str]:
    """FIPS code -> country name, from country-level locations (ActionGeo type 1)."""
    out: dict[str, dict[str, int]] = {}
    for r in rows:
        if r[GTYPE] == "1" and r[GCC] and r[GNAME]:
            c = out.setdefault(r[GCC], {})
            c[r[GNAME]] = c.get(r[GNAME], 0) + 1
    return {cc: max(names, key=names.get) for cc, names in out.items()}
