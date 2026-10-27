"""Prepare web/ for deploy: the public sources list and the "Updated" date. Run before `firebase deploy`.

    python -I scripts/build_web.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
cat = json.loads((ROOT / "catalog" / "sources.json").read_text(encoding="utf-8"))
keep = ("name", "group", "format", "rss_status", "lang")
sources = [{k: s[k] for k in keep if k in s} for s in cat["sources"] if s.get("rss_status") != "dropped"]
sources.sort(key=lambda s: (s["group"], s["name"].lower()))
out = ROOT / "web" / "data"
out.mkdir(parents=True, exist_ok=True)
(out / "sources.json").write_text(json.dumps({"groups": cat["groups"], "sources": sources}, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
(ROOT / "web" / "build.json").write_text(json.dumps({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}),
                                         encoding="utf-8")
print(f"web/data/sources.json: {len(sources)} sources; web/build.json written")
