"""Re-score stored days with the calibrated z (docs/method/2026-11-16-z-calibration.md, proposal step 3). Free.

The z calibration (picked 16 Nov 2026; live from the 16 Nov build) changed the estimators, not the counts. Days
built before it keep the old z (option A: in-sample weekday means, population SD, read as normal) until re-scored:
- countries.json: each country's `urls_score` and `violent_score` become option C (`robust-1`, pipeline/zstats.robust_z,
  against that day's pooled weekday shape per metric), the Rising and Elevated lists are rebuilt from them, and each
  zone's violence `named_score` becomes option B (`pred-1`);
- summary.json: each entity's `attention` becomes option B, and its alarms follow.
Counts are untouched, except that Serbia's second code RB is folded into RI in the day being re-scored (the live
build has done that since 16 Nov 2026 and every history read folds it, so a day left unfolded would score Serbia's
own half against the doubled history). An article placed under both codes in one file counts twice, as on read.

    python -I scripts/rescore_z.py --start 2026-07-29 --end 2026-11-15 --root <dir> --fetch --check
    python -I scripts/rescore_z.py --start 2026-07-29 --end 2026-11-15 --root <dir>
    python -I scripts/rescore_z.py --start 2026-07-29 --end 2026-11-15 --root <dir> --write

--fetch downloads each day's summary.json and countries.json (Class B reads) into --root and records their
generations in --root/manifest.json. Start at the first stored day (29 Jul 2026): a country's 90-day median reads the
90 days of countries.json before it.
--check re-scores with the old estimator and must reproduce every stored field (scores, lists, alarms); with
--verify-new DAY it also re-scores DAY (built live with the calibrated z) with the new estimators and must reproduce
it. Run both first, so every difference is known to come from the estimator.
A dry run (no --check, no --write) re-scores a copy in <root>-dry and writes <root>-dry/zrescore-report.json:
Rising listings kept, dropped and added per metric, alarms, and z changes.
--write re-scores --root itself and uploads the changed files (gzip, as the bucket sink writes them), each only if its
generation still matches the manifest (HTTP 412: re-fetch that day). Re-scored files carry `rescored_z`; an earlier
`rescored` stamp (headline terms) is kept. Samples and violent.jsonl are left as built, so a listing the rescore adds
has no sample headlines or map events. Uses `gcloud auth print-access-token`; nothing is printed from it.
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median, pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import countries, daily, measures  # noqa: E402
from pipeline.events import METRICS, canon  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402
from scripts.rescore_terms import BUCKET, _token, day_key, upload  # noqa: E402

FILES = ("summary.json", "countries.json")
SCORED = countries.SCORED


# ---------------------------------------------------------------- the old estimator (option A), for --check

def legacy_attention(history: dict[date, float], day: date, count: float) -> dict | None:
    """measures.attention_anomaly as it was before the calibration (e35582f), statistics module and all."""
    start = day - timedelta(days=measures.BASELINE_DAYS)
    base = {d: c for d, c in history.items() if start <= d < day and c is not None}
    if len(base) < measures.MIN_BASELINE_DAYS:
        return None
    y = {d: math.log1p(c) for d, c in base.items()}
    level = mean(y.values())
    by_wd: dict[int, list[float]] = {}
    for d, v in y.items():
        by_wd.setdefault(d.weekday(), []).append(v)
    adjust = {wd: mean(vs) - level for wd, vs in by_wd.items() if len(vs) >= 2}
    resid = [v - level - adjust.get(d.weekday(), 0.0) for d, v in y.items()]
    sd = max(pstdev(resid), measures.SD_FLOOR)
    expected = level + adjust.get(day.weekday(), 0.0)
    z = (math.log1p(count) - expected) / sd
    return {"z": round(z, 2), "expected": round(math.expm1(expected), 1),
            "ratio": round(count / math.expm1(expected), 2) if math.expm1(expected) > 0 else None,
            "baseline_days": len(base), "weekday_adjusted": day.weekday() in adjust}


def legacy_score(hist: dict[date, int], complete: list[date], day: date, count: int) -> dict:
    """countries.score as it was before the calibration (e35582f)."""
    out: dict = {}
    start28 = day - timedelta(days=measures.BASELINE_DAYS)
    att = legacy_attention({d: hist.get(d, 0) for d in complete if d >= start28}, day, count)
    if att:
        out.update(z=att["z"], expected=att["expected"], ratio=att["ratio"])
    ref = [hist.get(d, 0) for d in complete if d >= day - timedelta(days=countries.REF_DAYS)]
    if len(ref) >= countries.MIN_REF_DAYS:
        med = median(ref)
        out.update(median90=med, ratio90=round(count / med, 2) if med > 0 else None)
    return out


def legacy_listed(scored: dict[str, dict], metric: str) -> tuple[list[str], list[str]]:
    """countries._listed before the calibration: no pass for an expectation of 1 or less."""
    rising, elevated = [], []
    known = countries.names()
    for cc, c in scored.items():
        s = c.get(f"{metric}_score") or {}
        if c.get(metric, 0) < countries.MIN_ARTICLES[metric] or (known and cc not in known):
            continue
        if (s.get("z") or 0) >= countries.RISING_Z and (s.get("ratio") or 0) >= countries.RISING_RATIO:
            rising.append(cc)
        elif (s.get("ratio90") or 0) >= countries.ELEVATED_RATIO:
            elevated.append(cc)
    rising.sort(key=lambda cc: -scored[cc][f"{metric}_score"]["z"])
    elevated.sort(key=lambda cc: -scored[cc][f"{metric}_score"]["ratio90"])
    return rising[:countries.MAX_LISTED], elevated[:countries.MAX_LISTED]


# ---------------------------------------------------------------- re-scoring

def country_history(sink, day: date, fold: bool) -> tuple[dict, list[date]]:
    """countries.history, with the RB fold optional: days stored before 16 Nov were scored without it."""
    if fold:
        return countries.history(sink, day)
    out: dict = {m: {} for m in SCORED}
    out["zone_named"] = {}
    complete = []
    for i in range(1, countries.REF_DAYS + 1):
        d = day - timedelta(days=i)
        s = sink.read_json(day_key(d, "countries.json"))
        if not s or s.get("partial"):
            continue
        complete.append(d)
        for cc, c in s["countries"].items():
            for m in SCORED:
                h = out[m].setdefault(cc, {})
                h[d] = h.get(d, 0) + c.get(m, 0)
        for zid, zv in (s.get("zones") or {}).items():
            out["zone_named"].setdefault(zid, {})[d] = zv.get("named", 0)
    return out, complete


def fold_day(c: dict) -> list[str]:
    """Fold codes counted under another (events.FOLD: RB into RI) in a stored day's countries; returns the codes."""
    folded = []
    for cc in [cc for cc in c["countries"] if canon(cc) != cc]:
        src, to = c["countries"].pop(cc), canon(cc)
        dst = c["countries"].get(to)
        if dst is None:
            c["countries"][to] = {**src, "name": countries.names().get(to, to)}
        else:
            for m in METRICS:
                if m in src:
                    dst[m] = dst.get(m, 0) + src[m]
        sm = (c.get("samples") or {}).pop(cc, None)
        if sm:
            have = c["samples"].setdefault(to, [])
            have.extend(u for u in sm if u not in have and len(have) < countries.SAMPLES_KEPT)
        folded.append(cc)
    return folded


