"""Test grouping stories across languages through GDELT's event mentions (28 Oct 2026). Free, local.

GDELT links every article it processes, in any language, to the events it reports (the 15-minute mentions files).
Two stories whose articles report the same events are likely the same story in different languages. This
downloads one day's mentions, joins them to that day's stored zone articles, and shows what different merge rules
would join.

    python -I scripts/eval_xlang.py --root data/backfill/baseline --day 2026-10-26 --entity 18_Ethiopia_Eritrea
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import daily, gdelt, stories  # noqa: E402
from pipeline.relevance import TermMatcher  # noqa: E402
from pipeline.sinks import LocalSink  # noqa: E402

NAMES = {"english": "{stamp}.mentions.CSV.zip", "translation": "{stamp}.translation.mentions.CSV.zip"}


def mentions(stamp: str, stream: str, want: set[str]) -> dict[str, set[str]]:
    try:
        data = gdelt.fetch(gdelt.BASE + NAMES[stream].format(stamp=stamp))
    except Exception:
        return {}
    out: dict[str, set[str]] = defaultdict(set)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for line in z.read(z.namelist()[0]).split(b"\n"):
            f = line.rstrip(b"\r").split(b"\t")
            if len(f) > 5:
                url = f[5].decode("utf-8", "replace")
                if url in want:
                    out[url].add(f[0].decode())
    return out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")  # headlines in every script; Windows consoles default to cp1252
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--day", required=True)
    ap.add_argument("--entity", action="append", required=True)
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()
    sink = LocalSink(Path(a.root))
    day = date.fromisoformat(a.day)
    rows, _ = daily.load_day_rows(sink, day)
    m = TermMatcher()
    by_ent = {e: [r for r in rows if r.get("kind") == "gdelt" and e in r.get("labels", []) and m.hit(e, r.get("title") or "")]
              for e in a.entity}
    want = {r["url"] for rs in by_ent.values() for r in rs}
    t = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    stamps = [(t + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(-8, 100)]
    ev: dict[str, set[str]] = defaultdict(set)
    with ThreadPoolExecutor(8) as ex:
        for got in ex.map(lambda sa: mentions(sa[0], sa[1], want), [(s, st) for s in stamps for st in NAMES]):
            for u, ids in got.items():
                ev[u] |= ids
    print(f"{len(want)} headline-filtered articles, {sum(1 for u in want if ev.get(u))} with events")
    for eid, rs in by_ent.items():
        rs = list({r["url"]: r for r in rs}.values())
        # Every article's story, via the same headline grouping build_stories uses.
        members = defaultdict(list)
        norms = [stories.normalize_title(r.get("title") or "") or r["url"] for r in rs]
        ids = stories.group_titles(norms)
        for gid, r in zip(ids, rs):
            members[gid].append(r)
        sev = {g: set().union(*(ev.get(r["url"], set()) for r in mem)) for g, mem in members.items()}
        langs = {g: {r.get("lang", "eng") for r in mem} for g, mem in members.items()}
        print(f"\n== {eid}: {len(rs)} articles, {len(members)} stories by headline, "
              f"{sum(1 for g in members if sev[g])} with events")
        event_story = defaultdict(set)
        for g, es in sev.items():
            for e in es:
                event_story[e].add(g)
        # How many stories each event touches: a broad event joins unrelated stories.
        breadth = Counter(len(gs) for gs in event_story.values())
        print("  stories per event:", dict(sorted(breadth.items())[:10]))
        for rule, ok in (("share 1 event", lambda x, y: len(x & y) >= 1),
                         ("share 2 events", lambda x, y: len(x & y) >= 2),
                         ("jaccard >= 0.3", lambda x, y: len(x & y) / len(x | y) >= 0.3 if x | y else False)):
            parent = {g: g for g in members}

            def find(g):
                while parent[g] != g:
                    parent[g] = parent[parent[g]]
                    g = parent[g]
                return g
            for e, gs in event_story.items():
                gs = sorted(gs)
                if len(gs) > 25:  # an event most stories mention says little about any one
                    continue
                for x in gs[1:]:
                    if ok(sev[gs[0]], sev[x]):
                        parent[find(x)] = find(gs[0])
            groups = defaultdict(list)
            for g in members:
                groups[find(g)].append(g)
            merged = [gl for gl in groups.values() if len(gl) > 1]
            cross = [gl for gl in merged if len(set().union(*(langs[g] for g in gl))) > 1]
            print(f"  {rule}: {len(groups)} stories ({len(merged)} merged groups, {len(cross)} across languages)")
            if rule == "share 2 events":
                for gl in sorted(cross, key=lambda gl: -sum(len(members[g]) for g in gl))[:a.show]:
                    print("    --")
                    for g in gl[:5]:
                        r = members[g][0]
                        print(f"     [{r.get('lang')}] {(r.get('title') or '')[:90]}  ({len(members[g])} art.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
