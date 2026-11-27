"""Independent origins: how many separate pieces of reporting stand behind a count (17-18 Nov 2026, a measurement).

Watchfloor's country counts are distinct articles (GDELT Events `urls`), and one syndicated story can move them: on
20 Oct 2026 one Rubio story ran on 131 Newsquest sites under one slug. An origin is one cluster of articles that
carry the same text, so a wire story and its copies count once:

- Text: the page title where there is one, else the words of the URL slug (`stories.title_from_url`); Events rows
  carry only the URL. Normalised and stop-worded as in `stories.py`.
- Same text (OSINT Swarm's rule): word overlap >= 80% (`|A & B| / min(|A|, |B|)`), on texts of at least
  MIN_TOKENS words; shorter texts join only an identical one.
- Group average (Europe Media Monitor's linkage): a text joins a cluster only when its mean overlap with the
  cluster's members (up to AVERAGE_OVER of them) is >= 80%, not just with one member, so chains do not form.
  Clustering is per language in effect, since texts in different languages share no words. Cross-language and
  across-day linking (EMM's "related clusters within 7 days") are not done here.
- An article with no usable text (numeric-id URLs, common on Arabic, Chinese and Persian sites) is its own origin,
  so origins err high and a flag that "rests on one or two origins" is a lower bound.
- Outlets: per cluster, distinct registrable domains, with aggregators (MSN, Yahoo, AOL, NewsBreak...) left out.
  Wires need no table: their copies share the text, so they are one cluster whatever the domain.

`scripts/origins_backtest.py` measures the clustering on raw GDELT files. The live pipeline (18 Nov 2026: z
stays on articles, origins shown beside them) uses the cheap form: each Events record keeps per country a count of
articles by exact text key (`text_key`), and the daily build counts distinct keys (`day_origins`).
"""
from __future__ import annotations

import base64
import hashlib
from collections import defaultdict
from urllib.parse import urlparse

from .stories import normalize_title, title_from_url, tokens

OVERLAP = 0.8
MIN_TOKENS = 4
AVERAGE_OVER = 8
# Pages that republish other outlets' copy: never an independent outlet.
AGGREGATORS = frozenset({
    "msn.com", "yahoo.com", "aol.com", "aol.co.uk", "newsbreak.com", "flipboard.com", "ground.news", "newsnow.co.uk",
    "headtopics.com", "inkl.com", "news.google.com", "bignewsnetwork.com", "newsr.in", "devdiscourse.com",
    "dailyhunt.in", "menafn.com", "zawya.com", "streetinsider.com", "marketscreener.com", "dnyuz.com",
})
_SECOND_LEVEL = frozenset({"co", "com", "org", "net", "gov", "ac", "edu", "or", "ne", "go", "gob", "nic", "mil"})


def domain(url: str) -> str:
    """Registrable domain: the last two labels, or three under a country's second level (bbc.co.uk)."""
    host = urlparse(url).netloc.lower().split(":")[0].removeprefix("www.")
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def text_tokens(url: str, title: str = "") -> frozenset[str]:
    return tokens(normalize_title(title) or normalize_title(title_from_url(url)))


def text_key(url: str, title: str = "") -> str:
    """A short key for the exact text (8 characters, 48 bits), or "" when the link has no usable text. Copies of a
    wire story share their slug, so they share a key; the daily build counts distinct keys (`day_origins`)."""
    tk = text_tokens(url, title)
    if not tk:
        return ""
    return base64.urlsafe_b64encode(hashlib.blake2b(" ".join(sorted(tk)).encode(), digest_size=6).digest()).decode()


def day_origins(per_file: list[dict[str, int]]) -> dict:
    """Origins from files' key counts ({key: distinct articles}, "" = articles with no text, each its own origin):
    exact text only, so near-copies with a changed word count twice and origins err high, as in `summarise`."""
    keys: dict[str, int] = defaultdict(int)
    for f in per_file:
        for k, n in f.items():
            keys[k] += n
    alone = keys.pop("", 0)
    articles = alone + sum(keys.values())
    return {"origins": alone + len(keys), "largest": max(keys.values(), default=1 if alone else 0),
            "articles": articles}


def overlap(a: frozenset[str], b: frozenset[str]) -> float:
    return len(a & b) / min(len(a), len(b)) if a and b else 0.0


def cluster(items: list[tuple[str, frozenset[str]]]) -> list[list[int]]:
    """Clusters of item indexes, largest first. `items`: (url, tokens). Equal token sets go together first; the
    distinct sets are then placed largest group first, each into the best cluster whose group-average overlap is
    >= OVERLAP (candidates through an index of the clusters' words), else into a new one."""
    exact: dict[frozenset, list[int]] = defaultdict(list)
    alone: list[list[int]] = []
    for i, (_, tk) in enumerate(items):
        if tk:
            exact[tk].append(i)
        else:
            alone.append([i])
    groups = sorted(exact.items(), key=lambda kv: -len(kv[1]))
    clusters: list[dict] = []  # {"sets": [token sets], "members": [indexes]}
    index: dict[str, set[int]] = defaultdict(set)
    for tk, members in groups:
        best, best_score = None, 0.0
        if len(tk) >= MIN_TOKENS:
            cand: dict[int, int] = defaultdict(int)
            for w in tk:
                for c in index.get(w, ()):
                    cand[c] += 1
            need = OVERLAP * len(tk)
            for c, shared in cand.items():
                sets = clusters[c]["sets"]
                # A cheap bound first: the cluster must share enough words with this text at all.
                if shared < min(need, OVERLAP * min(len(s) for s in sets)):
                    continue
                sample = sets[:AVERAGE_OVER]
                score = sum(overlap(tk, s) if len(s) >= MIN_TOKENS else 0.0 for s in sample) / len(sample)
                if score >= OVERLAP and score > best_score:
                    best, best_score = c, score
        if best is None:
            clusters.append({"sets": [tk], "members": list(members)})
            if len(tk) >= MIN_TOKENS:
                for w in tk:
                    index[w].add(len(clusters) - 1)
        else:
            clusters[best]["sets"].append(tk)
            clusters[best]["members"].extend(members)
    out = [c["members"] for c in clusters] + alone
    out.sort(key=len, reverse=True)
    return out


def summarise(urls: list[str], titles: dict[str, str] | None = None, top: int = 5) -> dict:
    """Origins for one set of distinct article URLs (a country-day, a zone-day): article and origin counts, outlets
    (registrable domains, aggregators left out), the largest clusters' sizes and a sample of each."""
    titles = titles or {}
    urls = list(dict.fromkeys(urls))
    items = [(u, text_tokens(u, titles.get(u, ""))) for u in urls]
    cl = cluster(items)
    outlets = {domain(u) for u in urls} - AGGREGATORS
    tops = []
    for c in cl[:top]:
        doms = {domain(urls[i]) for i in c} - AGGREGATORS
        tops.append({"articles": len(c), "outlets": len(doms), "sample": urls[c[0]]})
    return {"articles": len(urls), "origins": len(cl), "outlets": len(outlets),
            "no_text": sum(1 for _, tk in items if not tk), "sizes": [len(c) for c in cl[:top]], "top": tops}
