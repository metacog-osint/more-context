"""Zone-country violence items: how many of a listed zone country's violent-event articles pass the zone's headline
filter (headline terms on the article link's words, as zone violence `named` does).

python -I scripts/zcal/zone_filter.py <stories root with YYYY/MM/DD/violent.jsonl> <first day> <last day> <out.json>
Reads each day's violent.jsonl once, line by line; writes {day: {cc: [articles, named]}} for zone countries.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from pipeline.countries import zone_countries  # noqa: E402
from pipeline.relevance import TermMatcher  # noqa: E402
from pipeline.stories import title_from_url  # noqa: E402


def main(root: Path, first: date, last: date, out: Path) -> None:
    cat = json.loads((ROOT / "catalog/entities.json").read_text(encoding="utf-8"))
    zone_of = {cc: z["id"] for z in cat["zones"] for cc in z.get("countries", [])}  # as feed_v2: last zone wins
    zc = zone_countries()
    m = TermMatcher()
    res = {}
    d = first
    while d <= last:
        p = root / f"{d:%Y/%m/%d}/violent.jsonl"
        urls: dict[str, set] = {}
        if p.exists():
            with p.open(encoding="utf-8") as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    v = json.loads(line)
                    if v["cc"] in zc:
                        urls.setdefault(v["cc"], set()).add(v["url"])
        day = {}
        for cc, us in urls.items():
            z = zone_of[cc]
            named = sum(1 for u in us if m.hit(z, title_from_url(u)))
            named_any = sum(1 for u in us if any(m.hit(zz, title_from_url(u)) for zz in zc[cc]))
            day[cc] = [len(us), named, named_any]
        res[d.isoformat()] = day
        d += timedelta(days=1)
    out.write_text(json.dumps(res), encoding="utf-8")
    print("days", len(res), file=sys.stderr)


if __name__ == "__main__":
    main(Path(sys.argv[1]), date.fromisoformat(sys.argv[2]), date.fromisoformat(sys.argv[3]), Path(sys.argv[4]))
