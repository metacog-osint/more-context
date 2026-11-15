# Watchfloor (working name MORE CONTEXT) - Claude Context

Watchfloor is Tom's parallel rebuild of CONTEXT (v4.3, `D:\Projects\geo-context`, live at
https://context.theintelligence.company). Both will be fully built and scored side by side; the better
parts win. Private work of The Intelligence Company: publicly available information only, no
classification markings anywhere, no references to other work.

**Name (Tom, 27 Oct 2026):** the public name is Watchfloor. Internal ids keep the working name on purpose:
the repo `more-context`, functions `mc-ingest` / `mc-api`, bucket `more-context-484804`, Scheduler job
`mc-ingest-15min`. Do not rename them; that would mean redeploys and new URLs for nothing.

**Plan (read first):** https://claude.ai/artifact/ShyAN6L2qhb6MBiq5284kk ("Watchfloor: Build Plan").

**Current state (read next):** [`HANDOFF.md`](./HANDOFF.md), the 4 Nov 2026 handoff: live state, the parked
`wip/2026-11-01-unreviewed` branch, decisions waiting on Tom and next steps.

Dated measurements, incidents and test results (the 29-31 Oct cost audit, the feed and coverage audits, the 28 Oct
memory incident, first runs and deploys) and the fuller notes on each mechanism are in [`HISTORY.md`](./HISTORY.md),
moved there verbatim on 6 Nov 2026. It isn't auto-loaded; read the matching section before changing a mechanism.

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

## Doctrine kit (30 Oct 2026)
- `doctrine/kit/` is a vendored copy of The Intelligence Company's shared kit (`D:\Projects\tic-doctrine`): never edit
  it here; change the kit and run `python D:/Projects/tic-doctrine/tools/sync.py D:/Projects/more-context`. CI runs
  `doctrine/kit/tic.py kitcheck` and `registers doctrine`.
- `doctrine/` holds Watchfloor's registers: requirements (SQ1 "Is a zone escalating?", PIRs, EEIs), one warning problem
  per zone and topic (`WF-WP-Z01` ... `WF-WP-T5`, three hypotheses each, the measured indicators `WF-IND-1`..`6`),
  assumptions, the function map for topics, source grades (proposed; Tom to confirm) and a method summary. Each
  warning problem's charter indicators and watch condition wait on Tom's charters in `catalog/indicators/`.
