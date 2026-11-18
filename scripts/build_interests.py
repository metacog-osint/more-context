"""Write doctrine/interests.json: what Watchfloor reads from the suite's other programs instead of collecting it again
(doctrine kit 0.4.1 tips; Tom, 1 Nov 2026). Run after changing a zone's countries, boxes or an interest below.

    python -I scripts/build_interests.py            # write
    python -I scripts/build_interests.py --check    # exit 1 if the file is out of date (tests run this)

Areas are the zones' countries from catalog/entities.json (a zone's violence countries where its `violence` block
sets `suite_area`: Iran & Red Sea, Tom 18 Nov 2026), in ISO alpha-2 (the feed contract's codes) through
catalog/fips_iso.json; each area is the zone's warning problem id (WF-WP-Z01 ...). Boxes add adjacent sea areas
[west, south, east, north] for items placed by geometry (such as NGA navigational warnings). Topics have no countries:
their interests are worldwide ("anywhere") and name the topic in `warning_problems`, which the zone page's
"From the suite" panel reads (pipeline/suite.py).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "doctrine" / "interests.json"

INTERESTS = [
    {"id": "WF-INT-1", "programs": ["cordon"],
     "about": "US embassy posture in a zone country (authorized or ordered departure, suspended operations): a "
              "diplomatic warning step that news counts do not show",
     "response_stage_prefix": ["state_post_posture:"], "fingerprint": ["measures.posture"]},
    {"id": "WF-INT-2", "programs": ["cordon"],
     "about": "State Department travel advisory at level 3 or 4 for a zone country; a level change is a change",
     "response_stage_prefix": ["state_travel_advisory:"],
     "where": [{"path": "measures.level", "op": "gte", "value": 3}], "fingerprint": ["measures.level"]},
    {"id": "WF-INT-3", "programs": ["cordon"],
     "about": "EASA conflict-zone bulletin in force over a zone country's airspace",
     "response_stage_prefix": ["easa_czib:"]},
    {"id": "WF-INT-4", "programs": ["cordon"], "anywhere": True,
     "about": "NGA navigational warnings on military activity, mines, launches or restricted areas, placed in a zone "
              "when their geometry falls inside a zone country or maritime theatre box",
     "where": [{"path": "measures.category", "op": "in", "value": ["military", "mines", "launch", "restricted_area"]}]},
    {"id": "WF-INT-5", "programs": ["cordon"], "anywhere": True, "warning_problems": ["WF-WP-T3"],
     "about": "NGA navigational warnings on cables, pipelines and underwater operations",
     "where": [{"path": "measures.category", "op": "in", "value": ["cable_pipeline", "underwater_ops"]}]},
    {"id": "WF-INT-6", "programs": ["noisefloor"], "anywhere": True, "tiers": ["anomaly"],
     "warning_problems": ["WF-WP-T4"],
     "about": "GPS interference areas Noisefloor flags as anomalies, worldwide; shown on a zone too when inside it"},
    {"id": "WF-INT-7", "programs": ["elements"],
     "about": "NASA FIRMS fire and heat detections in a zone country (strikes on energy sites, burning villages). "
              "Daily counts only, until Elements marks anomalies against its own baseline",
     "where": [{"path": "measures.detections", "op": "gte", "value": 1}]},
    {"id": "WF-INT-8", "programs": ["elements"], "tiers": ["anomaly", "warning"],
     "about": "Natural-hazard anomalies in a zone country (GDACS, USGS, Copernicus EMS), which change the conflict's "
              "conditions and its coverage"},
    {"id": "WF-INT-9", "programs": ["vigil"], "tiers": ["anomaly", "warning"],
     "about": "Cyber anomalies placed in a zone country"},
    {"id": "WF-INT-10", "programs": ["verdict"],
     "about": "Scheduled, resolvable events for a zone country (bulletin expiries, rule dates) from Verdict's calendar"},
    {"id": "WF-INT-11", "programs": ["cordon"], "anywhere": True, "warning_problems": ["WF-WP-T4"],
     "about": "NGA navigational warnings about GNSS trouble, worldwide",
     "where": [{"path": "measures.category", "op": "eq", "value": "gnss"}]},
]

# Maritime and adjacent-water boxes [west, south, east, north] for zones where navigational warnings, jamming or
# offshore events happen at sea outside any land polygon.
BOXES = {
    "WF-WP-Z01": [27.5, 43.0, 40.0, 47.5],                                       # Black Sea and Sea of Azov
    "WF-WP-Z02": [117.0, 21.0, 123.5, 26.5],                                     # Taiwan Strait and approaches
    "WF-WP-Z03": [123.5, 33.0, 132.5, 43.0],                                     # Yellow Sea and East Sea around Korea
    "WF-WP-Z05": [-73.5, 8.5, -58.0, 13.5],                                      # Venezuelan Caribbean and Essequibo coast
    "WF-WP-Z06": [66.0, 22.0, 78.0, 36.0],                                       # Northern Arabian Sea and Kashmir/LoC
    "WF-WP-Z07": [[10.0, 53.5, 30.5, 66.0], [15.0, 68.0, 45.0, 76.0]],           # Baltic Sea and Barents Sea
    "WF-WP-Z08": [105.0, 4.0, 121.0, 21.0],                                      # South China Sea
    "WF-WP-Z10": [33.5, 31.0, 36.0, 34.7],                                       # Eastern Mediterranean Levant coast
    "WF-WP-Z11": [[32.0, 11.0, 51.5, 30.0], [47.5, 23.5, 60.0, 30.5]],           # Red Sea, Gulf of Aden, Persian Gulf, Hormuz
    "WF-WP-Z15": [-85.5, 19.5, -74.0, 24.5],                                     # Cuban waters and Florida Straits
    "WF-WP-Z19": [41.0, -2.0, 54.0, 13.5],                                       # Gulf of Aden and Somali coast
}


def areas() -> dict[str, list[str]]:
    zones = json.loads((ROOT / "catalog" / "entities.json").read_text(encoding="utf-8"))["zones"]
    codes = json.loads((ROOT / "catalog" / "fips_iso.json").read_text(encoding="utf-8"))["codes"]
    out = {}
    for z in zones:
        v = z.get("violence") or {}
        ccs = v["countries"] if v.get("suite_area") else z.get("countries", [])
        iso = sorted({codes[c]["iso"] for c in ccs if codes.get(c, {}).get("iso")})
        if iso:
            out[f"WF-WP-Z{z['id'][:2]}"] = iso
    return dict(sorted(out.items()))


def build() -> str:
    a = areas()
    doc = {"program": "watchfloor",
           "note": "Written by scripts/build_interests.py; edit the script, not this file. What Watchfloor reads from "
                   "the suite's other programs instead of collecting it again (doctrine kit tips.py). Areas are the "
                   "zones' countries in ISO alpha-2, keyed by each zone's warning problem; boxes add adjacent sea "
                   "areas [west, south, east, north] for items placed by geometry; warning_problems names the "
                   "topics an interest serves, since topics have no countries.",
           "areas": a, "boxes": {k: v for k, v in sorted(BOXES.items()) if k in a}, "interests": INTERESTS}
    return json.dumps(doc, ensure_ascii=False, indent=1) + "\n"


def main() -> int:
    text = build()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current.replace("\r\n", "\n") != text:
            print("doctrine/interests.json is out of date: run python -I scripts/build_interests.py")
            return 1
        print("doctrine/interests.json is current")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(json.loads(text)['areas'])} areas, {len(INTERESTS)} interests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
