# Watchfloor z calibration: measured proposal (16 Nov 2026)

For Tom's decision. Nothing here is live: no scoring change, no bucket write, no commit, no deploy. Measured
16 Nov 2026, about 9:00-10:45 AM CST, from read-only copies of the stored days. Answers the 15 Nov 2026 suite review,
Watchfloor section (`the private planning notes:1441-1457`).

Prototype code: worktree a separate worktree, branch `method/z-calibration` (from
`origin/main` `017cc35`, uncommitted), folder `scripts/zcal/`: `estimators.py` (the options), `real.py` (stored days),
`sim.py` (event-free simulation), `report_real.py`, `listings.py`, `zones.py`, `zone_filter.py`, `tone.py`. Standard
library only, run with `python -I`. Data copies on C: (`%TEMP%\zcal`): `countries.json` 29 Jul-15 Nov (29 Jul-14 Nov
from `more-context\data\rescore`, 15 Nov and `relations/series.json` read from the bucket), `violent.jsonl` and
`summary.json` read in place from `data\rescore` (no recursive scan).

## Decision (Tom, 16 Nov 2026, about 10:05 AM CST)

Tom picked the recommended option on all four: C for countries and B for zones, zone violence and pair counts; the
ratio floor max(expected, 90-day median, 3); zone-country items neutral now, (b) after the charters; T2 for press tone
and the pairs' 7-day values. Built the same day on branch `method/z-calibration` (section "What was built", at the end).

## Recommendation in brief

