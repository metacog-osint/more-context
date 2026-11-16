"""GDELT country codes against the catalog: Serbia's two codes, and no busy code left without a name."""
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from pipeline import countries, events
from pipeline.sinks import LocalSink
from tests.test_events import row, write_day

ROOT = Path(__file__).resolve().parent.parent
CODES = json.loads((ROOT / "tests" / "gdelt_codes.json").read_text(encoding="utf-8"))
NAMES = json.loads((ROOT / "catalog" / "fips_countries.json").read_text(encoding="utf-8"))["names"]
ISO = json.loads((ROOT / "catalog" / "fips_iso.json").read_text(encoding="utf-8"))["codes"]
# Codes in GDELT's list deliberately left out of the catalog: uninhabited or disputed territories GDELT rarely
# places anything in (28 Oct 2026: at most one article each). A code that grows busy fails the next test.
UNLISTED = {"AX", "AT", "FQ", "BS", "IO", "IP", "CK", "CR", "DX", "PJ", "FK", "FS", "GO", "HM", "IM", "DQ", "JU",
            "KQ", "MQ", "PF", "PC", "TB", "SX", "TE", "WF"}


class CatalogCoverageTests(unittest.TestCase):
    def test_every_code_busy_enough_to_list_has_a_name(self):
        floor = min(countries.MIN_ARTICLES.values())
        busy: dict[str, int] = {}
        for cc, n in CODES["seen"].items():
            cc = events.canon(cc)
            busy[cc] = busy.get(cc, 0) + n
        missing = {cc: n for cc, n in busy.items()
                   if n >= floor and cc not in NAMES and cc not in countries.NOT_COUNTRIES}
        self.assertEqual(missing, {}, "codes in GDELT's data with no entry in catalog/fips_countries.json")

    def test_gdelt_country_list_is_catalogued_or_left_out_on_purpose(self):
        gaps = set(CODES["gdelt_list"]) - set(NAMES) - UNLISTED - countries.NOT_COUNTRIES
        self.assertEqual(gaps, set())

    def test_every_name_has_an_iso_entry(self):
        self.assertEqual(set(NAMES) - set(ISO), set())

    def test_added_codes(self):
        for fips, iso in {"PU": "GW", "TP": "ST", "TK": "TC", "SC": "KN"}.items():
            self.assertEqual(ISO[fips]["iso"], iso)
            self.assertIsNotNone(ISO[fips]["point"])

    def test_folded_codes_point_at_a_catalogued_code(self):
        for src, dst in events.FOLD.items():
            self.assertNotIn(src, NAMES)
            self.assertIn(dst, NAMES)


class SerbiaFoldTests(unittest.TestCase):
    def test_record_counts_belgrade_rb_as_serbia_once(self):
        rows = [row("1", "RI", "https://a/1", gtype="1", place="Serbia"),
                row("2", "RB", "https://a/1", place="Belgrade, Serbia (general)"),
                row("3", "RB", "https://a/2", place="Belgrade, Serbia (general)")]
        r = events.record(rows, "20261028120000", "english")
        self.assertNotIn("RB", r["countries"])
        self.assertEqual(r["countries"]["RI"][1], 2)  # distinct articles
        self.assertEqual({v["cc"] for v in r["violent"]}, {"RI"})

    def test_stored_records_and_days_fold_on_read(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            start = date(2026, 9, 1)
            # Days stored before the fold: Serbia split across RI and RB.
            for i in range(30):
                d = start + timedelta(days=i)
                write_day(sink, d, {"RI": 120 + (i % 3), "RB": 100 + (i % 2), "US": 3000})
                countries.build_day(sink, d)
            d = start + timedelta(days=30)
            write_day(sink, d, {"RI": 121, "RB": 101, "US": 3000})
            countries.build_day(sink, d)
            c = sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
            self.assertNotIn("RB", c["countries"])
            self.assertEqual(c["countries"]["RI"]["urls"], 222)
            # History sums RI and RB from the stored days, so the day is scored against the whole country.
            hist, _ = countries.history(sink, d)
            self.assertEqual(hist["urls"]["RI"][d - timedelta(days=1)], 122 + 101)  # day 29: RI 122, RB 101
            self.assertNotIn("RB", hist["urls"])
            self.assertLess(abs(c["countries"]["RI"]["urls_score"]["z"]), 1)
            self.assertEqual(c["uncatalogued"], {})

    def test_history_adds_rb_to_ri_for_old_days(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            d = date(2026, 10, 2)
            prev = d - timedelta(days=1)
            sink.write_json(f"stories/{prev:%Y/%m/%d}/countries.json", {
                "partial": False, "countries": {"RI": {"urls": 444, "violent": 5}, "RB": {"urls": 400, "violent": 3}}})
            hist, complete = countries.history(sink, d, days=1)
            self.assertEqual(complete, [prev])
            self.assertEqual(hist["urls"], {"RI": {prev: 844}})
            self.assertEqual(hist["violent"], {"RI": {prev: 8}})


class UncataloguedTests(unittest.TestCase):
    def test_busy_code_without_a_name_is_reported(self):
        tot = {"ZZ": {"urls": 40}, "OS": {"urls": 500}, "RI": {"urls": 300}, "QQ": {"urls": 2}}
        self.assertEqual(countries.uncatalogued(tot), {"ZZ": 40})


if __name__ == "__main__":
    unittest.main()