- `GET /feed?day=` on mc-api serves the day in feed contract v2 (`tic-feed/2`, GeoJSON) from the same files as
  `/summary` and `/countries` (`pipeline/feed_v2.py`; no new storage writes). Every item is an observation; an item
  that fails the kit's linter is left out and listed in `dropped`. Countries are ISO alpha-2 through
  `catalog/fips_iso.json` (GDELT's FIPS codes; built by `scripts/build_fips_iso.py` from Natural Earth 1:50m).
- **Tips from the other programs (kit 0.4.0, 1 Nov 2026; Tom: "don't recreate these datasets when you can leverage
  them from the other programs").** Before adding a collector, check `doctrine/kit/vocab/programs.json` (the suite
  registry: who owns which dataset). Travel advisories, embassy posture, EASA bulletins and NGA warnings belong to
  Cordon; fires (FIRMS), quakes and GDACS to Elements; GPS interference to Noisefloor; cyber to Vigil; dated events to
  Verdict; outages, ships, flights, launches, statements, attention and sanctions to planned programs. Watchfloor
  owns the news layer (GDELT raw files, feeds, Google News searches, Telegram).
  `doctrine/interests.json` (written by `scripts/build_interests.py`; edit the script) lists what Watchfloor wants:
  areas are the zones' countries in ISO, keyed by warning problem; 10 interests (WF-INT-1..10).
  `python doctrine/kit/tic.py tips doctrine` runs them against COP's bus plus Verdict's calendar. Items placed only
  by geometry, such as NGA navigational warnings, land in a zone through eleven sea-area `boxes` ([west, south, east,
  north]: Black Sea and Azov, Taiwan Strait, Red Sea / Gulf of Aden / Hormuz and others) in `scripts/build_interests.py`
  (kit 0.4.1, `6f3a63d`, 4 Nov 2026: 13 of 48 NGA warnings placed). Run the script after changing a zone's countries,
  boxes or an interest. Live in the panel since mc-api-00016-duh (6 Nov 2026): `doctrine/kit/geo/` must ship with
  the API (`.gcloudignore` excluded it until then, and `/suite` failed with a missing `geo/countries.json`).
- **"From the suite" panel** (1 Nov 2026): `GET /suite?entity=<id>` (`pipeline/suite.py`) gathers and matches the
  interests at most every 30 minutes per instance (5 after a failed source), then picks a zone's tips by area and a
  topic's by `warning_problems` (topics have no countries). Anomalies first, then standing items newest first, at most
  12 per program. Sources that could not be read are named in `missing` and shown as missing, never quiet; a stale
  producer's items draw grey. The zone page loads the panel after the stories, so a slow feed never holds them up.
  Nothing from the panel is counted in Watchfloor's measures.

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

## Costs and storage (Tom, 29 Oct 2026: no paid usage, lose nothing, keep a historical record)
Measurements and the reasoning behind each point: `HISTORY.md`, "Cost audit".
- Free tiers are per **billing account** (019D1C-D7ADF2-989261: context-484804, geo-context, listening-post-app,
  morning-brief-tic), not per project: Cloud Storage 5 GB-months in us-central1/us-east1/us-west1, 5,000 Class A
  (writes, lists) and 50,000 Class B (reads) a month, 100 GB egress; BigQuery 1 TiB scanned a month; Scheduler
  3 jobs (paused jobs still count, $0.10/job/month after); Cloud Run 2M requests, 180,000 vCPU-s, 360,000 GiB-s,
  1 GB egress. Verified on Google's pages 28 Oct 2026. Soft-deleted objects are billed like live ones.
- **State lives in Firestore** (Tom's choice, 30 Oct 2026, to keep bucket Class A writes under the free 5,000):
  `pipeline/statestore.py`, `MC_STATE=firestore` on both functions, document `mc_state/ingest` (gzip JSON, ~100 KB;
  larger states split into `mc_state/ingest.1`, ... in one commit) in the `(default)` database shared with v4.3 (free
  20,000 writes and 50,000 reads a day). A missing document falls back to the bucket's `state/state.json`, rewritten
  daily as a backup; any other Firestore error stops the run. `mc-ingest@` needs `roles/datastore.user`, which also
  reaches v4.3's collections. Back to the bucket: redeploy without `MC_STATE` (the state restarts from the last daily
  backup: one two-hour GDELT re-read and a day of repeat feed rows, which the build drops).
- Feeds remember 8-character fingerprints (`seen_fp`) in last-listed order, sized per feed (`max_items`); a forgotten
  link seen again costs one cycle row, never a double count.
- Events records ride in each run's cycle file as `"kind": "events"` rows (older ones, and backfills, in `events/`);
  the story build skips them.
- The bucket (soft delete 7 days) gzips every object it writes (`pipeline/sinks.py`; ~17 MiB a day, so 5 GB lasts
  into mid-2027). Reads take gzip or plain; local folders stay plain. `gcloud storage cp` unzips, `gcloud storage
  cat` prints raw gzip.
  `scripts/recompress.py` converts plain objects (dry run by default). Past 5 GB, the free path is moving older files
  to Tom's own storage.
- Poll every 15 minutes: 30 risks dropping items from the busiest feeds (TASS-ru, the Air Force Telegram) on heavy
  strike nights.
- Count Class A in Cloud Monitoring (`storage.googleapis.com/api/request_count` by method, a free read) with hourly
  alignment. Every build read is bounded; no BigQuery anywhere in Watchfloor.
- Same account: GEO CONTEXT v4.0's job `generate-watchcon-data` (project `geo-context`) was paused 29 Oct 2026 on
  Tom's yes; deleting it is Tom's. Scheduler has 6 jobs on the account (3 free).
- Windows: use `python`, not `python3`; run downloaded-data tooling with `python -I`.
- Current-situation research (charters, briefs): MORE CONTEXT's own stories first (`mc-api` `/zone`), then
  extended web searches with month, year, outlets and conflict trackers in the query; a date and source on every
  claim; say when nothing recent turns up, never call a zone quiet for lack of results (26 Oct 2026 lesson).

## Layout
- `catalog/entities.json` - zones and Watch Topics, each with a one-sentence `profile` (scope for embeddings and
  prompts) and a `map` position. `match_v43` holds v4.3's exact rules (baseline for comparison); MORE CONTEXT's own
  matching replaces them in Phase 2.
- `catalog/sources.json` - 124 sources in 20 groups (catalog 2026-11-14.1): 99 polled (53 news feeds, 21 Google
  News searches by zone or topic, 18 outlets read through Google News `site:` searches, 7 Telegram channels), 1 to
  retry (Granma), 10 dropped (not read at all), 14 GDELT-only. 2026-11-14.1 added Radio Tamazuj, DVB English and
  Sudan War Monitor (an ordinary feed with `entity`, so every item is a Sudan item), moved Crisis Group to a site
  search (its feed stopped at 30 Oct) and recorded Oryx as dropped (its loss lists are updated in place). They include the front-line sources Tom approved on
  27 Oct 2026: Suspilne, RBC-Ukraine, Meduza (ru, en), ISW (now through a site search, since its site refuses
  automated requests) and 7 Telegram channels (`format: telegram`): Ukrainian Air Force (nightly tallies), General
  Staff, Russian MoD, DeepState, Rybar, Two Majors, WarGonzo. Group `iranian_exile` is Iran International (doctrine
  grade proposed C). `rss_status` means how a source is read: `dropped` = not read, `none` = read only through
  GDELT (checked against measured GDELT counts).
- `catalog/blocklist.json` + `pipeline/blocklist.py` - sites left out (Tom, 31 Oct 2026), each with its reason:
  GDELT rows by domain or URL pattern at ingest (`cycle.gdelt_rows`) and again at day build (`daily.build_day`);
  Google News items by publisher tail at ingest (`feeds.poll`) and at build. GDELT Events (country counts) are
  not filtered.
- **Two-source rule (Tom, 27 Oct 2026):** an indicator hit counts once two independent sources report it
  (different outlets, not both from the same government); an official claim counts once an outlet outside that
  government reports it. Single-source hits are shown as "claimed" and do not move the ladder. Use `owner` + `group`.
- `catalog/indicators/` - per-zone charters (key questions + indicator ladder). Tom writes these.
- `catalog/title_terms.json` - multilingual headline terms per entity: the free keyword baseline for relevance.
- `catalog/eval/` - relevance test sets (`relevance_v1.jsonl`: 278 stories labelled on/off/unclear, Claude's
  draft, accepted by Tom 26 Oct 2026 as the working set) + population files for weighting. Rules and results: `catalog/eval/README.md`.
- `catalog/vertex_prices.json` - Gemini prices with source and date checked.
- `pipeline/` - Python, standard library only so far. `python -I run.py <command>` (run.py makes `python -I` work):
  `cycle` (local dry run of one cycle), `measure-reprints --hours 6`, `rss-poll`, `feed-health`, `build-stories
  --day YYYY-MM-DD --root <folder>`, `eval-relevance`, `vertex-estimate` (free), and `code-stories --cap <USD>`,
  which is BILLABLE: Tom's yes first.
  - Ingest: `cycle.py` (one 15-minute cycle: new GDELT files, late ones retried up to 3 h, never blocking; one feed
    poll; writes `cycles/YYYY/MM/DD/HHMMSS.jsonl` and the state), `gdelt.py` (GKG 2.1 15-minute files, English +
    translation streams), `events.py` (GDELT Events 2.0), `feeds.py` + `rss.py` (RSS, Atom and RDF with
    ETag/Last-Modified; titles + short leads only), `telegram.py` (public channels via `t.me/s/<channel>`, no account;
    latest ~20 posts, so very busy channels can drop posts between polls), `health.py` (fresh / late / stale /
    failing / never against each source's interval), `sinks.py` (local folder or GCS), `statestore.py`,
    `instance.py` (restarts the Cloud Run instance after refused searches).
  - Build: `daily.py` (day D is built on the first run after D+1 03:15 UTC from rows published on D; writes
    `stories/YYYY/MM/DD/stories.jsonl` + `summary.json`), `match.py`, `sources.py` (domain -> source group, so GDELT
    articles get the same groups as RSS items), `stories.py` (exact + near-duplicate grouping, MinHash LSH),
    `feedlabels.py`, `countries.py` (Rising, Elevated, zone violence, `violent.jsonl`), `measures.py` (attention:
    log-scale z vs the entity's previous 28 complete days, weekday-adjusted; the casualty share was removed 27 Oct
    2026, see its docstring).
  - AI and API: `relevance.py` (scores relevance methods against a labelled set), `coding.py` (PLOVER v0.8 event
    types + quads, actors, direction, casualties, frame, confidence; prompt and validation, no calls), `vertex.py`
    (Vertex Gemini REST client, global endpoint, that refuses to run without a spend cap and stops at it),
    `budget.py`, `ondemand.py`, `api.py` (`mc-api`), `feed_v2.py` (`/feed`), `suite.py` (`/suite`).
- `scripts/` - backfills (`backfill.py`, `backfill_events.py`, free), `relabel.py`, `eval_*.py`, `build_*.py`
  (`build_web.py`, `build_interests.py`, FIPS tables), `recompress.py`, `dev_server.py` (local preview of web/
  against a local data folder; AI off), `deploy_ingest.sh`, `deploy_ai.sh`.
- `main.py`, `requirements.txt`, `.gcloudignore` - Cloud Run function wrapper (`mc-ingest`).
  `scripts/deploy_ingest.sh` creates bucket, service accounts, private function, one Scheduler job.
  Local dry run: `python -I run.py cycle`. Redeploy after code changes with the `gcloud functions deploy`
  line from `scripts/deploy_ai.sh` (needs Tom's yes, like any deploy). **In PowerShell, single-quote the env-var
  argument:** `'--set-env-vars=MC_BUCKET=more-context-484804,MC_AI=on,MC_STATE=firestore'`. PowerShell runs `gcloud.ps1`, which turns an
  unquoted `a,b` into a list and rejoins it with a space: on 29 Oct 2026 that deployed `MC_BUCKET` as
  `more-context-484804 MC_AI=on` and every run failed with "Invalid bucket name" until redeployed. After any
  deploy, check `gcloud functions describe mc-ingest --gen2 --region=us-central1 --project=context-484804
  --format="json(serviceConfig.environmentVariables)"` shows each variable separately. **No rollback by traffic:**
  old revisions' images are cleaned up ("Container import failed"), and a failed `gcloud run services
  update-traffic` still pins the spec to the dead revision, so later deploys are refused until
  `gcloud run services update-traffic mc-api --to-latest` (6 Nov 2026). Fix forward and redeploy instead.

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

## Feeds and saved searches
- Feed items (RSS, Telegram, saved searches) get zone labels when the day is built (`pipeline/feedlabels.py`):
  a saved search (source with `"entity"`) belongs to its zone; other items count for each zone whose headline
  terms they contain, within the source's `focus` when it lists zones. They become `kind: "feed"` stories,
  shown on the zone page under "From news feeds and searches" and kept out of the GDELT counts and baselines.
- 21 Google News searches (`gn_<entity>`) and 17 `site:` searches (outlets that turn away cloud addresses, such as
  france24_en, rfi_afrique, timesofisrael and reliefweb, and wires GDELT lacks) are polled hourly (`poll_minutes`).
  A site search keeps the outlet's id, group and focus; `url` is the search, `feed_url` the old feed, `query` the
  readable search. `feeds.is_search` treats any `news.google.com/rss/search` address as a search; `feedlabels` cuts
  the " - Publisher" tail (otherwise "The Times of Israel" puts "Israel" in every headline) and names the outlet;
  items with no headline are dropped at ingest. Google's terms are understood (secondary sources only, 27 Oct 2026)
  to allow personal, non-commercial use: review before Watchfloor earns money.
- Google refuses Cloud Run's changing addresses in multi-hour blocks (expected). Each run tries one search first and
  holds the rest when refused (probe row `held`); failed searches retry next run (`RETRY_MINUTES`); after a run whose
  searches were all refused (`summary.rss.searches_refused`), `pipeline/instance.py` restarts the instance (SIGTERM
  3 s after the response, only when `K_SERVICE` is set; `restart_instance: true` in the run log) so the next run gets
  a new address. If Google ever refuses every address, switch search source. A fixed address (Cloud NAT) would cost
  money; not done.
- **GDELT carries none of the wires** (Reuters, AP, AFP, Bloomberg, CNN, NYT and many regional outlets; audit 31 Oct
  2026), so the attention counts (GDELT only) never see them; the site searches bring them in as feed stories.
  Myanmar and Sudan remain thin.
- Measure filters at story level, not by distinct headlines. Before calling a feed broken, check
  `consecutive_failures` and the HTTP code, not the fresh count (weekend lulls run 24-34 h). `/status` on a Saturday
  evening reads worse than on a weekday: 15 Nov 2026 01:50 UTC (Saturday 14 Nov, 7:50 PM CST) gave 9 stale and 23
  late, all fetching cleanly.
  A feed can also freeze while still answering 200 or 304 (Crisis Group, 30 Oct 2026), which health never flags; the
  test is new rows per source per day from the cycle files against the source's own weekdays (feed health pass,
  14 Nov 2026, in `HANDOFF.md`).
- A Sudan headline term (`sudan*`) also matches "South Sudan": 9 of 167 Sudan stories on 13 Nov 2026 were South
  Sudan's, GDELT ones included, so they reach the Sudan attention count. Not fixed yet (see `HANDOFF.md`).
- A partial day (ingest started or stopped mid-day) gets no attention z and no alarm.

## Relevance and attention
- Headline terms are the relevance filter: 82% precision / 78% retention on relevance_v1, against 42% on topic for
  v4.3's rules; main location alone is not a fix (`scripts/eval_location.py`, 28 Oct 2026). Attention and alarms
  count headline-filtered stories (`filtered_stories`), and `history()` reads that count. Known noise: Vietnamese
  weather headlines naming "Bien Dong" (the South China Sea).
- Memory guards (from the 28 Oct 2026 out-of-memory incident; the function has 512 MiB): `run_cycle` saves state
  before building; the MinHash token cache is compact and cleared per call; `load_day_rows` keeps only
  `BUILD_FIELDS` and one copy of each (record id, kind, source, link). The link is in the key because GDELT reused
  translation record ids for other articles.

## Rising, map and zone violence (28 Oct 2026, Tom: "start the rising list, then the map, violent events...")
- From GDELT Events 2.0 (~100 KB per 15 minutes against GKG's ~20 MB, so every country is counted live and 90 days
  back for free; `scripts/backfill_events.py`). The daily build writes `stories/.../countries.json` and `violent.jsonl`.
- Counts per country-day: distinct articles with an event located there (`urls`, attention) and with an assault,
  fight or mass-violence event there (`violent`, CAMEO 18-20). Scored against the country's own last 28 complete
  days (log z, weekday-adjusted) and its 90-day median. Rising: z >= 2.5, >= 1.5x expected, >= 40 articles
  (violence: 15). Elevated: >= 2x the 90-day median. Country names: `catalog/fips_countries.json` (FIPS 10-4, as
  GDELT; "RI" is Serbia, "CG" DR Congo, "NG" Niger, "NI" Nigeria). Codes for non-countries ("OS", oceans) are
  never listed. Violence leads the page; attention is noisier (GDELT geocodes names).
- Zone violence replaces the casualty share: violent events placed inside the zone (`countries`, or `violence`
  for Russia-NATO: NATO states + Kaliningrad RS23) in articles whose headline names the zone, z against 28 days.
  Display only, not an alarm reason (yet). The map's event layer (`/violent?zone=`) shows the same events the
  measure counts.
- Map (`#/map`): Leaflet 1.9.4 from `web/vendor/leaflet/`, Natural Earth 110m outlines in `web/geo/world.json`; no tile
  server, so the CSP stays self-only. Local preview: `scripts/dev_server.py` (launch config `watchfloor-dev`, port
  8734) serves web/ and the API from `data/backfill/baseline`; the site switches to it on localhost.
- Cross-language grouping: multilingual embeddings (Vertex, billable) are the route (GDELT mentions were too noisy
  and too sparse); needs Tom's yes after a measured sample.

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
- **Switch:** Vertex calls from the cloud happen only with env `MC_AI=on` (both functions since 26 Oct 2026, approved
  by Tom; `mc-ingest@` holds roles/aiplatform.user). Kill switch: redeploy with MC_AI=off.
- **Public API:** https://mc-api-odg3xhcd4a-uc.a.run.app (`/status`, `/zone?entity=&day=`, `POST /code`; also
  `/entities`, `/days`, `/summary`, `/countries`, `/violent`, `/feed`, `/suite`), open to anyone, max 1 instance,
  concurrency 1. The first call coded 25 stories for $0.0049; a repeat is served from the cache for $0.
- The ledger counts list prices; Google's bill is the final word. A Cloud Billing budget alert is the backstop.

## Cloud (deployed 26 Oct 2026, approved by Tom)
- Function `mc-ingest` (Cloud Run functions gen2, us-central1, python312, 512 MiB, 300 s, max 1 instance),
  runs as `mc-ingest@context-484804.iam.gserviceaccount.com`. Private: anonymous calls get 403; only
  `mc-scheduler@` holds `roles/run.invoker`.
- Scheduler job `mc-ingest-15min`, `5,20,35,50 * * * *` UTC, OIDC token, 320 s deadline. It is not a v4.3
  duplicate; v4.3's own job is `trigger-context-update`.
- Bucket `gs://more-context-484804` (us-central1, uniform access, public access prevented):
  `cycles/YYYY/MM/DD/HHMMSS.jsonl` (rows kind=gdelt|rss) and `state/state.json` (GDELT progress and
  retry lists, feed health, last run summary). Since 30 Oct 2026 the live state is the Firestore document
  `mc_state/ingest` and `state/state.json` is its daily backup; objects are gzip, so download rather than cat:
  `gcloud storage cp gs://more-context-484804/state/state.json .` (cp unzips).
- `tests/` - `python -m unittest discover -s tests -t .` (CI runs this on every push).
- `data/` - downloads and reports, git-ignored.

## Build status
- Phase 1: GDELT + RSS ingest in the cloud every 15 minutes since 26 Oct 2026 (gate: 7 days of stored data, about
  2 Nov, and reprint inflation measured: 1.25x overall). Phase 2 (relevance, then coding) started 26 Oct 2026; its
  first findings and the first Vertex run are in `HISTORY.md`.
- Coding prompt code-v0.2 (topics overlap zones; confidence rule) is not yet re-run. Score a codings file with
  `python -I run.py eval-relevance --codings data/coding/relevance_v1.codings.jsonl`. Estimates: ~$188/month to code
  every v4.3 match, ~$12/month ($6 batch) for the top 100 stories per entity per day, so code only filtered or top
  stories.
- Casualty flags (`killed`/`wounded` on GDELT rows, per-story tallies) exist from 26 Oct 2026 20:57 UTC; measures
  count only rows that have them. Attention z needs 14 complete days, so it first appears around 10 Nov.
- Charters: Claude drafted four (Ukraine, Israel-Gaza-Lebanon, Iran & Red Sea, India-Pakistan) on 26 Oct 2026 in
  the plan doc's "Indicator charters (draft)" tab; Tom marks them up, then an interview settles open questions;
  the final versions go to `catalog/indicators/` as catalog data. Budget decided: $5/month AI cap (see above);
  a Cloud Billing budget alert ($5, project context-484804, 50/90/100% actual + 100% forecast) emails billing admins.
- Waiting on Tom: charter mark-up and interview; decisions on the source list (plan doc, "Source list (draft)" tab).
  Current decisions and next steps: `HANDOFF.md`.