| # | Problem | Recommend | Effect measured |
|---|---|---|---|
| 1 | Rising z inflated | Countries: option **C** (pooled weekday shape, median centre, MAD scale with a Poisson floor, predictive term, t on the MAD's degrees of freedom). Zones, zone violence and relation-pair counts: option **B** (same model as today, honest SD) | Event-free: z >= 2.5 on 0.26-0.38% of country-days (live estimator 2.9-3.1%; target 0.62%). Stored days: 1.0-1.8% (live 5.1-5.2%). Feed country items 14.6 a day to 9.7 |
| 2 | "79.3x normal" | Ratio over max(expected, 90-day median, 3); write the count when the floor binds | Guinea 13 Nov 79.3x to 5.0x, still listed (C z 2.70); violence listings at 20x+ 12 to 6 |
| 3 | Zone countries as H1 | (a) neutral now; (b) zone-named articles >= 5 after the charters | (b) keeps 144 of 231 items in 96 days; Russia-NATO and South China Sea countries mostly fail it |
| 4 | Press-tone z | T2: daily-tone SD, weighted means, autocorrelation inflation, t | Event-free 0.5% at abs(z) >= 2.5 (live 6.8%); UK press on Ukraine 10.2 to 3.0 |

Thresholds stay as they are (Rising z 2.5, alarm z 2.0); the estimators change. C runs a little conservative on
event-free data (0.26-0.38% against 0.62%); lowering Rising to about z 2.3 would match the nominal rate, which I do
not recommend until a backtest against dated events exists (the review's UCDP gap, `findings.md:1477`).

## 1. The Rising z-score

**Cause.** `pipeline/measures.py:39-49` (`attention_anomaly`; used for countries at `pipeline/countries.py:191`)
estimates a level and up to seven weekday means from the same 28 days it then scores against, divides by the
population SD of those in-sample residuals (n, not n minus the 7 fitted means), ignores the error in the weekday mean
itself (4 days each), and reads the result as normal. Each step shrinks the SD; on 28 days with 7 weekday means the
first two alone give a factor of about sqrt(28/21) × sqrt(1 + 1/4) = 1.29, and the SD's own noise adds the rest.
`relations._z_logs` (`pipeline/relations.py:241-255`) is the same estimator for the pair counts (flag at z 2.5,
`relations.py:52`).

**Options tested** (`scripts/zcal/estimators.py`):
- **A, live**: replica of `measures.attention_anomaly`. Check: reproduces every stored country z (44,032
  country-days, largest difference 0.005, rounding).
- **B, predictive SD**: same model; residual SD on n minus fitted means; variance × (1 + 1/days on that weekday);
  Student t to a normal-equivalent z. About ten lines in `measures.py`.
- **C, robust, pooled weekday**: one weekday shape for all countries that day (median over countries with a baseline
  mean of 5 or more), centre = median of the weekday-adjusted log counts, scale = MAD × 1.4826, floored at the Poisson
  SD on the log scale (sqrt(mu) / (1 + mu)) and 0.15, predictive term (1 + pi/2n), t on 0.37 (n - 1) degrees of
  freedom (the MAD's efficiency).
- **D, negative binomial**: pooled weekday factors, capped-mean centre, moment dispersion shrunk to the pooled value,
  mid-p tail. **Rejected**: 2.0-2.3% at z 2.5 even on data drawn from a negative binomial (dispersion shrinkage is wrong
  for sparse, overdispersed countries), and its tail hits the numeric ceiling (z 37.5) on large counts such as Poland's
  517 articles on 8 Nov, which would put large countries on top of COP every time.
- **E, robust, half own weekday**: as C with the weekday shape half the country's own. Rejected: 2.6-2.8% at z 2.5 on
  event-free small-count countries (own weekday means from 4 days are too noisy there).

**Event-free simulation** (`scripts/zcal/sim.py`): 453 country-metrics, each with its own measured level and
dispersion (last 90 stored days to 15 Nov, negative binomial, dispersion clipped 0.01-3) and the pooled weekday shape;
70 scored days each after a 28-day warm-up; S1 stationary, S2 with a slow AR(1) drift of the log level (phi 0.95,
SD 0.2). Rising = z >= 2.5, >= 1.5x expected, >= 40 / 15 articles.

| Option | SD of z (S1 / S2) | z >= 2.5, % (S1 / S2) | z >= 3.0, % | baseline under 5 a day: z >= 2.5, % | Rising listings a day with no events (S1 / S2) |
|---|---|---|---|---|---|
| A live | 1.35 / 1.38 | 2.85 / 3.11 | 1.22 / 1.29 | 4.3 / 4.1 | 5.2 / 6.8 |
| B | 0.99 / 1.02 | 0.51 / 0.59 | 0.16 / 0.15 | 1.0 / 1.0 | 0.64 / 1.11 |
| C | 0.97 / 1.00 | 0.26 / 0.38 | 0.08 / 0.10 | 0.36 / 0.52 | 0.56 / 1.01 |
| D | 1.24 / 1.17 | 1.96 / 2.26 | 0.97 / 1.07 | 2.4 / 2.6 | 4.6 / 6.3 |
| E | 1.06 / 1.09 | 1.01 / 1.26 | 0.43 / 0.52 | 2.6 / 2.8 | 0.84 / 1.66 |

Normal reference: 0.62% at 2.5, 0.13% at 3.0. A reproduces the review verifier's figure (SD 1.36, 3.4%).

**Stored days**, 12 Aug-15 Nov 2026 (96 scored days, 22,016 country-days per measure). These contain real events, so
the rates are an upper bound on false alarms; the interquartile SD (IQR / 1.349) reads the body of the distribution,
which events barely touch, and should be near 1.0.

| Option | Attention: SD / IQR-SD | Attention z >= 2.5 | Violence: SD / IQR-SD | Violence z >= 2.5 | Rising listings a day (attention + violence) | Feed country items a day (range) |
|---|---|---|---|---|---|---|
| A live | 1.43 / 1.22 | 5.16% | 1.46 / 1.25 | 5.07% | 6.7 + 4.4 | 14.6 (1-28) |
| B | 1.02 / 0.93 | 1.79% | 1.03 / 0.94 | 1.76% | 2.8 + 1.6 | 8.7 (0-23) |
| C | 1.05 / 0.98 | 1.82% | 0.98 / 0.94 | 0.97% | 3.7 + 2.0 | 9.7 (0-23) |
| D | 1.54 / 1.00 | 3.28% | 1.49 / 0.83 | 2.40% | 5.2 + 3.8 | 12.2 (2-26) |
| E | 1.09 / 1.03 | 2.33% | 1.06 / 0.97 | 2.10% | 4.4 + 2.3 | 10.6 (0-23) |

Live, small baselines (under 5 articles a day) clear 2.5 on 8.9% (attention) and 6.0% (violence) of country-days;
C: 0.61% and 0.36%. Feed items count violence Rising + violence Elevated + attention Rising (`feed_v2.py:189-198`),
15 per list as live; the Elevated rule (2x the 90-day median) is unchanged.

**Past alarms kept and dropped**, Rising listings 12 Aug-15 Nov (live: 646 attention, 424 violence):

| Option | Attention kept / dropped / added | Violence kept / dropped / added |
|---|---|---|
| B | 268 / 378 / 0 | 151 / 273 / 0 |
| C | 287 / 359 / 68 | 160 / 264 / 29 |
| D | 393 / 253 / 109 | 267 / 157 / 96 |
| E | 362 / 284 / 57 | 197 / 227 / 20 |

B can only drop (same centre, wider scale). C also adds listings the live baseline masked after an earlier spike: Nepal
attention 31 Aug-2 Sep (894, 880, 725 articles; live z 2.1, 2.0, 1.2; C 4.2, 4.2, 3.6), Panama attention 9-10 Nov,
Jordan 25 Oct, Serbia 27 Oct, Afghanistan violence 24 Sep (104 articles), Pakistan violence 20 Sep (115). Why each
spiked is not checked here.

Named listings under each option (z; "L" listed):

| Listing | Articles | Live | B | C |
|---|---|---|---|---|
| Guinea violence 13 Nov (clashes in Siguiri and Balato, HANDOFF.md) | 15 | L 6.67 | L 4.10 | L 2.70 |
| Central African Republic violence 23 Sep | 24 | L 7.59 | L 4.47 | L 3.31 |
| Latvia violence 14 Aug (sample headlines: drone shot down) | 125 | L 8.75 | L 3.50 | L 3.18 |
| Germany violence 2 Sep (sample headlines: drone attack on Leipzig airport blamed on Russia) | 255 | L 5.47 | L 3.56 | L 3.55 |
| Poland violence 8 Nov (sample headlines: Krakow shooting) | 517 | L 4.59 | L 3.11 | L 4.13 |
| Albania violence 14 Oct (sample headlines: student protests turn violent) | 64 | L 3.32 | 2.37 | L 2.69 |
| Iran violence 31 Aug (sample headlines: US strikes on Larak Island) | 682 | L 4.68 | L 3.16 | L 3.61 |
| Taiwan violence 13 Nov (the review's fraud-story case) | 20 | 2.27 | 1.68 | 1.33 |

**Spot check of dropped listings** (my reading of the stored sample headlines, six per listing, unverified beyond
that): of 12 violence listings C drops, chosen at random, 9 read as noise (Mexico 6 Sep fiction and local politics,
Switzerland 26 Oct, Sri Lanka 10 Sep, Greece 15 Nov celebrity stories, Czech Republic 12 Aug, UK 9 Nov, Brazil 18 Sep,
Iran 15 Nov, Panama 13 Aug) and 3 carry a real event: Syria 1 Oct (gunmen kill seven on a bus), Iraq 9 Nov (drone
strike on the Khor Mor gas field), Djibouti 13 Sep (Houthi and Red Sea coverage, likely placed in Djibouti by
geocoding). Of 8 dropped by B, 6 read as noise, Libya 14 Aug is unclear (Arabic links only), and Albania 14 Oct is real; B drops
it where C keeps it.

**Zones and topics.** The same estimator sets the zone alarm (`measures.py:70-78`, z >= 2 on >= 5 stories; a spending
trigger for coding). 28 Sep-14 Nov, 711 entity-days (`scripts/zcal/zones.py`; the replica gives the same 47 alarms as
live; 20 entity-days differ in z by more than 0.01): live 47 alarms (6.6%), B 16 (2.3%), C 26 (3.7%). C's pooled weekday shape hurts here:
headline-filtered zone stories do not share GDELT's weekend dip (pooled Saturday -0.35, Sunday -0.47 in log units),
and C drops Taiwan Strait on 12 Nov (185 stories against a usual 60-110; live z 4.26, B 2.93, C 1.89). So zones keep
their own weekday means: B. AI spend is $0.05 of $5 this month (HANDOFF.md), so fewer alarms costs nothing; keeping
today's alarm volume would need a lower alarm threshold under B (not measured).

**Proposal.**
1. `measures.attention_anomaly` becomes B (zones, zone violence `named_score`, and through `relations._z_logs` the
   pair-count flags).
2. `countries.score` uses C for the Rising list, the feed and COP.
3. Rescore the stored `countries.json` and `summary.json` scores with the new estimators (like `rescore_terms.py`:
   `--check` first, a dry run on a copy, Tom's yes before `--write`), so the history and the website agree.
4. Rename "z" in titles to "z (calibrated)" for the first month, so COP and readers know the scale changed on that date.

## 2. "N× normal" on small counts

**What happens.** The title's ratio is `count / expected` (`pipeline/feed_v2.py:63-68` `_times`, ratio from
`pipeline/measures.py:53`). On a baseline of mostly zero days the expected value is near zero: Guinea's violence on
13 Nov was 15 articles against 0.19 expected (Fridays 0, 1, 0, 0), so "79.3x normal (z 6.7)". The z is the bigger
problem for COP: COP ranks Watchfloor items by `measures.score.z` (`../cop\config\programs.json`, the
`watchfloor` strength rule; `tools/snapshot.py:74-87`), and a near-zero baseline with the 0.15 SD floor gives a large z.

**Measured, live listings 12 Aug-15 Nov 2026 (stored `countries.json`):**

| | Attention Rising (656) | Violence Rising (430) |
|---|---|---|
| expected below 1 | 0 | 4 |
| expected below 3 | 3 | 28 |
| ratio 10x or more | 15 | 38 |
| ratio 20x or more | 3 | 12 |

Largest violence ratios: Central African Republic 23 Sep, 24 articles against 0.2 (126.9x); Latvia 14 Aug, 125 against
1.4 (86.2x; the stored sample headlines report a drone shot down in Latvian airspace); Guinea 13 Nov, 15 against 0.2
(79.3x).

**Floors compared on the same listings** (Guinea 13 Nov / Latvia 14 Aug / Bahrain 15 Nov):

| Denominator | Guinea 13 Nov | Latvia 14 Aug | Bahrain 15 Nov (84 vs 2.7, median 4) | Violence listings at 10x+ / 20x+ | Attention 10x+ / 20x+ | Largest |
|---|---|---|---|---|---|---|
| expected (live) | 79.3x | 86.2x | 31.6x | 40 / 12 | 16 / 3 | 126.9x |
| max(expected, 3) | 5.0x | 41.7x | 28.0x | 29 / 7 | 16 / 2 | 41.7x |
| max(expected, 90-day median) | 7.5x | 89.3x (no median yet) | 21.0x | 33 / 9 | 13 / 2 | 120.0x |
| max(expected, 90-day median, 3) | 5.0x | 41.7x | 21.0x | 26 / 6 | 13 / 2 | 41.7x |

(Ratios here are recomputed from the stored, rounded `expected`, so the 10x counts differ by one or two from the
first table.)

The 90-day median alone does not help before a country has 60 complete reference days (`countries.py:47`), which was
every day before about 27 Sep; the fixed 3 always applies.

**z on small baselines under each estimator** (Guinea violence, 13 Nov): live 6.67; B 4.10; C 2.70 (expected 2.0).
Every option still lists Guinea (z >= 2.5, ratio >= 1.5, 15 articles), which is right: HANDOFF.md records the clashes
in Siguiri and Balato as real.

**Proposal.**
1. Ratio in titles: `count / max(expected, median90, 3)`; when the floor binds, write the count instead of a ratio:
   "15 violent-event articles (usually 3 or fewer)". 
2. Minimum baseline before z is shown: keep the 14 complete days, and with the recommended estimator no extra cut is
   needed, because its Poisson floor already holds small-count z down (C: 0.4-0.6% of small-baseline country-days
   clear 2.5 on real data, against 6-9% live; 10 of C's 544 Rising listings have an expected value under 3). Without the estimator change, suppress z when expected < 3 and the
   90-day median < 3 (28 violence and 3 attention listings in 96 days, Guinea 13 Nov among them).
3. COP keeps ranking on `measures.score.z`. Under C the largest listed z in 96 days is 5.6 (live: 11.5, and 5.7% of
   live listings at 6 or more), so no cap is needed; the article count is already in `measures.articles`.

## 3. Zone countries published as supporting escalation

**What happens.** A zone country on the Rising or Elevated violence list becomes a feed item with
`hypothesis_id <zone>-H1`, `direction "supports"`, `indicator_state "present"` (`pipeline/feed_v2.py:177-181` on
`origin/main` `017cc35`; it was 175-179 before the `feed/day-precision` merge). The country count has no relevance
filter: it is every article with a CAMEO 18-20 event GDELT placed in that country (`pipeline/countries.py:7-9`).

**Measured, 12 Aug-15 Nov 2026** (live lists in the stored `countries.json`; headlines from the article links in
`violent.jsonl`, the zone's terms through `TermMatcher`, as zone violence `named` does at `countries.py:80-96`):
- 231 zone-country violence items: 130 Rising, 101 Elevated (not Rising).
- The headline filter can be checked on the articles `violent.jsonl` keeps: events placed below country level
  (`pipeline/events.py:13`), 11,925 of the 20,054 counted articles (59%). Of those, 5,235 (44%) name the zone; the
  median item has 46% naming it.
- Items by country, with how many keep 5 or more zone-named articles:

| Country | Items | Named >= 5 | Country | Items | Named >= 5 |
|---|---|---|---|---|---|
| Ethiopia | 33 | 32 | Poland | 12 | 2 |
| Somalia | 15 | 11 | Norway | 8 | 0 |
| Sudan | 13 | 11 | Philippines | 7 | 0 |
| North Korea | 12 | 11 | Djibouti | 6 | 0 |
| Venezuela | 11 | 8 | Vietnam | 6 | 0 |
| Yemen | 9 | 9 | Finland | 5 | 0 |
| West Bank | 8 | 8 | Estonia | 5 | 0 |
| Iran | 8 | 8 | Belarus | 5 | 0 |
| Lithuania | 9 | 3 | Taiwan | 5 | 1 |
| Gaza | 5 | 4 | Pakistan | 5 | 5 |

- Taiwan on 13 Nov (Elevated, 20 counted, 7 inspectable): 4 name the zone. The filter is not clean either way: the
  Nikkei online-fraud story passes (its headline names Taiwan), the Independent's Nvidia honeytrap story fails, and so
  does a relevant Serbian-language Blic story on unannounced Chinese naval drills (no Taiwan term in its link).
  Option (b) would have left Taiwan on 13 Nov below 5 named articles either way.
- The Russia-NATO countries (Poland, Norway, Finland, Estonia, Lithuania, Denmark) and the South China Sea's
  Philippines and Vietnam almost never pass: their violent-event articles are domestic crime and politics.

**Options.**

| | (a) Neutral, no hypothesis | (b) Count only zone-named articles |
|---|---|---|
| Change | `feed_v2.py:177-181`: drop `hypothesis_id` and set `direction "neutral"` for every country item | per-country named count at build time; an item supports H1 only with >= 5 zone-named articles |
| Items supporting H1, 96 days | 0 (all 231 stay, as neutral observations) | 144 of 231 (named >= 5); 75 with >= 15 |
| Effort | two lines, no data change | `countries.build_day` must count named articles per zone country (the URLs are in the Events records, `events.py:114`), a `countries.json` field, and a rescore of stored days for history |
| Loses | the H1 link for Ethiopia, Sudan, Yemen and the others where it is right | Somalia 4, Venezuela 3, Gaza 1 items fall below 5 |

Recommendation: (a) now (it is the honest reading until the charters set indicators), then (b) as the charter work
defines what a zone country's violence indicates. The `feed/day-precision` branch has merged into `main`
(`017cc35`), so the edit lands on that file as it is now.

## 4. Press-tone 7-day z

**Same family of problem, worse.** `pipeline/press.py:240-270` (`row_view`) compares this week's mean tone with the
7-day values ending 7-34 days before. Those windows overlap, so the 15-28 baseline values span only three or four
independent weeks; their population SD understates week-to-week change, and `TONE_FLOOR` 0.3 is below typical
weekly swings. The same estimator is `relations._window_z` (`pipeline/relations.py:268-282`), whose docstring already
says its z runs large.

**Measured (16 Nov 2026; press series 19 Oct-15 Nov, pair series 19 Jul-15 Nov, `relations/series.json`).**
Two-sided share of |z| >= 2.5; a calibrated z gives 1.2%.

| Data | Live (T0) | T1: daily SD, weighted means, t | T2: T1 + autocorrelation inflation |
|---|---|---|---|
| Event-free simulation, independent days | 6.8% (SD of z 1.37) | 0.7% (0.92) | 0.5% (0.88) |
| Event-free simulation, day-to-day correlation 0.5 | 10.2% (1.54) | 5.3% (1.29) | 3.1% (1.11) |
| Press rows, median >= 8 articles a day, 202 row-days | 26.2% (2.42) | 7.9% (1.40) | 5.9% (1.30) |
| All press rows with median >= 2, 307 row-days | 23.5% (2.28) | 5.2% (1.26) | 3.9% (1.17) |
| Pair Events tone, 120 days, 7,614 pair-days | 12.6% (1.71) | 9.4% (1.50) | 6.2% (1.30) |

At 15 Nov, 37 of 158 press rows (23%) showed |z| >= 2.5 and 12 showed |z| >= 4.

| Row (15 Nov) | 7-day tone vs baseline | Live z | T2 z |
|---|---|---|---|
| UK press on Ukraine | -0.53 vs -3.76 (772 articles) | 10.17 | 2.99 |
| Japan on South Korea | 1.61 vs -0.23 | 6.12 | 3.47 |
| Italy on Ukraine | -0.33 vs -1.79 | 4.87 | 3.01 |
| Greece on Ukraine | -1.70 vs -3.06 | 4.56 | 2.73 |
| Estonia on Lithuania (weekly row, 12 articles) | -0.71 vs 0.80 | -5.03 | -1.06 |
| Poland on Denmark (weekly, 16 articles) | 0.12 vs -1.24 | 4.51 | 0.82 |

UK press on Ukraine: daily tone ran mostly -2 to -6.5 from 19 Oct to 3 Nov and -1.5 to +0.6 on 10-13 Nov; Italian and Greek
press on Ukraine moved the same way the same week, so it is not one UK outlet's artefact, but the cause is not checked
here. UK daily counts are erratic (10 to 349 articles), which is why the weighting by articles matters.

**Proposal (T2).** z = (this week's article-weighted tone - the 21 days before it, article-weighted) / (s ×
sqrt(1/neff_week + 1/neff_base)), with s the sample SD of the baseline days' daily tones (floor 0.3 on the daily SD,
inflated by sqrt(1 + 2 × the first three autocorrelations) when positive), neff = (Σn)² / Σn², converted through
Student t on (days - 1) to a normal-equivalent z. Minimums: 14 baseline days with articles, 10 articles in the week
(as now). With 28 days of history it first scores on 9 Nov rather than 15 Nov. Rows read "weekly" or "thin"
(`press.py:249`) should show the z only when the week has 30 or more articles; the two weekly rows above are where
the live z misleads most. Apply the same change to `relations._window_z` for the pair 7-day values. Press tone stays
display only (HANDOFF.md, next step 1).

## What happens next

Each step waits for Tom's yes:
1. Pick the options (or others) for 1-4.
2. Build them on a branch with tests (`tests/test_measures.py`, `tests/test_feed_v2.py`, a calibration test that runs
   the event-free simulation on a fixed seed and asserts the z >= 2.5 rate stays under 1%).
3. Rescore stored days with `--check`, then a dry run on a copy; Tom's yes for `--write` to the bucket.
4. Commit, push, deploy both functions, each on its own yes. COP needs no change; its next snapshot reads the new z.

Not covered here: the Elevated list (90-day ratio, no z), the zone-violence `named_score` beyond its shared estimator,
and the review's other Watchfloor findings (Serbia RB, the country-build retry, labels).

## What was built (16 Nov 2026, branch `method/z-calibration`)

- `pipeline/zstats.py`: `predictive_z` (B), `pooled_profile` + `robust_z` (C), `weighted_window_z` (T2),
  `floored_ratio`, `t_to_z`. A port of `scripts/zcal/estimators.py` in float arithmetic: on 400 random baselines it
  gives the prototype's z exactly (largest difference 0 for B and C).
- `measures.attention_anomaly` is B; scores carry `z_method` (`pred-1`), `ratio_shown` and `floored`. `ratio` (count /
  expected) is unchanged and still drives the Rising rule.
- `countries.score` is C against the day's pooled weekday shape per metric (`robust-1`); zone violence `named_score`
  stays B. One departure from the prototype: C's centre is a median, so a country with mostly zero days has an
  expected value of 0 and no ratio; `_listed` now passes the ratio test when expected <= 1 (the day already has at
  least 15 or 40 articles). On the stored days 12 Aug-15 Nov this changes no listing (no C listing had expected <= 0).
- `relations._z_logs` is B; `relations._window_z` and `press.row_view` are T2 (the base shown is the article-weighted
  mean of the 21 days before the week; the page says "3-wk avg"). A weekly or thin press row shows its z only from 30
  articles in the week. Check on the copied series: UK press on Ukraine 15 Nov z 2.99, Italy 3.01, Greece 2.73 (as
  the proposal measured). Cost: the Ukraine pairs view went from 0.78 s to 1.40 s on read (cached 30 minutes).
- `/feed` (`watchfloor-feed-1.1`): titles say "calibrated z" when the score has `z_method` and use the floored ratio
  ("at 15, usually 3 or fewer"); zone-country items carry no hypothesis. The doctrine kit refuses an `indicator_id`
  without a `hypothesis_id`, so those items also lose `indicator_id`, `direction` and `indicator_state`; they keep
  their warning problem and `WF-PIR-2`.
- Website: badges use `ratio_shown`, say "usually 3 or fewer" when floored, and name the calibrated z in the tooltip.
- Tests: `tests/test_zstats.py` (event-free calibration on fixed seeds: C and B under 1% at z 2.5, T2 under 3%
  two-sided; t quantiles; Guinea's small baseline; the floored ratio and the zero-centre listing).

Not built yet: the rescore of stored `countries.json` and `summary.json` scores (proposal step 3). Until it runs,
days built before the deploy keep the old z, and titles and badges for them keep the plain "z".

## After (17 Nov 2026)

- Stored days 29 Jul-15 Nov re-scored and written to the bucket by `scripts/rescore_z.py` (04:12-04:18 UTC, Tom's
  yes): 145 files; `--check` with the old estimator and `--verify-new` on the 16 Nov build both passed first. Rising
  attention 290 kept / 366 dropped / 69 added, violence 160 / 270 / 30, zone alarms 18 / 31 / 0.
- With every day on the calibrated scale, "calibrated" was dropped from `/feed` titles (`watchfloor-feed-1.2`) and
  website tooltips at Tom's request, ahead of the planned month; scores keep `z_method`.

