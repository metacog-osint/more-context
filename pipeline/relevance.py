"""Relevance scoring: is a story that a rule assigned to a zone or topic actually about it?

The test set (catalog/eval/relevance_v*.jsonl) holds stories v4.3's rules matched, each labelled on, off
or unclear. Per entity the set has the largest stories ("top", all of them) plus a random draw from the
rest; the random draw is weighted up to the whole window using <set>.population.json, so the estimates
describe everything v4.3 matched, not just the sample.

Measures, for a method that keeps or drops each story:
- precision: share of kept weight that is on-topic (unclear stories left out of both sides)
- retention: share of on-topic weight kept. This is recall against v4.3's matches only; stories v4.3
  never matched are not in the set, so a method's gain on those is not measured here.
- off_removed: share of off-topic weight dropped
Both story-weighted (each story counts once) and article-weighted (a story counts by its article count,
the way v4.3's volumes count) are reported.
"""
from __future__ import annotations

import json
import random
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Callable, Iterable

from .stories import title_from_url

TERMS = Path(__file__).resolve().parent.parent / "catalog" / "title_terms.json"
_BOUNDARY_SCRIPTS = ("LATIN", "CYRILLIC", "GREEK", "DIGIT")
_QUOTES = str.maketrans({"’": "'", "ʼ": "'", "‘": "'", "׳": "'", "״": '"', "“": '"', "”": '"'})


def fold(text: str) -> str:
    """Case- and accent-insensitive form used on both terms and headlines."""
    t = unicodedata.normalize("NFKD", text.translate(_QUOTES))
    return "".join(ch for ch in t if not unicodedata.combining(ch)).casefold()


def _script(ch: str) -> str:
    try:
        return unicodedata.name(ch).split()[0]
    except ValueError:
        return ""


def term_pattern(term: str) -> str:
    """Regex for one catalog term. '*' allows any word ending; spaces and hyphens match either."""
    words = []
    for word in fold(term).split():
        parts = [re.escape(p) for p in word.replace("*", "\0*\0").split("\0") if p]
        rx = "".join(r"\w*" if p == r"\*" else p for p in parts)
        words.append(rx.replace(r"\-", r"[\s\-]?"))
    body = r"[\s\-]+".join(words)
    script = _script(term.strip()[0])
    if script in _BOUNDARY_SCRIPTS:
        return r"(?<!\w)" + body + ("" if term.endswith("*") else r"(?!\w)")
    if script == "HANGUL":
        return r"(?<!\w)" + body
    return body


class TermMatcher:
    def __init__(self, terms: dict[str, list[str]] | None = None):
        if terms is None:
            terms = json.loads(TERMS.read_text(encoding="utf-8"))["terms"]
        self.rx = {eid: re.compile("|".join(term_pattern(t) for t in ts)) for eid, ts in terms.items()}

    def hit(self, entity: str, text: str) -> bool:
        rx = self.rx.get(entity)
        return bool(rx and text and rx.search(fold(text)))


def load_set(path: str | Path) -> tuple[list[dict], dict]:
    path = Path(path)
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").split("\n") if l.strip()]
    pop = json.loads(path.with_name(path.stem + ".population.json").read_text(encoding="utf-8"))
    return rows, pop


def weights(rows: list[dict], population: dict) -> list[float]:
    """Story weight: 1 for a 'top' story; for a random one, the rest of the entity's stories / random draws."""
    tops, rands = defaultdict(int), defaultdict(int)
    for r in rows:
        (tops if r["draw"] == "top" else rands)[r["entity"]] += 1
    out = []
    for r in rows:
        if r["draw"] == "top":
            out.append(1.0)
        else:
            total = population["entities"][r["entity"]]["stories"]
            out.append(max(total - tops[r["entity"]], 0) / rands[r["entity"]])
    return out


def _tally(rows: Iterable[dict], w: Iterable[float], keep: Iterable[bool]) -> dict:
    t = {k: 0.0 for k in ("on", "off", "unclear", "on_kept", "off_kept", "on_a", "off_a", "on_kept_a", "off_kept_a")}
    for r, wt, k in zip(rows, w, keep):
        lab, a = r["label"], wt * r["articles"]
        if lab == "unclear":
            t["unclear"] += wt
            continue
        t[lab] += wt
        t[lab + "_a"] += a
        if k:
            t[lab + "_kept"] += wt
            t[lab + "_kept_a"] += a
    return t


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


def _measures(t: dict, suffix: str = "") -> dict:
    on, off = t["on" + suffix], t["off" + suffix]
    on_k, off_k = t["on_kept" + suffix], t["off_kept" + suffix]
    p, r = _ratio(on_k, on_k + off_k), _ratio(on_k, on)
    f1 = round(2 * p * r / (p + r), 3) if p and r else None
    return {"precision": p, "retention": r, "f1": f1, "off_removed": _ratio(off - off_k, off)}


