import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from pipeline import api, countries, gdelt, press, relations
from pipeline.sinks import LocalSink
from tests.test_cycle import zipped
from tests.test_gdelt import gkg_row

TABLE = {"news.cn": "CH", "yna.co.kr": "KS", "aljazeera.com": "US", "nknews.org": "XX", "example.com": "US"}
SUBJ = frozenset({"KN", "KS", "UP"})


def loc(name, cc):
    return f"1#{name}#{cc}#{cc}##1#2#x#10"


def v2(*locs):
    return ";".join(locs)


class LocationTests(unittest.TestCase):
    def test_counts_by_mention_and_drops_listed_names(self):
        c = press.location_counts(v2(loc("Pyongyang", "KN"), loc("North Korea", "KN"), loc("Suede", "SW"),
                                     loc("Seoul", "KS")), frozenset({"Suede"}))
        self.assertEqual(c, {"KN": 2, "KS": 1})

    def test_real_sweden_survives_the_suede_fix(self):
        drop = frozenset(press.outlets_catalog()["drop_location_names"])
        self.assertEqual(press.location_counts(v2(loc("Suecia", "SW"), loc("Suede", "SW")), drop), {"SW": 1})

    def test_main_country_is_single_most_mentioned(self):
        self.assertEqual(press.main_country({"KN": 2, "KS": 1}), "KN")
        self.assertIsNone(press.main_country({"KN": 1, "KS": 1}))
        self.assertIsNone(press.main_country({}))


class OutletTests(unittest.TestCase):
    def test_parent_domains_and_www(self):
        self.assertEqual(press.outlet_country("www.news.cn", TABLE), "CH")
        self.assertEqual(press.outlet_country("english.news.cn", TABLE), "CH")
        self.assertIsNone(press.outlet_country("cn", TABLE))
        self.assertIsNone(press.outlet_country("unknown.example.org", TABLE))

    def test_catalog_overrides(self):
        t = press.domain_table()
        self.assertEqual(press.outlet_country("aljazeera.com", t), "QA")
        self.assertEqual(press.outlet_country("aljazeera.net", t), "QA")
        self.assertEqual(press.outlet_country("storm.mg", t), "TW")
        self.assertIsNone(press.outlet_country("nknews.org", t))  # deliberately unassigned
        self.assertEqual(press.outlet_country("www.koreaherald.com", t), "KS")  # from the trimmed 2018 table
        self.assertEqual(press.outlet_country("sputnik.af", t), "RS")  # 2026-11-16.2
        # 2026-11-16.3: GDELT's 2018 table codes these Sputnik sites Georgia and China; state media keep their sponsor
        self.assertEqual(press.outlet_country("sputnik-georgia.com", t), "RS")
        self.assertEqual(press.outlet_country("sputniknews.cn", t), "RS")
        for gov in ("valtioneuvosto.fi", "puolustusvoimat.fi", "raja.fi"):  # Finnish government pages, not press
            self.assertIn(gov, t)
            self.assertIsNone(press.outlet_country(gov, t))

    def test_every_override_and_block_code_is_a_fips_country(self):
        names = press.fips_names()
        codes = [c for c in press.outlets_catalog()["overrides"].values() if c]
        for b in press.zone_blocks().values():
            codes += b["about"] + b["outlets"] + b.get("home", []) + b.get("self", [])
        self.assertEqual([c for c in codes if c not in names and c not in ("GZ", "WE", "RQ")], [])


