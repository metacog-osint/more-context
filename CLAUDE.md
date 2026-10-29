# Watchfloor (working name MORE CONTEXT) - Claude Context

Watchfloor is Tom's parallel rebuild of CONTEXT (v4.3, `D:\Projects\geo-context`, live at
https://context.theintelligence.company). Both will be fully built and scored side by side; the better
parts win. Private work of The Intelligence Company: publicly available information only, no
classification markings anywhere, no references to other work.

**Name (Tom, 27 Oct 2026):** the public name is Watchfloor. Internal ids keep the working name on purpose:
the repo `more-context`, functions `mc-ingest` / `mc-api`, bucket `more-context-484804`, Scheduler job
`mc-ingest-15min`. Do not rename them; that would mean redeploys and new URLs for nothing.

**Plan (read first):** https://claude.ai/artifact/ShyAN6L2qhb6MBiq5284kk ("Watchfloor: Build Plan").

## Website (deployed 27 Oct 2026, approved by Tom)
- https://watchfloor.web.app: Firebase Hosting site `watchfloor` in project context-484804 (free tier: 10 GB stored,
  360 MB/day transfer). Static files in `web/` (no build tool, no dependencies; `web/app.js` inserts API text as
  text, never HTML). Reads the public API https://mc-api-odg3xhcd4a-uc.a.run.app.
- Hidden from search engines until Tom says public: `noindex` meta, `X-Robots-Tag`, and `robots.txt` Disallow.
  To go public, remove all three and add a link from CONTEXT.
- Custom domain `watchfloor.theintelligence.company`: live since 28 Oct 2026 (Firebase custom domain on the
  watchfloor site, CNAME `watchfloor` → `watchfloor.web.app` in Squarespace DNS). Claude set it up at Tom's request;
  method in `D:\Projects\CLAUDE_HANDOVER.md` §3.11.
