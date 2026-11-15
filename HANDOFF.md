# Watchfloor handoff

Read `CLAUDE.md` first; this file is current state and next steps. Times CST unless marked UTC.

## Where things stand (14 Nov 2026, about 9:15 PM CST; feed health pass live, South Sudan exclusion built)
- **Live and healthy** (measured 15 Nov 01:35-01:55 UTC): ingest every 15 minutes (last run 01:35 UTC, GDELT read
  through 01:45 UTC), days built through 13 Nov (14 Nov builds after 03:15 UTC 15 Nov), `/feed` in COP fresh
  (41 items for 13 Nov, 19 anomalies, all country-level; no zone or topic above normal). AI spend $0.05 of $5 for
  November. 186 tests passed on `main` before this pass; CI green on the last six pushes.
- **Live revisions not checked this session:** `mc-api-00016-duh` and `mc-ingest-00019-gux` per the 6 Nov notes.
  gcloud was signed out at the start; Tom signed in mid-session.
- **Website:** live with house bar tic-nav v1.10 and another session's contrast fix `ba51ad7` (WCAG AA badges,
  primary button, alarm column header), pushed 14 Nov 7:53 PM. Worktrees `_worktrees\watchfloor-contrast`
  (`contrast-fix`) and `_worktrees\watchfloor-nav110` (`tic-nav-v1.10`) belong to those sessions.
- **Feed health pass: live.** `32115ec` pushed to `main` on Tom's "Yes, all three" (14 Nov); `mc-ingest-00020-sif`
  deployed 02:43 UTC 15 Nov, env vars checked separate (`MC_BUCKET`, `MC_AI=on`, `MC_STATE=firestore`). The 03:05
  UTC run: 99 sources; Sudan War Monitor fresh (20 items), DVB English fresh, Radio Tamazuj late (12 items, newest
  19:57 UTC). Crisis Group's search had not run yet (polls hourly; its last read was the old feed at 02:35 UTC):
  check it. The website's Sources page still lists the old catalog (`scripts/build_web.py` + hosting deploy, Tom's
  yes).
