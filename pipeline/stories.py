"""Group articles into stories: exact URL dedup, normalised-title match, then near-duplicate titles.

Near duplicates use MinHash LSH over title word sets (Jaccard >= 0.6), so syndicated copies that differ
by a site suffix or a word or two collapse into one story. Embedding-based grouping (Phase 2) will
replace this for cross-language matching; this pass is the cheap first cut and costs nothing.
"""
from __future__ import annotations

import hashlib
import random
import re
from collections import Counter, defaultdict
from urllib.parse import unquote, urlparse

MIN_TOKENS = 4  # shorter titles only merge on an exact match
THRESHOLD = 0.6
BANDS, ROWS = 16, 4
NUM_PERM = BANDS * ROWS
_P = (1 << 61) - 1
_rng = random.Random(1729)
_PARAMS = [(_rng.randrange(1, _P), _rng.randrange(0, _P)) for _ in range(NUM_PERM)]

_SEP = re.compile(r"\s+[-|–—:]{1,2}\s+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)
_STOP = set(
    "a an the and or of to in on at for from by with as is are was were be been it its this that "
    "after over into amid says said new will has have had not but than".split()
)


def normalize_title(title: str) -> str:
    """Lower-case, drop a trailing site name ('... - Reuters', '... | BBC News'), strip punctuation."""
    t = title.strip().lower()
    parts = _SEP.split(t)
    if len(parts) > 1 and len(parts[-1].split()) <= 4:
        t = " ".join(parts[:-1])
    return " ".join(_NON_WORD.sub(" ", t).split())


def title_from_url(url: str) -> str:
    """Readable words from the URL slug, used when GDELT has no page title."""
    path = unquote(urlparse(url).path)
    for seg in reversed([s for s in path.split("/") if s]):
        seg = re.sub(r"\.(s?html?|php|aspx?)$", "", seg, flags=re.I)
        words = [w for w in re.split(r"[-_.]+", seg) if w and not w.isdigit() and not (len(w) >= 6 and any(c.isdigit() for c in w))]
        if len(words) >= 3:
            return " ".join(words)
    return ""


def tokens(norm: str) -> frozenset[str]:
    return frozenset(w for w in norm.split() if len(w) > 1 and w not in _STOP)


_token_cache: dict[str, list[int]] = {}


def _token_hashes(tok: str) -> list[int]:
    vals = _token_cache.get(tok)
    if vals is None:
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "little")
        vals = [(a * h + b) % _P for a, b in _PARAMS]
        _token_cache[tok] = vals
    return vals


def signature(toks: frozenset[str]) -> list[int]:
    return [min(col) for col in zip(*(_token_hashes(t) for t in toks))]


def jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        ri, rj = self.find(i), self.find(j)
        if ri != rj:
            self.parent[rj] = ri


def group_titles(norms: list[str]) -> list[int]:
    """Story id for each normalised title. Equal titles share an id; near duplicates are merged."""
    uniq: dict[str, int] = {}
    for n in norms:
        uniq.setdefault(n, len(uniq))
    reps = list(uniq)
    toks = [tokens(r) for r in reps]
    uf = _UnionFind(len(reps))
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, tk in enumerate(toks):
        if len(tk) < MIN_TOKENS:
            continue
        sig = signature(tk)
        for b in range(BANDS):
            buckets[(b, tuple(sig[b * ROWS:(b + 1) * ROWS]))].append(i)
    seen: set[tuple[int, int]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        # Large buckets are compared against their first member only, to stay near-linear.
        pairs = ((members[0], m) for m in members[1:]) if len(members) > 40 else (
            (members[x], members[y]) for x in range(len(members)) for y in range(x + 1, len(members)))
        for i, j in pairs:
            if (i, j) in seen:
                continue
            seen.add((i, j))
            if jaccard(toks[i], toks[j]) >= THRESHOLD:
                uf.union(i, j)
    root_of = [uf.find(i) for i in range(len(reps))]
    return [root_of[uniq[n]] for n in norms]


def _domain(a: dict) -> str:
    return a.get("domain") or urlparse(a["url"]).netloc.lower().removeprefix("www.")


def build_stories(articles: list[dict]) -> list[dict]:
    """Group article dicts (url, title, published, lang; domain or source) into story dicts, largest first.

    Each story carries a stable id (hash of its normalised title), its article, outlet and language counts,
    and counts by source group (western_wire, russian_state...) where the articles carry one.
    Articles without a usable title or slug stay as single-article stories.
    """
    by_url: dict[str, dict] = {}
    for a in articles:
        by_url.setdefault(a["url"], a)
    arts = list(by_url.values())
    norms = []
    for a in arts:
        n = normalize_title(a.get("title") or "") or normalize_title(title_from_url(a["url"]))
        norms.append(n or f"__url__ {a['url']}")
    ids = group_titles(norms)
    groups: dict[int, list[dict]] = defaultdict(list)
    norm_of: dict[int, str] = {}
    for sid, a, n in zip(ids, arts, norms):
        groups[sid].append(a)
        norm_of.setdefault(sid, n)
    stories = []
    for sid, members in groups.items():
        members.sort(key=lambda a: a.get("published") or a.get("fetched") or "")
        first = members[0]
        by_group = Counter(a["group"] for a in members if a.get("group"))
        stories.append({
            "story_id": hashlib.sha1(norm_of[sid].encode("utf-8")).hexdigest()[:16],
            "title": first.get("title") or title_from_url(first["url"]),
            "first_seen": first.get("published") or first.get("fetched"),
            "articles": len(members),
            "outlets": len({_domain(a) for a in members}),
            "languages": sorted({a.get("lang", "eng") for a in members}),
            "groups": dict(by_group),
            "sample_urls": [a["url"] for a in members[:5]],
            "killed_articles": sum(1 for a in members if (a.get("killed") or 0) > 0),
            "wounded_articles": sum(1 for a in members if (a.get("wounded") or 0) > 0),
        })
    stories.sort(key=lambda s: (-s["articles"], s["first_seen"] or ""))
    return stories
