"""Write catalog/fips_iso.json: GDELT's FIPS 10-4 country codes -> ISO 3166-1 alpha-2, with a label point.

    python -I scripts/build_fips_iso.py <ne_50m_admin_0_countries.geojson>

GDELT codes countries in FIPS 10-4; the doctrine kit's feed contract (tic-feed/2) needs ISO alpha-2. Natural Earth
1:50m admin-0 (public domain) carries FIPS_10, ISO_A2_EH and a label point (LABEL_Y, LABEL_X) placed inside each
country. Codes Natural Earth leaves out or marks -99 are mapped by hand below from the FIPS 10-4 and ISO 3166-1
lists. Codes with no ISO country (the Spratly Islands, the dissolved Netherlands Antilles) map to null.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "catalog" / "fips_iso.json"

HAND = {  # FIPS 10-4 -> ISO 3166-1 alpha-2 where Natural Earth's FIPS_10 is missing or ambiguous
    "BQ": "UM", "BV": "BV", "EU": "TF", "FG": "GF", "GI": "GI", "GP": "GP", "GZ": "PS", "HQ": "UM", "IS": "IL",
    "JN": "SJ", "JQ": "UM", "KT": "CX", "LQ": "UM", "MB": "MQ", "MF": "YT", "NO": "NO", "OD": "SS", "RE": "RE",
    "SV": "SJ", "TL": "TK", "WE": "PS", "WQ": "UM",
    "PG": None,  # Spratly Islands: disputed, no ISO code
    "NT": None,  # Netherlands Antilles: dissolved 2010 (now CW, SX, BQ)
}
HAND_POINT = {  # [lat, lon] near the middle of each, so Gaza and the West Bank do not share the PS label point
    "GZ": [31.42, 34.38], "WE": [31.95, 35.25],
}


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    ne = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    by_fips, label = {}, {}
    for f in ne["features"]:
        p = f["properties"]
        iso = p.get("ISO_A2_EH") if p.get("ISO_A2_EH") not in (None, "-99") else p.get("ISO_A2")
        if not iso or iso == "-99":
            continue
        if p.get("LABEL_Y") is not None and iso not in label:
            label[iso] = [round(p["LABEL_Y"], 3), round(p["LABEL_X"], 3)]
        fips = p.get("FIPS_10")
        if fips and fips != "-99":
            by_fips.setdefault(fips, set()).add(iso)
    names = json.loads((ROOT / "catalog" / "fips_countries.json").read_text(encoding="utf-8"))["names"]
    codes, unmapped = {}, []
    for fips in sorted(names):
        if fips in HAND:
            iso = HAND[fips]
        elif len(by_fips.get(fips, ())) == 1:
            iso = next(iter(by_fips[fips]))
        else:
            unmapped.append(fips)
            continue
        point = HAND_POINT.get(fips) or (label.get(iso) if iso else None)
        codes[fips] = {"iso": iso, "name": names[fips], "point": point}
    if unmapped:
        print("no ISO code for:", ", ".join(f"{c} ({names[c]})" for c in unmapped))
        return 1
    doc = {"source": "Natural Earth 1:50m admin-0 (public domain): FIPS_10, ISO_A2_EH and LABEL_Y/LABEL_X; "
                     "hand-mapped codes in scripts/build_fips_iso.py",
           "point": "[lat, lon] label point inside the ISO country; Gaza and the West Bank are placed by hand",
           "codes": codes}
    OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {OUT}: {len(codes)} codes, {sum(1 for c in codes.values() if c['iso'] is None)} with no ISO country")
    return 0


if __name__ == "__main__":
    sys.exit(main())