def rescore_countries(sink, day: date, legacy: bool) -> tuple[dict | None, dict | None]:
    """(stored, re-scored) countries.json for `day`; re-scored is None for a missing or partial day."""
    c = sink.read_json(day_key(day, "countries.json"))
    if not c or c.get("partial"):
        return c, None
    new = copy.deepcopy(c)
    folded = [] if legacy else fold_day(new)
    hist, complete = country_history(sink, day, fold=not legacy)
    profs = {m: countries.profile(hist[m], complete, day) for m in SCORED}
    for cc, row in new["countries"].items():
        for m in SCORED:
            h = hist[m].get(cc, {})
            row[f"{m}_score"] = (legacy_score(h, complete, day, row.get(m, 0)) if legacy
                                 else countries.score(h, complete, day, row.get(m, 0), profs[m]))
    listed = legacy_listed if legacy else countries._listed
    new["lists"] = {m: dict(zip(("rising", "elevated"), listed(new["countries"], m))) for m in SCORED}
    for zid, zv in (new.get("zones") or {}).items():
        if "named_score" not in zv:
            continue
        zh = hist["zone_named"].get(zid, {})
        zc = [d for d in complete if d in zh]
        zv["named_score"] = (legacy_score(zh, zc, day, zv.get("named", 0)) if legacy
                             else countries.score(zh, zc, day, zv.get("named", 0)))
    if not legacy:
        new["rescored_z"] = {"countries": countries.Z_METHOD, "zones": measures.Z_METHOD, **({"folded": folded} if folded else {})}
    return c, new