class FileTableTests(unittest.TestCase):
    def test_counts_any_and_main_with_tone(self):
        ft = press.FileTable(SUBJ, TABLE)
        ft.add("news.cn", -2.0, v2(loc("Pyongyang", "KN"), loc("Pyongyang", "KN"), loc("Seoul", "KS")))
        ft.add("news.cn", 1.0, v2(loc("Seoul", "KS")))
        ft.add("yna.co.kr", -4.0, v2(loc("Pyongyang", "KN")))
        ft.add("news.cn", None, v2(loc("Seoul", "KS")))  # no tone: not counted
        ft.add("news.cn", -1.0, v2(loc("Paris", "FR")))  # no subject country: not counted
        ft.add("mystery.example", -1.0, v2(loc("Seoul", "KS")))  # unknown outlet
        row = ft.row("20261113000000", "english")
        self.assertEqual(row["kind"], "press")
        self.assertEqual(row["t"]["CH>KN"], [1, -2.0, 1, -2.0])
        self.assertEqual(row["t"]["CH>KS"], [2, -1.0, 1, 1.0])  # main only where Seoul led
        self.assertEqual(row["t"]["KS>KN"], [1, -4.0, 1, -4.0])
        self.assertEqual((row["articles"], row["unknown"]), (4, 1))
        self.assertEqual(row["unknown_top"], [["mystery.example", 1]])
        self.assertEqual(press.day_table([row, row])["unknown_top"], [["mystery.example", 2]])
        self.assertTrue(json.dumps(row).startswith(press.ROW_PREFIX))

    def test_parse_keeps_v2_locations_out_of_rows(self):
        a = gdelt.parse_row(gkg_row(f10=loc("Kyiv", "UP")), "english")
        self.assertEqual(a.v2_locations, loc("Kyiv", "UP"))
        self.assertNotIn("v2_locations", a.to_dict())

    def test_add_zip_skips_blocked_rows_and_counts_the_rest(self):
        data = zipped(gkg_row(f3="news.cn", f10=loc("Kyiv", "UP")), gkg_row(f0="b", f3="news.cn", f10=loc("Kyiv", "UP")))
        row = press.FileTable(SUBJ, TABLE).add_zip(data, "english").row("s", "english")
        self.assertEqual(row["t"]["CH>UP"][0], 2)


class ZoneRowsTests(unittest.TestCase):
    def test_roles(self):
        rows = press.zone_rows({"about": ["RP", "VM"], "outlets": ["CH", "US"], "home": ["RP", "VM"],
                                "self": ["RP", "VM", "CH"]})
        self.assertIn(("CH", "RP", "outside"), rows)
        self.assertIn(("RP", "VM", "home"), rows)
        self.assertNotIn(("RP", "RP", "home"), rows)
        self.assertIn(("RP", "RP", "self"), rows)
        self.assertIn(("CH", "CH", "self"), rows)
        self.assertEqual(len(rows), len(set((o, s) for o, s, _ in rows)))

    def test_catalog_blocks(self):
        blocks = press.zone_blocks()
        self.assertNotIn("12_Sahel_West_Africa", blocks)
        self.assertEqual(blocks["08_South_China_Sea"]["self"], ["RP", "VM", "CH"])
        self.assertNotIn("RS", blocks["07_Russia_NATO"]["about"])
        self.assertIn("RS>PL", press.series_keys())
        self.assertTrue({"UP", "KN", "CH", "RS"} <= press.subjects())


def prow(stamp, stream, t):
    return {"kind": "press", "stamp": stamp, "stream": stream, "articles": 1, "unknown": 0, "t": t}


