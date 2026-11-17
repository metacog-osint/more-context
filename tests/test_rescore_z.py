import importlib.util
import math
import random
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from pipeline import countries, measures
from pipeline.sinks import LocalSink

_spec = importlib.util.spec_from_file_location("rescore_z", Path(__file__).resolve().parent.parent / "scripts" /
                                               "rescore_z.py")
rz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rz)

START = date(2026, 9, 1)


def build_legacy(sink, days, counts, named):
    """Store countries.json and summary.json days as the pre-calibration build scored them."""
    for d in days:
        c = {"day": d.isoformat(), "partial": False, "countries": {}, "zones": {}, "samples": {}}
        hist, complete = rz.country_history(sink, d, fold=False)
        for cc, series in counts.items():
            row = {"name": cc, "urls": series[d], "violent": series[d] // 4}
            for m in countries.SCORED:
                row[f"{m}_score"] = rz.legacy_score(hist[m].get(cc, {}), complete, d, row[m])
            c["countries"][cc] = row
        c["lists"] = {m: dict(zip(("rising", "elevated"), rz.legacy_listed(c["countries"], m))) for m in countries.SCORED}
        zh = hist["zone_named"].get("13_Sudan", {})
        c["zones"]["13_Sudan"] = {"events": 1, "articles": named[d], "named": named[d],
                                  "named_score": rz.legacy_score(zh, [x for x in complete if x in zh], d, named[d])}
        sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", c)
        sh = rz.daily.history(sink, d)
        att = rz.legacy_attention(sh.get("13_Sudan", {}), d, named[d])
        ent = {"stories": named[d], "filtered_stories": named[d], "attention": att}
        ent["alarms"] = measures.alarm_reasons(ent)
        sink.write_json(f"stories/{d:%Y/%m/%d}/summary.json", {
            "day": d.isoformat(), "first_cycle": f"cycles/{d:%Y/%m/%d}/000500.jsonl", "entities": {"13_Sudan": ent},
            "alarms": {"13_Sudan": ent["alarms"]} if ent["alarms"] else {}})


class RescoreZTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = LocalSink(Path(self.tmp.name))
        rnd = random.Random(7)
        self.days = [START + timedelta(days=i) for i in range(40)]
        counts = {cc: {d: max(0, round(rnd.gauss(mu, mu ** 0.5))) for d in self.days}
                  for cc, mu in (("SU", 80), ("RI", 60), ("RB", 50), ("GV", 2))}
        counts["GV"][self.days[-1]] = 60  # a spike on a near-zero baseline
        named = {d: max(0, round(rnd.gauss(12, 3))) for d in self.days}
        build_legacy(self.sink, self.days, counts, named)

    def tearDown(self):
        self.tmp.cleanup()

    def test_old_estimator_reproduces_what_was_stored(self):
        res, _ = rz.rescore_days(self.sink, self.days, legacy=True, write=False)
        self.assertEqual([], [line for r in res for line in rz.diff_fields(r["old"], r["new"])])

    def test_new_scores_carry_their_methods_and_fold_serbia(self):
        res, changed = rz.rescore_days(self.sink, self.days, legacy=False, write=True)
        self.assertTrue(changed)
        last = self.sink.read_json(f"stories/{self.days[-1]:%Y/%m/%d}/countries.json")
        self.assertNotIn("RB", last["countries"])
        old = [r for r in res if r["day"] == self.days[-1] and r["file"] == "countries.json"][0]["old"]
        self.assertEqual(last["countries"]["RI"]["urls"], old["countries"]["RI"]["urls"] + old["countries"]["RB"]["urls"])
        self.assertEqual("robust-1", last["countries"]["SU"]["urls_score"]["z_method"])
        self.assertEqual("pred-1", last["zones"]["13_Sudan"]["named_score"]["z_method"])
        self.assertEqual(["RB"], last["rescored_z"]["folded"])
        self.assertIn("at", last["rescored_z"])
        s = self.sink.read_json(f"stories/{self.days[-1]:%Y/%m/%d}/summary.json")
        self.assertEqual("pred-1", s["entities"]["13_Sudan"]["attention"]["z_method"])

    def test_rescoring_a_rescored_day_changes_nothing(self):
        rz.rescore_days(self.sink, self.days, legacy=False, write=True)
        res, changed = rz.rescore_days(self.sink, self.days, legacy=False, write=True)
        self.assertEqual([], changed)

    def test_near_zero_baseline_spike_has_a_smaller_calibrated_z(self):
        res, _ = rz.rescore_days(self.sink, self.days, legacy=False, write=True)
        r = [r for r in res if r["day"] == self.days[-1] and r["file"] == "countries.json"][0]
        zo, zn = r["old"]["countries"]["GV"]["urls_score"]["z"], r["new"]["countries"]["GV"]["urls_score"]["z"]
        self.assertLess(zn, zo)
        self.assertTrue(math.isfinite(zn))
        self.assertTrue(r["new"]["countries"]["GV"]["urls_score"]["floored"])


if __name__ == "__main__":
    unittest.main()
