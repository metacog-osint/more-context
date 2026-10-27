import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from pipeline import daily, feedlabels, feeds
from pipeline.relevance import TermMatcher
from pipeline.sinks import LocalSink

SOURCES = {
    "gn_19_somalia": {"id": "gn_19_somalia", "name": "Google News search: Somalia", "group": "search", "entity": "19_Somalia"},
    "kyiv": {"id": "kyiv", "name": "Kyiv Independent", "group": "ukrainian", "focus": ["01_Ukraine_Conflict"]},
    "bbc": {"id": "bbc", "name": "BBC News - World", "group": "western_public", "focus": ["global"]},
}


class FeedLabelTests(unittest.TestCase):
    def setUp(self):
        self.m = TermMatcher()
        self.ids = feedlabels.entity_ids()

    def test_split_publisher(self):
        self.assertEqual(feedlabels.split_publisher("Attacks kill 60 in Ethiopia - AP News"), ("Attacks kill 60 in Ethiopia", "AP News"))
        self.assertEqual(feedlabels.split_publisher("No publisher here"), ("No publisher here", None))
        self.assertEqual(feedlabels.split_publisher("Gaza - Israel - live updates - BBC"), ("Gaza - Israel - live updates", "BBC"))

    def test_search_belongs_to_its_zone_whatever_the_headline(self):
        row = {"source": "gn_19_somalia", "title": "Election crisis deepens"}
        self.assertEqual(feedlabels.labels(row, self.m, self.ids, SOURCES), ["19_Somalia"])

    def test_focused_feed_matches_only_its_focus(self):
        row = {"source": "kyiv", "title": "Sudan's army retakes a town in Darfur"}
        self.assertEqual(feedlabels.labels(row, self.m, self.ids, SOURCES), [])  # Sudan is outside this feed's focus
        row = {"source": "kyiv", "title": "Ukraine says drones hit Kherson overnight"}
        self.assertEqual(feedlabels.labels(row, self.m, self.ids, SOURCES), ["01_Ukraine_Conflict"])

    def test_global_feed_matches_any_zone_named(self):
        row = {"source": "bbc", "title": "Sudan's army retakes town as Ethiopia talks stall"}
        self.assertEqual(set(feedlabels.labels(row, self.m, self.ids, SOURCES)), {"13_Sudan", "18_Ethiopia_Eritrea"})

    def test_prepared_strips_publisher_and_names_outlets(self):
        rows = [{"source": "gn_19_somalia", "group": "search", "title": "Al-Shabaab attack kills 12 - Reuters", "url": "https://news.google.com/a"},
                {"source": "gn_19_somalia", "group": "search", "title": "Al-Shabaab attack kills 12 - BBC", "url": "https://news.google.com/b"}]
        out = feedlabels.prepared(rows, sources=SOURCES)
        self.assertEqual([r["title"] for r in out["19_Somalia"]], ["Al-Shabaab attack kills 12"] * 2)
        self.assertEqual([r["domain"] for r in out["19_Somalia"]], ["Reuters", "BBC"])


class PollTimingTests(unittest.TestCase):
    def test_is_due(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        src = {"poll_minutes": 60}
        self.assertTrue(feeds.is_due(src, None, now))
        self.assertTrue(feeds.is_due({}, {"last_ok": "2026-10-27T11:55:00Z"}, now))  # no poll_minutes: every cycle
        self.assertFalse(feeds.is_due(src, {"last_ok": "2026-10-27T11:30:00Z"}, now))
        self.assertTrue(feeds.is_due(src, {"last_ok": "2026-10-27T11:00:00Z"}, now))
        self.assertFalse(feeds.is_due(src, {"last_ok": "2026-10-27T10:00:00Z", "last_attempt_error_at": "2026-10-27T11:45:00Z"}, now))


class BuildDayFeedTests(unittest.TestCase):
    def test_feed_stories_are_built_per_zone_and_kept_out_of_counts(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            day = date(2026, 11, 30)
            rows = [{"kind": "rss", "source": "gn_19_somalia", "group": "search", "lang": "eng",
                     "title": f"Al-Shabaab attack kills 12 - Outlet{i}", "url": f"https://news.google.com/{i}",
                     "published": "2026-11-30T10:00:00Z"} for i in range(3)]
            rows.append({"kind": "gdelt", "url": "https://x.com/a", "title": "Somali troops clash", "domain": "x.com",
                         "published": "2026-11-30T10:00:00Z", "labels": ["19_Somalia"], "lang": "eng"})
            sink.write_lines("cycles/2026/11/30/000500.jsonl", rows)
            daily.build_day(sink, day)
            s = sink.read_json("stories/2026/11/30/summary.json")
            self.assertEqual(s["feed_stories"]["19_Somalia"], 1)  # three outlets, one story
            self.assertEqual(s["entities"]["19_Somalia"]["stories"], 1)  # GDELT count unchanged by feeds
            feed = [r for r in sink.read_lines("stories/2026/11/30/stories.jsonl") if r["kind"] == "feed"]
            self.assertEqual((len(feed), feed[0]["outlets"], feed[0]["outlet_names"]), (1, 3, ["Outlet0", "Outlet1", "Outlet2"]))

    def test_partial_day_has_no_z_and_no_alarm(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            day = date(2026, 11, 30)
            for i in range(1, 21):
                prev = day - timedelta(days=i)
                sink.write_json(f"stories/{prev:%Y/%m/%d}/summary.json", {
                    "day": prev.isoformat(), "first_cycle": f"cycles/{prev:%Y/%m/%d}/000500.jsonl",
                    "entities": {"13_Sudan": {"stories": 2}}})
            rows = [{"kind": "gdelt", "url": f"https://a{i}.com/x", "title": f"k{i}a k{i}b k{i}c k{i}d", "domain": f"a{i}.com",
                     "published": "2026-11-30T18:00:00Z", "labels": ["13_Sudan"], "lang": "eng"} for i in range(30)]
            sink.write_lines("cycles/2026/11/30/171045.jsonl", rows)  # ingest started late in the day
            daily.build_day(sink, day)
            s = sink.read_json("stories/2026/11/30/summary.json")
            self.assertTrue(s["partial"])
            self.assertIsNone(s["entities"]["13_Sudan"]["attention"])
            self.assertEqual((s["entities"]["13_Sudan"]["alarms"], s["alarms"]), ([], {}))


if __name__ == "__main__":
    unittest.main()
