import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from pipeline import daily, feedlabels, feeds
from pipeline.relevance import TermMatcher
from pipeline.sinks import LocalSink

SOURCES = {
    "gn_19_somalia": {"id": "gn_19_somalia", "name": "Google News search: Somalia", "group": "search", "entity": "19_Somalia"},
    "kyiv": {"id": "kyiv", "name": "Kyiv Independent", "group": "ukrainian", "focus": ["01_Ukraine_Conflict"]},
    "bbc": {"id": "bbc", "name": "BBC News - World", "group": "western_public", "focus": ["global"]},
    "toi": {"id": "toi", "name": "The Times of Israel", "group": "israeli",
            "url": "https://news.google.com/rss/search?q=site%3Atimesofisrael.com%20when%3A1d&hl=en-US&gl=US&ceid=US:en",
            "focus": ["10_Israel_Gaza_Lebanon", "11_Iran_Red_Sea"]},
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

    def test_site_search_loses_the_outlet_tail_before_matching(self):
        # The tail " - The Times of Israel" alone would label every headline for the Israel zone.
        tail_only = {"source": "toi", "group": "israeli", "title": "Poland suspends chief justice, sparking protests - The Times of Israel"}
        self.assertIn("10_Israel_Gaza_Lebanon", feedlabels.labels(tail_only, self.m, self.ids, SOURCES))
        about = {"source": "toi", "group": "israeli", "title": "Israel says Hezbollah fired rockets at Galilee - The Times of Israel"}
        out = feedlabels.prepared([tail_only, about], sources=SOURCES)
        self.assertEqual([r["title"] for r in out["10_Israel_Gaza_Lebanon"]], ["Israel says Hezbollah fired rockets at Galilee"])
        self.assertEqual(out["10_Israel_Gaza_Lebanon"][0]["domain"], "The Times of Israel")


class PollTimingTests(unittest.TestCase):
    def test_is_due(self):
        now = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
        src = {"poll_minutes": 60}
        self.assertTrue(feeds.is_due(src, None, now))
        self.assertTrue(feeds.is_due({}, {"last_ok": "2026-10-27T11:55:00Z"}, now))  # no poll_minutes: every cycle
        self.assertFalse(feeds.is_due(src, {"last_ok": "2026-10-27T11:30:00Z"}, now))
        self.assertTrue(feeds.is_due(src, {"last_ok": "2026-10-27T11:00:00Z"}, now))
        # After a failure: the next run (15 minutes), not the full hour.
        self.assertFalse(feeds.is_due(src, {"last_ok": "2026-10-27T10:00:00Z", "last_attempt_error_at": "2026-10-27T11:50:00Z"}, now))
        self.assertTrue(feeds.is_due(src, {"last_ok": "2026-10-27T10:00:00Z", "last_attempt_error_at": "2026-10-27T11:45:00Z"}, now))
        self.assertTrue(feeds.is_due(src, {"last_attempt_error_at": "2026-10-27T11:45:00Z"}, now))
        # A success after an older failure waits the full hour.
        self.assertFalse(feeds.is_due(src, {"last_ok": "2026-10-27T11:45:00Z", "last_attempt_error_at": "2026-10-27T10:00:00Z"}, now))


class _Res:
    def __init__(self, status):
        self.status, self.ok, self.not_modified = status, status == 200, False
        self.etag = self.last_modified = None
        self.error = "" if status == 200 else f"HTTP {status}"


SEARCHES = [{"id": f"gn_{i}", "group": "search", "owner": "private", "lang": "eng", "expected_minutes": 120,
             "poll_minutes": 60, "url": f"https://news.google.com/rss/search?q={i}"} for i in range(3)]
PLAIN = {"id": "bbc", "group": "western_public", "owner": "public", "lang": "eng", "expected_minutes": 60,
         "url": "https://feeds.bbci.co.uk/news/world/rss.xml"}


class SearchProbeTests(unittest.TestCase):
    def run_poll(self, first_status):
        now = datetime(2026, 10, 28, 20, 0, tzinfo=timezone.utc)
        state = {"rss": {"gn_1": {"last_attempt_error_at": "2026-10-28T19:00:00Z", "consecutive_failures": 4}}}
        tried = []

        def fetch_one(src, entry):
            tried.append(src["id"])
            status = first_status if len(tried) == 1 else 200
            items = [] if status != 200 else [{"url": f"https://x/{src['id']}", "title": "t", "summary": "",
                                               "published": now}]
            return _Res(status), (items if status == 200 else None), (None if status == 200 else f"HTTP {status}")

        with mock.patch.object(feeds, "load_sources", lambda include_candidates=False: SEARCHES + [PLAIN]):
            rows, probe = feeds.poll(state, now, fetch_one=fetch_one)
        return tried, rows, {p["id"]: p for p in probe}, state

    def test_refused_probe_holds_the_other_searches(self):
        tried, rows, probe, state = self.run_poll(503)
        self.assertEqual(tried, ["gn_0", "bbc"])  # gn_0 has never been tried, so it goes first
        self.assertEqual(set(r["source"] for r in rows), {"bbc"})
        self.assertTrue(probe["gn_1"].get("held") and probe["gn_2"].get("held"))
        self.assertEqual(state["rss"]["gn_1"]["consecutive_failures"], 4)  # held, not counted as a failure
        self.assertEqual(state["rss"]["gn_0"]["consecutive_failures"], 1)

    def test_accepted_probe_lets_the_rest_through(self):
        tried, rows, probe, _ = self.run_poll(200)
        self.assertEqual(sorted(tried), ["bbc", "gn_0", "gn_1", "gn_2"])
        self.assertEqual(tried[0], "gn_0")
        self.assertFalse(any(p.get("held") for p in probe.values()))


SITE = {"id": "toi", "group": "israeli", "owner": "private", "lang": "eng", "expected_minutes": 60, "poll_minutes": 60,
        "url": "https://news.google.com/rss/search?q=site%3Atimesofisrael.com%20when%3A1d&hl=en-US&gl=US&ceid=US:en"}


class SiteSearchTests(unittest.TestCase):
    """An outlet read through a Google News site: search keeps its own group but is handled as a search."""

    def poll(self, status_for, items_for=None, sources=None):
        now = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)
        state, tried = {"rss": {}}, []

        def fetch_one(src, entry):
            tried.append(src["id"])
            status = status_for(src, len(tried))
            if status != 200:
                return _Res(status), None, f"HTTP {status}"
            items = (items_for or {}).get(src["id"]) or [{"url": f"https://x/{src['id']}", "title": "t - Pub",
                                                           "summary": "", "published": now}]
            return _Res(200), items, None

        with mock.patch.object(feeds, "load_sources", lambda include_candidates=False: sources or SEARCHES + [SITE, PLAIN]):
            rows, probe = feeds.poll(state, now, fetch_one=fetch_one)
        return tried, rows, {p["id"]: p for p in probe}, state

    def test_is_search_by_group_or_address(self):
        self.assertTrue(feeds.is_search(SEARCHES[0]) and feeds.is_search(SITE))
        self.assertFalse(feeds.is_search(PLAIN))

    def test_site_search_is_held_when_the_probe_is_refused(self):
        tried, rows, probe, state = self.poll(lambda src, n: 503 if n == 1 else 200)
        self.assertEqual(tried, ["gn_0", "bbc"])
        self.assertTrue(probe["toi"].get("held") and probe["toi"].get("search"))
        self.assertNotIn("toi", state["rss"])  # not tried, so no failure recorded
        self.assertTrue(feeds.searches_refused(list(probe.values())))

    def test_refused_site_search_alone_counts_as_refused(self):
        tried, _, probe, _ = self.poll(lambda src, n: 503, sources=[SITE, PLAIN])
        self.assertEqual(sorted(tried), ["bbc", "toi"])
        self.assertTrue(feeds.searches_refused(list(probe.values())))
        self.assertNotIn("search", probe["bbc"])

    def test_items_without_a_headline_are_dropped_from_searches_only(self):
        now = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)
        bare = [{"url": "https://news.google.com/a", "title": "- ReliefWeb", "summary": "", "published": now},
                {"url": "https://news.google.com/b", "title": "Sudan: floods displace 20,000 - ReliefWeb", "summary": "",
                 "published": now}]
        plain = [{"url": "https://bbc/a", "title": "- odd but kept", "summary": "", "published": now}]
        _, rows, probe, _ = self.poll(lambda src, n: 200, items_for={"toi": bare, "bbc": plain}, sources=[SITE, PLAIN])
        self.assertEqual([r["title"] for r in rows if r["source"] == "toi"], ["Sudan: floods displace 20,000 - ReliefWeb"])
        self.assertEqual(probe["toi"]["items"], 1)
        self.assertEqual([r["title"] for r in rows if r["source"] == "bbc"], ["- odd but kept"])

    def test_blocked_publishers_are_dropped_from_searches(self):
        now = datetime(2026, 10, 31, 21, 0, tzinfo=timezone.utc)
        items = [{"url": "https://news.google.com/a", "title": "Russian drone strikes kill two - Modern Ghana", "summary": "",
                  "published": now},
                 {"url": "https://news.google.com/b", "title": "Russian drone strikes kill two - Reuters", "summary": "",
                  "published": now}]
        _, rows, _, _ = self.poll(lambda src, n: 200, items_for={"toi": items}, sources=[SITE, PLAIN])
        self.assertEqual([r["title"] for r in rows if r["source"] == "toi"], ["Russian drone strikes kill two - Reuters"])

    def test_has_headline(self):
        self.assertFalse(feeds.has_headline("- ReliefWeb"))
        self.assertFalse(feeds.has_headline("  "))
        self.assertFalse(feeds.has_headline(None))
        self.assertTrue(feeds.has_headline("Gaza - Israel - live updates - BBC"))


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
