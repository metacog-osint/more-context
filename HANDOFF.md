# Watchfloor handoff

Read `CLAUDE.md` first; this file is current state and next steps. Times CST unless marked UTC.

## Where things stand (15 Nov 2026, about 4:30 PM CST)
- **Relation pairs reviewed and live.** Tom went through every zone's pairs on 15 Nov; `catalog/relations.json`
  2026-11-15.2 (87 pairs) is `64c1c6f` on `main`, pushed; `mc-ingest-00023-xat` and `mc-api-00020-qec` deployed
  20:38-20:40 UTC from a clean archive, env vars checked; the 20:50 UTC run was clean (288 rows). `/relations`
  serves the new catalog; the new pairs have no history until the 15 Nov redo (next steps), which also rebuilds the
  series. Tom approved that bucket write on 15 Nov ("yes to all four").
- **Press tone by outlet country: planned, not built.** Checks, Tom's outlet picks and the plan:
  `docs/relations/2026-11-15-press-outlets.md`.
- **Crisis Group:** its site search works (HTTP 200; the old ETag/Last-Modified do not trigger 304) but Google News
  lists nothing from crisisgroup.org after 13 Nov 14:32 UTC (checked about 20:50 UTC 15 Nov, a weekend).
- **South Sudan exclusion: live.** `9d42d68` pushed to `main` on Tom's "Yes, all three" (15 Nov); `mc-ingest-00021-ruw`
  and `mc-api-00018-zon` deployed 14:37 UTC 15 Nov from a clean `git archive` of that commit (another session shared
  the folder), env vars checked separate on both. Stored days 29 Jul-14 Nov re-scored in the bucket (section below).
  194 tests pass. 15 Nov is the first day built with the new terms (after 03:15 UTC 16 Nov).
- **Live and healthy** (measured 15 Nov 01:35-01:55 UTC): ingest every 15 minutes, days built through 14 Nov
  (built 03:21 UTC 15 Nov), `/feed` in COP fresh. AI spend $0.05 of $5 for November.
- **Crisis Group's site search runs from the cloud** (first read 03:35 UTC 15 Nov: HTTP 200, 0 items). 0 is right:
  the search is `when:1d` and its newest piece was 13 Nov 14:32 UTC; with `when:7d` it lists 5 (10-13 Nov). Its state
  still carries the old feed's ETag and Last-Modified, which are sent with the search; Google ignores them today.
- **Tone and relations (Tom, 15 Nov):** casualty counts are a small part of what matters; Tom wants relations between
  nations, between people and their governments, how one country's press and people see another, and changes in
  tone (North Korea as the example). Watchfloor uses no tone today: GKG V2Tone is parsed and dropped, and Events'
  actors, QuadClass, Goldstein and AvgTone are read and discarded. A prototype on the Korea zone (90 days of Events
  dyads) runs in session "Watchfloor: relations and tone layer, Korea prototype" (`local_e3467a19`).
- **Website:** live with house bar tic-nav v1.10 and another session's contrast fix `ba51ad7` (WCAG AA badges,
  primary button, alarm column header), pushed 14 Nov 7:53 PM. Worktrees `_worktrees\watchfloor-contrast`
  (`contrast-fix`) and `_worktrees\watchfloor-nav110` (`tic-nav-v1.10`) belong to those sessions.
- **Feed health pass: live.** `32115ec` pushed to `main` on Tom's "Yes, all three" (14 Nov); `mc-ingest-00020-sif`
  deployed 02:43 UTC 15 Nov, env vars checked separate (`MC_BUCKET`, `MC_AI=on`, `MC_STATE=firestore`). The 03:05
  UTC run: 99 sources; Sudan War Monitor fresh (20 items), DVB English fresh, Radio Tamazuj late (12 items, newest
  19:57 UTC). Crisis Group's search had not run yet (polls hourly; its last read was the old feed at 02:35 UTC):
  check it. The website's Sources page still lists the old catalog (`scripts/build_web.py` + hosting deploy, Tom's
  yes).

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

