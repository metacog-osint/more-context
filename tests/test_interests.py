import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "doctrine" / "kit" / "python"))
from tic_doctrine import registers, tips  # noqa: E402

spec = importlib.util.spec_from_file_location("build_interests", ROOT / "scripts" / "build_interests.py")
build_interests = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_interests)


class InterestsTests(unittest.TestCase):
    """doctrine/interests.json: what Watchfloor reads from the suite's other programs (kit 0.4.0 tips)."""

    def doc(self):
        return json.loads((ROOT / "doctrine" / "interests.json").read_text(encoding="utf-8"))

    def test_file_is_current(self):
        current = (ROOT / "doctrine" / "interests.json").read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(current, build_interests.build(), "run python -I scripts/build_interests.py")

    def test_sound_and_tied_to_the_zones(self):
        doc = self.doc()
        self.assertEqual(tips.check_interests(doc), [])
        self.assertEqual(registers.check(ROOT / "doctrine"), [])
        wps = {w["id"] for w in json.loads((ROOT / "doctrine" / "indicators.json").read_text(encoding="utf-8"))["warning_problems"]}
        zones = json.loads((ROOT / "catalog" / "entities.json").read_text(encoding="utf-8"))["zones"]
        self.assertEqual(set(doc["areas"]), {f"WF-WP-Z{z['id'][:2]}" for z in zones if z.get("countries")})
        self.assertLessEqual(set(doc["areas"]), wps)
        self.assertEqual(doc["areas"]["WF-WP-Z01"], ["UA"])  # FIPS UP -> ISO UA
        named = {w for i in doc["interests"] for w in i.get("warning_problems", [])}
        self.assertLessEqual(named, wps)  # topics an interest serves are real warning problems

    def test_matches_a_live_shaped_bus(self):
        items = [
            {"_program": "cordon", "id": "a", "title": "Russia: Level 4, Do Not Travel", "countries": ["RU"],
             "response_stage": "state_travel_advisory:level_4", "measures": {"level": 4}, "cop_stale": False},
            {"_program": "cordon", "id": "b", "title": "NAVAREA III 1/2026: CABLE OPERATIONS", "countries": [],
             "measures": {"category": "cable_pipeline"}, "cop_stale": False},
            {"_program": "noisefloor", "id": "c", "title": "GPS interference newly seen near Pskov", "tier": "anomaly",
             "countries": ["RU"], "cop_stale": False},
            {"_program": "watchfloor", "id": "d", "title": "own item", "tier": "anomaly", "countries": ["RU"]},
        ]
        got = {(t["interest_id"], t["item_id"], tuple(t["areas"])) for t in tips.tips(items, self.doc())}
        self.assertEqual(got, {("WF-INT-2", "a", ("WF-WP-Z07",)), ("WF-INT-5", "b", ()),
                               ("WF-INT-6", "c", ("WF-WP-Z07",))})


if __name__ == "__main__":
    unittest.main()
