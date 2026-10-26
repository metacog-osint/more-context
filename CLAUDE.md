# MORE CONTEXT - Claude Context

MORE CONTEXT is Tom's parallel rebuild of CONTEXT (v4.3, `D:\Projects\geo-context`, live at
https://context.theintelligence.company). Both will be fully built and scored side by side; the better
parts win. Private work of The Intelligence Company: publicly available information only, no
classification markings anywhere, no references to other work.

**Plan (read first):** https://claude.ai/artifact/ShyAN6L2qhb6MBiq5284kk ("MORE CONTEXT: Build Plan").

## What it does
Turns GDELT articles into stories (reprints grouped), codes each story with Gemini, tracks warning
indicators per zone, and measures attention, escalation, casualty reporting and framing divergence.
Serves warning (did something change?) and awareness (what is the picture, how is each side telling it?).

## Rules that carry over from v4.3
- **Vertex AI (Gemini) is the only model provider.** Do not suggest others.
- Free tier first. Anything billable (Vertex calls, new GCP resources, BigQuery scans) is measured on a
  sample and approved by Tom before it runs. Dry-run every BigQuery query.
- Same GCP project as v4.3: `context-484804`. Keep MORE CONTEXT's tables/collections separate (prefix `mc_`).
- No secrets in files. Keys live in Secret Manager or GitHub secrets; Tom sets them.
- One scheduler per job, defined in this repo. v4.3 once ran a duplicate Scheduler job for months.
- Windows: use `python`, not `python3`; run downloaded-data tooling with `python -I`.

## Layout
- `catalog/entities.json` - zones and Watch Topics. `match_v43` holds v4.3's exact rules (baseline for
  comparison); MORE CONTEXT's own matching replaces them in Phase 2.
- `catalog/indicators/` - per-zone charters (key questions + indicator ladder). Tom writes these.
- `pipeline/` - Python, standard library only so far.
  - `gdelt.py` - list, download and parse GDELT GKG 2.1 15-minute files (English + translation streams).
  - `match.py` - zone/topic matching from the catalog.
  - `stories.py` - title normalisation, exact + near-duplicate grouping (MinHash LSH) into stories.
  - `cli.py` - `python -I run.py measure-reprints --hours 6` (run.py makes `python -I` work)
- `tests/` - `python -m unittest discover -s tests -t .` (CI runs this on every push).
- `data/` - downloads and reports, git-ignored.

## Build status
Phase 0 (foundation) and Phase 1 (ingest + stories) in progress as of 26 Oct 2026.
