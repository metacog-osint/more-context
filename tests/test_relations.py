import json
import tempfile
import unittest
from datetime import date, timedelta
from unittest import mock

from pipeline import api, events, relations
from pipeline.sinks import LocalSink
from tests.test_events import zipped

CAT = {"version": "test", "names": {"PRK": "North Korea", "KOR": "South Korea"},
       "zones": {"03_Korea_Peninsula": {"pairs": [["PRK", "KOR"]]}}}


def ev(a1, a2, quad, url, *, gold=-4.0, tone=-3.0, day="20261113", root="1", kg1="", kg2=""):
    r = [""] * 61
    r[1], r[7], r[8], r[17], r[18] = day, a1, kg1, a2, kg2
    r[25], r[29], r[30], r[34], r[60] = root, str(quad), str(gold), str(tone), url
    return r


def vec(n, verbal=0, material=0, gold=1.0, tone=-1.0):
    """A day's VEC for n articles, `verbal`/`material` of them with conflict events."""
    conf = verbal + material
    return [n, n - conf, 0, verbal, material, conf, gold * n, tone * n, n]


class PairTableTests(unittest.TestCase):
    def test_counts_each_article_once_per_pair(self):
        rows = [ev("PRK", "KOR", 3, "https://a/1", gold=-4.0), ev("PRK", "KOR", 1, "https://a/1", gold=2.0),
                ev("PRK", "KOR", 4, "https://a/2", gold=-10.0, root="0"), ev("KOR", "PRK", 1, "https://a/1")]
        t = relations.pair_table(rows, "20261113000000")
        self.assertEqual(t["PRK|KOR"][:6], [2, 1, 0, 1, 1, 2])
        self.assertAlmostEqual(t["PRK|KOR"][6], -1.0 + -10.0)  # each article's mean Goldstein, summed
        self.assertEqual(t["PRK|KOR"][8], 1)  # one article with a lead-paragraph event
        self.assertEqual(t["KOR|PRK"][0], 1)

    def test_un_and_nato_are_partners_and_old_or_one_sided_events_are_not(self):
        rows = [ev("", "PRK", 3, "https://a/1", kg1="UNO"), ev("RUS", "WST", 3, "https://a/2", kg2="NAT"),
                ev("PRK", "KOR", 4, "https://a/3", day="20261101"), ev("PRK", "", 4, "https://a/4"),
                ev("PRK", "PRK", 4, "https://a/5")]
        self.assertEqual(sorted(relations.pair_table(rows, "20261113000000")), ["RUS|NAT", "UNO|PRK"])

    def test_events_records_carry_the_table(self):
        r = events.record(events.parse_zip(zipped([ev("PRK", "KOR", 3, "https://a/1")])), "20261113000000", "english")
        self.assertEqual(r["pairs"]["PRK|KOR"][0], 1)


class BuildTests(unittest.TestCase):
    def recs(self, n_files=96, pairs=True):
        out = []
        for stream in ("english", "translation"):
            for i in range(n_files):
                r = {"stamp": f"20261113{i:04d}00", "stream": stream}
                if pairs:
                    r["pairs"] = {"PRK|KOR": [1, 0, 0, 1, 0, 1, -2.0, -3.0, 1]} if i == 0 else {}
                out.append(r)
        return out

    def test_day_table_sums_files_and_marks_partial_days(self):
        t = relations.day_table(date(2026, 11, 13), self.recs())
        self.assertFalse(t["partial"])
        self.assertEqual(t["pairs"]["PRK|KOR"], [2, 0, 0, 2, 0, 2, -4.0, -6.0, 2])
        self.assertTrue(relations.day_table(date(2026, 11, 13), self.recs(n_files=60))["partial"])
        self.assertTrue(relations.day_table(date(2026, 11, 13), self.recs(pairs=False))["partial"])  # before pairs

    def test_build_writes_the_day_and_keeps_only_named_pairs_in_the_series(self):
        recs = self.recs()
        recs[1]["pairs"] = {"USA|CHN": [5, 5, 0, 0, 0, 0, 10.0, 0.0, 5]}
        with tempfile.TemporaryDirectory() as td, mock.patch.object(relations, "catalog", lambda: CAT):
            sink = LocalSink(td)
            relations.build_day(sink, date(2026, 11, 13), recs)
            self.assertIn("USA|CHN", sink.read_json("stories/2026/11/13/relations.json")["pairs"])
            s = sink.read_json(relations.SERIES_KEY)
            self.assertEqual(list(s["days"]["2026-11-13"]["pairs"]), ["PRK|KOR"])
            # a rebuild from stored days gives the same series, and the series keeps the newest SERIES_DAYS
            again = relations.rebuild_series(sink, date(2026, 11, 13), days=3)
            self.assertEqual(again["days"], s["days"])
            many = [{"day": (date(2026, 1, 1) + timedelta(days=i)).isoformat(), "partial": False, "pairs": {}}
                    for i in range(relations.SERIES_DAYS + 5)]
            trimmed = relations.update_series(sink, many, series={})
            self.assertEqual(len(trimmed["days"]), relations.SERIES_DAYS)
            self.assertEqual(min(trimmed["days"]), "2026-01-06")


