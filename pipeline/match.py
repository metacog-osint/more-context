"""Zone and Watch Topic matching driven by catalog/entities.json.

`rules="match_v43"` reproduces CONTEXT v4.3 exactly: zones are first-match-wins on GKG V1 Locations
plus Themes; topics match the lower-cased article URL and may overlap a zone.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "entities.json"


def load_catalog(path: Path = CATALOG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rx(pattern: str | None):
    return re.compile(pattern) if pattern else None


class _ZoneRule:
    def __init__(self, zid: str, spec: dict):
        self.id = zid
        self.loc = _rx(spec["loc"])
        alt = spec.get("loc_alt") or {}
        self.alt_loc = _rx(alt.get("loc"))
        self.alt_not_loc = _rx(alt.get("not_loc"))
        self.themes = _rx(spec["themes"])
        self.not_themes = _rx(spec.get("not_themes"))

    def matches(self, locations: str, themes: str) -> bool:
        loc_ok = bool(self.loc.search(locations))
        if not loc_ok and self.alt_loc is not None:
            loc_ok = bool(self.alt_loc.search(locations)) and not (
                self.alt_not_loc and self.alt_not_loc.search(locations)
            )
        if not loc_ok or not self.themes.search(themes):
            return False
        return not (self.not_themes and self.not_themes.search(themes))


class _TopicRule:
    def __init__(self, tid: str, spec: dict):
        self.id = tid
        self.url = _rx(spec.get("url"))
        self.broad = _rx(spec.get("url_broad"))
        self.context = _rx(spec.get("url_context"))

    def matches(self, url_lower: str) -> bool:
        if self.url is not None and self.url.search(url_lower):
            return True
        return bool(self.broad and self.context and self.broad.search(url_lower) and self.context.search(url_lower))


class Matcher:
    def __init__(self, catalog: dict | None = None, rules: str = "match_v43"):
        catalog = catalog or load_catalog()
        self.zones = [_ZoneRule(z["id"], z[rules]) for z in catalog["zones"]]
        self.topics = [_TopicRule(t["id"], t[rules]) for t in catalog["topics"]]
        self.names = {e["id"]: e["name"] for e in catalog["zones"] + catalog["topics"]}

    def zone(self, locations: str, themes: str) -> str | None:
        for rule in self.zones:
            if rule.matches(locations, themes):
                return rule.id
        return None

    def topic(self, url: str) -> str | None:
        u = url.lower()
        for rule in self.topics:
            if rule.matches(u):
                return rule.id
        return None

    def labels(self, article) -> list[str]:
        """Every entity an article counts toward: at most one zone plus at most one topic."""
        out = []
        z = self.zone(article.locations, article.themes)
        if z:
            out.append(z)
        t = self.topic(article.url)
        if t:
            out.append(t)
        return out
