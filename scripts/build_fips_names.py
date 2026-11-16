"""Write catalog/fips_countries.json (FIPS 10-4 code -> country name) from the names GDELT used for country-level
locations during an Events backfill (`events/names.json`, written by backfill_events.py). Free, local.

    python -I scripts/build_fips_names.py --root data/backfill/baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import events  # noqa: E402
# GDELT's names for a few codes are long or dated; shorter names read better in lists.
SHORT = {"CG": "DR Congo", "CF": "Republic of the Congo", "KN": "North Korea", "KS": "South Korea",
         "WE": "West Bank", "GZ": "Gaza Strip", "BM": "Myanmar", "OD": "South Sudan", "UK": "United Kingdom",
         "US": "United States", "RS": "Russia", "IR": "Iran", "SY": "Syria", "TW": "Taiwan", "VM": "Vietnam",
         "LA": "Laos", "TZ": "Tanzania", "BO": "Belarus", "MD": "Moldova", "TU": "Turkey"}
# Codes GDELT uses that the backfill never saw at country level, with GDELT's FIPS.country.txt names (16 Nov 2026).
# RB is not here: it is Serbia's second code and is counted as RI (pipeline/events.py FOLD).
EXTRA = {"PU": "Guinea-Bissau", "TP": "Sao Tome and Principe", "TK": "Turks and Caicos Islands",
         "SC": "Saint Kitts and Nevis"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    a = ap.parse_args()
    raw = json.loads((Path(a.root) / "events" / "names.json").read_text(encoding="utf-8"))
    best: dict[str, tuple[int, str]] = {}
    for key, n in raw.items():
        cc, name = key.split("|", 1)
        if len(cc) == 2 and cc.isalpha() and (cc not in best or n > best[cc][0]):
            best[cc] = (n, name)
    names = {cc: SHORT.get(cc, name) for cc, (_, name) in best.items() if cc not in events.FOLD}
    names = dict(sorted({**EXTRA, **names}.items()))
    out = {"source": f"Most common GDELT Events country-level ActionGeo name per FIPS code, backfill to {date.today()}",
           "names": names}
    (ROOT / "catalog" / "fips_countries.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(names), "countries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
