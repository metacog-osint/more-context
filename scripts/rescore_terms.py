"""Re-score stored days after a change to catalog/title_terms.json, without rebuilding them. Free: no models.

The headline terms decide three stored things: each entity's `filtered_stories` / `filtered_articles` in a day's
summary.json (and from them its attention z and alarms, against the earlier days' filtered counts), and each zone's
`named` violence count in countries.json (with its `named_score`). Everything else in a day is untouched. Days are
re-scored oldest first in a local copy, so each day's baseline reads the re-scored days before it, as the daily
build would have.

    python -I scripts/rescore_terms.py --start 2026-07-29 --end 2026-11-14 --root data/rescore --fetch --check
    python -I scripts/rescore_terms.py --start 2026-07-29 --end 2026-11-14 --root data/rescore
    python -I scripts/rescore_terms.py --start 2026-07-29 --end 2026-11-14 --root data/rescore --write

Start at the first stored day (29 Jul 2026: countries.json from the events backfill; stories from 28 Sep). A zone's
`named_score` reads the 90 days of countries.json before it (`countries.history`), so a later start re-scores
against a short history and loses the 90-day median, and the days before it would keep their old counts.

--fetch downloads each day's summary.json, countries.json, stories.jsonl and violent.jsonl from the bucket into
--root (Class B reads; about 4.5 MB of gzip a day) and records each object's generation in --root/manifest.json.
--check re-scores with the terms alone (no exclusions) and must reproduce every stored field, scores included: run it
first, so a difference is known to come from the change, not from the method. Without --write nothing leaves --root, and --root
itself is left as fetched: the check re-scores a copy in <root>-check, a dry run one in <root>-dry.
--write uploads the changed summary.json and countries.json files (gzip, as the bucket sink writes them), each only
if its generation still matches the manifest (two Class A writes a changed day). Re-scored files carry
`rescored: {at, terms_version}`. Feed stories (kind "feed") are left as built. Uses `gcloud auth print-access-token`.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import countries, daily, measures  # noqa: E402
from pipeline.relevance import TERMS, TermMatcher  # noqa: E402
from pipeline.sinks import LocalSink, gz  # noqa: E402
from pipeline.stories import title_from_url  # noqa: E402

BUCKET = "more-context-484804"
FILES = ("summary.json", "countries.json", "stories.jsonl", "violent.jsonl")


def day_key(day: date, name: str) -> str:
    return f"stories/{day:%Y/%m/%d}/{name}"


def rescore_summary(sink, day: date, matcher: TermMatcher) -> list[tuple]:
    """Re-score one day's summary.json in `sink`; returns [(entity, field, old, new)] for what changed."""
    s = sink.read_json(day_key(day, "summary.json"))
    if not s:
        return []
    by_entity: dict[str, list[dict]] = defaultdict(list)
    for r in sink.read_lines(day_key(day, "stories.jsonl")):
        if r.get("kind") == "gdelt" and r.get("entity"):
            by_entity[r["entity"]].append(r)
    hist = daily.history(sink, day)
    partial = measures.is_partial(s)
    changes = []
    for eid, e in s.get("entities", {}).items():
        if e.get("filtered_stories") is None:  # built before the filter count existed: left as it is
            continue
        kept = [st for st in by_entity.get(eid, []) if matcher.hit(eid, st.get("title") or "")]
        new = {"filtered_stories": len(kept), "filtered_articles": sum(st.get("articles", 0) for st in kept)}
        new["attention"] = None if partial else measures.attention_anomaly(hist.get(eid, {}), day, len(kept))
        for f, v in new.items():
            if e.get(f) != v:
                changes.append((eid, f, e.get(f), v))
            e[f] = v
        e["alarms"] = [] if partial else measures.alarm_reasons(e)
    s["alarms"] = {} if partial else {eid: e["alarms"] for eid, e in s["entities"].items() if e.get("alarms")}
    if changes:
        s["rescored"] = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "terms_version": _version()}
        sink.write_json(day_key(day, "summary.json"), s)
    return changes


def rescore_countries(sink, day: date, matcher: TermMatcher, zones: set[str]) -> list[tuple]:
    """Re-score `named` (violent-event articles whose URL words name the zone) for `zones` in countries.json, from
    violent.jsonl, which keeps every event placed in a zone country. Russia-NATO's scope reaches NATO states that
    violent.jsonl need not keep, so only zones whose scope is their own countries are re-scored."""
    c = sink.read_json(day_key(day, "countries.json"))
    if not c or not c.get("zones"):
        return []
    scopes = countries.violence_scopes()
    zc = countries.zone_countries()
    urls: dict[str, set] = defaultdict(set)
    for v in sink.read_lines(day_key(day, "violent.jsonl")):
        for zid in zones:
            ccs, adm1 = scopes.get(zid, (frozenset(), frozenset()))
            if v.get("cc") in ccs or v.get("adm1") in adm1:
                urls[zid].add(v["url"])
    hist, complete = countries.history(sink, day) if not c.get("partial") else ({"zone_named": {}}, [])
    changes = []
    for zid in zones:
        zv = c["zones"].get(zid)
        ccs, adm1 = scopes.get(zid, (frozenset(), frozenset()))
        if zv is None or adm1 or not set(ccs) <= set(zc):  # violent.jsonl may not hold this zone's whole scope
            continue
        named = sum(1 for u in urls[zid] if matcher.hit(zid, title_from_url(u)))
        if zv.get("named") != named:
            changes.append((zid, "named", zv.get("named"), named))
        zv["named"] = named
        if not c.get("partial") and "named_score" in zv:
            zh = hist["zone_named"].get(zid, {})
            score = countries.score(zh, [d for d in complete if d in zh], day, named)
            if zv.get("named_score") != score:
                changes.append((zid, "named_score", zv.get("named_score"), score))
            zv["named_score"] = score
    if changes:
        c["rescored"] = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "terms_version": _version()}
        sink.write_json(day_key(day, "countries.json"), c)
    return changes


