import tempfile
import unittest
from datetime import date, datetime, timezone

from pipeline import daily, events
from pipeline.sinks import LocalSink


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def g(url, title, published, labels=("01_Ukraine_Conflict",), group=None, domain="x.com"):
    r = {"kind": "gdelt", "url": url, "title": title, "published": published, "labels": list(labels),
         "domain": domain, "lang": "eng"}
    if group:
        r["group"] = group
    return r


class DaysTests(unittest.TestCase):
    def test_waits_for_build_delay(self):
        self.assertEqual(daily.days_to_build(None, utc(2026, 10, 27, 2, 0), date(2026, 10, 26)), [])
        self.assertEqual(daily.days_to_build(None, utc(2026, 10, 27, 3, 20), date(2026, 10, 26)), [date(2026, 10, 26)])

    def test_catches_up_two_days_per_run(self):
        self.assertEqual(daily.days_to_build("2026-10-26", utc(2026, 10, 30, 4, 0), None),
                         [date(2026, 10, 27), date(2026, 10, 28)])

    def test_nothing_without_data(self):
        self.assertEqual(daily.days_to_build(None, utc(2026, 10, 30, 4, 0), None), [])


class BuildDayTests(unittest.TestCase):
    def test_build_day(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_lines("cycles/2026/10/26/120500.jsonl", [
                g("https://a.com/1", "Strike on Kharkiv injures six - A News", "2026-10-26T11:00:00Z", group="western_wire", domain="a.com"),
                g("https://b.com/1", "Strike on Kharkiv injures six | B Times", "2026-10-26T11:30:00Z", group="russian_state", domain="b.com"),
                g("https://c.com/1", "Old story from the day before", "2026-10-25T23:50:00Z"),
                {"kind": "rss", "url": "https://r.com/1", "title": "Talks resume in Geneva", "published": "2026-10-26T09:00:00Z",
                 "source": "bbc_world", "group": "western_public", "lang": "eng"},
            ])
            # Written after midnight but published on the 26th: still counts for the 26th
            sink.write_lines("cycles/2026/10/27/010500.jsonl", [
                g("https://d.com/1", "Late file: drone strike reported in Odesa region", "2026-10-26T23:40:00Z", domain="d.com"),
            ])
            sink.write_lines("cycles/2026/10/27/050500.jsonl", [
                g("https://e.com/1", "Read too late to count", "2026-10-26T23:59:00Z"),
            ])
            out = daily.build_day(sink, date(2026, 10, 26))
            self.assertEqual(out["gdelt_articles"], 3)
            self.assertEqual(out["rss_items"], 1)
            summary = sink.read_json("stories/2026/10/26/summary.json")
            ukr = summary["entities"]["01_Ukraine_Conflict"]
            self.assertEqual((ukr["articles"], ukr["stories"]), (3, 2))
            self.assertEqual(ukr["by_group"], {"western_wire": 1, "russian_state": 1})
            top = ukr["top"][0]
            self.assertEqual((top["articles"], top["groups"]), (2, {"western_wire": 1, "russian_state": 1}))
            self.assertEqual(summary["first_cycle"], "cycles/2026/10/26/120500.jsonl")
            rows = sink.read_lines("stories/2026/10/26/stories.jsonl")
            self.assertEqual(sum(1 for r in rows if r["kind"] == "rss"), 1)
            self.assertTrue(all(len(r["story_id"]) == 16 for r in rows))

    def test_rows_repeated_across_cycle_files_load_once(self):
        # 28 Oct 2026: runs that died re-read the same slots, so one record sat in many cycle files.
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            a = {**g("https://a.com/1", "Strike on Kharkiv", "2026-10-26T11:00:00Z", group="western_wire"),
                 "record_id": "20261026110000-1"}
            item = {"kind": "rss", "url": "https://r.com/1", "title": "Talks resume", "published": "2026-10-26T09:00:00Z",
                    "source": "bbc_world"}
            search = {**item, "source": "gn_01_ukraine_conflict"}  # same link from a saved search: kept
            reused = {**a, "url": "https://b.com/2", "group": None}  # GDELT reused the record id: kept
            sink.write_lines("cycles/2026/10/26/120500.jsonl", [a, a, item])
            # Events records share the cycle file since 30 Oct 2026; the story build leaves them to countries.py.
            ev = events.as_row({"stamp": "20261026120000", "stream": "english", "rows": 1, "countries": {},
                                "samples": {}, "violent": [], "published": "2026-10-26T12:00:00Z"})
            sink.write_lines("cycles/2026/10/26/122000.jsonl", [a, item, search, reused, ev])
            rows, _ = daily.load_day_rows(sink, date(2026, 10, 26))
            self.assertEqual(len(rows), 4)
            summary = daily.build_day(sink, date(2026, 10, 26))
            self.assertEqual(summary["gdelt_articles"], 2)
            ukr = sink.read_json("stories/2026/10/26/summary.json")["entities"]["01_Ukraine_Conflict"]
            self.assertEqual(ukr["by_group"], {"western_wire": 1})


if __name__ == "__main__":
    unittest.main()