- Deploy (needs Tom's yes): `python -I scripts/build_web.py` (sources list + "Updated" date), then
  `firebase deploy --only hosting:watchfloor --project context-484804`. Pages revalidate on every load (no-cache).
- Footer pattern (shared with Tom's noisefloor): "A project of The Intelligence Company. Updated <date>." + terms
  link + data credits (GDELT requires a citation and link) + a Sources page.

## What it does
Turns GDELT articles into stories (reprints grouped), codes each story with Gemini, tracks warning
indicators per zone, and measures attention, escalation and framing divergence.
Serves warning (did something change?) and awareness (what is the picture, how is each side telling it?).

## Rules that carry over from v4.3
- **Vertex AI (Gemini) is the only model provider.** Do not suggest others.
- Free tier first. Anything billable (Vertex calls, new GCP resources, BigQuery scans) is measured on a
  sample and approved by Tom before it runs. Dry-run every BigQuery query.
- Same GCP project as v4.3: `context-484804`. Keep MORE CONTEXT's tables/collections separate (prefix `mc_`).
- No secrets in files. Keys live in Secret Manager or GitHub secrets; Tom sets them.
- One scheduler per job, defined in this repo. v4.3 once ran a duplicate Scheduler job for months.

## Cost audit (29 Oct 2026; Tom: no paid usage, lose nothing, keep a historical record)
- Free tiers are per **billing account** (019D1C-D7ADF2-989261: context-484804, geo-context, listening-post-app,
  morning-brief-tic), not per project: Cloud Storage 5 GB-months in us-central1/us-east1/us-west1, 5,000 Class A
  (writes, lists) and 50,000 Class B (reads) a month, 100 GB egress; BigQuery 1 TiB scanned a month; Scheduler
  3 jobs (paused jobs still count, $0.10/job/month after); Cloud Run 2M requests, 180,000 vCPU-s, 360,000 GiB-s,
  1 GB egress. Verified on Google's pages 28 Oct 2026. Soft-deleted objects are billed like live ones.
- Bucket `more-context-484804` (soft delete 7 days): 1,002 MiB live + 840 MiB soft-deleted. 633 MiB of that was
  the history re-uploads (expires by ~4 Nov). `state/state.json` (99% per-feed "seen" link lists, capped at 1,000
  links a feed, most not yet full) is written twice a run, 8 copies an hour kept a week: 1.9 GB held at today's
  1.45 MB, ~15 GB once the lists fill (~11 MB). Biggest risk to the free tier.
- **State fix (29 Oct 2026, `pipeline/health.py`, `cycle.py`):** feeds remember 8-character fingerprints
  (`seen_fp`), not links, in the order items were last listed, sized per feed (3 x the most items it has returned,
  200-2,000; `max_items`). Last-listed order matters: feeds keep sticky items for months (tribune_pk one 238 days
  old, jpost 49), and trimming by first sighting would have dropped 30 of 4,100 listed items on the first run.
  Old `seen` lists are converted untrimmed (`upgrade_seen`); each feed's next fetch trims its own. State is written
  once a run, twice only when a day build or pending Vertex alarms follow. Checked on the 29 Oct state copy with a
  live poll of all feeds: 0 listed items forgotten; 1.98 MB -> 173 KB (~276 KB once every list is full); a week of
  old copies 2.66 GB -> ~0.12 GB (~0.19 GB full). A forgotten link seen again costs one cycle row, never a double
  count: the build keeps one copy per source and link and skips rows dated before its day, and none of ~98,000
  feed rows read 26-29 Oct lacked a date.
- Writes counted from code: ~4 Class A a run (cycle, events, state x2) x 2,880 runs = ~11,500 a month, over the
  5,000 free (~$0.03/month). After the state fix, 3 a run (~8,600 a month): still over; merging the cycle and
  events files and a longer interval are the next levers. The API lists all of `stories/` for its day lists
  (grows with history; cached 5 min).
- Every build read is bounded (one day of files + 28 or 90 daily summaries); no BigQuery anywhere in Watchfloor.
- Same account: old GEO CONTEXT v4.0 in project `geo-context` (job `generate-watchcon-data`, 3 runs a day, deployed
  16 Jan 2026) still scans ~350 GiB of BigQuery a month and nothing reads its output; October was at 962 of 1,024
  free GiB on 29 Oct. Paused 29 Oct 2026 14:39 UTC on Tom's yes (a paused job still counts as one of the 3 free
  Scheduler jobs; deleting it is Tom's). Scheduler has 6 jobs on the account (3 free).
- Windows: use `python`, not `python3`; run downloaded-data tooling with `python -I`.
- Current-situation research (charters, briefs): MORE CONTEXT's own stories first (`mc-api` `/zone`), then
  extended web searches with month, year, outlets and conflict trackers in the query; a date and source on every
  claim; say when nothing recent turns up, never call a zone quiet for lack of results (26 Oct 2026 lesson).

## Layout
- `catalog/entities.json` - zones and Watch Topics. `match_v43` holds v4.3's exact rules (baseline for
  comparison); MORE CONTEXT's own matching replaces them in Phase 2.
- `catalog/sources.json` - 95 sources in 18 groups: 51 polled RSS feeds, 2 to retry, 17 dropped (reason
  recorded), 13 GDELT-only outlets tagged by domain (wires, Russian/Chinese/Iranian outlets with no usable feed),
  plus 12 front-line sources Tom approved on 27 Oct 2026: Suspilne, RBC-Ukraine, Meduza (ru, en), ISW (dropped:
  HTTP 403 to automated requests), and 7 Telegram channels (`format: telegram`): Ukrainian Air Force (nightly
  tallies), General Staff, Russian MoD, DeepState, Rybar, Two Majors, WarGonzo. New groups: russian_independent,
  russian_milblog.
- **Two-source rule (Tom, 27 Oct 2026):** an indicator hit counts once two independent sources report it
  (different outlets, not both from the same government); an official claim counts once an outlet outside that
  government reports it. Single-source hits are shown as "claimed" and do not move the ladder. Use `owner` + `group`.
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
  - `telegram.py` - public Telegram channels via the web preview `t.me/s/<channel>` (no account or key); latest
    ~20 posts per poll, so very busy channels can drop posts between 15-minute polls.
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
    The casualty-reporting share was removed on 27 Oct 2026 (it flagged deaths from other places and times;
    see the module docstring); zone violence in `countries.py` replaced it on 28 Oct 2026.
  - `daily.py` - daily story build inside the cycle: day D is built on the first run after D+1 03:15 UTC, from
    rows published on D; writes `stories/YYYY/MM/DD/stories.jsonl` + `summary.json` (per-entity totals, reprint
    inflation, source-group counts). Local: `python -I run.py build-stories --day YYYY-MM-DD --root <folder>`.
  - `events.py` - GDELT Events 2.0 files (~100 KB per stream per 15 minutes, against ~20 MB for GKG): one
    compact record per file with per-country article counts, sample links and placed violent events.
  - `countries.py` - per-country days (`stories/YYYY/MM/DD/countries.json`), the Rising and Elevated lists, zone
    violence, and `violent.jsonl` for the map. See "Rising, map and zone violence" below.
  - `instance.py` - restarts the Cloud Run instance after a run whose saved searches were refused.
- `scripts/backfill_events.py` (Events history, free), `scripts/eval_rising.py` (compares country counts),
  `scripts/eval_xlang.py` (cross-language grouping test), `scripts/build_fips_names.py` (catalog/fips_countries.json),
  `scripts/dev_server.py` (local preview of web/ against a local data folder; AI off).
- `main.py`, `requirements.txt`, `.gcloudignore` - Cloud Run function wrapper (`mc-ingest`).
  `scripts/deploy_ingest.sh` creates bucket, service accounts, private function, one Scheduler job.
  Local dry run: `python -I run.py cycle`. Redeploy after code changes with the `gcloud functions deploy`
  line from that script (needs Tom's yes, like any deploy). **In PowerShell, single-quote the env-var argument:**
  `'--set-env-vars=MC_BUCKET=more-context-484804,MC_AI=on'`. PowerShell runs `gcloud.ps1`, which turns an
  unquoted `a,b` into a list and rejoins it with a space: on 29 Oct 2026 that deployed `MC_BUCKET` as
  `more-context-484804 MC_AI=on` and every run failed with "Invalid bucket name" until redeployed. After any
  deploy, check `gcloud functions describe mc-ingest --gen2 --region=us-central1 --project=context-484804
  --format="json(serviceConfig.environmentVariables)"` shows the two variables separately.

## Changing the watchlist
- Zones and topics live in `catalog/entities.json` (order matters: first zone match wins). A retired id goes in
  its `"retired"` list with what replaced it; its headline terms stay in `catalog/title_terms.json` so older
  labelled sets still score. A zone that departs from CONTEXT v4.3's rules carries a `match_note`.
- Splitting a zone: if the new rules are a subset of the old one (same themes, places from its list), run
  `scripts/relabel.py` on the stored rows and rebuild the days; no download. Anything wider needs
  `scripts/backfill.py`, because rows the old rules never matched were not kept.
- 27 Oct 2026 (Tom): 17_Horn_of_Africa split into 18_Ethiopia_Eritrea and 19_Somalia after Ethiopia's renewed
  war (from 23 Sep) was lost inside it. Main-location relevance was tested and dropped (see below); the
  per-country baseline and the Rising list followed on 28 Oct, so new crises surface without a catalog edit.

## Feeds and saved searches (27 Oct 2026)
- Feed items (RSS, Telegram, saved searches) get zone labels when the day is built (`pipeline/feedlabels.py`):
  a saved search (source with `"entity"`) belongs to its zone; other items count for each zone whose headline
  terms they contain, within the source's `focus` when it lists zones. They become `kind: "feed"` stories,
  shown on the zone page under "From news feeds and searches" and kept out of the GDELT counts and baselines.
- 21 Google News searches (`group: "search"`, ids `gn_<entity>`, readable `query` field) are polled hourly
  (`poll_minutes`). Google News headlines end in " - Publisher"; that becomes the outlet. Google's terms are
  understood (secondary sources only, 27 Oct 2026) to allow personal, non-commercial use: review before
  Watchfloor earns money.
- From Cloud Run, Google News answers 503 to some runs and 200 to others, all 21 searches together (28 Oct 2026:
  about 25 of 62 runs got through; from Tom's machine every try works). The egress address changes between runs.
  So a failed search is retried next run (`RETRY_MINUTES` 15), and each run tries one search first and holds the
  rest when it is refused (probe row `held`), keeping refused requests to one per run. A fixed egress address
  (Cloud NAT) would cost money; not done.
- Retrying alone did not help: a healthy function reuses one warm instance, and its address stays refused (four
  runs in a row after the fix). Today's successes all came while the function was crashing, when every run got a
  fresh instance (19 instances, about 4 in 10 got through). So after a run whose searches were all refused
  (`summary.rss.searches_refused`), `pipeline/instance.py` sends SIGTERM to the gunicorn server 3 s after the
  response, and the next run starts on a new instance (`restart_instance: true` in the run log). Only when
  `K_SERVICE` is set (Cloud Run). If Google ever refuses every address, this restarts every run: harmless (free
  cold starts), but then switch to another search source.
- Also failing from the cloud (139 failures in a row by 28 Oct 2026): france24_en, rfi_afrique, timesofisrael
  (HTTP 403) and reliefweb (empty body). suspilne has returned 403 since 28 Oct 03:05 UTC.
- A partial day (ingest started or stopped mid-day) gets no attention z and no alarm.

## Relevance and attention (28 Oct 2026)
- `scripts/eval_location.py` scored "where + what" rules on relevance_v1 (zones only, weighted): v4.3 rules 42% on
  topic; headline terms 82% precision / 78% retention; main location (GDELT V2 mention counts) 42% / 57%; main
  location AND headline terms 99% / 55%. Main location alone is not a fix; the headline filter is the balance.
- Attention and alarms therefore count headline-filtered stories (`filtered_stories`), and `history()` reads that
  count. On 12-26 Oct this removed Somalia's Ilhan Omar alarms and raised Ukraine (16 Oct strikes, Starlink),
  Somalia (Djibouti boat sinking) and DRC (Ebola past 9,000 cases). Known noise: Vietnamese weather headlines
  naming "Bien Dong" (the South China Sea).
- Incident, 28 Oct 2026: the first full-day cloud build (27 Oct) ran out of memory, and since state was saved after
  the build, every run from 03:20 UTC repeated the same ingest and died. Fixes: the MinHash token cache is compact
  and cleared per call (full-day peak 475 -> 200 MiB, nothing kept between runs), `load_day_rows` keeps only
  `BUILD_FIELDS`, and `run_cycle` saves state before building.
- Its leftovers: from 03:35 to 19:50 UTC 28 Oct each cycle file re-wrote up to 17 slots (0.4 -> 6-7 MB per file;
  that day's cycles are 360 MiB against ~50 MiB normal). Loading them all for the 28 Oct build held 266,950 rows
  for 41,208 distinct and peaked at 518 MiB locally, over the 512 MiB function. `load_day_rows` now keeps one
  copy of each (record id, kind, source, link): peak 295 MiB, same 34,509 articles. The link is in the key
  because GDELT reused 89 translation record ids for other articles that day.

## Rising, map and zone violence (28 Oct 2026, Tom: "start the rising list, then the map, violent events...")
- Source: GDELT Events 2.0 export files, not GKG: ~100 KB per stream per 15 minutes against ~20 MB, so every
  country is counted live and 90 days back for free (`scripts/backfill_events.py`: 8,832 slots, 29 Jul-28 Oct,
  ~20 minutes, ~550 MB local). Each ingest run fetches the Events files for the GKG slots it read and writes
  `events/YYYY/MM/DD/HHMMSS.json`; the daily build writes `stories/.../countries.json` and `violent.jsonl`.
- Counts per country-day: distinct articles with an event located there (`urls`, attention) and with an assault,
  fight or mass-violence event there (`violent`, CAMEO 18-20). Scored against the country's own last 28 complete
  days (log z, weekday-adjusted) and its 90-day median. Rising: z >= 2.5, >= 1.5x expected, >= 40 articles
  (violence: 15). Elevated: >= 2x the 90-day median. Country names: `catalog/fips_countries.json` (FIPS 10-4, as
  GDELT; "RI" is Serbia, "CG" DR Congo, "NG" Niger, "NI" Nigeria).
- Test (`scripts/eval_rising.py`, 63 scored days, 26 Aug-27 Oct): countries flagged per day, violence 4.5 (max
  9), attention 7.1, events 8.4, lead-paragraph articles 7.0, placed articles 5.6. Ethiopia on 23 Sep (war restart):
  violence z 5.6 (18x expected), attention z 4.8. Violence leads the page; attention is noisier (GDELT geocodes
  names: "Guadalupe" became Guadeloupe; routine Finnish and Norwegian news). Codes GDELT uses for non-countries
  ("OS", oceans) are never listed. On 27 Oct the 90-day reference keeps Ethiopia on "violence elevated for weeks"
  (5.6x its 90-day median) while its 28-day z reads normal.
- Zone violence replaces the casualty share: violent events placed inside the zone (`countries`, or `violence`
  for Russia-NATO: NATO states + Kaliningrad RS23) in articles whose headline names the zone, z against 28 days.
  Display only, not an alarm reason (yet). Ethiopia & Eritrea on 23 Sep: 37 articles against 0.7 expected (z 6.6).
  The map's event layer (`/violent?zone=`) shows the same events the measure counts.
- Local preview: `scripts/dev_server.py` (launch config `watchfloor-dev`, port 8734) serves web/ and the API from
  `data/backfill/baseline`; the site switches to it on localhost.
- Map (`#/map`): Leaflet 1.9.4 served from `web/vendor/leaflet/` (identical from cdnjs and unpkg, sha256 db49d009...),
  Natural Earth 110m outlines in `web/geo/world.json` (public domain, FIPS codes added). No tile server, so the
  site's CSP stays self-only. Zone positions in `entities.json` `map` (CONTEXT v4.3's, plus the two Horn zones).
- Cross-language grouping via GDELT mentions (`scripts/eval_xlang.py`, 26 Oct): too noisy and too sparse. It joined
  the UN crimes-against-humanity finding across English and Ukrainian, but chained unrelated Ukraine stories through
  broad events, and most events sit in one story only (about 2% of Ukraine's stories could merge). Multilingual
  embeddings (Vertex, billable) remain the route; needs Tom's yes after a measured sample.

## AI spend: on demand, capped (Tom's decision, 26 Oct 2026)
Most stories are never read by a person, so model work waits for a reason to spend:
- **Always on, $0:** ingest, stories, headline-term filter, counts, attention z.
- **Alarm:** the daily build flags an entity-day when attention z >= 2 (and >= 5
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