def series(spike_day: date, start=date(2026, 9, 1), end=date(2026, 11, 14)) -> dict:
    days, d = {}, start
    while d <= end:
        quiet = 6 + (d.toordinal() % 3)
        if d == spike_day:
            days[d.isoformat()] = {"partial": False, "pairs": {"PRK|KOR": vec(40, verbal=20, gold=-3.0),
                                                                 "KOR|PRK": vec(30, verbal=4)}}
        else:
            days[d.isoformat()] = {"partial": d == date(2026, 10, 1), "pairs": {"PRK|KOR": vec(quiet, verbal=1),
                                                                                 "KOR|PRK": vec(quiet)}}
        d += timedelta(days=1)
    return {"vec": list(relations.VEC), "days": days}


class ViewTests(unittest.TestCase):
    def test_a_spike_is_flagged_both_ways_and_by_verbal_conflict(self):
        spike = date(2026, 11, 10)
        v = relations.zone_view(series(spike), "03_Korea_Peninsula", days=30, cat=CAT, detail=True)
        self.assertEqual(len(v["days"]), 30)
        p = v["pairs"][0]
        self.assertEqual(len(p["articles"]), 30)
        self.assertEqual(p["articles"][v["days"].index("2026-11-10")], 70)
        self.assertEqual(p["flagged"], ["2026-11-10"])
        self.assertEqual(p["latest"]["day"], "2026-11-14")
        self.assertNotIn("rows", relations.zone_view(series(spike), "03_Korea_Peninsula", days=30, cat=CAT)["pairs"][0])
        self.assertEqual(v["flags"][0]["day"], "2026-11-10")
        why = {(w["direction"], w["count"]) for w in v["flags"][0]["why"]}
        self.assertIn(("both", "articles"), why)
        self.assertIn(("ab", "verbal_conflict"), why)
        day = next(d for d in v["pairs"][0]["rows"] if d["day"] == "2026-11-10")
        self.assertEqual(day["ab"]["articles"], 40)
        self.assertEqual(day["ab"]["conflict_share"], 0.5)
        self.assertEqual(day["both"]["articles"], 70)
        self.assertGreater(day["ab"]["z_conflict_share_7d"], 2)
        self.assertEqual(v["pairs"][0]["a_name"], "North Korea")

    def test_partial_days_are_shown_but_never_scored_and_unnamed_zones_have_no_view(self):
        v = relations.zone_view(series(date(2026, 11, 10)), "03_Korea_Peninsula", end=date(2026, 10, 20), days=30,
                                cat=CAT, detail=True)
        d = next(x for x in v["pairs"][0]["rows"] if x["day"] == "2026-10-01")
        self.assertFalse(v["complete"][v["days"].index("2026-10-01")])
        self.assertFalse(d["complete"])
        self.assertNotIn("z_articles", d["both"])
        self.assertEqual(v["end"], "2026-10-20")
        self.assertIsNone(relations.zone_view(series(date(2026, 11, 10)), "13_Sudan", cat=CAT))


