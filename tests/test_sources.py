import json
import unittest
from collections import Counter

from pipeline.sources import SOURCES, lookup_domain


class DomainLookupTests(unittest.TestCase):
    def test_subdomains_resolve(self):
        self.assertEqual(lookup_domain("english.news.cn")["group"], "chinese_state")
        self.assertEqual(lookup_domain("www.bbc.co.uk")["source"], "bbc_world")
        self.assertEqual(lookup_domain("lenta.ru")["group"], "russian_state")
        self.assertEqual(lookup_domain("apnews.com")["group"], "western_wire")

    def test_unknown_domain(self):
        self.assertIsNone(lookup_domain("example.org"))
        self.assertIsNone(lookup_domain(""))


class CatalogShapeTests(unittest.TestCase):
    def test_every_source_is_well_formed(self):
        cat = json.loads(SOURCES.read_text(encoding="utf-8"))
        groups = set(cat["groups"])
        ids = Counter(s["id"] for s in cat["sources"])
        self.assertEqual([i for i, n in ids.items() if n > 1], [])
        for s in cat["sources"]:
            with self.subTest(source=s["id"]):
                self.assertIn(s["group"], groups)
                self.assertIn(s["rss_status"], {"active", "candidate", "dropped", "none"})
                if s["group"] == "search":  # a saved search spans many publishers: no domain of its own
                    self.assertTrue(s.get("entity") and s.get("query"))
                else:
                    self.assertTrue(s["domains"])
                if s["rss_status"] in {"active", "candidate"}:
                    self.assertTrue(s["url"].startswith("http"))
                    self.assertGreater(s["expected_minutes"], 0)
                if s["rss_status"] == "dropped":
                    self.assertTrue(s.get("rss_note"))


if __name__ == "__main__":
    unittest.main()
