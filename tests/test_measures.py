import tempfile
import unittest
from datetime import date, timedelta

from pipeline import daily, gdelt, measures
from pipeline.sinks import LocalSink


class AttentionTests(unittest.TestCase):
    def history(self, weekday_bump=0, days=28, level=100):
        end = date(2026, 11, 30)
        h = {}
        for i in range(1, days + 1):
            d = end - timedelta(days=i)
            h[d] = level + (i % 3) * 5 + (weekday_bump if d.weekday() == end.weekday() else 0)
        return end, h

    def test_needs_minimum_baseline(self):
        end, h = self.history(days=10)
        self.assertIsNone(measures.attention_anomaly(h, end, 300))

    def test_spike_scores_high_and_normal_day_low(self):
        end, h = self.history()
        spike = measures.attention_anomaly(h, end, 300)
        normal = measures.attention_anomaly(h, end, 105)
        self.assertGreater(spike["z"], 3)
        self.assertLess(abs(normal["z"]), 1)
        self.assertEqual(spike["baseline_days"], 28)
        self.assertTrue(spike["weekday_adjusted"])

    def test_weekday_adjustment(self):
        end, h = self.history(weekday_bump=100)  # this weekday always runs ~double
        r = measures.attention_anomaly(h, end, 200)
        self.assertLess(abs(r["z"]), 1)  # a usual level for that weekday
        self.assertGreater(r["expected"], 150)

    def test_ignores_days_outside_window(self):
        end, h = self.history()
        h[end] = 10_000                      # the day itself
        h[end - timedelta(days=60)] = 10_000  # too old
        r = measures.attention_anomaly(h, end, 105)
        self.assertLess(abs(r["z"]), 1)


class CountsTests(unittest.TestCase):
    # GDELT's KILL/WOUND counts are still parsed onto each row (a story's coding can quote a toll); the
    # casualty-reporting share built on them was removed on 27 Oct 2026.
    def test_parse_v1_counts(self):
        f = "KILL#6##1#Ukraine#UP#UP#49#32#UP;WOUND#12##1#Ukraine#UP#UP#49#32#UP;KILL#2##1#X#;ARREST#4##;KILL#many##"
        self.assertEqual(gdelt.casualty_counts(f), (6, 12))
        self.assertEqual(gdelt.casualty_counts(""), (None, None))


class PartialTests(unittest.TestCase):
    def test_partial_day(self):
        self.assertTrue(measures.is_partial({"day": "2026-10-26", "first_cycle": "cycles/2026/10/26/171000.jsonl"}))
        self.assertFalse(measures.is_partial({"day": "2026-10-27", "first_cycle": "cycles/2026/10/27/000500.jsonl"}))
        self.assertTrue(measures.is_partial({"day": "2026-10-27", "first_cycle": None}))
        self.assertFalse(measures.is_partial({"partial": False}))


class DailyMeasuresTests(unittest.TestCase):
    def test_build_day_adds_measures(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            day = date(2026, 11, 30)
            for i in range(1, 21):  # 20 complete earlier days with ~2 stories each
                prev = day - timedelta(days=i)
                sink.write_json(f"stories/{prev:%Y/%m/%d}/summary.json", {
                    "day": prev.isoformat(), "first_cycle": f"cycles/{prev:%Y/%m/%d}/000500.jsonl",
                    "entities": {"13_Sudan": {"stories": 2 + i % 2}}})
            rows = [{"kind": "gdelt", "url": f"https://a{i}.com/x", "title": f"k{i}a k{i}b k{i}c k{i}d k{i}e",  # distinct headlines, so 30 stories
                     "published": "2026-11-30T10:00:00Z", "labels": ["13_Sudan"], "domain": f"a{i}.com", "lang": "eng",
                     "killed": 5 if i % 2 else None, "wounded": None} for i in range(30)]
            sink.write_lines("cycles/2026/11/30/000500.jsonl", rows)
            daily.build_day(sink, day)
            e = sink.read_json("stories/2026/11/30/summary.json")["entities"]["13_Sudan"]
            self.assertNotIn("casualty", e)
            self.assertEqual(e["attention"]["baseline_days"], 20)
            self.assertGreater(e["attention"]["z"], 3)
            self.assertFalse(sink.read_json("stories/2026/11/30/summary.json")["partial"])


if __name__ == "__main__":
    unittest.main()
