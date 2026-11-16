# Press tone by outlet country: checks and Tom's outlet picks (15 Nov 2026)

The next layer after the country pairs (`docs/relations/2026-11-15-relations-tone.md`, layer 3). Tom approved
planning the build on 15 Nov 2026 and picked outlets zone by zone the same evening. **Not built.** Data files
named here are in the git-ignored `data/relations/`.

## What each zone measures
For each zone country as the most-mentioned country of a GKG article (GKG 2.1 V2 enhanced locations, field 10,
counted by mention, as the probe did): articles a day and mean tone per outlet country (GDELT's 2018 domain table),
the 7-day mean tone and its z against that outlet country's own 28 days. Display only: no flags, alarms or `/feed`
items until Tom has read it for a month. Each outlet country is read against its own baseline only (tone is a
dictionary score that differs by language and outlet mix).

**Automatic in every zone:** outlets of the zone's own countries about the zone's other countries (South Korean
outlets on North Korea about 36 a day, India on Pakistan 100, Pakistan on India 64, Israel on Lebanon 20, Russia on
Poland 82 and Belarus 42, Russia on Finland 23 and on each Baltic state 5-12).

## Tom's picks (outside outlets, FIPS codes)
Volumes: estimated articles a day where the zone country is the main subject, 1-14 Nov 2026 (one 15-minute file an
hour, both streams, x4; `data/relations/press_all_zones.json`, script `press_all_zones.py`).

| Zone | Outlet countries | Notes |
|---|---|---|
| 01 Ukraine | RS, US, GM, UK, CH, PL, IT, GR, RI, FR | Tom added Poland, Italy, Greece, Serbia, France. Poland and France on Ukraine were not in the top nine (under 76 a day): measure them. |
| 07 Russia-NATO | UP, US, GM, CH, UK | Outside outlets on the Baltic states are all under 6 a day. |
| 02 Taiwan Strait | CH, US, JA | Japan about 4 a day: weekly. |
| 08 South China Sea | CH, US, MY, RP, VM | Tom listed the zone's own countries (Philippines, Vietnam). Their outlets on each other are automatic; confirm with Tom whether he also wants each country's press on itself. Malaysia about 9 a day on Vietnam: weekly. |
| 03 Korea | US, CH, JA, RS, GM | On North Korea only US reads daily (47); Germany 18, Russia 5, Japan 3.4, China 3.1. |
| 10 Israel-Gaza-Lebanon | US, TU, EG, SY, UK, GM, QA | Qatar about 1.4 a day: GDELT's table barely places Qatari outlets; check where aljazeera.com/.net land. Gaza (GZ) and the West Bank (WE) are mostly geocoded as Israel. |
| 11 Iran & Red Sea | US, IS, SA, TU, RS, CH, UK, IN, IZ | On Yemen: Saudi 21, Turkey 20, Israel 15, US 10. |
| 06 India-Pakistan | US, CH, BG, AF, SA | Afghanistan and Saudi under 13 a day. |
| 13 Sudan | US, EG, OD, SA | All weekly (4-13 a day). |
| 18 Ethiopia-Eritrea | US, TU | Weekly; Eritrea has almost nothing (about 1 a day in total). |
| 19 Somalia | US, TU | Weekly (US on 8 of 14 days). |
| 12 Sahel, 14 DRC-Rwanda, 16 Myanmar | none | No outside outlet reaches 8 a day; no press block. |
| 05 Venezuela | SP, US, CO, BR | Brazil about 13 a day. |
| 15 Cuba | US, SP, MX, VE | Venezuela about 6 a day. |

## Checks run 15 Nov 2026 (full day 13 Nov, all 192 GKG files, `data/relations/press_checks.json`)
- **"Spanish outlets about Sweden" is a geocoding fault:** every sampled article carries a location named "Suede"
  in ordinary Spanish local news (abc.es, elconfidencial.com, europapress.es, Diario Vasco, Mundo Deportivo). On
  13 Nov Spanish-language outlets (Spain 511, Argentina 422, Mexico 236, Chile 93, Colombia 91) made about 1,350 of
  2,100 articles mainly about Sweden. Fix: drop V2 location entries named exactly "Suede"; test that real Spanish
  coverage ("Suecia") survives. Cause not verified. US outlets on Sweden (184 a day in the sample) are unexplained:
  check them too.
- **"Madagascar outlets about Taiwan" is storm.mg** (Storm Media, Taiwanese, on Madagascar's .mg): all 86 on 13 Nov.
  Fix: domain override to TW (beside nknews.org and kcna.co.jp).
- **Domain table:** trimmed to the domains seen on 13 Nov, 10,116 domains, 181 KB (64 KB gzip), about 0.2 MB in
  memory (`data/relations/domains_trimmed.txt`); the full table (189,546) takes about 26 MB. 2.0% of articles had
  no outlet country (5,053 of 253,265): mostly post-2018 outlets (unn.ua, dnews.gr, ici.fr, inews24.com,
  punjabijagran.com). Build the trimmed table from a week of domains, add overrides for the largest unknowns.
- **Cost in the cycle (laptop):** the press work adds a median 0.06 s per English file and 0.09 s per translation
  file (max 0.5 and 1.3 s); a run reads 1 English and up to 4 translation files, so worst case about 5 s of 300 s.
  Press rows for a full day: about 0.29 MB gzip (zone countries as subjects, every outlet country).
- **V1 vs V2 locations:** the most-mentioned country differs in 25% of articles (41,236 agree of 54,799); use V2.
- **Backfill:** a full GKG day is 1.3 GB and about 5 minutes on Tom's connection: 28 days (enough for the z) about
  36 GB and 2.5 hours.

## Build plan (approved to plan, not to build)
1. `parse_row` (or the cycle's GKG loop) keeps a per-country mention count from field 10; the cycle adds one
   `kind: "press"` row per GKG file (outlet FIPS > zone FIPS: n_any, tone_any, n_main, tone_main).
2. The daily build sums them into a `press` section of `stories/YYYY/MM/DD/relations.json` and
   `relations/series.json` (no extra writes).
3. `catalog/relations.json`: each zone gains `"press": {"about": [zone FIPS], "outlets": [the picks above]}`; the
   trimmed domain table and overrides go in `catalog/`.
4. `GET /relations` gains `press` rows; the zone page shows "How other countries' press covers <zone>" under the
   pairs.
5. `scripts/backfill_relations.py --press` for history (full files, 28 days); tests; local preview with
   `scripts/dev_server.py`.
6. Tom's yes for each of commit, push, deploy (clean `git archive`, `scripts/deploy_ai.sh` commands, env vars
   checked) and the bucket backfill.
