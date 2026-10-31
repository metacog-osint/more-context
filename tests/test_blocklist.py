import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pipeline import blocklist, cycle, daily
from pipeline.sinks import LocalSink

ROOT = Path(__file__).resolve().parent.parent


class BlocklistRuleTests(unittest.TestCase):
    def test_domains_and_their_subdomains(self):
        self.assertTrue(blocklist.gdelt_reason("indiankanoon.org", "https://indiankanoon.org/doc/95663263/"))
        self.assertTrue(blocklist.gdelt_reason("wjbo.iheart.com", "https://wjbo.iheart.com/content/2026-10-29-x/"))
        self.assertIsNone(blocklist.gdelt_reason("bbc.com", "https://www.bbc.com/news/articles/c1"))
        self.assertIsNone(blocklist.gdelt_reason("jpost.com", "https://www.jpost.com/middle-east/article-1"))
        self.assertIsNone(blocklist.gdelt_reason("heart.com", "https://heart.com/a"))  # not a subdomain of iheart.com

    def test_reprint_network_path(self):
        self.assertTrue(blocklist.gdelt_reason("iranherald.com", "https://www.iranherald.com/news/279404749/helicopter-crash"))
        self.assertIsNone(blocklist.gdelt_reason("x.com", "https://x.com/news/12345/story"))
        self.assertIsNone(blocklist.gdelt_reason("x.com", "https://x.com/news/1234567890/story"))  # ten digits
        self.assertIsNone(blocklist.gdelt_reason("x.com", "https://x.com/world/news/279404749/a"))  # not at the root

    def test_press_release_paths(self):
        url = "https://www.manilatimes.net/2026/10/30/tmt-newswire/globenewswire/propanc-biopharma/1"
        self.assertTrue(blocklist.gdelt_reason("manilatimes.net", url))
        self.assertTrue(blocklist.gdelt_reason("x.com", "https://x.com/PRNewswire/a"))  # case ignored
        self.assertIsNone(blocklist.gdelt_reason("manilatimes.net", "https://www.manilatimes.net/2026/10/29/world/x/1"))

    def test_search_publishers(self):
        self.assertTrue(blocklist.blocked_publisher("Sudan accuses Ethiopia over drone strikes - Facebook"))
        self.assertTrue(blocklist.blocked_publisher("Russian drone strikes kill two - modern ghana"))
        self.assertFalse(blocklist.blocked_publisher("Facebook fined in Kenya - Reuters"))
        self.assertFalse(blocklist.blocked_publisher("No publisher tail"))
        self.assertFalse(blocklist.blocked_publisher(None))

    def test_every_entry_has_a_reason(self):
        cat = json.loads((ROOT / "catalog" / "blocklist.json").read_text(encoding="utf-8"))
        for e in cat["gdelt_domains"] + cat["gdelt_url_patterns"] + cat["search_publishers"]:
            with self.subTest(entry=e):
                self.assertTrue(e["reason"].strip())


class BlocklistAppliedTests(unittest.TestCase):
    def test_ingest_skips_blocked_articles(self):
        arts = [SimpleNamespace(domain="kfab.iheart.com", url="https://kfab.iheart.com/content/a/",
                                to_dict=lambda: {"url": "https://kfab.iheart.com/content/a/", "domain": "kfab.iheart.com"}),
                SimpleNamespace(domain="bbc.com", url="https://www.bbc.com/news/a",
                                to_dict=lambda: {"url": "https://www.bbc.com/news/a", "domain": "bbc.com"})]
        matcher = SimpleNamespace(labels=lambda art: ["15_Cuba"])
        with mock.patch.object(cycle.gdelt, "parse_zip", lambda data, stream: iter(arts)):
            rows = cycle.gdelt_rows("20261031210000", "english", b"", matcher)
        self.assertEqual([r["domain"] for r in rows], ["bbc.com"])

    def test_day_build_drops_blocked_rows_written_earlier(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            day = date(2026, 11, 30)
            row = {"kind": "gdelt", "title": "Cuban diplomat expelled after UN row", "published": "2026-11-30T10:00:00Z",
                   "labels": ["15_Cuba"], "lang": "eng"}
            rows = [{**row, "url": "https://kfab.iheart.com/content/a/", "domain": "kfab.iheart.com"},
                    {**row, "url": "https://www.iranherald.com/news/279404749/cuban", "domain": "iranherald.com"},
                    {**row, "url": "https://www.bbc.com/news/a", "domain": "bbc.com"},
                    {"kind": "rss", "source": "gn_15_cuba", "group": "search", "lang": "eng",
                     "title": "Cuban diplomat expelled after UN row - Facebook", "url": "https://news.google.com/rss/articles/a",
                     "published": "2026-11-30T10:00:00Z"}]
            sink.write_lines("cycles/2026/11/30/000500.jsonl", rows)
            daily.build_day(sink, day)
            s = sink.read_json("stories/2026/11/30/summary.json")
            self.assertEqual(s["entities"]["15_Cuba"]["articles"], 1)
            self.assertEqual(s["feed_stories"].get("15_Cuba", 0), 0)


class CatalogConsistencyTests(unittest.TestCase):
    def test_site_searches_and_groups(self):
        cat = json.loads((ROOT / "catalog" / "sources.json").read_text(encoding="utf-8"))
        grades = json.loads((ROOT / "doctrine" / "sources.json").read_text(encoding="utf-8"))["grading"]["reliability_by_group"]
        self.assertEqual(set(cat["groups"]) - set(grades), set())  # every perspective group has a proposed grade
        for s in cat["sources"]:
            if s.get("rss_status") == "active" and (s.get("url") or "").startswith("https://news.google.com/rss/search"):
                with self.subTest(source=s["id"]):
                    self.assertTrue(s.get("query"))
                    self.assertEqual(s.get("poll_minutes"), 60)
                    if s["group"] != "search":
                        self.assertTrue(s.get("domains"))  # an outlet search still tags the outlet's GDELT rows


if __name__ == "__main__":
    unittest.main()
