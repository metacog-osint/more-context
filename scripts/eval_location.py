"""Score "where + what" relevance rules on a labelled set (27 Oct 2026). Free: re-downloads the GDELT files the
set came from (no models, no BigQuery).

v4.3 puts an article in a zone when a zone place is named anywhere and a broad theme appears anywhere. These rules
add GDELT's per-mention data (V2 enhanced locations and themes, one entry per mention):
- where: the zone's mentions are at least as many as any single other country's (main location), or its share;
- what: how many times the zone's own themes are mentioned.
A mention counts for a zone when its country code is one of the zone's countries, or its place block matches the
zone's v4.3 place rule (that catches seas and features such as Scarborough Shoal).

    python -I scripts/eval_location.py                       # relevance_v1, prints the table
    python -I scripts/eval_location.py --json out.json       # also writes per-story features
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import gdelt, relevance  # noqa: E402
from pipeline.match import load_catalog  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SET = ROOT / "catalog" / "eval" / "relevance_v1.jsonl"
RAW = ROOT / "data" / "raw" / "matched-20261026163000-6h.jsonl"

# FIPS 10-4 codes, as GDELT uses them. Draft for scoring; adopted ones move into catalog/entities.json.
ZONE_CC = {
    "01_Ukraine_Conflict": {"UP"},
    "07_Russia_NATO": {"RS", "PL", "LH", "LG", "EN", "FI", "RO", "BO", "MD"},
    "02_Taiwan_Strait": {"TW"},
    "08_South_China_Sea": {"RP", "VM"},
    "03_Korea_Peninsula": {"KS", "KN"},
    "10_Israel_Gaza_Lebanon": {"IS", "GZ", "WE", "LE"},
    "11_Iran_Red_Sea": {"IR", "YM"},
    "06_India_Pakistan": {"IN", "PK"},
    "13_Sudan": {"SU"},
    "17_Horn_of_Africa": {"ET", "ER", "SO", "DJ"},
    "18_Ethiopia_Eritrea": {"ET", "ER"},
    "19_Somalia": {"SO", "DJ"},
    "12_Sahel_West_Africa": {"ML", "UV", "NG"},
    "14_DRC_Rwanda": {"CG", "RW"},
    "16_Myanmar": {"BM"},
    "05_Venezuela": {"VE"},
    "15_Cuba": {"CU"},
}
# The labelled set predates the Horn split; score its Horn stories with Horn's own rule.
HORN_V43 = {"loc": "Ethiopia|Eritrea|Somalia|Somaliland|Puntland|Mogadishu|Addis Ababa|Asmara|Tigray|Amhara|Djibouti",
            "themes": "MILITARY|KILL|ARMEDCONFLICT|TERROR|REBEL|PIRACY|BORDER|CEASEFIRE"}


def zone_rules() -> dict[str, dict]:
    cat = load_catalog()
    rules = {z["id"]: z["match_v43"] for z in cat["zones"]}
    rules["17_Horn_of_Africa"] = HORN_V43
    return rules


def features(v2_locs: str, v2_themes: str, eid: str, rule: dict) -> dict:
    loc_rx, theme_rx = re.compile(rule["loc"]), re.compile(rule["themes"])
    ccs = ZONE_CC.get(eid, set())
    zone, others, total = 0, Counter(), 0
    for block in filter(None, v2_locs.split(";")):
        p = block.split("#")
        if len(p) < 3:
            continue
        total += 1
        if p[2] in ccs or loc_rx.search(block):
            zone += 1
        elif p[2]:
            others[p[2]] += 1
    themes = sum(1 for t in filter(None, v2_themes.split(";")) if theme_rx.search(t.split(",")[0]))
    top_other = max(others.values(), default=0)
    return {"zone_mentions": zone, "loc_mentions": total, "top_other": top_other,
            "top_other_cc": others.most_common(1)[0][0] if others else None,
            "share": round(zone / total, 3) if total else 0.0, "theme_mentions": themes}


def load_features() -> dict[str, dict]:
    rows = [json.loads(x) for x in SET.read_text(encoding="utf-8").split("\n") if x.strip()]
    raw = {}
    for line in RAW.read_text(encoding="utf-8").split("\n"):
        if line.strip():
            r = json.loads(line)
            raw[r["url"]] = r
    want = {}  # record_id -> label row id
    files = set()
    for r in rows:
        a = raw.get(r["url"])
        if a:
            want[a["record_id"]] = r["id"]
            files.add((a["record_id"].split("-")[0], a["stream"]))
    rules = zone_rules()
    feats = {}
    for i, (stamp, stream) in enumerate(sorted(files)):
        data = gdelt.download(stamp, stream)
        if not data:
            continue
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            body = z.read(z.namelist()[0])
        for line in body.split(b"\n"):
            f = [gdelt._decode(x) for x in line.rstrip(b"\r").split(b"\t")]
            if len(f) < 11 or f[0] not in want:
                continue
            rid = want[f[0]]
            eid = rid.split(":")[0]
            if eid in rules:
                feats[rid] = features(f[10], f[8], eid, rules[eid])
        print(f"  file {i + 1}/{len(files)} {stamp} {stream}: {len(feats)} stories with features", file=sys.stderr)
    return feats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    args = ap.parse_args()
    rows, pop = relevance.load_set(SET)
    feats = load_features()
    rows = [r for r in rows if r["entity"] in ZONE_CC]  # topics are matched on URLs, not places
    w = relevance.weights(rows, pop)
    m = relevance.TermMatcher()

    def f(r):
        return feats.get(r["id"]) or {"zone_mentions": 0, "loc_mentions": 0, "top_other": 0, "share": 0.0, "theme_mentions": 0}

    def main_loc(r):
        x = f(r)
        return x["zone_mentions"] > 0 and x["zone_mentions"] >= x["top_other"]

    def terms(r):
        return m.hit(r["entity"], r["title"])

    methods = {
        "v43 (today)": lambda r: True,
        "headline terms (today's filter)": terms,
        "main location": main_loc,
        "zone share >= 40%": lambda r: f(r)["share"] >= 0.4,
        "main location + 2 theme mentions": lambda r: main_loc(r) and f(r)["theme_mentions"] >= 2,
        "main location OR headline terms": lambda r: main_loc(r) or terms(r),
        "main location AND headline terms": lambda r: main_loc(r) and terms(r),
        "headline terms OR (main + 2 themes)": lambda r: terms(r) or (main_loc(r) and f(r)["theme_mentions"] >= 2),
    }
    print(f"\n{len(rows)} zone stories ({sum(1 for r in rows if r['id'] in feats)} with GDELT mention data). "
          "Weighted to everything v4.3 matched in the 6 hours.\n")
    print(f"{'method':40} {'precision':>10} {'retention':>10} {'off removed':>12}   90% interval (precision)")
    results = {}
    for name, fn in methods.items():
        keep = [fn(r) for r in rows]
        s = relevance.score(rows, w, keep)
        b = relevance.bootstrap(rows, w, keep, iters=1000)
        st = s["overall"]["stories"]
        results[name] = s
        print(f"{name:40} {st['precision'] or 0:>10.0%} {st['retention'] or 0:>10.0%} {st['off_removed'] or 0:>12.0%}"
              f"   {b['stories'].get('precision', ['?', '?'])}")
    best = "headline terms OR (main + 2 themes)"
    print(f"\nPer zone, stories ({best} vs today's filter):")
    for eid in sorted(ZONE_CC):
        a = results[best]["entities"].get(eid)
        t = results["headline terms (today's filter)"]["entities"].get(eid)
        if a:
            print(f"  {eid:26} n={a['n']:>2}  precision {a['stories']['precision']} / {t['stories']['precision']}"
                  f"  retention {a['stories']['retention']} / {t['stories']['retention']}")
    if args.json:
        Path(args.json).write_text(json.dumps(feats, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
