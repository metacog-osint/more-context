# MORE CONTEXT

A warning-and-awareness monitor for 15 conflict zones and 5 strategic Watch Topics, built from
publicly available news: GDELT's article and event files (the main source, and the only one the attention counts
use), plus publishers' own feeds, Google News searches and public Telegram channels for outlets GDELT does not
carry, such as Reuters, AP and AFP (`catalog/sources.json`). Sites that are not news or only copy it are left out
(`catalog/blocklist.json`). It groups reprinted articles into stories, codes each story with
Gemini on Vertex AI, and tracks indicators, attention, escalation and how different source groups frame
the same events. Every signal is backtested before it drives a status.

Built by The Intelligence Company. Not affiliated with any government.
Publicly available information only. A media signal, not ground truth.

## Run the reprint measurement

```
python -I run.py measure-reprints --hours 6
```

Downloads the last 6 hours of GDELT GKG files (English and translated streams), keeps articles that
match a zone or topic, groups them into stories, and writes a report to `data/reports/`.

## Tests

```
python -m unittest discover -s tests -t .
```

## Licence

Copyright © 2026 Thomas Brummer, The Intelligence Company. MORE CONTEXT's code is licensed under the GNU Affero General Public License
v3.0 (`LICENSE`). Third-party and shared files keep their own licences, and data keeps its sources'
terms; both are listed in `NOTICE`.

## AI assistance

This repository is built with AI coding assistance (Anthropic's Claude Code). The Intelligence Company is responsible for everything published here.