- **Uncommitted on `main`: the South Sudan exclusion** (Tom's "Build the South Sudan exclusion", 14 Nov). See the
  section below.

## Feed health pass (14 Nov 2026)
- **`/status` said 64 fresh, 23 late, 9 stale** at 01:50 UTC 15 Nov, a Saturday evening. All 96 sources fetched
  cleanly that run (HTTP 200 or 304, no failures except one HTTP 500 from Radio Okapi, fine on the next fetch).
- **New rows per source per day, 1-14 Nov, from the 1,343 cycle files** (scratch script, read-only bucket reads):
  every active feed except two ran at its own normal rate. The weekend dip is plain (Breaking Defense, Defense
  News, Irrawaddy, Meduza English, Splash247, TWZ go to 0 on Saturdays and Sundays), so the stale count is a
  weekend artifact.
  - **Crisis Group: broken, fixed in the catalog.** Its feed still answers but stopped at 30 Oct; nothing stored
    after 3 Nov while Google News listed six pieces dated 5-13 Nov. Now a `site:crisisgroup.org` search, like ISW.
  - **Granma:** nothing in 14 days, as expected for a source marked "retry".
  - Watch, not acted on: Tehran Times had full-day zeros on 5 and 12 Nov; Yonhap gave 8 on Saturday 14 Nov
    against 21-35 on earlier weekends.
- **Plan step 1 (approved 1 Nov), tested from Tom's machine 15 Nov:**
  - Radio Tamazuj added (about 13 a day). Most items are about South Sudan; see the South Sudan item below.
  - DVB English added (about 5.5 a day), focus Myanmar.
  - Sudan War Monitor added (about 2.4 a day). 19 of its 20 latest items were in Arabic and name places, not
    Sudan, so it carries `"entity": "13_Sudan"` (every item is a Sudan item, as a saved search is) and `lang: ara`.
  - **Oryx not added**, recorded as dropped: its feed's newest post is 7 Dec 2024. The loss lists are two 2022 posts
    updated in place (last 8 Nov 2026), and a seen link is never new. Its counts belong to a military-activity
    layer (Tempo), not the news feed. This departs from the approved step: Tom's call.
- **Guinea's 13 Nov spike is real:** violent-event articles 79.3x normal (z 6.7) from at least 10 killed in clashes
  between security forces and artisanal gold miners in Siguiri and Balato (Kouroussa) after a mining crackdown
  (DW, Senenews, Koaci, Mining.com, The Northern Miner, AP via US papers). Not a geocoding error.
- **Found: "South Sudan" counts as Sudan.** `sudan*` matches it: 9 of 167 Sudan stories on 13 Nov, GDELT ones too,
  so they reach Sudan's attention count. Built (uncommitted); next section.

## South Sudan exclusion (built 14-15 Nov 2026, uncommitted, not deployed)
- **Files:** `pipeline/relevance.py` (`TermMatcher(terms, exclude)`: an entity's exclusion phrases are blanked out
  of the folded headline before its terms are searched, so "Sudan and South Sudan sign deal" still counts for Sudan;
  given `terms` alone nothing is excluded), `catalog/title_terms.json` (version 2026-11-14.1, `exclude.13_Sudan`:
  21 phrases in 16 languages, note added), `tests/test_relevance.py` (2 tests), `scripts/rescore_terms.py` (new),
  `tests/test_rescore_terms.py` (new, 3 tests). Relevance and feed-label tests pass (32), rescore tests pass (3);
  **the full suite was not rerun after these edits.**
- **Scoring:** `relevance_v1` cannot measure it. None of its 16 Sudan rows mention South Sudan, so precision and
  retention are unchanged (no regressions anywhere). The evidence is the stored stories (dry run below).
- **Every user of the matcher picks it up:** the daily build's `filtered_stories` (attention z, alarms), zone
  violence `named` (URL words), feed labels (Radio Tamazuj's South Sudan items stop counting for Sudan), and
  mc-api's `/zone` (needs an mc-api deploy too).
- **Stored days:** `scripts/rescore_terms.py` re-scores only the term fields of stored days (summary.json
  `filtered_stories`, `filtered_articles`, attention, alarms; countries.json zone `named`, `named_score`) from each
  day's stored stories.jsonl and violent.jsonl, oldest first, without a rebuild. Feed stories stay as built.
  `--check` reruns with no exclusions and must reproduce every stored count before anything is trusted. `--write`
  uploads only changed files, gzip, each only if its generation still matches the manifest.
- **15 Nov session: the first check's PASS was false, fixed.** `--check` from 28 Sep reproduced every count but
  rewrote all 47 Sudan `named_score` blocks without `median90`/`ratio90` (28 also without `z`): a zone's score reads
  90 days of countries.json and the copy started at 28 Sep, while the first stored day is 29 Jul (countries.json and
  violent.jsonl from the events backfill; stories from 28 Sep). A `--write` would have stripped those fields. Fixed in
  `scripts/rescore_terms.py`: `--check` now fails on any changed field (new test), the window starts at 29 Jul, and a
  dry run works on a copy (`data/rescore-dry`); before, a dry run re-scored `data/rescore` in place, so a later
  `--write` would have found no changes and uploaded nothing. 29 Jul-27 Sep and 14 Nov fetched; 194 tests pass.
- **Where the first session stopped (about 03:15 UTC 15 Nov):** `--fetch --check` for 28 Sep to 13 Nov (47 days) was running in a
  background shell. The download finished (`data/rescore/manifest.json` exists; git-ignored); the check result
  was not seen. Rerun without `--fetch`: `python -I scripts/rescore_terms.py --start 2026-09-28 --end 2026-11-13
  --root data/rescore --check`. 14 Nov was being built in the cloud at about 03:20 UTC with the old terms: fetch it
  too (`--start 2026-11-14 --end 2026-11-14 --root data/rescore --fetch`; `fetch` adds to `manifest.json`).
  Re-fetch any day the cloud rebuilt after its fetch, or its `--write` is refused (generation mismatch, HTTP 412).
- **To go live, in order, each step on Tom's yes:** full test suite; dry run with exclusions (what changes for
  Sudan, day by day); commit and push; deploy mc-ingest and mc-api (commands in `scripts/deploy_ai.sh`, single-quote
  the env vars in PowerShell, check them after); then `--write` for every stored day through the last built one,
  away from the daily build at about 03:20 UTC. Then update `CLAUDE.md` (its South Sudan line still says "Not
  fixed yet").

## Decisions waiting on Tom
1. The South Sudan exclusion's go-live steps (above).
2. Oryx: keep dropped, or poll it anyway.
3. Website deploy so the Sources page shows catalog 2026-11-14.1.
4. The zone charters: still none in `catalog/indicators/`. The AI-drafted ones on `wip/2026-11-01-unreviewed`
   (`459d578`) were reviewed 14 Nov in `D:\Projects\CLAUDE_HANDOVER.md`: do not merge; use the 13 indicators as a
   draft for Tom's own charters.
5. October usage totals (Class A and BigQuery), carried from 4 Nov.

## Next steps, in order
1. Check the Crisis Group search from the cloud (`feed_health` and `rss.crisisgroup` in the Firestore state
   document `mc_state/ingest`; read it over the Firestore REST API with `gcloud auth print-access-token`, never
   printing the token). Then finish the South Sudan exclusion.
2. Charter interview, one zone at a time, Iran & Red Sea first (December three-signal watch).
3. Indicators that act on tips (step 3 of the tipping plan), after the charters.
4. Headline service for other programs (step 4); Bluesky/Telegram lists need Tom's picks (`presstv`, `farsna`
   Telegram channels live but ownership unconfirmed).
5. Requests to other programs: Elements to mark FIRMS anomalies against its baseline; Vigil to tag state-linked
   actors.

## History
- 4 Nov 2026 (session "Geo-context project review"): geometry matching `6f3a63d` (doctrine kit 0.4.1); CI later
  passed. 6 Nov: mc-api `mc-api-00016-duh` deployed from `070ee8f` with `doctrine/kit/geo/` shipped (NGA warnings
  land in zones: Ukraine 3, Russia-NATO 1, Taiwan Strait 1, South China Sea 3, Iran & Red Sea 1).
- 1 Nov 2026: a session left zone charters and charter-hit code uncommitted; parked on `wip/2026-11-01-unreviewed`.
