"""Feed contract v2: pipeline/feed_v2.py and GET /feed. Offline; uses the vendored doctrine kit."""
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from pipeline import api, feed_v2
from pipeline.sinks import LocalSink

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "doctrine" / "kit" / "python"))
from tic_doctrine import contract, registers  # noqa: E402

DAY = "2026-10-21"
NOW = datetime(2026, 10, 22, 4, 0, tzinfo=timezone.utc)


def summary(partial=False, cuba_alarm=True):
    return {"day": DAY, "partial": partial, "built_at": "2026-10-22T03:22:00Z", "entities": {
        "15_Cuba": {"attention": {"z": 3.36, "ratio": 2.87}, "alarms": ["attention z 3.36"] if cuba_alarm else [],
                    "filtered_stories": 40, "violence": {"named": 6, "named_score": {"z": 1.1, "ratio": 3.1}}},
        "03_Korea_Peninsula": {"attention": {"z": 0.4, "ratio": 1.3}, "alarms": [],
                               "violence": {"named": 28, "named_score": {"z": 2.19, "ratio": 9.2}}},
        "13_Sudan": {"attention": {"z": 0.3, "ratio": 1.1}, "alarms": [],
                     "violence": {"named": 3, "named_score": {"z": 4.0, "ratio": 5.0}}},  # too few articles
        "T4_GNSS_Counterspace": {"attention": {"z": 0.2, "ratio": 1.2}, "alarms": []},
    }}


def countries():
    row = lambda z: {"urls": 100, "violent": 20, "urls_score": {"z": z, "ratio": 2.0},  # noqa: E731
                     "violent_score": {"z": z, "ratio": 2.0, "ratio90": 3.0}}
    return {"day": DAY, "files": 180, "partial": False,
            "lists": {"violent": {"rising": ["KS", "BR", "PG"], "elevated": ["KS", "ET", "GP"]},
                      "urls": {"rising": ["CD"]}},
            "countries": {cc: row(2.6) for cc in ("KS", "BR", "ET", "GP", "CD", "PG")}}


def by_id(fc):
    return {f["properties"]["id"].split(":", 2)[2]: f for f in fc["features"]}


