import re
import subprocess
import unittest
from pathlib import Path

from pipeline.match import Matcher, load_catalog

M = Matcher()
V43_SOURCE = Path("[local path]")


class ZoneTests(unittest.TestCase):
    def test_israel_without_iran(self):
        self.assertEqual(M.zone("1#Israel#IS#IS#31#35#IS;", "MILITARY;"), "10_Israel_Gaza_Lebanon")

    def test_israel_with_iran_goes_to_iran(self):
        self.assertEqual(M.zone("1#Israel#IS;1#Iran#IR;", "MILITARY;"), "11_Iran_Red_Sea")

    def test_gaza_wins_even_with_iran(self):
        self.assertEqual(M.zone("1#Gaza#GZ;1#Iran#IR;", "KILL;"), "10_Israel_Gaza_Lebanon")

    def test_indiana_is_not_india(self):
        self.assertIsNone(M.zone("2#Indiana, United States#US#USIN;", "MILITARY;"))

    def test_south_sudan_is_not_sudan(self):
        self.assertIsNone(M.zone("1#South Sudan#OD#OD;", "KILL;"))
        self.assertEqual(M.zone("1#Sudan#SU#SU;", "KILL;"), "13_Sudan")

    def test_nigeria_is_not_niger(self):
        self.assertIsNone(M.zone("1#Nigeria#NI#NI;", "TERROR;"))
        self.assertEqual(M.zone("1#Niger#NG#NG;", "TERROR;"), "12_Sahel_West_Africa")

    def test_theme_required(self):
        self.assertIsNone(M.zone("1#Ukraine#UP;", "TAX_FNCACT_FARMER;"))

    def test_venezuela_immigration_excluded(self):
        self.assertIsNone(M.zone("1#Venezuela#VE;", "ELECTION;IMMIGRATION;"))


class TopicTests(unittest.TestCase):
    def test_sanctions_needs_context(self):
        self.assertIsNone(M.topic("https://thehindu.com/7-crore-sanctioned-for-tourism-facilities/"))
        self.assertEqual(M.topic("https://x.com/uk-sanctions-15-sudan-commanders/"), "T5_Sanctions_Shadow_Fleet")
        self.assertEqual(M.topic("https://x.com/north-koreas-shadow-fleet/"), "T5_Sanctions_Shadow_Fleet")

    def test_gps_jamming_not_jammu(self):
        self.assertIsNone(M.topic("https://x.com/jammu-and-kashmir-police/"))
        self.assertEqual(M.topic("https://x.com/drones-without-gps-ukraine/"), "T4_GNSS_Counterspace")

    def test_rare_earths(self):
        self.assertEqual(M.topic("https://x.com/japan-rare-earth-supply/"), "T1_Critical_Minerals")


@unittest.skipUnless(V43_SOURCE.exists(), "v4.3 source not on this machine")
class CatalogMatchesV43(unittest.TestCase):
    """Every match_v43 regex must appear verbatim in v4.3's SQL, so the baseline is exact."""

    def test_regexes_present_in_v43_sql(self):
        src = V43_SOURCE.read_text(encoding="utf-8").replace("\\\\", "\\")
        cat = load_catalog()
        for e in cat["zones"] + cat["topics"]:
            spec = e["match_v43"]
            pats = [spec.get(k) for k in ("loc", "themes", "not_themes", "url", "url_broad", "url_context")]
            alt = spec.get("loc_alt") or {}
            pats += [alt.get("loc"), alt.get("not_loc")]
            for p in filter(None, pats):
                with self.subTest(entity=e["id"], pattern=p[:40]):
                    self.assertIn(f"r'{p}'", src)


if __name__ == "__main__":
    unittest.main()
