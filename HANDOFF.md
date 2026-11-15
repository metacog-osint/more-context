# Watchfloor handoff

Read `CLAUDE.md` first; this file is current state and next steps. Times CST unless marked UTC.

## Where things stand (14 Nov 2026, about 8:45 PM CST; feed health pass)
- **Live and healthy** (measured 15 Nov 01:35-01:55 UTC): ingest every 15 minutes (last run 01:35 UTC, GDELT read
  through 01:45 UTC), days built through 13 Nov (14 Nov builds after 03:15 UTC 15 Nov), `/feed` in COP fresh
  (41 items for 13 Nov, 19 anomalies, all country-level; no zone or topic above normal). AI spend $0.05 of $5 for
  November. 186 tests passed on `main` before this pass; CI green on the last six pushes.
- **Live revisions not checked this session:** `mc-api-00016-duh` and `mc-ingest-00019-gux` per the 6 Nov notes.
  gcloud was signed out at the start; Tom signed in mid-session.
- **Website:** live with house bar tic-nav v1.10 and another session's contrast fix `ba51ad7` (WCAG AA badges,
  primary button, alarm column header), pushed 14 Nov 7:53 PM. Worktrees `_worktrees\watchfloor-contrast`
  (`contrast-fix`) and `_worktrees\watchfloor-nav110` (`tic-nav-v1.10`) belong to those sessions.
- **Uncommitted on `main` (this pass, not deployed):** `catalog/sources.json` (catalog 2026-11-14.1),
  `tests/test_feedlabels.py` (2 tests), `CLAUDE.md`, this file. Catalog changes reach the cloud only with an
  `mc-ingest` deploy (Tom's yes); the Sources page needs `scripts/build_web.py` and a hosting deploy.

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
  so they reach Sudan's attention count. Fix proposed, not built: exclusion phrases per entity in
  `catalog/title_terms.json` ("south sudan*" and its translations) removed before matching, scored on
  `relevance_v1`, then a relabel of stored days so the baseline matches.

## Decisions waiting on Tom
1. Commit this pass (catalog, test, notes) to `main` and deploy `mc-ingest` so the cloud reads the new sources.
2. Oryx: keep dropped, or poll it anyway.
3. The South Sudan exclusion (above): build it.
4. The zone charters: still none in `catalog/indicators/`. The AI-drafted ones on `wip/2026-11-01-unreviewed`
   (`459d578`) were reviewed 14 Nov in `D:\Projects\CLAUDE_HANDOVER.md`: do not merge; use the 13 indicators as a
   draft for Tom's own charters.
5. October usage totals (Class A and BigQuery), carried from 4 Nov.

## Next steps, in order
1. After a deploy: check the three new feeds and the Crisis Group search from the cloud (`feed_health` in the
   Firestore state, `mc_state/ingest`).
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
