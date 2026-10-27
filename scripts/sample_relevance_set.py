"""Draw the relevance test set: stories matched to each zone/topic by v4.3's rules, to be labelled
on-topic / off-topic. Per zone: the 8 largest stories (they move the counts most) plus 8 at random;
per topic: up to 12. Fixed seed so the draw is repeatable. Also writes <dest>.population.json (stories and
articles per entity in the whole window), which the scorer uses to weight the random draws.

    python -I scripts/sample_relevance_set.py data/raw/matched-<stamp>.jsonl catalog/eval/relevance_v1.jsonl
    python -I scripts/sample_relevance_set.py <src> <dest> --population-only   # keep existing labels
"""
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.stories import build_stories  # noqa: E402

TOP, RANDOM_ZONE, TOPIC = 8, 8, 12


def population_path(dest: str) -> Path:
    d = Path(dest)
    return d.with_name(d.stem + ".population.json")


def main(src: str, dest: str, population_only: bool = False) -> None:
    rows = [json.loads(l) for l in Path(src).read_text(encoding="utf-8").split("\n") if l.strip()]
    by_entity = defaultdict(list)
    for r in rows:
        for label in r["labels"]:
            by_entity[label].append(r)
    built = {eid: build_stories(arts) for eid, arts in by_entity.items()}
    population = {"source": Path(src).name, "articles_in_file": len(rows), "entities": {
        eid: {"stories": len(st), "articles": sum(s["articles"] for s in st)} for eid, st in sorted(built.items())}}
    population_path(dest).parent.mkdir(parents=True, exist_ok=True)
    population_path(dest).write_text(json.dumps(population, indent=1), encoding="utf-8")
    print(f"population -> {population_path(dest)}")
    if population_only:
        return
    if Path(dest).exists():
        raise SystemExit(f"{dest} exists (it may hold labels); delete it first or use --population-only")
    rng = random.Random(20261026)
    out = []
    for eid in sorted(by_entity):
        stories = built[eid]
        if eid.startswith("T"):
            picked = stories[:6] + rng.sample(stories[6:], min(6, len(stories[6:])))
        else:
            picked = stories[:TOP] + rng.sample(stories[TOP:], min(RANDOM_ZONE, len(stories[TOP:])))
        for rank, s in enumerate(picked):
            out.append({
                "id": f"{eid}:{s['story_id']}", "entity": eid, "draw": "top" if rank < (6 if eid.startswith('T') else TOP) else "random",
                "title": s["title"], "languages": s["languages"], "articles": s["articles"], "outlets": s["outlets"],
                "url": s["sample_urls"][0], "label": None, "note": "",
            })
    Path(dest).parent.mkdir(parents=True, exist_ok=True)
    Path(dest).write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in out), encoding="utf-8")
    print(f"{len(out)} stories from {len(rows)} articles -> {dest}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--population-only" in sys.argv[3:])
