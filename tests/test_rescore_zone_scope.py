import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from pipeline import countries
from pipeline.relevance import TermMatcher
from pipeline.sinks import LocalSink
from scripts import rescore_zone_scope as rz

ZONE = "11_Iran_Red_Sea"
DAY = date(2026, 11, 17)
REC = {"stamp": "20261117120000", "stream": "english", "countries": {"BA": [2, 2, 0, 2, 2], "IR": [1, 1, 0, 1, 1]},
       "samples": {}, "violent": [
           {"id": "1", "cc": "BA", "adm1": "BA16", "url": "https://x/iran-launches-third-round-of-strikes-on-bahrain"},
           {"id": "2", "cc": "BA", "adm1": "BA16", "url": "https://x/manama-court-jails-robbery-gang"},
           {"id": "3", "cc": "IR", "adm1": "IR11", "url": "https://x/us-strikes-iran-qeshm-island"}]}


class RescoreZoneScopeTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root, self.cache = Path(self.td.name) / "root", Path(self.td.name) / "cache"
        self.cache.mkdir()
        self.sink = LocalSink(self.root)
        old = {ZONE: (frozenset({"IR", "YM"}), frozenset())}
        # A day stored as built with the old scope (Iran and Yemen only), before members were counted.
        orig, orig_m = countries.violence_scopes, countries.member_zones
        countries.violence_scopes = lambda: {**orig(), **old}
        countries.member_zones = lambda: frozenset()
        try:
            countries.build_day(self.sink, DAY, recs=[REC])
        finally:
            countries.violence_scopes, countries.member_zones = orig, orig_m
        (self.cache / f"{DAY.isoformat()}.json").write_text(json.dumps([
            {"stamp": REC["stamp"], "stream": REC["stream"],
             "violent": [{k: v[k] for k in rz.KEEP} for v in REC["violent"]]}]), encoding="utf-8")
        self.old = old

    def tearDown(self):
        self.td.cleanup()

    def stored(self):
        return self.sink.read_json(f"stories/{DAY:%Y/%m/%d}/countries.json")["zones"][ZONE]

    def test_the_old_scope_reproduces_the_stored_day(self):
        before = self.stored()
        res, changed = rz.rescore_days(self.sink, self.cache, [DAY], self.old, TermMatcher(), stamp=False)
        self.assertEqual(changed, [])
        self.assertEqual(rz.diff(res[0]), [])
        self.assertEqual(before, {"events": 1, "articles": 1, "named": 1})

    def test_the_new_scope_adds_gulf_articles_that_name_the_zone(self):
        scopes = {ZONE: countries.violence_scopes()[ZONE]}
        res, changed = rz.rescore_days(self.sink, self.cache, [DAY], scopes, TermMatcher(), stamp=True)
        self.assertEqual(len(changed), 1)
        self.assertEqual(self.stored(), {"events": 3, "articles": 3, "named": 2})
        stamp = self.sink.read_json(changed[0])["rescored_scope"]
        self.assertIn("BA", stamp["zones"][ZONE])
        # Every other zone is left as built.
        self.assertEqual(list(res[0]["new"]), [ZONE])
        self.assertNotIn("members", stamp)

    def test_members_and_spikes_are_added_where_the_zone_counts_them(self):
        scopes = {ZONE: countries.violence_scopes()[ZONE]}
        res, changed = rz.rescore_days(self.sink, self.cache, [DAY], scopes, TermMatcher(), stamp=True,
                                       members=frozenset({ZONE}))
        z = self.stored()
        self.assertEqual((z["members"]["BA"]["named"], z["members"]["IR"]["named"], z["members"]["SA"]["named"]), (1, 1, 0))
        self.assertNotIn("spikes", z)  # the stored day is partial (one file): counted, not scored
        self.assertEqual(self.sink.read_json(changed[0])["rescored_scope"]["members"], [ZONE])
        self.assertEqual(rz.report(res)["zones"][ZONE]["spike_days"], 0)


if __name__ == "__main__":
    unittest.main()
