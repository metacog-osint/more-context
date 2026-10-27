import importlib.util
import unittest
from pathlib import Path

from pipeline.match import Matcher, load_catalog

_spec = importlib.util.spec_from_file_location("relabel", Path(__file__).resolve().parent.parent / "scripts" / "relabel.py")
relabel = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(relabel)


class RelabelTests(unittest.TestCase):
    def test_horn_rows_move_to_the_split_zones(self):
        cat = load_catalog()
        retired = {r["id"] for r in cat["retired"]}
        rows = [
            {"kind": "gdelt", "labels": ["17_Horn_of_Africa"], "url": "https://x.com/a",
             "locations": "4#Mekele, Tigray, Ethiopia#ET#ET08#13.5#39.5#-1", "themes": "ARMEDCONFLICT;"},
            {"kind": "gdelt", "labels": ["17_Horn_of_Africa"], "url": "https://x.com/b",
             "locations": "1#Somalia#SO#SO#10#49#SO", "themes": "TERROR;"},
            {"kind": "gdelt", "labels": ["13_Sudan"], "url": "https://x.com/c",
             "locations": "1#Sudan#SU#SU#15#30#SU", "themes": "KILL;"},
            {"kind": "rss", "labels": ["17_Horn_of_Africa"]},
        ]
        out, moved = relabel.relabel_rows(rows, retired, Matcher(cat))
        self.assertEqual([r["labels"] for r in out[:3]], [["18_Ethiopia_Eritrea"], ["19_Somalia"], ["13_Sudan"]])
        self.assertEqual(out[3]["labels"], ["17_Horn_of_Africa"])  # only GDELT rows are matched
        self.assertEqual(dict(moved), {"18_Ethiopia_Eritrea": 1, "19_Somalia": 1})

    def test_new_zones_stay_within_the_old_zone(self):
        # Relabelling is only sound when every new rule is a subset of what the retired zone stored.
        cat = load_catalog()
        zones = {z["id"]: z["match_v43"] for z in cat["zones"]}
        old_places = set("Ethiopia|Eritrea|Somalia|Somaliland|Puntland|Mogadishu|Addis Ababa|Asmara|Tigray|Amhara|Djibouti".split("|"))
        old_themes = "MILITARY|KILL|ARMEDCONFLICT|TERROR|REBEL|PIRACY|BORDER|CEASEFIRE"
        for zid in ("18_Ethiopia_Eritrea", "19_Somalia"):
            self.assertLessEqual(set(zones[zid]["loc"].split("|")), old_places)
            self.assertEqual(zones[zid]["themes"], old_themes)


if __name__ == "__main__":
    unittest.main()
