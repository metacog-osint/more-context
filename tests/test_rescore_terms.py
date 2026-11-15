import importlib.util
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from pipeline import measures
from pipeline.relevance import TermMatcher
from pipeline.sinks import LocalSink

_spec = importlib.util.spec_from_file_location("rescore_terms", Path(__file__).resolve().parent.parent / "scripts" /
                                               "rescore_terms.py")
rescore = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rescore)

TERMS = {"13_Sudan": ["sudan*"]}
EXCLUDE = {"13_Sudan": ["south sudan*"]}


def store_day(sink, day, titles, violent_urls=()):
    base = f"stories/{day:%Y/%m/%d}/"
    rows = [{"day": day.isoformat(), "entity": "13_Sudan", "kind": "gdelt", "story_id": str(i), "title": t,
             "articles": 2} for i, t in enumerate(titles)]
    rows.append({"day": day.isoformat(), "entity": "13_Sudan", "kind": "feed", "title": "South Sudan feed item"})
    sink.write_lines(base + "stories.jsonl", rows)
    old = TermMatcher(TERMS)  # how the day was built: no exclusions yet
    kept = [t for t in titles if old.hit("13_Sudan", t)]
    sink.write_json(base + "summary.json", {
        "day": day.isoformat(), "first_cycle": f"cycles/{day:%Y/%m/%d}/000500.jsonl",
        "entities": {"13_Sudan": {"stories": len(titles), "filtered_stories": len(kept),
                                  "filtered_articles": 2 * len(kept), "attention": None, "alarms": []}},
        "alarms": {}})
    sink.write_lines(base + "violent.jsonl", [{"id": str(i), "cc": "SU", "url": u} for i, u in enumerate(violent_urls)])
    sink.write_json(base + "countries.json", {"day": day.isoformat(), "partial": False, "countries": {},
                                              "zones": {"13_Sudan": {"events": len(violent_urls), "articles": len(violent_urls),
                                                                     "named": sum(1 for u in violent_urls if "sudan" in u)}}})


class RescoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = LocalSink(Path(self.tmp.name))
        self.days = [date(2026, 11, 1) + timedelta(days=i) for i in range(measures.MIN_BASELINE_DAYS + 2)]
        for d in self.days:
            store_day(self.sink, d, ["Sudan army retakes town", "RSF drone hits Sudan's Port Sudan",
                                     "South Sudan registers voters", "Sudan and South Sudan sign deal"],
                      ["https://x.com/sudan-clashes-darfur", "https://x.com/south-sudan-massacre"])

    def tearDown(self):
        self.tmp.cleanup()

    def test_terms_alone_reproduce_what_was_stored(self):
        m = TermMatcher(TERMS, {})
        for d in self.days:
            # Stored attention was left empty here, so only the counts must come back unchanged.
            self.assertEqual([c for c in rescore.rescore_summary(self.sink, d, m) if c[1] != "attention"], [])
            self.assertEqual([c for c in rescore.rescore_countries(self.sink, d, m, {"13_Sudan"}) if c[1] == "named"], [])

    def test_exclusion_drops_only_the_south_sudan_story_and_rescores_the_baseline(self):
        m = TermMatcher(TERMS, EXCLUDE)
        for d in self.days:
            ch = rescore.rescore_summary(self.sink, d, m)
            self.assertIn(("13_Sudan", "filtered_stories", 4, 3), ch)
            rescore.rescore_countries(self.sink, d, m, {"13_Sudan"})
        last = self.sink.read_json(f"stories/{self.days[-1]:%Y/%m/%d}/summary.json")
        e = last["entities"]["13_Sudan"]
        self.assertEqual((e["filtered_stories"], e["filtered_articles"]), (3, 6))
        self.assertEqual(e["attention"]["z"], 0.0)  # a steady 3 a day against a re-scored baseline of 3 a day
        self.assertEqual(last["rescored"]["terms_version"], rescore._version())
        c = self.sink.read_json(f"stories/{self.days[-1]:%Y/%m/%d}/countries.json")
        self.assertEqual(c["zones"]["13_Sudan"]["named"], 1)  # the south-sudan URL no longer names Sudan
        feed = [r for r in self.sink.read_lines(f"stories/{self.days[-1]:%Y/%m/%d}/stories.jsonl") if r["kind"] == "feed"]
        self.assertEqual(len(feed), 1)  # feed stories are left as built

    def test_check_sees_a_changed_score_not_only_changed_counts(self):
        # As on 15 Nov 2026: every count reproduced, but a stored score came from history the copy lacks.
        d = self.days[-1]
        c = self.sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
        c["zones"]["13_Sudan"]["named_score"] = {"z": 0.0, "expected": 1.0, "ratio": 1.0, "median90": 1, "ratio90": 1.0}
        self.sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", c)
        changes, files = rescore.rescore_days(self.sink, self.days, TermMatcher(TERMS, {}), {"13_Sudan"})
        self.assertEqual([x for x in changes if x[2] in ("filtered_stories", "named")], [])
        self.assertIn((d, "13_Sudan", "named_score"), [x[:3] for x in changes])
        self.assertIn(f"stories/{d:%Y/%m/%d}/countries.json", files)

    def test_alarm_follows_the_rescored_count(self):
        m = TermMatcher(TERMS, EXCLUDE)
        for d in self.days[:-1]:
            rescore.rescore_summary(self.sink, d, m)
        store_day(self.sink, self.days[-1], [f"Sudan clash {i}" for i in range(30)])
        rescore.rescore_summary(self.sink, self.days[-1], m)
        e = self.sink.read_json(f"stories/{self.days[-1]:%Y/%m/%d}/summary.json")["entities"]["13_Sudan"]
        self.assertGreaterEqual(e["attention"]["z"], measures.ALARM_Z)
        self.assertTrue(e["alarms"])


if __name__ == "__main__":
    unittest.main()