def rescore_summary(sink, day: date, legacy: bool) -> tuple[dict | None, dict | None]:
    s = sink.read_json(day_key(day, "summary.json"))
    if not s or measures.is_partial(s):
        return s, None
    new = copy.deepcopy(s)
    hist = daily.history(sink, day)
    for eid, e in new.get("entities", {}).items():
        if e.get("filtered_stories") is None:  # built before the filter count existed: no attention then either
            continue
        h = hist.get(eid, {})
        e["attention"] = (legacy_attention(h, day, e["filtered_stories"]) if legacy
                          else measures.attention_anomaly(h, day, e["filtered_stories"]))
        e["alarms"] = measures.alarm_reasons(e)
    new["alarms"] = {eid: e["alarms"] for eid, e in new.get("entities", {}).items() if e.get("alarms")}
    if not legacy:
        new["rescored_z"] = {"entities": measures.Z_METHOD}
    return s, new


def _same(a: dict, b: dict) -> bool:
    strip = lambda x: {k: v for k, v in x.items() if k != "rescored_z"}  # noqa: E731
    return strip(a) == strip(b)


def diff_fields(old, new, path="") -> list[str]:
    """Paths where two JSON values differ (for --check output)."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for k in sorted(set(old) | set(new), key=str):
            if k == "rescored_z":
                continue
            out += diff_fields(old.get(k), new.get(k), f"{path}.{k}")
        return out
    return [] if old == new else [f"{path}: {json.dumps(old)} -> {json.dumps(new)}"]


def rescore_days(sink, days: list[date], legacy: bool, write: bool) -> tuple[list[dict], list[str]]:
    """Oldest first. Returns ([per-day {day, file, old, new}], [changed keys]); writes changed files when `write`."""
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, changed = [], []
    for d in days:
        for name, fn in (("countries.json", rescore_countries), ("summary.json", rescore_summary)):
            old, new = fn(sink, d, legacy)
            if new is None or _same(old, new):
                continue
            out.append({"day": d, "file": name, "old": old, "new": new})
            if write:
                new["rescored_z"]["at"] = stamp
                sink.write_json(day_key(d, name), new)
                changed.append(day_key(d, name))
    return out, changed


# ---------------------------------------------------------------- report

def report(results: list[dict]) -> dict:
    """Rising listings and alarms kept / dropped / added, and how the z moved."""
    lists = {m: Counter() for m in SCORED}
    detail = {m: {"dropped": [], "added": []} for m in SCORED}
    feed = {"old": 0, "new": 0, "days": 0}
    alarms = Counter()
    alarm_detail = {"dropped": [], "added": []}
    zdiff = {m: [] for m in (*SCORED, "attention", "named")}
    for r in results:
        d, old, new = r["day"].isoformat(), r["old"], r["new"]
        if r["file"] == "countries.json":
            for m in SCORED:
                o = set((old.get("lists") or {}).get(m, {}).get("rising", []))
                n = set(new["lists"][m]["rising"])
                lists[m].update(kept=len(o & n), dropped=len(o - n), added=len(n - o))
                for cc in sorted(o - n):
                    detail[m]["dropped"].append((d, cc, _z(old, cc, m), _z(new, cc, m)))
                for cc in sorted(n - o):
                    detail[m]["added"].append((d, cc, _z(old, cc, m), _z(new, cc, m), new["countries"][cc].get(m)))
                for cc, row in new["countries"].items():
                    zo, zn = _z(old, cc, m), _z(new, cc, m)
                    if zo is not None and zn is not None:
                        zdiff[m].append(zn - zo)
            ol, nl = old.get("lists") or {}, new["lists"]
            feed["old"] += sum(len(ol.get(m, {}).get(k, [])) for m, k in (("violent", "rising"), ("violent", "elevated"), ("urls", "rising")))
            feed["new"] += sum(len(nl[m][k]) for m, k in (("violent", "rising"), ("violent", "elevated"), ("urls", "rising")))
            feed["days"] += 1
            for zid, zv in (new.get("zones") or {}).items():
                zo = ((old.get("zones") or {}).get(zid, {}).get("named_score") or {}).get("z")
                zn = (zv.get("named_score") or {}).get("z")
                if zo is not None and zn is not None:
                    zdiff["named"].append(zn - zo)
        else:
            o, n = set(old.get("alarms") or {}), set(new.get("alarms") or {})
            alarms.update(kept=len(o & n), dropped=len(o - n), added=len(n - o))
            alarm_detail["dropped"] += [(d, e, (old["entities"][e].get("attention") or {}).get("z"),
                                         (new["entities"][e].get("attention") or {}).get("z")) for e in sorted(o - n)]
            alarm_detail["added"] += [(d, e, (old["entities"][e].get("attention") or {}).get("z"),
                                       (new["entities"][e].get("attention") or {}).get("z")) for e in sorted(n - o)]
            for e, ent in new.get("entities", {}).items():
                zo = (old["entities"][e].get("attention") or {}).get("z")
                zn = (ent.get("attention") or {}).get("z")
                if zo is not None and zn is not None:
                    zdiff["attention"].append(zn - zo)
    zsum = {k: ({"n": len(v), "median_change": round(median(v), 2)} if v else {"n": 0}) for k, v in zdiff.items()}
    return {"rising": {m: dict(lists[m]) for m in SCORED}, "rising_detail": detail,
            "feed_country_items_per_day": {k: round(feed[k] / feed["days"], 1) for k in ("old", "new")} if feed["days"] else {},
            "alarms": dict(alarms), "alarm_detail": alarm_detail, "z_change": zsum}


def _z(c: dict, cc: str, m: str):
    return ((c.get("countries", {}).get(cc) or {}).get(f"{m}_score") or {}).get("z")


# ---------------------------------------------------------------- bucket

def fetch(root: Path, days: list[date]) -> None:
    mpath = root / "manifest.json"
    tok, manifest = _token(), (json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {})
    for d in days:
        for name in FILES:
            key = day_key(d, name)
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
        print("fetched", d, flush=True)
    mpath.write_text(json.dumps(manifest, indent=0), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--fetch", action="store_true", help="download the days from the bucket first")
    ap.add_argument("--check", action="store_true", help="re-score with the old estimator; must reproduce every field")
    ap.add_argument("--verify-new", type=date.fromisoformat, help="with --check: a day built live with the new z")
    ap.add_argument("--write", action="store_true", help="re-score --root and upload the changed files")
    a = ap.parse_args()
    days = [a.start + timedelta(days=i) for i in range((a.end - a.start).days + 1)]
    if a.fetch:
        fetch(a.root, days + ([a.verify_new] if a.verify_new and a.verify_new not in days else []))
    if a.check:
        res, _ = rescore_days(LocalSink(a.root), days, legacy=True, write=False)
        bad = 0
        for r in res:
            for line in diff_fields(r["old"], r["new"]):
                print(r["day"], r["file"], line)
                bad += 1
        if a.verify_new:
            res2, _ = rescore_days(LocalSink(a.root), [a.verify_new], legacy=False, write=False)
            for r in res2:
                for line in diff_fields(r["old"], r["new"]):
                    print(r["day"], r["file"], "(new)", line)
                    bad += 1
        print("check:", "PASS (every stored field reproduced)" if not bad else f"FAIL ({bad} fields differ)")
        return 0 if not bad else 1
    # Only --write re-scores --root itself; a dry run works on a copy, so --root keeps matching the bucket.
    work = a.root if a.write else a.root.with_name(a.root.name + "-dry")
    if work != a.root:
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(a.root, work)
    res, changed = rescore_days(LocalSink(work), days, legacy=False, write=True)
    rep = report(res)
    (work / "zrescore-report.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ("rising", "feed_country_items_per_day", "alarms", "z_change")}, indent=1))
    print(f"files changed: {len(changed)} (report: {work / 'zrescore-report.json'})")
    if a.write:
        upload(a.root, changed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