class FastZTests(unittest.TestCase):
    def test_same_z_as_measures(self):
        import random
        from pipeline import measures
        rnd = random.Random(7)
        hist = {date(2026, 9, 1) + timedelta(days=i): float(rnd.choice([0, 1, 2, 3, 5, 8, 13, 40])) for i in range(60)}
        for i in range(10, 60, 3):
            d = date(2026, 9, 1) + timedelta(days=i)
            ref = measures.attention_anomaly(hist, d, hist[d])
            self.assertEqual(relations.anomaly_z(hist, d, hist[d]), ref["z"] if ref else None)


class ApiRelationsTests(unittest.TestCase):
    def test_relations_endpoint(self):
        api._CACHE.clear()
        with tempfile.TemporaryDirectory() as td, mock.patch.object(relations, "catalog", lambda: CAT):
            sink = LocalSink(td)
            today = date(2026, 11, 15)
            status, _ = api.handle("GET", "/relations", {"zone": "03_Korea_Peninsula"}, None, sink, ai_on=False,
                                   today=today)
            self.assertEqual(status, 404)  # nothing built yet
            sink.write_json(relations.SERIES_KEY, series(date(2026, 11, 10)))
            api._CACHE.clear()
            status, body = api.handle("GET", "/relations", {"zone": "03_Korea_Peninsula", "days": "30"}, None, sink,
                                      ai_on=False, today=today)
            self.assertEqual(status, 200)
            self.assertEqual(body["flags"][0]["day"], "2026-11-10")
            status, body = api.handle("GET", "/relations", {}, None, sink, ai_on=False, today=today)
            self.assertEqual((status, list(body["zones"])), (200, ["03_Korea_Peninsula"]))
            status, _ = api.handle("GET", "/relations", {"zone": "03_Korea_Peninsula", "days": "x"}, None, sink,
                                   ai_on=False, today=today)
            self.assertEqual(status, 400)
        api._CACHE.clear()


class CatalogTests(unittest.TestCase):
    def test_every_zone_named_exists_and_every_code_has_a_name(self):
        cat = json.loads(relations.CATALOG.read_text(encoding="utf-8"))
        ents = json.loads((relations.CATALOG.parent / "entities.json").read_text(encoding="utf-8"))
        zones = {z["id"] for z in ents["zones"]}
        self.assertLessEqual(set(cat["zones"]), zones)
        for z in cat["zones"].values():
            for a, b in z["pairs"]:
                self.assertIn(a, cat["names"])
                self.assertIn(b, cat["names"])
                self.assertNotEqual(a, b)



class CycleHookTests(unittest.TestCase):
    def test_the_day_build_reads_records_once_and_a_relations_failure_holds_nothing_up(self):
        from datetime import datetime, timezone
        from pipeline import countries, cycle, daily
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-11-12", "stories": {"last_day": "2026-11-12"}})
            reads, got = [], {}
            recs = [{"stamp": "20261113000000", "stream": "english", "countries": {}, "pairs": {}}]

            def fake_records(s, day):
                reads.append(day)
                return recs

            def fake_relations(s, day, r):
                got["recs"] = r
                raise RuntimeError("relations broke")

            now = datetime(2026, 11, 14, 5, 0, tzinfo=timezone.utc)
            with mock.patch.object(daily, "build_day", lambda s, d: {"day": d.isoformat()}), \
                    mock.patch.object(countries, "day_records", fake_records), \
                    mock.patch.object(countries, "build_day", lambda s, d, r=None: {"day": d.isoformat()}), \
                    mock.patch.object(relations, "build_day", fake_relations):
                summary = cycle.run_cycle(sink, now=now, streams=(), poll_rss=False, ai_on=False)
            self.assertEqual(reads, [date(2026, 11, 13)])
            self.assertIs(got["recs"], recs)
            self.assertIn("relations broke", summary["relations_error"])
            self.assertEqual(sink.read_json(cycle.STATE_KEY)["stories"]["last_day"], "2026-11-13")


if __name__ == "__main__":
    unittest.main()
