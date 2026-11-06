# Watchfloor handoff (session "Geo-context project review", archived 4 Nov 2026)

Read `CLAUDE.md` first; this file is current state and next steps. Times CT.

**Update 6 Nov 2026:** GitHub CI passed on 6f3a63d and on the two house-bar commits after it. Next
step 1's `CLAUDE.md` note is done: the boxes are in its Doctrine kit section and the parked branch in its
header.

## Where things stand (4 Nov 2026, 3:01 PM CT, when the usage limit hit)
- **Live and healthy.** mc-ingest-00019-gux and mc-api-00013-bif (built from df04a4b), website deployed 1 Nov.
  4 Nov 20:05 UTC run: 80 feeds fresh, 16 late, 0 failing. The 17 Google News `site:` searches work from the cloud
  (Google refuses searches in multi-hour blocks, e.g. 3-11 PM CT on 30-31 Oct; that is expected).
- **Committed and pushed (not yet deployed):** 6f3a63d geometry matching (sea-area `boxes` in
  `scripts/build_interests.py` / `doctrine/interests.json`, doctrine kit 0.4.1). 186 tests pass locally; **GitHub
  CI on 6f3a63d was not checked.** The live "From the suite" panel places NGA warnings by geometry only after an
  mc-api deploy (Tom's yes).
- **Uncommitted on main:** nothing (only `.claude/`).
- **Local branch `wip/2026-11-01-unreviewed` (459d578, never pushed):** work a session left uncommitted on 1 Nov
  (no transcript found). Not finished; needs Tom:
  - `catalog/indicators/{01,06,10,11}.json` and `WF-Z*-IND-*` (13 indicators) in `doctrine/indicators.json`:
    zone charters that session wrote itself. `catalog/indicators/README.md` says Tom writes the charters.
  - `pipeline/coding.py` (load_charters) and `pipeline/feed_v2.py`: charter hits would make a zone an anomaly in
    /feed (and on COP). Tests on that branch passed (188).

## Decisions waiting on Tom
1. Deploy mc-api for geometry matching in the panel.
2. Review the 13 AI-drafted charter indicators: adopt, rewrite or discard (then merge or delete the branch).
3. October usage totals: run `gcloud auth login`, then measure Class A and BigQuery for October (script idea:
   Monitoring request_count hourly sums + `INFORMATION_SCHEMA.JOBS_BY_PROJECT`, ~10 MB billed per project).

## Next steps, in order
1. Watch CI on 6f3a63d; add a `CLAUDE.md` note on the boxes and the parked branch.
2. Plan step 1 (approved 1 Nov): add Radio Tamazuj (`https://www.radiotamazuj.org/en/rss`), DVB English
   (`https://english.dvb.no/feed/`), Sudan War Monitor (`https://sudanwarmonitor.com/feed`) and Oryx
   (`https://www.oryxspioenkop.com/feeds/posts/default`) to `catalog/sources.json`; all worked from Tom's machine on
   1 Nov; test from the cloud after deploy.
3. Indicators that act on tips (step 3 of the tipping plan), after the charter decision.
4. Headline service for other programs (step 4); Bluesky/Telegram lists need Tom's picks (`presstv`, `farsna`
   Telegram channels live but ownership unconfirmed).
5. Requests to other programs: Elements to mark FIRMS anomalies against its baseline (`data/firms_daily.json` is not
   published); Vigil to tag state-linked actors.

Cross-project items (kit 0.4.1, COP, the four seed-data programs, Cordon/Verdict, other files):
`D:\Projects\CLAUDE_HANDOVER.md` §3.12.
