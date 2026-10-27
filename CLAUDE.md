# MORE CONTEXT - Claude Context

MORE CONTEXT is Tom's parallel rebuild of CONTEXT (v4.3, `[local path]`, live at
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
- Current-situation research (charters, briefs): MORE CONTEXT's own stories first (`mc-api` `/zone`), then
  extended web searches with month, year, outlets and conflict trackers in the query; a date and source on every
  claim; say when nothing recent turns up, never call a zone quiet for lack of results (26 Oct 2026 lesson).

## Layout
- `catalog/entities.json` - zones and Watch Topics. `match_v43` holds v4.3's exact rules (baseline for
  comparison); MORE CONTEXT's own matching replaces them in Phase 2.
- `catalog/sources.json` - 83 sources in 16 groups: 51 polled RSS feeds, 2 to retry, 17 dropped (reason
  recorded), 13 GDELT-only outlets tagged by domain (wires, Russian/Chinese/Iranian outlets with no usable feed).
- `catalog/indicators/` - per-zone charters (key questions + indicator ladder). Tom writes these.
- `catalog/entities.json` also holds a one-sentence `profile` per zone/topic (scope for embeddings and prompts).
- `catalog/title_terms.json` - multilingual headline terms per entity: the free keyword baseline for relevance.
- `catalog/eval/` - relevance test sets (`relevance_v1.jsonl`: 278 stories labelled on/off/unclear, Claude's
  draft, accepted by Tom 26 Oct 2026 as the working set) + population files for weighting. Rules and results: `catalog/eval/README.md`.
