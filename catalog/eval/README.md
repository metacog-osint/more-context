# Relevance test sets

A relevance set answers one question: when a rule assigns a story to a zone or topic, is the story about
that zone or topic? v4.3 counts every match as volume, so off-topic matches inflate its numbers directly.

## relevance_v1 (26 Oct 2026)

- **Source:** `data/raw/matched-20261026163000-6h.jsonl`: 6 hours of GDELT (English + translation streams)
  ending 26 Oct 2026 16:30 UTC, 8,985 articles that v4.3's rules matched (`catalog/entities.json`, `match_v43`).
- **Draw:** `scripts/sample_relevance_set.py`, seed 20261026. Articles are grouped into stories first
  (reprints merged). Per zone: the 8 largest stories plus 8 at random from the rest; per topic: 6 plus 6.
  278 stories in all. GPS Jamming had no matches in that window.
- **Population:** `relevance_v1.population.json` has each entity's total stories and articles in the window.
  The scorer weights each random story by (stories not in the top draw) / (random draws), so estimates cover
  everything v4.3 matched, not just the largest stories.
- **Labels:** `on`, `off` or `unclear`, with a short note where a reviewer may disagree.
  `labelled_by: claude-draft-2026-10-26` means Claude drafted them from the headline. They are waiting for
  Tom's spot-check, and nothing here should be quoted as final until then.

### Labelling rules

- **on:** the story is substantively about the zone's conflict, security or political-military situation:
  fighting, attacks, posture and exercises, diplomacy and talks about the conflict, casualties, conflict-driven
  humanitarian crisis, conflict-linked sanctions, the conflict's leaders acting in that role. For a topic, the
  story is about that strategic theme (supply, policy, security), not a company's routine business.
- **off:** the place or term appears only in passing, or the story is about something else: US or other
  domestic politics, business and markets, sport, entertainment, crime, history features, weather.
- **unclear:** the headline alone cannot settle it (missing headline, essay title, or a link to the conflict
  that the headline implies but does not state).
- A story that belongs to a neighbouring zone is `off` for the zone it was wrongly matched to (for example
  Iran-US talks matched to Israel-Gaza-Lebanon).

## Scoring

```
python -I run.py eval-relevance [--set catalog/eval/relevance_v1.jsonl] [--out data/reports/relevance_v1.json]
```

- **precision:** on-topic share of what a method keeps (unclear stories left out).
- **retention:** share of on-topic stories kept. This is recall against v4.3's matches only. Stories v4.3
  never matched are not in the set, so this cannot show what v4.3 misses.
- **off removed:** share of off-topic stories dropped.
- Each measure is reported per story and per article (a story counts by its article count, as v4.3's volumes do),
  with 90% bootstrap intervals (resampled within each entity and draw).

Free baselines in `pipeline/relevance.py`:

- `v43_rules`: keep everything (v4.3 as it runs today).
- `title_terms`: keep a story if its headline contains one of the entity's terms in `catalog/title_terms.json`
  (multilingual names of the country, capital, leaders, key places and armed groups).
- `title_or_url_terms`: headline or words from the URL.

### First results (relevance_v1, Claude-drafted labels)

| method | precision (stories) | 90% range | retention | off removed | F1 |
|---|---|---|---|---|---|
| v4.3 rules | 42% | 30-53% | 100% | 0% | 59% |
| headline terms | 82% | 62-98% | 78% | 88% | 80% |

Weak spots for headline terms: Russia-NATO and the South China Sea (on-topic headlines often name neither),
Taiwan (Chinese-language headlines that say 台陸軍 or 中共 rather than Taiwan), and zones where a matching
name is not enough (Ebola stories that name Congo, Trump remarks that name Somalia).

### Caveats

- 16 stories per zone: per-zone numbers are rough. Use them to rank problems, not as measurements.
- The same reviewer (Claude) wrote the labels and the term lists, and the terms were written after reading
  these headlines, so the headline-terms result may be flattered. relevance_v2 should come from a different
  day and be scored with the terms frozen.
- Headlines only. Some `unclear` stories would resolve from the article text.
