import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from pipeline import api, suite
from pipeline.sinks import LocalSink

NOW = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)


def tip(interest, program, item, title, areas=(), tier="routine", day="2026-11-01T00:00:00Z", **extra):
    t = {"interest_id": interest, "program": program, "item_id": item, "title": title, "areas": list(areas),
         "tier": tier, "kind": "observation", "status_class": "reported", "countries": [], "data_as_of": day,
         "published_at": day, "link": f"https://example.org/{item}", "stale": False}
    t.update(extra)
    return t


SNAP = {"as_of": "2026-11-01T04:00:00Z", "items": 9, "problems": [], "tips": [
    tip("WF-INT-2", "cordon", "c1", "Russia: Level 4, Do Not Travel", ["WF-WP-Z07"], day="2026-10-20T00:00:00Z"),
    tip("WF-INT-1", "cordon", "c2", "Belarus: US embassy has suspended operations", ["WF-WP-Z07"]),
    tip("WF-INT-6", "noisefloor", "n1", "GPS interference newly seen near Pskov", ["WF-WP-Z07"], tier="anomaly"),
    tip("WF-INT-6", "noisefloor", "n2", "GPS interference newly seen near Las Vegas", [], tier="anomaly"),
    tip("WF-INT-11", "cordon", "c3", "NAVAREA III 9/2026: GNSS INTERFERENCE", []),
    tip("WF-INT-5", "cordon", "c4", "HYDROLANT 1/2026: CABLE OPERATIONS", []),
    tip("WF-INT-7", "elements", "e1", "5,947 fire and heat detections in Sudan", ["WF-WP-Z13"], link="javascript:alert(1)"),
    tip("WF-INT-2", "cordon", "c1", "Russia: Level 4, Do Not Travel", ["WF-WP-Z07"]),  # same item via a second match
]}


class SuitePanelTests(unittest.TestCase):
    def test_zone_gets_its_areas_anomalies_first_newest_first(self):
        out = suite.for_entity("07_Russia_NATO", SNAP)
        self.assertEqual(out["warning_problem"], "WF-WP-Z07")
        self.assertEqual([t["title"][:20] for t in out["tips"]],
                         ["GPS interference new", "Belarus: US embassy ", "Russia: Level 4, Do "])  # c1 once only
        self.assertEqual(out["tips"][0]["program_name"], "Noisefloor")
        self.assertTrue(out["tips"][0]["why"])

    def test_topic_gets_the_interests_that_name_it(self):
        gnss = {t["title"] for t in suite.for_entity("T4_GNSS_Counterspace", SNAP)["tips"]}
        self.assertEqual(gnss, {"GPS interference newly seen near Pskov", "GPS interference newly seen near Las Vegas",
                                "NAVAREA III 9/2026: GNSS INTERFERENCE"})
        self.assertEqual([t["title"] for t in suite.for_entity("T3_Undersea_Infrastructure", SNAP)["tips"]],
                         ["HYDROLANT 1/2026: CABLE OPERATIONS"])
        self.assertEqual(suite.for_entity("T1_Critical_Minerals", SNAP)["tips"], [])

    def test_unsafe_link_falls_back_to_the_program_site(self):
        t = suite.for_entity("13_Sudan", SNAP)["tips"][0]
        self.assertEqual(t["link"], "https://elements.theintelligence.company/")

    def test_cap_per_program_and_missing_sources(self):
        many = dict(SNAP, tips=[tip("WF-INT-5", "cordon", f"x{i}", f"HYDROLANT {i}/2026") for i in range(15)],
                    problems=[{"source": "bus", "error": "x"}, {"source": "vigil", "error": "y"}])
        out = suite.for_entity("T3_Undersea_Infrastructure", many)
        self.assertEqual((len(out["tips"]), out["more"]), (suite.MAX_PER_PROGRAM, {"cordon": 3}))
        self.assertEqual(out["missing"], ["COP's combined feed", "Vigil"])

    def test_snapshot_caches_and_retries_sooner_after_a_failure(self):
        calls = []

        def gather(doc):
            calls.append(1)
            return [], ([{"source": "bus", "error": "down"}] if len(calls) == 1 else [])
        suite._CACHE.update(at=0.0, value=None, ttl=suite.TTL)
        clock = iter([1000.0, 1100.0, 1000.0 + suite.TTL_AFTER_FAILURE + 1, 2000.0]).__next__
        first = suite.snapshot(now=NOW, gather=gather, clock=clock)
        self.assertEqual(first["problems"][0]["source"], "bus")
        suite.snapshot(now=NOW, gather=gather, clock=clock)            # within the short retry window: cached
        self.assertEqual(len(calls), 1)
        suite.snapshot(now=NOW, gather=gather, clock=clock)            # after it: fetched again, now healthy
        self.assertEqual(len(calls), 2)
        suite.snapshot(now=NOW, gather=gather, clock=clock)            # healthy: cached for the full TTL
        self.assertEqual(len(calls), 2)
        suite._CACHE.update(at=0.0, value=None, ttl=suite.TTL)

    def test_api_route(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(suite, "snapshot", lambda: SNAP):
            status, body = api.handle("GET", "/suite", {"entity": "07_Russia_NATO"}, None, LocalSink(d), ai_on=False)
            self.assertEqual((status, len(body["tips"])), (200, 3))
            status, _ = api.handle("GET", "/suite", {"entity": "nowhere"}, None, LocalSink(d), ai_on=False)
            self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
