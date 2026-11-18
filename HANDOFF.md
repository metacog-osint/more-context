# Watchfloor handoff

Current state and open items. Read `CLAUDE.md` first. Replace lines as they change; delete items when done; leave
shas and "landed" notes to git. Slimmed 18 Nov 2026 from 27 KB; the full earlier handoff (build checks, rescore
figures, South Sudan exclusion, feed health pass, Crisis Group checks) is
`D:\Projects\_ideas\archive\watchfloor-HANDOFF-2026-11-18.md`. Times UTC unless marked.

## State (18 Nov 2026; measure before acting)
- Live: `mc-ingest-00028-giw`, `mc-api-00027-biw` (env vars `MC_BUCKET`, `MC_AI=on`, `MC_STATE=firestore`, checked),
  and the website, deployed 20:08-20:12 UTC 18 Nov from `7f99841` (Iran & Red Sea charter, on top of `3dae530`'s
  country `origins`, `watchfloor-feed-1.3`). Origins first appear on 19 Nov, the first full day of keyed records
  (built about 03:20 UTC 20 Nov); 18 Nov has none.
- 17 Nov build checked (03:21 UTC 18 Nov): all outputs written, not partial, no retry or relations error; `/feed`
  42 items, none dropped. AI spend $0.05 of $5 for November (15 Nov).
- Main checkout `D:\Projects\more-context` was 3 commits behind origin with an uncommitted `CLAUDE.md` line (the
  "Elsewhere today" note, folded into the slim `CLAUDE.md` and this file): drop it with `git checkout -- CLAUDE.md`
  once the slim lands (Tom's yes). Untracked there: `.claude/`, `GEMINI.md` (another tool's notes).
- **Iran & Red Sea charter: live (18 Nov).** `catalog/indicators/11_Iran_Red_Sea.json` (no code
  reads it yet; only IRN-13 is exempt from the two-source rule). Zone violence counts nine countries; Saudi Arabia kept
  (Tom: "keep all nine, but let's find a way to still highlight spikes of interest"), so each member is scored too and
  a burst is a `spike` (badge, `/feed` anomaly). Suite area widened to the nine. Dry run 29 Jul-17 Nov (data in
  `%LOCALAPPDATA%\watchfloor\zscope` on C:): zone z >= 2 on 3 days, spikes on 11, 12 of 98 scored days flagged.
  Each step on Tom's yes: `--write` 20:04-20:05 UTC, all 112 countries.json 29 Jul-17 Nov (`rescored_scope`, members
  and spikes; read back: 15 Nov Bahrain 8 articles z 3.69, 16 Nov Kuwait, 17 Nov Oman 15 z 3.6). `/feed` 17 Nov: 42
  items, none dropped; Iran & Red Sea is an anomaly naming "spike in Oman". The 18 Nov build (about 03:20 UTC 19 Nov) is
  the first built with nine countries; check it.
- Worktrees with uncommitted work, each another session's:
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
