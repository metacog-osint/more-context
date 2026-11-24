"""The zone scope id changes with what a zone counts, and a change cannot pass without a new catalog_version."""
import copy
import json
import unittest

from pipeline import zone_scope


class ZoneScope(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(zone_scope.CATALOG.read_text(encoding="utf-8"))
        cls.lock = json.loads(zone_scope.LOCK.read_text(encoding="utf-8"))
        cls.zone = next(z for z in cls.catalog["zones"] if z["id"] == "11_Iran_Red_Sea")

    def test_lock_matches_catalog(self):
        self.assertEqual(self.lock["catalog_version"], self.catalog["catalog_version"],
                         "run python -m pipeline.zone_scope after bumping catalog_version")
        self.assertEqual(self.lock["scopes"], zone_scope.scopes(self.catalog),
                         "a zone's scope changed: bump catalog_version, then run python -m pipeline.zone_scope")

    def test_violence_countries_change_the_id(self):
        z = copy.deepcopy(self.zone)
        z["violence"]["countries"] = ["IR", "YM"]
        self.assertNotEqual(zone_scope.scope_id(z), zone_scope.scope_id(self.zone))

    def test_wording_and_map_do_not_change_the_id(self):
        z = copy.deepcopy(self.zone)
        z["violence"]["why"] = "reworded"
        z["name"] = "Renamed"
        z["map"] = [0, 0]
        self.assertEqual(zone_scope.scope_id(z), zone_scope.scope_id(self.zone))

    def test_feed_items_carry_the_stamp(self):
        from pipeline import feed_v2
        from tests.test_feed_v2 import NOW, by_id, countries, summary
        m = by_id(feed_v2.build(summary(), countries(), now=NOW))["zone:11_Iran_Red_Sea"]["properties"]["measures"]
        self.assertEqual(m["catalog_version"], self.catalog["catalog_version"])
        self.assertEqual(m["zone_scope"], self.lock["scopes"]["11_Iran_Red_Sea"])


if __name__ == "__main__":
    unittest.main()
