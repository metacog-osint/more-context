"""A short id for what each zone or topic counts, so a reader can tell when a series changes meaning.

The id is a hash of the catalog fields that decide what is counted: countries, the violence scope, the match rules and
the profile used for embeddings and model prompts. Names, map points and notes are left out, so rewording a note does
not start a new series. `catalog/zone_scopes.json` records the ids for the current `catalog_version`; a test fails when
an id changes and the version has not, so a scope change cannot pass unversioned.

    python -m pipeline.zone_scope    rewrite catalog/zone_scopes.json (after bumping catalog_version)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "entities.json"
LOCK = ROOT / "catalog" / "zone_scopes.json"


def scope_id(zone: dict) -> str:
    violence = {k: v for k, v in (zone.get("violence") or {}).items() if k != "why"}
    fields = {"countries": zone.get("countries") or [], "violence": violence, "match_v43": zone.get("match_v43"),
              "profile": zone.get("profile")}
    text = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def scopes(catalog: dict) -> dict:
    return {z["id"]: scope_id(z) for z in [*catalog.get("zones", []), *catalog.get("topics", [])]}


def lock_body(catalog: dict) -> dict:
    return {"note": "Scope id of each zone and topic at this catalog_version. Written by pipeline/zone_scope.py.",
            "catalog_version": catalog["catalog_version"], "scopes": scopes(catalog)}


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    LOCK.write_text(json.dumps(lock_body(catalog), indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{LOCK.name}: {len(scopes(catalog))} scopes at {catalog['catalog_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