def _version() -> str:
    return json.loads(TERMS.read_text(encoding="utf-8")).get("version", "?")


# --- bucket I/O (JSON API with the gcloud user's token; nothing is printed) ---

def _token() -> str:
    gcloud = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    tok = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
    if not tok:
        sys.exit("gcloud auth print-access-token gave nothing: run gcloud auth login")
    return tok


def fetch(root: Path, days: list[date]) -> dict:
    """Download the days into `root`, adding their generations to manifest.json (days fetched earlier are kept)."""
    mpath = root / "manifest.json"
    tok, manifest = _token(), (json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {})
    for d in days:
        for name in FILES:
            key = day_key(d, name)
            url = (f"https://storage.googleapis.com/storage/v1/b/{BUCKET}/o/" + urllib.parse.quote(key, safe="")
                   + "?alt=media")
            req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:  # no Accept-Encoding: the server unzips
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
    return manifest


def upload(root: Path, keys: list[str]) -> None:
    tok = _token()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for key in keys:
        body = gz((root / key).read_bytes())
        q = urllib.parse.urlencode({"uploadType": "media", "name": key, "contentEncoding": "gzip",
                                    "ifGenerationMatch": manifest[key]})
        req = urllib.request.Request(f"https://storage.googleapis.com/upload/storage/v1/b/{BUCKET}/o?{q}", data=body,
                                     method="POST", headers={"Authorization": "Bearer " + tok,
                                                             "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                manifest[key] = json.loads(r.read())["generation"]
            print("wrote", key, flush=True)
        except urllib.error.HTTPError as e:
            print("NOT written", key, f"HTTP {e.code}", "(changed since fetch?)" if e.code == 412 else "", flush=True)
    (root / "manifest.json").write_text(json.dumps(manifest, indent=0), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--fetch", action="store_true", help="download the days from the bucket first")
    ap.add_argument("--check", action="store_true", help="re-score with no exclusions; must reproduce the stored counts")
    ap.add_argument("--write", action="store_true", help="upload changed summary.json and countries.json")
    a = ap.parse_args()
    days = [a.start + timedelta(days=i) for i in range((a.end - a.start).days + 1)]
    if a.fetch:
        fetch(a.root, days)
    # Only --write re-scores --root itself. A check or a dry run works on a throwaway copy, so --root keeps matching
    # the bucket: a dry run in place would leave nothing for a later --write to find, and it would upload nothing.
    work = a.root if a.write and not a.check else a.root.with_name(a.root.name + ("-check" if a.check else "-dry"))
    if work != a.root:
        shutil.rmtree(work, ignore_errors=True)
        shutil.copytree(a.root, work)
    terms = json.loads(TERMS.read_text(encoding="utf-8"))
    matcher = TermMatcher(terms["terms"], {} if a.check else terms.get("exclude", {}))
    changes, changed = rescore_days(LocalSink(work), days, matcher, set(terms.get("exclude", {})))
    counts = [c for c in changes if c[2] in ("filtered_stories", "named")]
    for d, eid, f, old, new in changes:
        if f == "attention":
            print(f"{d} {eid} attention z {(old or {}).get('z')} -> {(new or {}).get('z')}")
        elif f not in ("filtered_stories", "named") and a.check:
            print(f"{d} {eid} {f} {json.dumps(old)} -> {json.dumps(new)}")
    for d, eid, f, old, new in counts:
        print(f"{d} {eid} {f} {old} -> {new}")
    print(f"{len(counts)} count changes over {len(days)} days; files changed: {len(changed)}")
    if a.check:
        # Every field, not only the counts: on 15 Nov 2026 a check from 28 Sep reproduced every count but rewrote
        # each Sudan named_score without its 90-day median, because the days before 28 Sep were not in --root.
        ok = not changes
        print("check:", "PASS (every stored field reproduced)" if ok else
              f"FAIL ({len(changes)} fields differ; start at the first stored day?)")
        return 0 if ok else 1
    if a.write:
        upload(a.root, changed)
    return 0


def rescore_days(sink, days: list[date], matcher: TermMatcher, zones: set[str]) -> tuple[list[tuple], list[str]]:
    """Re-score `days` oldest first; returns ([(day, entity, field, old, new)], [changed file keys])."""
    changes, changed = [], []
    for d in days:
        cs, cc = rescore_summary(sink, d, matcher), rescore_countries(sink, d, matcher, zones)
        changed += [day_key(d, "summary.json")] * bool(cs) + [day_key(d, "countries.json")] * bool(cc)
        changes += [(d, *c) for c in cs + cc]
    return changes, changed


if __name__ == "__main__":
    raise SystemExit(main())
