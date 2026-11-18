"""Prepare web/ for deploy: the public sources list, the blocklist, the FIPS-to-ISO country codes and the "Updated"
date. Run before `firebase deploy`.

    python -I scripts/build_web.py

Each source gets `read`, how Watchfloor reads it (shown on the Sources page). Sources not read at all (dropped) are
left out of the list.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEWS_SEARCH = "https://news.google.com/rss/search"
cat = json.loads((ROOT / "catalog" / "sources.json").read_text(encoding="utf-8"))
blocked = json.loads((ROOT / "catalog" / "blocklist.json").read_text(encoding="utf-8"))


def read(s: dict) -> str:
    if s.get("format") == "telegram":
        return "Telegram channel"
    if (s.get("url") or "").startswith(NEWS_SEARCH):
        return "Google News search" if s["group"] == "search" else "Google News site search"
    if s.get("rss_status") == "active":
        return "News feed"
    if s.get("rss_status") == "candidate":
        return "Feed being retried"
    return "GDELT only"


keep = ("name", "group", "format", "rss_status", "lang")
sources = [{**{k: s[k] for k in keep if k in s}, "read": read(s)} for s in cat["sources"] if s.get("rss_status") != "dropped"]
sources.sort(key=lambda s: (s["group"], s["name"].lower()))
left_out = ([{"what": d["domain"], "why": d["reason"]} for d in blocked["gdelt_domains"]]
            + [{"what": None, "why": p["reason"]} for p in blocked["gdelt_url_patterns"]]
            + [{"what": f"{p['publisher']} (in Google News results)", "why": p["reason"]} for p in blocked["search_publishers"]])
out = ROOT / "web" / "data"
out.mkdir(parents=True, exist_ok=True)
(out / "sources.json").write_text(json.dumps({"groups": cat["groups"], "sources": sources, "left_out": left_out,
                                              "catalog_version": cat["catalog_version"]}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
# Zones list their countries in GDELT's FIPS codes; "Elsewhere today" (tic-related.js) asks COP in ISO codes.
fips = json.loads((ROOT / "catalog" / "fips_iso.json").read_text(encoding="utf-8"))["codes"]
(out / "fips_iso.json").write_text(json.dumps({k: v["iso"] for k, v in sorted(fips.items()) if v.get("iso")},
                                              separators=(",", ":")), encoding="utf-8")
(ROOT / "web" / "build.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}),
                                         encoding="utf-8")
print(f"web/data/sources.json: {len(sources)} sources, {len(left_out)} left-out entries; web/data/fips_iso.json and "
      "web/build.json written")