- `catalog/vertex_prices.json` - Gemini prices with source and date checked.
- `pipeline/` - Python, standard library only so far.
  - `gdelt.py` - list, download and parse GDELT GKG 2.1 15-minute files (English + translation streams).
  - `match.py` - zone/topic matching from the catalog.
  - `stories.py` - title normalisation, exact + near-duplicate grouping (MinHash LSH) into stories.
  - `rss.py` - fetch (ETag/Last-Modified) and parse RSS, Atom and RDF feeds; titles + short leads only.
  - `health.py` - feed health (fresh / late / stale / failing / never) against each source's expected interval.
  - `sources.py` - domain -> source group lookup, so GDELT articles get the same groups as RSS items.
  - `cli.py` - `python -I run.py measure-reprints --hours 6`, `rss-poll`, `feed-health` (run.py makes `python -I` work)
  - `feeds.py` - one RSS poll over the active sources (shared by the CLI and the cloud cycle).
  - `cycle.py` - one 15-minute ingest cycle: new GDELT files (late files retried up to 3 h, never blocking),
    one RSS poll; writes `cycles/YYYY/MM/DD/HHMMSS.jsonl` + `state/state.json`. `sinks.py`: local folder or GCS.
  - `relevance.py` - scores relevance methods against a labelled set (weighted precision, retention vs v4.3,
    bootstrap intervals); headline-term matcher. `python -I run.py eval-relevance`.
  - `coding.py` - story coding schema (PLOVER v0.8 event types + quads, actors, direction, casualties, frame,
    confidence), prompt builder, answer validation. No calls.
  - `vertex.py` - Vertex Gemini REST client (global endpoint, gcloud token locally, metadata token on Cloud Run)
    that refuses to run without a spend cap and stops at it; token and cost estimates with no calls.
    `python -I run.py vertex-estimate` (free). `python -I run.py code-stories --cap <USD>` is BILLABLE: Tom's yes first.
  - `measures.py` - attention anomaly (log-scale z vs the entity's previous 28 complete days, weekday-adjusted)
    and casualty-reporting share (presence of GDELT KILL/WOUND counts; the numbers themselves are unreliable).
  - `daily.py` - daily story build inside the cycle: day D is built on the first run after D+1 03:15 UTC, from
    rows published on D; writes `stories/YYYY/MM/DD/stories.jsonl` + `summary.json` (per-entity totals, reprint
    inflation, source-group counts). Local: `python -I run.py build-stories --day YYYY-MM-DD --root <folder>`.
- `main.py`, `requirements.txt`, `.gcloudignore` - Cloud Run function wrapper (`mc-ingest`).
  `scripts/deploy_ingest.sh` creates bucket, service accounts, private function, one Scheduler job.
  Local dry run: `python -I run.py cycle`. Redeploy after code changes with the `gcloud functions deploy`
  line from that script (needs Tom's yes, like any deploy).

## AI spend: on demand, capped (Tom's decision, 26 Oct 2026)
Most stories are never read by a person, so model work waits for a reason to spend:
- **Always on, $0:** ingest, stories, headline-term filter, counts, attention z, casualty share.
- **Alarm:** the daily build flags an entity-day when attention z >= 2 or casualty-share z >= 2 (and >= 5
  stories); the 15-minute cycle codes up to 2 flagged entity-days per run (`state.ai.pending`). A spending
  trigger only; Watch / Warning / Crisis come from the charters.
- **On view:** `POST /code` on the public API (`pipeline/api.py`, function `mc-api`) codes one entity-day's
  top 25 uncached stories. Anyone may call it (Tom's choice); `GET /zone` and `GET /status` never spend.
- **Cache:** `codings/YYYY/MM/DD/<entity>.jsonl`; a story is never coded twice.
- **Ledger:** `state/ai_spend.json` (`pipeline/budget.py`), compare-and-swap on the GCS generation. Hard cap
  $5 per UTC month; on-view work at most $0.50 per day and never the last $1 (kept for alarms). Every call
  reserves estimate x 1.5 first and settles to the cost from Vertex's token counts.
- **Switch:** Vertex calls from the cloud happen only with env `MC_AI=on`. Deployed with `scripts/deploy_ai.sh`
  on 26 Oct 2026 22:11-22:14 UTC (approved by Tom): mc-ingest@ holds roles/aiplatform.user; mc-ingest revision
  mc-ingest-00005-muw and mc-api revision mc-api-00001-zoy both run with MC_AI=on. Kill switch: redeploy with MC_AI=off.
- **Public API:** https://mc-api-odg3xhcd4a-uc.a.run.app (`/status`, `/zone?entity=&day=`, `POST /code`), open to
  anyone, max 1 instance, concurrency 1. First call, 26 Oct 22:14 UTC: 13_Sudan / 2026-10-26, 25 stories coded for
  $0.0049 (22 on-topic); a repeat call was served from the cache for $0.
- The ledger counts list prices; Google's bill is the final word. A Cloud Billing budget alert is the backstop.

## Cloud (deployed 26 Oct 2026, approved by Tom)
- Function `mc-ingest` (Cloud Run functions gen2, us-central1, python312, 512 MiB, 300 s, max 1 instance),
  runs as `mc-ingest@context-484804.iam.gserviceaccount.com`. Private: anonymous calls get 403; only
  `mc-scheduler@` holds `roles/run.invoker`.
- Scheduler job `mc-ingest-15min`, `5,20,35,50 * * * *` UTC, OIDC token, 320 s deadline. It is not a v4.3
  duplicate; v4.3's own job is `trigger-context-update`.
- Bucket `gs://more-context-484804` (us-central1, uniform access, public access prevented):
  `cycles/YYYY/MM/DD/HHMMSS.jsonl` (rows kind=gdelt|rss) and `state/state.json` (GDELT progress and
  retry lists, feed health, last run summary). Read it with `gcloud storage cat gs://more-context-484804/state/state.json`.
- First cloud run 26 Oct 17:10 UTC: 46 s for a 2-hour catch-up, 4,001 rows. From Google Cloud,
  france24_en, rfi_afrique and timesofisrael answer HTTP 403 (they block cloud addresses; fine from a home
  connection) and reliefweb returned an empty body. GDELT still carries all four by domain.
- `tests/` - `python -m unittest discover -s tests -t .` (CI runs this on every push).
- `data/` - downloads and reports, git-ignored.

## Build status
- Phase 0 done. Phase 1: GDELT + RSS ingest running in the cloud every 15 minutes since 26 Oct 2026;
  gate = 7 days of stored data (about 2 Nov) and reprint inflation measured (done: 1.25x overall).
- First finding: only ~32% of English articles v4.3's rules assign to a zone name that zone in the headline,
  so Phase 2 starts with a relevance check (embeddings + model) before coding.
- Phase 2 started 26 Oct 2026. Relevance v1 (Claude-drafted labels): v4.3's rules are on-topic
  for ~42% of matched stories (90% range 30-53%); a free headline-term filter reaches ~82% while keeping ~78%
  of on-topic stories (likely flattered: same reviewer wrote terms and labels). Coding all 278 test stories with
  gemini-3.1-flash-lite: est. $0.07; coding every v4.3 match daily: est. ~$219/month, so code only filtered or top stories.
- First Vertex run (approved by Tom, cap $0.25), 26 Oct 21:00 UTC: 278 stories, 19 requests, $0.0595 billed
  (56,135 in / 30,314 out / 0 thinking tokens). Gemini's relevance call: 94% on-topic (86-100%), ~100% retention,
  agrees with Claude's labels on 243/253. It rarely says unclear and rates nearly everything high confidence.
  Prompt fixed in code-v0.2 (topics overlap zones; confidence rule), not yet re-run. Score a codings file with
  `python -I run.py eval-relevance --codings data/coding/relevance_v1.codings.jsonl`. Estimator recalibrated:
  ~$188/month for every v4.3 match, ~$12/month ($6 batch) for the top 100 stories per entity per day.
- Casualty flags (`killed`/`wounded` on GDELT rows, per-story tallies) and the two measures deployed 26 Oct 2026
  20:57 UTC (revision mc-ingest-00004-yuq, approved by Tom). Rows before that lack the fields; measures count
  only rows that have them. Attention z needs 14 complete days, so it first appears around 10 Nov.
- Charters: Claude drafted four (Ukraine, Israel-Gaza-Lebanon, Iran & Red Sea, India-Pakistan) on 26 Oct 2026 in
  the plan doc's "Indicator charters (draft)" tab; Tom marks them up, then an interview settles open questions;
  the final versions go to `catalog/indicators/` as catalog data. Budget decided: $5/month AI cap (see above);
  a Cloud Billing budget alert ($5, project context-484804, 50/90/100% actual + 100% forecast) emails billing admins.
- Waiting on Tom: charter mark-up and interview; decisions on the source list (plan doc, "Source list (draft)" tab).
