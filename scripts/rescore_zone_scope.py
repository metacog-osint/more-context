"""Re-score stored days' zone violence after a zone's violence countries change (catalog/entities.json). Free.

Zone violence (pipeline/countries.py) counts distinct articles with a violent event placed inside the zone's
violence scope (`violence.countries`, else `countries`) whose headline names the zone. Stored days keep the counts
of the scope they were built with; violent.jsonl keeps only zone and listed countries, so a country added to a scope
has no stored events to re-count. This script re-downloads GDELT Events (free, data.gdeltproject.org; nothing read
from the bucket for it), keeps each placed violent event's id, country, ADM1 and link, and re-counts the zones named
with --zones, oldest first, then re-scores each one's `named_score` (option B, `pred-1`) against the re-counted days
before it; a zone with `violence.members` also gets its `members` (each scored the same way) and `spikes`. Nothing
else in countries.json changes. First use: 11_Iran_Red_Sea gains the Gulf states that host US
forces and Iraq (charter answer, 18 Nov 2026).

    python -I scripts/rescore_zone_scope.py --start 2026-07-29 --end 2026-11-17 --root <dir> --cache <dir> --download --fetch
    python -I scripts/rescore_zone_scope.py ... --zones 11_Iran_Red_Sea --check-scope IR,YM
    python -I scripts/rescore_zone_scope.py ... --zones 11_Iran_Red_Sea
    python -I scripts/rescore_zone_scope.py ... --zones 11_Iran_Red_Sea --write

--download fills --cache with one file per day (`YYYY-MM-DD.json`, skipped when present). --fetch downloads each
day's countries.json (Class B reads) into --root with its generation in --root/manifest.json. Start at the first
stored day (29 Jul 2026): a zone's score reads the days before it.
--check-scope re-counts with the OLD scope (comma-separated FIPS codes) and must reproduce every stored count and
score of those zones, so every later difference comes from the scope. Days whose files GDELT and the cloud saw
differently show up here.
A dry run (no --check-scope, no --write) works on a copy in <root>-dry and writes <root>-dry/scope-report.json.
--write re-scores --root itself and uploads the changed countries.json files (gzip), each only if its generation
still matches the manifest (HTTP 412: re-fetch that day). Re-scored files carry `rescored_scope`; earlier stamps
are kept. violent.jsonl is left as built, so the map shows the added countries' events only from the first build
after the catalog change is deployed.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import countries, events, measures  # noqa: E402
from pipeline.relevance import TermMatcher  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402
from scripts.rescore_terms import BUCKET, _token, day_key, upload  # noqa: E402

STREAMS = ("english", "translation")
KEEP = ("id", "cc", "adm1", "url")


def slots(day: date) -> list[str]:
    t = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [(t + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(96)]


def fetch_slot(stamp: str) -> list[dict]:
    """The slot's records, reduced to what zone violence reads."""
    out = []
    for stream in STREAMS:
        data = None
        for attempt in range(3):
            try:
                data = events.download(stamp, stream)
                break
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(2 + attempt * 3)
        if data is None:
            continue
        rec = events.record(events.parse_zip(data), stamp, stream)
        out.append({"stamp": stamp, "stream": stream,
                    "violent": [{k: v.get(k) for k in KEEP} for v in rec["violent"]]})
    return out


def download(cache: Path, days: list[date], workers: int) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for d in days:
        p = cache / f"{d.isoformat()}.json"
        if p.exists():
            continue
        t0 = time.time()
        with ThreadPoolExecutor(workers) as ex:
            recs = [r for rs in ex.map(fetch_slot, slots(d)) for r in rs]
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(recs), encoding="utf-8")
        tmp.replace(p)
        print(f"downloaded {d}: {len(recs)} files, {time.time() - t0:.0f} s", flush=True)


def fetch(root: Path, days: list[date]) -> None:
    """Each day's countries.json into `root`, with its generation in manifest.json."""
    mpath = root / "manifest.json"
    tok, manifest = _token(), (json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {})
    for d in days:
        key = day_key(d, "countries.json")
        url = f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/{urllib.parse.quote(key, safe='')}?alt=media"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"Authorization": "Bearer " + tok}),
                                        timeout=180) as r:
                body, gen = r.read(), r.headers.get("x-goog-generation")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        p = root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body)
        manifest[key] = gen
    mpath.write_text(json.dumps(manifest, indent=0), encoding="utf-8")
    print(f"fetched {len(days)} days", flush=True)