## South Sudan exclusion (live 15 Nov 2026, `9d42d68`)
- **What it does:** `TermMatcher(terms, exclude)` in `pipeline/relevance.py` blanks an entity's exclusion phrases out
  of the folded headline before its terms are searched, so "Sudan and South Sudan sign deal" still counts for Sudan.
  `catalog/title_terms.json` 2026-11-14.1, `exclude.13_Sudan`: 21 phrases in 16 languages. Every user of the matcher
  picks it up: the daily build's `filtered_stories` (attention z, alarms), zone violence `named` (URL words), feed
  labels (Radio Tamazuj's South Sudan items stop counting for Sudan) and mc-api's `/zone`. `relevance_v1` cannot
  measure it (none of its 16 Sudan rows mention South Sudan; no regressions); the evidence is the stored days.
- **Re-scoring stored days:** `scripts/rescore_terms.py` re-scores only the term fields (summary.json
  `filtered_stories`, `filtered_articles`, attention, alarms; countries.json zone `named`, `named_score`) from each
  day's stored stories.jsonl and violent.jsonl, oldest first, without a rebuild; feed stories stay as built.
  Always start at the first stored day, **29 Jul 2026** (countries.json and violent.jsonl from the events backfill;
  stories from 28 Sep): a zone's `named_score` reads 90 days of countries.json. `--check` (no exclusions) must
  reproduce every stored field; checks and dry runs work on copies (`<root>-check`, `<root>-dry`); `--write` re-scores
  `--root` itself and uploads changed files, gzip, each only if its generation matches the manifest (HTTP 412 means
  re-fetch that day).
- **The first check's PASS was false (found 15 Nov).** From 28 Sep it reproduced every count but rewrote all 47 Sudan
  `named_score` blocks without `median90`/`ratio90` (28 also without `z`), so a `--write` would have stripped them; and
  a dry run re-scored `data/rescore` in place, so a later `--write` would have uploaded nothing. Both fixed in
  `9d42d68` (new test for the first).
- **Check 29 Jul-14 Nov: PASS** (109 days, no field changed). **Dry run, Sudan, 28 Sep-14 Nov:** filtered stories
  3,202 -> 2,951 (251 dropped); 11 Nov 68 -> 49 (z -0.59 -> -1.67), 12 Nov 64 -> 43 (-0.07 -> -1.38), 13 Nov 58 -> 44
  (-1.12 -> -1.84), 14 Nov 57 -> 34 (1.38 -> -0.45), driven by South Sudan's election postponement to 11 Feb 2027 and
  Amnesty's Abiemnom massacre report. Alarms: one added (13 Oct, z 1.78 -> 2.25), none lost (12, 20, 21 Oct stay).
  Zone violence `named` 29 Jul-14 Nov: 877 -> 861 (16 URLs; 20 Oct 28 -> 25, 21 Oct 19 -> 17). No other entity changes.
- **Spot check of the 251 dropped stories:** all South Sudan's, except a 9 Oct Arabic headline about a drone strike
  in Blue Nile ("النيل الأزرق جنوب السودان": Arabic "جنوب السودان" is both "South Sudan" and "southern Sudan"). The
  20-21 Oct Abyei market drone strike (153 dead; headlines: "South Sudan accuses neighbor of deadly drone strike")
  left Sudan's counts with 8 stories and 5 violent-event URLs: Tom, 15 Nov: leave "Abyei" out of Sudan's terms
  (who carried out the strike not verified here).
- **Written to the bucket 14:41-14:45 UTC 15 Nov** (`--write`, 29 Jul-14 Nov): 122 files (48 summary.json, 74
  countries.json), none refused; each carries `rescored: {at, terms_version: 2026-11-14.1}`. Read back: 14 Nov Sudan
  34 stories, z -0.45; 13 Oct alarm z 2.25; 20 Oct `named` 25 with its full score (z 3.03, median90 6). `/zone` for
  Sudan on 14 Nov lists 25 stories, none naming South Sudan.

## Decisions waiting on Tom
1. Oryx: keep dropped, or poll it anyway.
2. Website deploy so the Sources page shows catalog 2026-11-14.1.
3. The zone charters: still none in `catalog/indicators/`. The AI-drafted ones on `wip/2026-11-01-unreviewed`
   (`459d578`) were reviewed 14 Nov in `[local path]`: do not merge; use the 13 indicators as a
   draft for Tom's own charters.
4. October usage totals (Class A and BigQuery), carried from 4 Nov.
5. Press tone: the build (`docs/relations/2026-11-15-press-outlets.md`), and whether the South China Sea's
   press block includes each country's press on itself.

## Next steps, in order
1. After 03:20 UTC 16 Nov: check that 15 Nov built with the new terms (summary.json without `rescored`, Sudan's
   filtered count against its re-scored baseline), that the run's summary has `relations_built` and no
   `relations_error`, and that Crisis Group's search has listed a piece.
2. After 03:20 UTC 16 Nov: redo 15 Nov's relations (built as partial; pair tables began at 18:20 UTC; approved by
   Tom 15 Nov): `python -I scripts/backfill_relations.py --bucket more-context-484804 --start 2026-11-15 --end
   2026-11-15 --force` (also rebuilds the series with the 2026-11-15.2 pairs), then check `GET
   /relations?zone=03_Korea_Peninsula` ends on 15 Nov with it complete and a new pair (e.g. `07_Russia_NATO`
   RUS-DEU) has 120 days of history. The API caches 30 minutes.
2a. Build the press-tone layer (`docs/relations/2026-11-15-press-outlets.md`).
3. Charter interview, one zone at a time, Iran & Red Sea first (December three-signal watch).
4. Indicators that act on tips (step 3 of the tipping plan), after the charters.
5. Headline service for other programs (step 4); Bluesky/Telegram lists need Tom's picks (`presstv`, `farsna`
   Telegram channels live but ownership unconfirmed).
6. Requests to other programs: Elements to mark FIRMS anomalies against its baseline; Vigil to tag state-linked
   actors.

## History
- 4 Nov 2026 (session "Geo-context project review"): geometry matching `6f3a63d` (doctrine kit 0.4.1); CI later
  passed. 6 Nov: mc-api `mc-api-00016-duh` deployed from `070ee8f` with `doctrine/kit/geo/` shipped (NGA warnings
  land in zones: Ukraine 3, Russia-NATO 1, Taiwan Strait 1, South China Sea 3, Iran & Red Sea 1).
- 1 Nov 2026: a session left zone charters and charter-hit code uncommitted; parked on `wip/2026-11-01-unreviewed`.
