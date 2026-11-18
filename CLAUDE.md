# Watchfloor (working name MORE CONTEXT)

Tom's parallel rebuild of CONTEXT (v4.3, `D:\Projects\geo-context`, context.theintelligence.company); both are built
and scored side by side and the better parts win. Publicly available information only, no classification markings.
Public repo `metacog-osint/more-context`: nothing private in tracked files.

**Current state and open items: [`HANDOFF.md`](./HANDOFF.md)**; read it first. Fuller notes: `HISTORY.md`, `docs/`;
pre-slim text (18 Nov): `D:\Projects\_ideas\archive\watchfloor-CLAUDE-2026-11-18.md`. Plan:
https://claude.ai/artifact/ShyAN6L2qhb6MBiq5284kk. Keep this file under 12 KB.

**Name (Tom, 27 Oct 2026):** public name Watchfloor; internal ids (repo `more-context`, the functions, bucket and
Scheduler job under Cloud) keep the working name on purpose. Never rename them.

## What it does
Turns GDELT articles and news feeds into stories (reprints grouped), tracks warning indicators per zone, measures
attention, violence, relations between countries and press tone, and codes stories with Gemini on demand. Serves
warning (did something change?) and awareness (what is the picture, how is each side telling it?).

## Commands
- `python -I run.py <command>`: `cycle` (local dry run), `measure-reprints --hours 6`, `rss-poll`, `feed-health`,
  `build-stories --day YYYY-MM-DD --root <folder>`, `eval-relevance`, `vertex-estimate` (free); `code-stories --cap
  <USD>` is **billable** (Tom's yes).
- Tests: `python -m unittest discover -s tests -t .` (CI `ci.yml` runs it plus `doctrine/kit/tic.py kitcheck` and
  `registers doctrine` on every push and PR; **CI does not deploy**). 39 `tests.test_match` failures are expected
  locally: they read `D:/Projects/geo-context/functions/index.js` from disk.
- Local preview: `scripts/dev_server.py --root <data folder>` (launch config `watchfloor-dev`, port 8734), AI off.
- **Deploys are all by hand and each needs Tom's yes.** Deploy from a clean `git archive` of a named commit (assert
  HEAD), never from a shared working tree.
  - Website: `python -I scripts/build_web.py` first (writes the git-ignored `web/build.json` "Updated" date,
    `web/sources.json` and `web/data/fips_iso.json`; without them the date vanishes and the home page's "Elsewhere
    today" card stays hidden), then `firebase deploy --only hosting:watchfloor --project context-484804`. Before it,
    fetch `origin/main` and check the latest hosting release (other sessions deploy too; a 16 Nov deploy rolled back
    another's house bar).
  - Functions: the `gcloud functions deploy` lines in `scripts/deploy_ai.sh`. **In PowerShell single-quote the env-var argument:**
    `'--set-env-vars=MC_BUCKET=more-context-484804,MC_AI=on,MC_STATE=firestore'` (unquoted, `gcloud.ps1` joined them
    into one bad bucket name, 29 Oct). After any deploy check `gcloud functions describe mc-ingest --gen2
    --region=us-central1 --project=context-484804 --format="json(serviceConfig.environmentVariables)"` shows three
    separate variables. **No rollback by traffic:** old images are cleaned up, and a failed `update-traffic` pins the
    spec until `gcloud run services update-traffic mc-api --to-latest`. Fix forward.
  - A change to `catalog/relations.json` needs both functions deployed plus a series rebuild.

## Rules (Tom's standing decisions)
- **Vertex AI (Gemini) is the only model provider.** Free tier first; anything billable (Vertex, new GCP resources,
  BigQuery) is measured on a sample and approved by Tom first. No BigQuery anywhere in Watchfloor.
- GCP project `context-484804`, shared with v4.3: Watchfloor's resources carry the `mc_` prefix. One Scheduler job per
  job, defined here (v4.3's own is `trigger-context-update`). No secrets in files; Tom sets them.
- Hidden from search engines until Tom says public: `noindex` meta, `X-Robots-Tag`, `robots.txt` Disallow. To go
  public remove all three and link from CONTEXT. Footer: "A project of The Intelligence Company. Updated <date>." +
  terms + data credits (GDELT requires citation and link) + a Sources page. `web/app.js` inserts API text as text.
- **Two-source rule (27 Oct):** an indicator hit counts once two independent sources report it (different outlets,
  not one government); an official claim counts once an outlet outside that government reports it. Single-source
  hits show as "claimed" and never move the ladder (`owner` + `group`).
- **Don't recreate other programs' datasets (1 Nov):** check `doctrine/kit/vocab/programs.json` before adding a
  collector. Cordon owns advisories, embassy posture, EASA, NGA warnings; Elements fires, quakes, GDACS; Noisefloor GPS
  interference; Vigil cyber; Verdict dated events. Watchfloor owns the news layer (GDELT, feeds, Google News, Telegram).
- **AI spend on demand, capped (26 Oct):** always-on work costs $0. Alarm = attention z >= 2 and >= 5 stories; each
  15-minute cycle codes at most 2 flagged entity-days (`state.ai.pending`); it is a spending trigger, not a warning
  level. `POST /code` (anyone may call it) codes one entity-day's top 25 uncached stories; `GET /zone` and `/status`
  never spend. A story is never coded twice. Ledger `state/ai_spend.json`: hard cap $5 per UTC month, on-view at most
  $0.50/day and never the last $1. Kill switch: redeploy with `MC_AI=off`. A $5 Cloud Billing alert is the backstop.
- **Costs (29 Oct: no paid usage, lose nothing, keep a historical record):** free tiers are per billing account
  (shared with geo-context and two other projects; figures in `HISTORY.md` "Cost audit"): 5 GB storage, 5,000 Class
  A a month, 3 Scheduler jobs (6 on the account; paused ones count). Past 5 GB, move older files to Tom's own storage.
  Poll every 15 minutes (30 drops items on heavy strike nights).
- Google News terms read as allowing personal, non-commercial use: review before Watchfloor earns money. Never work
  round a site's bot block or robots.txt (Crisis Group's Cloudflare, ISW).
- Current-situation research: Watchfloor's own stories (`/zone`) first, then the global CLAUDE.md rule.
- Press tone and relations are display only: no alarm, no `/feed` item until Tom has read a month of them.

## Cloud
- `mc-ingest`: Cloud Run functions gen2, us-central1, python312, 512 MiB, 300 s, max 1 instance, SA `mc-ingest@`,
  private (only `mc-scheduler@` invokes). Scheduler `mc-ingest-15min`, `5,20,35,50 * * * *` UTC, 320 s deadline.
- `mc-api`: public, https://mc-api-odg3xhcd4a-uc.a.run.app, max 1 instance, concurrency 1: `/status`, `/zone`,
  `POST /code`, `/entities`, `/days`, `/summary`, `/countries`, `/violent`, `/relations`, `/feed`, `/suite`.
- Bucket `gs://more-context-484804` (soft delete 7 days): `cycles/`, `stories/YYYY/MM/DD/`, `relations/series.json`,
  `codings/`, `state/`. Every object is gzip: `gcloud storage cp` unzips, `cat` doesn't.
- **State lives in Firestore** (`MC_STATE=firestore`, `mc_state/ingest`, in the `(default)` database shared with
  v4.3); `state/state.json` is its daily backup and the fallback when the document is missing.
- Website: Firebase Hosting site `watchfloor`, watchfloor.theintelligence.company (CNAME in Squarespace DNS).

## Layout
- `catalog/` is data: `entities.json` (zones and topics; first zone match wins; `match_v43` is v4.3's baseline),
  `sources.json` (`rss_status` `dropped` = not read, `none` = GDELT only), `blocklist.json`, `title_terms.json` (terms
  plus `exclude` phrases blanked first, e.g. "South Sudan" for Sudan), `indicators/` (Tom's charters), `relations.json`
  (Tom's reviewed pairs and `press` blocks), `press_outlets.json`, FIPS tables, `eval/relevance_v1.jsonl`.
- `pipeline/` is standard-library Python; `scripts/` holds backfills, rescores, evals and builders; `data/` is ignored.
- `doctrine/`: registers (SQ1, PIRs, EEIs, warning problems `WF-WP-*`, indicators `WF-IND-1..6`, grades proposed).
  `doctrine/kit/` is vendored: never edit it here; `python D:/Projects/tic-doctrine/tools/sync.py
  D:/Projects/more-context`. `doctrine/interests.json` comes from `scripts/build_interests.py` (edit the script; rerun
  after changing a zone's countries, sea `boxes` or an interest). `doctrine/kit/geo/` must ship with the API.

## How it works (gotchas)
- **Ingest:** GDELT GKG 2.1 and Events 2.0 every 15 minutes, late files retried up to 3 h; feeds remember
  fingerprints (`seen_fp`), so a forgotten link costs one row, never a double count. Day D is built on the first run
  after D+1 03:15 UTC. Memory guards (512 MiB; 28 Oct incident) are in `HISTORY.md`: keep `load_day_rows` lean.
- **Feeds and searches:** feed items become `kind: "feed"` stories, kept out of GDELT counts. Google News and
  `site:` searches (outlets that refuse cloud addresses, wires) poll hourly. Google refuses Cloud Run addresses in
  blocks: after an all-refused run `instance.py` restarts the instance for a new address (Cloud NAT would cost money).
  **GDELT carries none of the wires** (Reuters, AP, AFP...); Myanmar and Sudan stay thin. A feed row counts only on
  its published day.
- **Feed health:** judge a feed by `consecutive_failures` and HTTP code, not the fresh count (weekends are quiet); a
  frozen feed still answers 200 (Crisis Group): compare new rows per day with its own weekdays.
- **Relevance:** headline terms (82% precision / 78% retention on relevance_v1); attention and alarms count
  `filtered_stories`. A partial day gets no z or alarm.
- **Countries (GDELT Events):** distinct articles per country-day, and violent ones (CAMEO 18-20), against the
  country's last 28 days and 90-day median. Rising: z >= 2.5, >= 1.5x expected, >= 40 articles (violence 15).
  Elevated: >= 2x the 90-day median. FIPS 10-4 codes ("RI" Serbia, "CG" DR Congo, "NG" Niger, "NI" Nigeria); `RB`
  (Belgrade) folds into RI. A failed country build retries six times (`countries_retry`, then `countries_failed`;
  rebuild with `backfill_events.py`). Country `origins` (wire copies once) are display only: `docs/method/2026-11-18-origins.md`.
- **z calibration (Tom, 16 Nov; `docs/method/2026-11-16-z-calibration.md`):** every z is normal-equivalent
  (`zstats.py`). Countries `robust-1`; zones, zone violence and pairs `pred-1`; press tone and 7-day pair values T2.
  Badges use `ratio_shown` = count / max(expected, 90-day median, 3). Stored days from 29 Jul are on this scale;
  `rescore_*.py` start at 29 Jul, `--check` first, Tom's yes for `--write`.
- **Zone violence:** violent events in the `violence` scope (Russia-NATO: NATO + Kaliningrad RS23; Iran & Red Sea:
  Iran, Yemen, Iraq, six Gulf states) in articles whose headline names the zone; the map shows the same events.
  `violence.members`: each scope country scored too, z >= 2.5 on 5+ articles is a `spike` (badge, `/feed` anomaly).
  After a scope change: `scripts/rescore_zone_scope.py`, `--check-scope` first. No map tiles.
- **Relations and press tone (15-16 Nov; `docs/relations/`):** articles per directed CAMEO actor pair by QuadClass,
  and outlet country > subject country tone; `/relations` computes z and flags (z >= 2.5 on 5+ articles) on read.
  Backfill `scripts/backfill_relations.py` (`--bucket` writes live: Tom's yes; finish earlier-day runs with
  `--series-only`).
- **`/feed`** (`feed_v2.py`, `tic-feed/2`): every item an observation, date-only (`data_as_of_precision: "day"`,
  `T00:00:00Z`); linter failures go in `dropped`; a day without `countries.json` is `partial_day`. Zone-country items
  are neutral, no hypothesis, until the charters. COP reads it, so a built day reads ~27 h old.
- **"From the suite" panel** (`/suite`): unread sources are named as missing, never quiet; nothing from it counts in
  Watchfloor's measures. The home page's "Elsewhere today" card (hub `tic-related.js`) needs `web/data/fips_iso.json`.
- **Changing the watchlist:** a split within the old zone's rules runs `scripts/relabel.py`; anything wider needs
  `scripts/backfill.py`. Cross-language grouping needs Vertex embeddings (billable).

## Build status
Ingest live since 26 Oct 2026; relevance and coding under way (code only filtered or top stories: ~$12/month
against ~$188 for all). Charters: one interview per zone, then `catalog/indicators/`.