class DayTests(unittest.TestCase):
    def test_one_pass_reads_events_and_press_and_keeps_first_copies(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            ev = {"kind": "events", "stamp": "20261113234500", "stream": "english", "countries": {}, "pairs": {}}
            p1 = prow("20261113234500", "english", {"CH>KN": [1, -1.0, 1, -1.0]})
            sink.write_lines("cycles/2026/11/13/235000.jsonl", [{"kind": "gdelt", "url": "x"}, ev, p1])
            sink.write_lines("cycles/2026/11/14/000500.jsonl", [ev, p1, prow("20261114000000", "english", {})])
            recs, prs = countries.day_records_and_press(sink, date(2026, 11, 13))
            self.assertEqual(len(recs), 1)
            self.assertEqual([r["stamp"] for r in prs], ["20261113234500"])
            self.assertEqual(len(countries.day_records(sink, date(2026, 11, 13))), 1)  # old reader unchanged

    def test_day_table_sums_and_series_keeps_zone_rows_only(self):
        recs = [prow(f"2026111300{m:02d}00", s, {"CH>KN": [2, -3.0, 1, -1.5], "ZZ>KN": [1, 0.0, 1, 0.0]})
                for m in (0, 15) for s in ("english", "translation")]
        t = press.day_table(recs)
        self.assertTrue(t["partial"])
        self.assertEqual(t["t"]["CH>KN"], [8, -12.0, 4, -6.0])
        rec = relations.day_table(date(2026, 11, 13), [], recs)
        with tempfile.TemporaryDirectory() as td:
            s = relations.update_series(LocalSink(td), [rec], keys=set(), press_keys={"CH>KN"})
        self.assertEqual(s["days"]["2026-11-13"]["press"]["t"], {"CH>KN": [8, -12.0, 4, -6.0]})
        self.assertNotIn("press", relations.day_table(date(2026, 11, 13), []))


CAT = {"version": "t", "names": {}, "zones": {"03_Korea_Peninsula": {
    "pairs": [["PRK", "KOR"]], "press": {"about": ["KN"], "outlets": ["US", "JA", "GM"]}}}}


def series(days=60, end=date(2026, 11, 13)):
    out = {}
    for i in range(days):
        d = end - timedelta(days=days - 1 - i)
        late = i >= days - 7
        out[d.isoformat()] = {"partial": False, "pairs": {}, "press": {"partial": False, "t": {
            "US>KN": [50, -100.0, 40, -80.0 if not late else -200.0],  # tone -2, then -5 in the last week
            "JA>KN": [4, -8.0, 3, -6.0],
            "GM>KN": [1, -1.0, 1, -1.0]}}}
    return {"days": out}


class ViewTests(unittest.TestCase):
    def test_cadence_tone_and_baseline(self):
        v = press.zone_view(series(), "03_Korea_Peninsula", date(2026, 11, 13), 30, CAT, names={"US": "United States"})
        rows = {r["outlet"]: r for r in v["rows"]}
        us = rows["US"]
        self.assertEqual(us["cadence"], "daily")
        self.assertEqual(us["tone_7d"], -5.0)
        self.assertEqual(us["base_tone_7d"], -2.0)
        self.assertLess(us["z_tone_7d"], -2)
        self.assertEqual(us["articles"][-1], 40)
        self.assertEqual(us["outlet_name"], "United States")
        self.assertEqual(rows["JA"]["cadence"], "weekly")  # 3 a day, 21 a week
        self.assertEqual(rows["GM"]["cadence"], "thin")
        self.assertIsNone(rows["GM"]["tone_7d"])  # 7 articles a week: under the 7-day floor
        self.assertEqual(len(v["days"]), 30)

    def test_partial_days_are_never_baselines_and_zones_without_a_block_get_none(self):
        s = series()
        s["days"]["2026-11-10"]["press"]["partial"] = True
        v = press.zone_view(s, "03_Korea_Peninsula", date(2026, 11, 13), 30, CAT, names={})
        self.assertIsNone({r["outlet"]: r for r in v["rows"]}["US"]["tone_7d"])  # the week has a partial day
        self.assertIsNone(press.zone_view(s, "16_Myanmar", date(2026, 11, 13), 30, CAT))

    def test_days_before_press_are_left_out(self):
        s = series()
        for d in list(s["days"])[:50]:
            del s["days"][d]["press"]
        v = press.zone_view(s, "03_Korea_Peninsula", date(2026, 11, 13), 90, CAT, names={})
        self.assertEqual(len(v["days"]), 10)

    def test_relations_view_and_api_carry_press(self):
        v = relations.zone_view(series(), "03_Korea_Peninsula", cat=CAT)
        self.assertEqual(len(v["press"]["rows"]), 3)
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            sink.write_json(relations.SERIES_KEY, series())
            api._CACHE.clear()
            status, out = api.handle("GET", "/relations", {"zone": "03_Korea_Peninsula"}, None, sink, ai_on=False)
            api._CACHE.clear()
        self.assertEqual(status, 200)
        self.assertIn("press", out)
        self.assertEqual(out["press"]["about"][0]["cc"], "KS")  # the deployed catalog's Korea block


class BackfillMergeTests(unittest.TestCase):
    def test_press_merge_keeps_pairs(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location(
            "backfill_relations", Path(__file__).resolve().parent.parent / "scripts" / "backfill_relations.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        old = {"day": "2026-11-13", "partial": False, "pairs": {"PRK|KOR": [1] * 9}, "files": 192}
        rec = mod.merge_press(date(2026, 11, 13), old, [prow("20261113000000", "english", {"US>KN": [1, -1.0, 1, -1.0]})])
        self.assertEqual(rec["pairs"], old["pairs"])
        self.assertEqual(rec["press"]["t"]["US>KN"], [1, -1.0, 1, -1.0])
        self.assertNotIn("press", old)
        fresh = mod.merge_press(date(2026, 11, 13), None, [])
        self.assertTrue(fresh["partial"])
        self.assertEqual(fresh["pairs"], {})


if __name__ == "__main__":
    unittest.main()