def score(rows: list[dict], w: list[float], keep: list[bool]) -> dict:
    """Overall and per-entity measures for one method's keep/drop decisions."""
    out = {"overall": None, "entities": {}}
    by = defaultdict(list)
    for i, r in enumerate(rows):
        by[r["entity"]].append(i)
    for eid, idx in sorted(by.items()):
        t = _tally([rows[i] for i in idx], [w[i] for i in idx], [keep[i] for i in idx])
        out["entities"][eid] = {"n": len(idx), "stories": _measures(t), "articles": _measures(t, "_a"),
                                "unclear_share": _ratio(t["unclear"], t["on"] + t["off"] + t["unclear"])}
    t = _tally(rows, w, keep)
    out["overall"] = {"n": len(rows), "stories": _measures(t), "articles": _measures(t, "_a"),
                      "unclear_share": _ratio(t["unclear"], t["on"] + t["off"] + t["unclear"])}
    return out


def bootstrap(rows: list[dict], w: list[float], keep: list[bool], iters: int = 2000, seed: int = 7) -> dict:
    """90% intervals for the overall measures: resample stories within each (entity, draw) stratum."""
    strata = defaultdict(list)
    for i, r in enumerate(rows):
        strata[(r["entity"], r["draw"])].append(i)
    rng = random.Random(seed)
    samples = defaultdict(list)
    for _ in range(iters):
        idx = [rng.choice(ids) for ids in strata.values() for _ in ids]
        t = _tally([rows[i] for i in idx], [w[i] for i in idx], [keep[i] for i in idx])
        for unit, suffix in (("stories", ""), ("articles", "_a")):
            for k, v in _measures(t, suffix).items():
                if v is not None:
                    samples[(unit, k)].append(v)
    out = defaultdict(dict)
    for (unit, k), vals in samples.items():
        vals.sort()
        out[unit][k] = [vals[int(0.05 * (len(vals) - 1))], vals[int(0.95 * (len(vals) - 1))]]
    return dict(out)


def load_codings(path: str | Path) -> dict[str, dict]:
    """Model codings (code-stories output), keyed like set rows: '<entity>:<story_id>'."""
    out = {}
    for line in Path(path).read_text(encoding="utf-8").split("\n"):
        if line.strip():
            c = json.loads(line)
            out[f"{c['entity']}:{c['story_id']}"] = c
    return out


def methods(matcher: TermMatcher | None = None, codings: dict[str, dict] | None = None) -> dict[str, Callable[[dict], bool]]:
    """The free baselines, plus the model's relevance call when a codings file is given."""
    m = matcher or TermMatcher()
    out = {
        "v43_rules": lambda r: True,
        "title_terms": lambda r: m.hit(r["entity"], r["title"]),
        "title_or_url_terms": lambda r: m.hit(r["entity"], r["title"]) or m.hit(r["entity"], title_from_url(r["url"])),
    }
    if codings:
        def rel(r):
            return (codings.get(r["id"]) or {}).get("relevance")
        out["gemini_on"] = lambda r: rel(r) == "on"
        out["gemini_on_or_unclear"] = lambda r: rel(r) in ("on", "unclear")
        out["terms_or_gemini"] = lambda r: rel(r) == "on" or m.hit(r["entity"], r["title"])
    return out


def agreement(rows: list[dict], codings: dict[str, dict]) -> dict:
    """Unweighted label-vs-model counts, e.g. {'on>off': 5}; 'missing' for stories the model did not code."""
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        c = codings.get(r["id"])
        out[f"{r['label']}>{c['relevance'] if c else 'missing'}"] += 1
    return dict(sorted(out.items()))


def evaluate(path: str | Path, iters: int = 2000, codings_path: str | Path | None = None) -> dict:
    rows, pop = load_set(path)
    codings = load_codings(codings_path) if codings_path else None
    unlabelled = [r["id"] for r in rows if r.get("label") not in ("on", "off", "unclear")]
    if unlabelled:
        raise ValueError(f"{len(unlabelled)} stories without a label, e.g. {unlabelled[0]}")
    w = weights(rows, pop)
    report = {"set": Path(path).name, "population": pop["source"], "labels": {}, "methods": {}}
    for lab in ("on", "off", "unclear"):
        report["labels"][lab] = sum(1 for r in rows if r["label"] == lab)
    if codings:
        report["codings"] = Path(codings_path).name
        report["agreement"] = agreement(rows, codings)
    for name, fn in methods(codings=codings).items():
        keep = [fn(r) for r in rows]
        res = score(rows, w, keep)
        res["interval_90"] = bootstrap(rows, w, keep, iters) if iters else {}
        res["kept"] = sum(keep)
        report["methods"][name] = res
    return report