class Build(unittest.TestCase):
    def test_every_item_passes_the_kit_linter(self):
        fc = feed_v2.build(summary(), countries(), now=NOW)
        self.assertEqual(fc["dropped"], [])
        regs = registers.ids(feed_v2.DOCTRINE)
        for f in fc["features"]:
            errs = [p for p in contract.check(f, regs) if p[1] == "error"]
            self.assertEqual(errs, [], f["properties"]["id"])
        self.assertEqual((fc["contract"], fc["program"], fc["generated_at"]), ("tic-feed/2", "watchfloor", "2026-10-22T04:00:00Z"))

    def test_items_are_date_only(self):
        """A whole UTC day carries data_as_of_precision "day" and midnight UTC, so no page shows "5:59 PM" (16 Nov 2026)."""
        fc = feed_v2.build(summary(), countries(), now=NOW)
        self.assertTrue(fc["features"])
        for f in fc["features"]:
            p = f["properties"]
            self.assertEqual((p["data_as_of_precision"], p["data_as_of"]), ("day", f"{DAY}T00:00:00Z"), p["id"])
        kinds = {f["properties"]["id"].split(":")[2] for f in fc["features"]}
        self.assertTrue({"zone", "topic", "country", "summary"} <= kinds, kinds)

    def test_zone_tiers_follow_the_alarm_rules(self):
        items = by_id(feed_v2.build(summary(), countries(), now=NOW))
        cuba, korea, sudan = (items[f"zone:{z}"]["properties"] for z in ("15_Cuba", "03_Korea_Peninsula", "13_Sudan"))
        self.assertEqual((cuba["tier"], cuba["indicator_id"], cuba["direction"]), ("anomaly", "WF-IND-1", "neutral"))
        self.assertEqual((korea["tier"], korea["indicator_id"], korea["direction"]), ("anomaly", "WF-IND-2", "supports"))
        self.assertEqual(korea["countries"], ["KP", "KR"])
        self.assertEqual(sudan["tier"], "routine")  # z 4.0 but only 3 articles
        self.assertEqual(items["zone:01_Ukraine_Conflict"]["properties"]["tier"], "routine")  # no data: no alarm
        self.assertEqual(items["zone:15_Cuba"]["geometry"], {"type": "Point", "coordinates": [-82.37, 23.11]})

    def test_topics_have_no_place_but_a_page_and_functions(self):
        p = by_id(feed_v2.build(summary(), countries(), now=NOW))["topic:T4_GNSS_Counterspace"]
        self.assertIsNone(p["geometry"])
        self.assertEqual(p["properties"]["visual"]["type"], "page")
        self.assertEqual(p["properties"]["ncf"], ["provide_pnt", "provide_satellite_access"])

    def test_countries_in_zones_link_to_the_zone_and_others_go_to_review(self):
        items = by_id(feed_v2.build(summary(), countries(), now=NOW))
        ks = items["country:KS:violence"]["properties"]
        self.assertEqual((ks["warning_problem_id"], ks["countries"]), ("WF-WP-Z03", ["KR"]))
        # The country count is not filtered to the zone: no hypothesis, no direction (Tom, 16 Nov 2026).
        for k in ("hypothesis_id", "direction", "indicator_id", "indicator_state"):
            self.assertNotIn(k, ks)
        self.assertNotIn("country:KS:violence:elevated", items)  # rising wins; one violence item per country
        et = items["country:ET:violence"]["properties"]
        self.assertEqual((et["warning_problem_id"], et["baseline_ref"]["id"]), ("WF-WP-Z18", "wf-90d-median"))
        self.assertNotIn("hypothesis_id", et)
        br = items["country:BR:violence"]["properties"]
        self.assertTrue(br["review_queue"])
        self.assertNotIn("indicator_id", br)
        self.assertEqual(items["country:CD:attention"]["properties"]["countries"], ["TD"])  # FIPS CD is Chad
        self.assertNotIn("country:PG:violence", items)  # Spratly Islands: no ISO country
        gp = items["country:GP:violence"]  # Guadeloupe: ISO code, no label point
        self.assertIsNone(gp["geometry"])
        self.assertEqual(gp["properties"]["visual"]["type"], "map")

    def test_partial_day_raises_no_anomaly(self):
        fc = feed_v2.build(summary(partial=True), countries(), now=NOW)
        zones = [f["properties"] for f in fc["features"] if ":zone:" in f["properties"]["id"]]
        self.assertTrue(all(p["tier"] == "routine" and p["partial_day"] for p in zones))
        self.assertIn("partial day", fc["features"][0]["properties"]["title"])

    def test_titles_floor_the_ratio_and_say_plain_z(self):
        c = countries()
        c["countries"]["KS"]["violent"] = 15
        c["countries"]["KS"]["violent_score"] = {"z": 2.7, "ratio": 79.3, "ratio_shown": 5.0, "floored": True,
                                                 "z_method": "robust-1"}
        c["countries"]["BR"]["violent_score"] = {"z": 3.1, "ratio": 4.2, "ratio_shown": 3.5, "floored": False,
                                                 "z_method": "robust-1"}
        items = by_id(feed_v2.build(summary(), c, now=NOW))
        self.assertIn("violent-event articles at 15, usually 3 or fewer (z 2.7), on the Rising list",
                      items["country:KS:violence"]["properties"]["title"])
        self.assertIn("3.5x normal (z 3.1)", items["country:BR:violence"]["properties"]["title"])
        self.assertFalse(any("calibrated" in f["properties"]["title"] for f in feed_v2.build(summary(), c, now=NOW)["features"]))
        # a score without ratio_shown keeps its own ratio
        self.assertIn("2.0x normal (z 2.6)", items["country:CD:attention"]["properties"]["title"])

    def test_missing_country_data_is_partial_not_quiet(self):
        fc = feed_v2.build(summary(), None, now=NOW)
        head = fc["features"][0]["properties"]
        self.assertIn("no country data", head["title"])
        self.assertNotIn("countries rising", head["title"])
        self.assertTrue(head["partial_day"])
        self.assertEqual(fc["dropped"], [])
        cuba = by_id(fc)["zone:15_Cuba"]["properties"]
        self.assertEqual(cuba["tier"], "anomaly")  # the stories' attention alarm still stands

    def test_summary_item_counts(self):
        head = feed_v2.build(summary(), countries(), now=NOW)["features"][0]["properties"]
        self.assertEqual(head["id"], f"watchfloor:{DAY}:summary")
        self.assertIn("1 of 21 zones and topics above normal attention", head["title"])
        self.assertIn("1 of 16 zones with violence above normal", head["title"])
        self.assertEqual(head["coverage_fraction"], 0.938)  # 180 of 192 files

    def test_a_failing_item_is_dropped_not_fatal(self):
        s = summary()
        s["built_at"] = "22 Oct 2026"  # not UTC ISO 8601: every item fails
        fc = feed_v2.build(s, countries(), now=NOW)
        self.assertEqual(fc["features"], [])
        self.assertTrue(fc["dropped"] and all(d["errors"] for d in fc["dropped"]))


class Route(unittest.TestCase):
    def test_get_feed(self):
        api._CACHE.clear()
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            d = date.fromisoformat(DAY)
            raw = summary()
            sink.write_json(f"stories/{d:%Y/%m/%d}/summary.json", {
                "day": DAY, "built_at": raw["built_at"],
                "entities": {k: {kk: vv for kk, vv in v.items() if kk != "violence"} for k, v in raw["entities"].items()}})
            sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", {
                **countries(), "zones": {k: v["violence"] for k, v in raw["entities"].items() if "violence" in v}})
            st, body = api.handle("GET", "/feed", {"day": DAY}, None, sink, ai_on=False, today=date(2026, 10, 22))
            self.assertEqual((st, body["type"], body["dropped"]), (200, "FeatureCollection", []))
            self.assertEqual(by_id(body)["zone:03_Korea_Peninsula"]["properties"]["indicator_id"], "WF-IND-2")
            st, _ = api.handle("GET", "/feed", {"day": "2026-10-20"}, None, sink, ai_on=False, today=date(2026, 10, 22))
            self.assertEqual(st, 404)
        api._CACHE.clear()


if __name__ == "__main__":
    unittest.main()
