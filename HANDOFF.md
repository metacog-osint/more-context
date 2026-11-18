# Watchfloor handoff

Current state and open items. Read `CLAUDE.md` first. Replace lines as they change; delete items when done; leave
shas and "landed" notes to git. Slimmed 18 Nov 2026 from 27 KB; the full earlier handoff (build checks, rescore
figures, South Sudan exclusion, feed health pass, Crisis Group checks) is
`D:\Projects\_ideas\archive\watchfloor-HANDOFF-2026-11-18.md`. Times UTC unless marked.

## State (18 Nov 2026; measure before acting)
- Live: `mc-ingest-00026-fur`, `mc-api-00025-doz` (env vars `MC_BUCKET`, `MC_AI=on`, `MC_STATE=firestore`); website
  deployed 16:14 UTC 18 Nov from `5fa2741` (adds the home page's "Elsewhere today" card). origin/main `5fa2741`.
- 17 Nov build checked (03:21 UTC 18 Nov): all outputs written, not partial, no retry or relations error; `/feed`
  42 items, none dropped. AI spend $0.05 of $5 for November (15 Nov).
- Main checkout `D:\Projects\more-context` was 3 commits behind origin with an uncommitted `CLAUDE.md` line (the
  "Elsewhere today" note, folded into the slim `CLAUDE.md` and this file): drop it with `git checkout -- CLAUDE.md`
  once the slim lands (Tom's yes). Untracked there: `.claude/`, `GEMINI.md` (another tool's notes).
- Worktrees with uncommitted work, each another session's:
  - `_worktrees\watchfloor-iran-charter` (`charter/iran-red-sea`): edits to `CLAUDE.md`, `catalog/entities.json`,
    `catalog/indicators/README.md`, `pipeline/countries.py`, `tests/test_events.py` (Iran & Red Sea violence scope
    from the 18 Nov charter answers, `scripts/rescore_zone_scope.py`). Its `CLAUDE.md` line must be re-added to the
    slim file as one short bullet under "Zone violence", not merged over it.
  - `_worktrees\watchfloor-shell` (`layout/elsewhere`): clean at `5fa2741`.
- Branches: `wip/2026-11-01-unreviewed` (`459d578`, AI-drafted charters; do not merge, use its 13 indicators only as
  a draft for Tom's own); `tic-nav-v1.13`, `tic-nav-v2.0` (old local house-bar branches).

## Decisions waiting on Tom
1. The zone charters: interview one zone at a time, Iran & Red Sea first (December three-signal watch); final
   versions go to `catalog/indicators/`. A session is on Iran & Red Sea now (worktree above).
2. Oryx: keep dropped (feed's newest post 7 Dec 2024; loss lists are edited in place), or poll it anyway.
3. ReliefWeb API `appname` (free; Tom requests it): would replace the ReliefWeb site search, which drops 2 in 5 items
   for having no headline. Not urgent.
4. October usage totals (Class A and BigQuery), carried from 4 Nov.
5. Delete GEO CONTEXT v4.0's paused Scheduler job `generate-watchcon-data` (project `geo-context`, paused 29 Oct).
6. Website public or not (remove noindex, X-Robots-Tag, robots.txt; link from CONTEXT).
7. Source list decisions (plan doc, "Source list (draft)" tab); source grades are proposed.

## Decided 18 Nov 2026 (Tom)
- Independent origins: z stays on articles; an `origins` count is carried beside the article count on country
  items (`docs/method/2026-11-18-origins.md`).
- Feed contract D11 ("reported, then corroborated"): all four picks, `_ideas\feed-contract-proposal-2026-11.md`
  section 9. Built after kit 0.6.0; Wake and Cordon first.

## Next steps, in order
1. Press tone stays display only: Tom reads the zone pages' press tables for a month from 16 Nov before any flag,
   alarm or `/feed` item.
2. Charters (above), then indicators that act on tips (tipping plan step 3).
3. Headline service for other programs (step 4); Bluesky/Telegram lists need Tom's picks (`presstv`, `farsna`
   Telegram channels live, ownership unconfirmed).
4. Requests to other programs: Elements to mark FIRMS anomalies against its baseline; Vigil to tag state-linked actors.
5. Re-run coding prompt code-v0.2 (billable; Tom's yes).

## Watch, nothing to build
- Crisis Group's site search catches its pieces again (18 Nov); 14-16 Nov was a publishing lull. Its own feed is
  frozen at 30 Oct; the site blocks scripts (respected).
- Tehran Times had full-day zeros on 5 and 12 Nov; Yonhap low on Saturday 14 Nov.
- Some 7-day press-tone z run large on a short baseline (UK press on Ukraine z 10.2, 16 Nov); cause not checked.
- Rising listings added by the 17 Nov rescore have no sample headlines or map events (stored as built).
- Known term misses: Arabic "جنوب السودان" also means "southern Sudan"; Abyei left out of Sudan's terms (Tom, 15 Nov).
