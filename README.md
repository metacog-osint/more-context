# MORE CONTEXT

A warning-and-awareness monitor for 15 conflict zones and 5 strategic Watch Topics, built from
publicly available news data (GDELT). It groups reprinted articles into stories, codes each story with
Gemini on Vertex AI, and tracks indicators, attention, escalation and how different source groups frame
the same events. Every signal is backtested before it drives a status.

Built by Thomas Brummer, The Intelligence Company. Not affiliated with any government.
Publicly available information only. A media signal, not ground truth.

## Run the reprint measurement

```
python -I -m pipeline.cli measure-reprints --hours 6
```

Downloads the last 6 hours of GDELT GKG files (English and translated streams), keeps articles that
match a zone or topic, groups them into stories, and writes a report to `data/reports/`.

## Tests

```
python -m unittest discover -s tests -t .
```
