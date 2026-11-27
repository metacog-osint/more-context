# Watchfloor method (doctrine summary)

The full method is in `CLAUDE.md` (measures, tests and incidents) and the build plan. This page states it in the terms
of The Intelligence Company's doctrine kit (`doctrine/kit/`).

## How sources are gathered
- **GDELT** (GKG 2.1 and Events 2.0, every 15 minutes) is the main source and the only one the measures below count.
  It does not carry many major outlets (none of Reuters, AP, AFP, Bloomberg, CNN, NHK, Kyodo, Iran International,
  Hiiraan, Addis Standard, ISW and others in 52,618 raw articles on 30 Oct 2026; WF-AS-5).
- **Read by Watchfloor itself** (`catalog/sources.json`): publishers' feeds, public Telegram channels, a Google News
  search per zone and topic, and Google News `site:` searches for outlets GDELT misses or whose feeds turn away
  automated readers. Their stories appear on the zone pages, kept out of the counts so each day stays comparable with
  the zone's history.
- **Left out** (`catalog/blocklist.json`): sites that are not news or only copy it (a court-records database,
  press-release wires, the Big News Network's ~100 reprint sites, radio-station copies, two aggregators). Removing
  them changed attention counts by 0-3% on 29-30 Oct 2026; they are dropped so story cards and outlet counts stay
  honest.

## What it measures
- **Attention:** GDELT articles about each zone and topic, grouped into stories so reprints count once, kept only when
  the headline names the zone (82% precision, 78% retention on the labelled set; likely flattered, see WF-AS-2).
- **Zone violence:** articles with an assault, fight or mass-violence event (CAMEO 18-20) placed in the zone's
  countries and a headline that names the zone.
- **Countries:** every country's article and violent-event counts from GDELT Events 2.0, with the Rising and Elevated
  lists.
- **Framing:** articles by source group, and on-demand story coding (frame, direction, actors) with Gemini under a
  $5 monthly cap.

## Baselines
Each measure is compared with the entity's own previous 28 complete days (log-scale z, weekday-adjusted) and with
its 90-day median. Both are rolling. JP 2-01.3 warns that a steady signal can come to look normal: a long war can sit
inside the 28-day window (Ethiopia, 27 Oct 2026), so the 90-day ratio is published beside every z (WF-IND-3).

## Anomaly versus warning
Everything Watchfloor publishes today is a measurement (kind observation; tier routine or anomaly). Warnings, which
are judged and carry likelihood and confidence, come only through the zone charters once they are final
(`catalog/indicators/`); until then no watch condition is set and anomalies move nothing.

## Two-source rule and independence
An indicator hit counts once two independent sources report it: different outlets, not owned by the same government.
An official claim counts once an outlet outside that government reports it; until then it is drawn hollow
(`status_class: claimed`). Lines of evidence for confidence: GDELT machine coding is one line; each independent outlet
group that reports a hit is another.

## Gaps and no data
A partial day (ingest started or stopped mid-day) gets no attention z and no alarm. Feeds that refuse cloud addresses
are listed in `CLAUDE.md`. A missing day turns its layer grey ("no data"), never quiet. Single events can be misplaced
by GDELT's geocoder, so Watchfloor reads country counts, not single events.

## Feed
`GET /feed?day=YYYY-MM-DD` on the public API returns the day in feed contract v2 (`tic-feed/2`, GeoJSON), built from
the same files as `/summary` and `/countries` (`pipeline/feed_v2.py`). Each item is checked by the kit's contract
linter; an item that fails is left out and listed in the feed header.