def rescore_days(sink, cache: Path, days: list[date], scopes: dict, matcher: TermMatcher,
                 stamp: bool, members: frozenset = frozenset()) -> tuple[list[dict], list[str]]:
    """Re-count and re-score the zones in `scopes` (and per member for the zones in `members`), oldest first,
    writing each day back so the next day's history reads it. Returns per-day results and the changed keys."""
    res, changed = [], []
    for d in days:
        key = day_key(d, "countries.json")
        c = sink.read_json(key)
        cp = cache / f"{d.isoformat()}.json"
        if not c or not cp.exists():
            res.append({"day": d, "missing": not c, "no_cache": not cp.exists()})
            continue
        recs = json.loads(cp.read_text(encoding="utf-8"))
        counts = countries.zone_violence(recs, matcher, scopes, members)
        new = copy.deepcopy(c)
        hist, complete = countries.history(sink, d) if not c.get("partial") else ({"zone_named": {}}, [])
        for zid, zv in counts.items():
            old = (c.get("zones") or {}).get(zid)
            if old is None:
                continue
            nz = new["zones"][zid]
            nz.update(zv)
            if "named_score" in old:
                countries.score_zone(zid, nz, hist, complete, d)
        if stamp and new != c:
            new["rescored_scope"] = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     "zones": {z: sorted(s[0]) for z, s in scopes.items()},
                                     **({"members": sorted(members & set(scopes))} if members & set(scopes) else {})}
        if new != c:
            sink.write_json(key, new)
            changed.append(key)
        res.append({"day": d, "partial": bool(c.get("partial")),
                    "old": {z: (c.get("zones") or {}).get(z) for z in scopes},
                    "new": {z: new["zones"].get(z) for z in scopes}})
    return res, changed


def diff(r: dict) -> list[str]:
    out = []
    for z, o in r["old"].items():
        n = r["new"][z]
        for k in sorted(set(o or {}) | set(n or {})):
            if (o or {}).get(k) != (n or {}).get(k):
                out.append(f"{z}.{k}: {(o or {}).get(k)} -> {(n or {}).get(k)}")
    return out


def report(res: list[dict]) -> dict:
    rows, zs = [], {}
    for r in res:
        if "old" not in r:
            continue
        for z in r["old"]:
            o, n = r["old"][z] or {}, r["new"][z] or {}
            oz, nz = (o.get("named_score") or {}).get("z"), (n.get("named_score") or {}).get("z")
            rows.append({"day": r["day"].isoformat(), "zone": z, "named_old": o.get("named"), "named_new": n.get("named"),
                         "articles_old": o.get("articles"), "articles_new": n.get("articles"), "z_old": oz, "z_new": nz})
            s = zs.setdefault(z, {"days": 0, "named_old": 0, "named_new": 0, "z2_old": 0, "z2_new": 0,
                                  "spike_days": 0, "spikes": {}})
            rows[-1]["spikes"] = n.get("spikes") or []
            s["spike_days"] += bool(rows[-1]["spikes"])
            for k in rows[-1]["spikes"]:
                s["spikes"][k] = s["spikes"].get(k, 0) + 1
            s["days"] += 1
            s["named_old"] += o.get("named") or 0
            s["named_new"] += n.get("named") or 0
            s["z2_old"] += oz is not None and oz >= 2
            s["z2_new"] += nz is not None and nz >= 2
    return {"zones": zs, "days": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--zones", default="", help="comma-separated zone ids to re-score")
    ap.add_argument("--download", action="store_true", help="fill --cache from GDELT first")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--fetch", action="store_true", help="download each day's countries.json from the bucket")
    ap.add_argument("--check-scope", default="", help="the old scope (FIPS codes); must reproduce the stored fields")
    ap.add_argument("--write", action="store_true", help="re-score --root and upload the changed files")
    a = ap.parse_args()
    days = [a.start + timedelta(days=i) for i in range((a.end - a.start).days + 1)]
    if a.download:
        download(a.cache, days, a.workers)
    if a.fetch:
        fetch(a.root, days)
    zones = [z for z in a.zones.split(",") if z]
    if not zones:
        return 0
    cat = countries.violence_scopes()
    matcher = TermMatcher()
    if a.check_scope:
        old = frozenset(a.check_scope.split(","))
        scopes = {z: (old, cat[z][1]) for z in zones}
        work = a.root.with_name(a.root.name + "-check")
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(a.root, work)
        res, _ = rescore_days(LocalSink(work), a.cache, days, scopes, matcher, stamp=False)  # stored days: no members
        bad = 0
        for r in res:
            if "old" not in r:
                print(r["day"], "skipped:", "no countries.json" if r.get("missing") else "no cache")
                continue
            for line in diff(r):
                print(r["day"], line)
                bad += 1
        print("check:", "PASS (every stored field reproduced)" if not bad else f"FAIL ({bad} fields differ)")
        return 0 if not bad else 1
    scopes = {z: cat[z] for z in zones}
    work = a.root if a.write else a.root.with_name(a.root.name + "-dry")
    if work != a.root:
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(a.root, work)
    res, changed = rescore_days(LocalSink(work), a.cache, days, scopes, matcher, stamp=True,
                                members=countries.member_zones() & set(zones))
    rep = report(res)
    (work / "scope-report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps(rep["zones"], indent=1))
    print(f"files changed: {len(changed)} (report: {work / 'scope-report.json'})")
    if a.write:
        upload(a.root, changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
