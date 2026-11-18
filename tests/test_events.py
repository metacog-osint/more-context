import io
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone

from pipeline import api, countries, cycle, events
from pipeline.sinks import LocalSink


def row(eid, cc, url, root="18", code="190", day="20261028", is_root="1", gtype="4", place="Mekelle, Tigray, Ethiopia",
        lat="13.5", lon="39.5", sources="2", articles="3"):
    f = [""] * events.FIELDS
    f[events.ID], f[events.DAY], f[events.A1NAME], f[events.A2NAME] = eid, day, "REBEL", "MILITARY"
    f[events.ROOT], f[events.CODE], f[events.ROOTCODE], f[events.QUAD] = is_root, code, root, "4"
    f[events.NUM_SOURCES], f[events.NUM_ARTICLES] = sources, articles
    f[events.GTYPE], f[events.GNAME], f[events.GCC], f[events.GLAT], f[events.GLON] = gtype, place, cc, lat, lon
    f[events.ADDED], f[events.URL] = "20261028120000", url
    return f


def zipped(rows):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x.export.CSV", "\n".join("\t".join(r) for r in rows))
    return buf.getvalue()


class RecordTests(unittest.TestCase):
    def test_counts_distinct_articles_per_country(self):
        rows = [row("1", "ET", "https://a/1"), row("2", "ET", "https://a/1", root="04", is_root="0"),
                row("3", "ET", "https://a/2", root="04", gtype="1"), row("4", "SO", "https://a/3", root="04")]
        r = events.record(events.parse_zip(zipped(rows)), "20261028120000", "english")
        # ev, urls, root, place, violent
        self.assertEqual(r["countries"]["ET"], [3, 2, 2, 1, 1])
        self.assertEqual(r["countries"]["SO"], [1, 1, 1, 1, 0])
        self.assertEqual([v["id"] for v in r["violent"]], ["1"])
        self.assertEqual(r["samples"]["ET"][0], "https://a/1")  # lead-paragraph, placed event first

    def test_old_events_and_country_level_violence_are_left_out(self):
        rows = [row("1", "ET", "https://a/1", day="20251028"), row("2", "ET", "https://a/2", gtype="1")]
        r = events.record(events.parse_zip(zipped(rows)), "20261028120000", "english")
        self.assertEqual(r["countries"]["ET"], [1, 1, 1, 0, 1])  # the year-old event is skipped
        self.assertEqual(r["violent"], [])  # violence placed only at the country's centre: not mapped


def write_day(sink, d: date, counts: dict[str, int], streams=("english", "translation"), files=96):
    """`files` slot records per stream in one object, the day's count for each country in the first slot."""
    recs = []
    for i in range(files):
        stamp = (datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S")
        for s in streams:
            c = {cc: [n, n, n, n, n] for cc, n in counts.items()} if i == 0 and s == "english" else {}
            recs.append({"stamp": stamp, "stream": s, "rows": 1, "countries": c,
                         "samples": {cc: [f"https://x/{cc}"] for cc in c}, "violent": []})
    sink.write_json(f"events/{d:%Y/%m/%d}/000000.json", {"files": recs})


class CountryDayTests(unittest.TestCase):
    def test_a_jump_against_the_country_normal_is_rising(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            start = date(2026, 9, 1)
            for i in range(30):
                d = start + timedelta(days=i)
                write_day(sink, d, {"ET": 50 + (i % 3), "US": 3000 + 10 * (i % 4)})
                countries.build_day(sink, d)
            d = start + timedelta(days=30)
            write_day(sink, d, {"ET": 400, "US": 3050})
            out = countries.build_day(sink, d)
            self.assertEqual(out["rising"], ["ET"])
            self.assertEqual(out["violent_rising"], ["ET"])
            c = sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")
            self.assertEqual(c["countries"]["ET"]["zones"], ["18_Ethiopia_Eritrea"])
            self.assertNotIn("zones", c["countries"]["US"])
            self.assertIn("ET", c["samples"])

    def test_a_day_missing_files_is_partial_and_not_scored(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            d = date(2026, 9, 1)
            write_day(sink, d, {"ET": 50}, files=40)
            out = countries.build_day(sink, d)
            self.assertTrue(out["partial"])
            self.assertNotIn("urls_score", sink.read_json(f"stories/{d:%Y/%m/%d}/countries.json")["countries"]["ET"])


class ZoneViolenceTests(unittest.TestCase):
    def test_counts_violence_in_the_zone_whose_headline_names_it(self):
        v = lambda i, cc, url, adm1="": {"id": i, "cc": cc, "adm1": adm1, "url": url}
        recs = [{"stamp": "20261026120000", "stream": "english", "violent": [
            v("1", "ET", "https://x/ethiopia-attack-kills-60-in-oromia"),
            v("2", "ET", "https://x/ethiopia-attack-kills-60-in-oromia"),  # same article, second event
            v("3", "ET", "https://x/eyes-open-in-addis"),  # no zone term in the headline
            v("4", "RS", "https://x/kaliningrad-drone-strike-on-depot", adm1="RS23"),  # Kaliningrad counts for Russia-NATO
            v("5", "RS", "https://x/russia-strikes-belgorod-again", adm1="RS09"),  # the rest of Russia does not
        ]}]
        z = countries.zone_violence(recs)
        self.assertEqual(z["18_Ethiopia_Eritrea"], {"events": 3, "articles": 2, "named": 1})
        self.assertEqual(z["07_Russia_NATO"]["articles"], 1)

    def test_iran_counts_the_gulf_hosts_and_iraq_when_the_headline_names_the_zone(self):
        v = lambda i, cc, url: {"id": i, "cc": cc, "adm1": "", "url": url}
        recs = [{"stamp": "20261117120000", "stream": "english", "violent": [
            v("1", "BA", "https://x/iran-launches-third-round-of-strikes-on-bahrain"),
            v("2", "IZ", "https://x/iran-backed-militia-attacks-base-in-iraq"),
            v("3", "BA", "https://x/manama-court-jails-robbery-gang"),  # no zone term: not counted
            v("4", "IR", "https://x/us-strikes-iran-qeshm-island"),
        ]}]
        z = countries.zone_violence(recs)["11_Iran_Red_Sea"]
        self.assertEqual({k: z[k] for k in ("events", "articles", "named")}, {"events": 4, "articles": 4, "named": 3})
        old = {"11_Iran_Red_Sea": (frozenset({"IR", "YM"}), frozenset())}
        self.assertEqual(countries.zone_violence(recs, scopes=old, members=frozenset()),
                         {"11_Iran_Red_Sea": {"events": 1, "articles": 1, "named": 1}})

    def test_iran_counts_each_member_and_lists_the_quiet_ones(self):
        v = lambda i, cc, url: {"id": i, "cc": cc, "adm1": "", "url": url}
        recs = [{"stamp": "20261115120000", "stream": "english", "violent": [
            v("1", "BA", "https://x/blasts-rock-bahrain-as-fresh-iran-strikes-target-us-base"),
            v("2", "IR", "https://x/blasts-rock-bahrain-as-fresh-iran-strikes-target-us-base"),  # one article, two members
            v("3", "SA", "https://x/houthis-claim-missile-attack-on-saudi-aramco-in-yemen-war"),
            v("4", "SA", "https://x/riyadh-traffic-crash-kills-four"),  # no zone term: not counted
        ]}]
        z = countries.zone_violence(recs)["11_Iran_Red_Sea"]
        self.assertEqual(z["named"], 2)  # the shared article counts once in the total
        m = {k: x["named"] for k, x in z["members"].items()}
        self.assertEqual(m, {"AE": 0, "BA": 1, "IR": 1, "IZ": 0, "KU": 0, "MU": 0, "QA": 0, "SA": 1, "YM": 0})
        self.assertEqual(z["members"]["BA"]["name"], "Bahrain")
        self.assertNotIn("members", countries.zone_violence(recs)["10_Israel_Gaza_Lebanon"])  # opt-in per zone

    def test_a_burst_in_a_quiet_member_is_a_spike_when_the_total_is_not(self):
        start = date(2026, 10, 1)
        hist = {"zone_named": {}, "zone_member": {}}
        complete = [start + timedelta(days=i) for i in range(28)]
        for d in complete:  # Saudi Arabia busy and steady; Bahrain 0-1 a day
            hist["zone_named"].setdefault("Z", {})[d] = 140 + d.day % 5
            hist["zone_member"].setdefault("Z", {}).setdefault("SA", {})[d] = 40 + d.day % 5
            hist["zone_member"]["Z"].setdefault("BA", {})[d] = d.day % 2
        day = start + timedelta(days=28)
        zv = {"named": 148, "members": {"SA": {"name": "Saudi Arabia", "named": 41},
                                        "BA": {"name": "Bahrain", "named": 8}}}
        countries.score_zone("Z", zv, hist, complete, day)
        self.assertLess(zv["named_score"]["z"], 2)
        self.assertEqual(zv["spikes"], ["BA"])
        self.assertGreaterEqual(zv["members"]["BA"]["named_score"]["z"], countries.MEMBER_Z)
        zv["members"]["BA"]["named"] = 4  # under MEMBER_MIN articles: no spike
        countries.score_zone("Z", zv, hist, complete, day)
        self.assertEqual(zv["spikes"], [])

    def test_members_are_scored_from_stored_days(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            start = date(2026, 10, 1)
            for i in range(28):
                d = start + timedelta(days=i)
                sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", {"partial": False, "countries": {}, "zones": {
                    "11_Iran_Red_Sea": {"named": 100, "members": {"BA": {"named": i % 2}, "SA": {"named": 40}}}}})
            hist, complete = countries.history(sink, start + timedelta(days=28))
            self.assertEqual(len(hist["zone_member"]["11_Iran_Red_Sea"]["BA"]), 28)
            self.assertEqual(hist["zone_member"]["11_Iran_Red_Sea"]["SA"][start], 40)

    def test_violent_jsonl_keeps_events_in_a_violence_scope(self):
        # Bahrain is in no zone's countries, only in Iran & Red Sea's violence scope: its events go on the map.
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            rec = {"stamp": "20261117120000", "stream": "english", "countries": {"BA": [1, 1, 0, 1, 1]}, "samples": {},
                   "violent": [{"id": "9", "cc": "BA", "adm1": "BA16", "url": "https://x/iran-drones-hit-bahrain",
                                "lat": 26.2, "lon": 50.6}]}
            countries.build_day(sink, date(2026, 11, 17), recs=[rec])
            rows = sink.read_lines("stories/2026/11/17/violent.jsonl")
            self.assertEqual([r["cc"] for r in rows], ["BA"])


class CycleEventsTests(unittest.TestCase):
    def test_events_follow_the_gkg_slots_read(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            now = datetime(2026, 10, 28, 12, 20, tzinfo=timezone.utc)
            asked = []

            def dl_events(stamp, stream):
                asked.append((stamp, stream))
                return zipped([row("1", "ET", "https://a/1")]) if stream == "english" else None

            empty = zipped([])
            summary = cycle.run_cycle(sink, now=now, streams=("english",), poll_rss=False, build_stories=False,
                                      ai_on=False, latest=lambda s: "20261028121500", download=lambda st, s: empty,
                                      download_events=dl_events)
            self.assertIn(("20261028121500", "english"), asked)
            ok = summary["events"]["english"]["ok"]
            self.assertEqual(ok, len([a for a in asked if a[1] == "english"]))
            # One data write a run: the records ride in the cycle file, no events/ object (30 Oct 2026).
            self.assertEqual(sink.list("events/"), [])
            key = summary["written"]["key"]
            self.assertEqual(summary["written"]["events_files"], ok)
            self.assertEqual(summary["written"]["rows"], 0)  # the fake GKG files held no articles
            recs = sink.read_lines(key, events.ROW_PREFIX)
            self.assertEqual(len(recs), ok)
            self.assertTrue(all(r["kind"] == "events" for r in recs))
            self.assertEqual(countries.day_records(sink, date(2026, 10, 28))[0]["countries"]["ET"][1], 1)


class EventsStorageTests(unittest.TestCase):
    """Records written before 30 Oct 2026 (and by backfills) sit in events/; newer ones in cycle files."""

    def rec(self, stamp, stream="english"):
        return {"stamp": stamp, "stream": stream, "rows": 1, "countries": {"ET": [1, 1, 1, 1, 1]},
                "samples": {}, "violent": []}

    def test_records_are_read_from_both_places_once(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            sink.write_json("events/2026/10/30/101500.json", {"files": [self.rec("20261030100000")]})
            sink.write_json("events/2026/10/30/20261030101500.json", {"files": [self.rec("20261030101500")]})
            sink.write_lines("cycles/2026/10/30/103000.jsonl", [
                {"kind": "gdelt", "url": "https://a/1", "published": "2026-10-30T10:20:00Z"},
                events.as_row(self.rec("20261030101500")),  # also in events/: counted once
                events.as_row(self.rec("20261030103000"))])
            # The next day's first runs fetch the day's last files; backfill names carry the full stamp or a "t".
            sink.write_lines("cycles/2026/10/31/001500.jsonl", [events.as_row(self.rec("20261030234500"))])
            sink.write_json("events/2026/10/31/20261031001500.json", {"files": [self.rec("20261030233000")]})
            sink.write_lines("cycles/2026/10/31/003000t.jsonl", [events.as_row(self.rec("20261030231500"))])
            sink.write_lines("cycles/2026/10/31/050000.jsonl", [events.as_row(self.rec("20261030230000"))])  # too late
            stamps = sorted(r["stamp"] for r in countries.day_records(sink, date(2026, 10, 30)))
            self.assertEqual(stamps, ["20261030100000", "20261030101500", "20261030103000", "20261030231500",
                                      "20261030233000", "20261030234500"])

    def test_row_line_starts_with_the_prefix(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            sink.write_lines("cycles/x.jsonl", [{"kind": "rss", "url": "u"}, events.as_row(self.rec("1"))])
            self.assertEqual([r["stamp"] for r in sink.read_lines("cycles/x.jsonl", events.ROW_PREFIX)], ["1"])
            self.assertEqual(len(sink.read_lines("cycles/x.jsonl")), 2)


class ApiTests(unittest.TestCase):
    def test_countries_and_violent_endpoints(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            d = date(2026, 10, 27)
            sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", {
                "day": d.isoformat(), "partial": False, "files": 192, "scored": ["urls", "violent"],
                "lists": {"violent": {"rising": ["ET"], "elevated": []}}, "countries": {"ET": {"name": "Ethiopia"}},
                "samples": {"ET": ["https://x.com/ethiopia-fighting-in-tigray-resumes", "javascript:alert(1)"]}})
            sink.write_lines(f"stories/{d:%Y/%m/%d}/violent.jsonl", [
                {"id": "1", "cc": "ET", "lat": 13.5, "lon": 39.5, "url": "https://a/ethiopia-clashes-in-tigray", "sources": 2},
                {"id": "4", "cc": "ET", "lat": 9.0, "lon": 38.7, "url": "https://a/eyes-open-in-addis", "sources": 5},  # no zone term
                {"id": "2", "cc": "US", "lat": 1.0, "lon": 2.0, "url": "https://a/2", "sources": 9},
                {"id": "3", "cc": "ET", "lat": 13.5, "lon": 39.5, "url": "javascript:x", "sources": 9}])
            st, body = api.handle("GET", "/countries", {}, None, sink, ai_on=False, today=date(2026, 10, 28))
            self.assertEqual(st, 200)
            self.assertEqual(body["day"], "2026-10-27")
            self.assertEqual([s["url"] for s in body["samples"]["ET"]], ["https://x.com/ethiopia-fighting-in-tigray-resumes"])
            st, body = api.handle("GET", "/violent", {"day": "2026-10-27", "zone": "18_Ethiopia_Eritrea"}, None, sink,
                                  ai_on=False, today=date(2026, 10, 28))
            self.assertEqual((st, [e["id"] for e in body["events"]]), (200, ["1"]))
            st, _ = api.handle("GET", "/violent", {"day": "2026-10-27", "zone": "T1_Critical_Minerals"}, None, sink,
                               ai_on=False, today=date(2026, 10, 28))
            self.assertEqual(st, 400)

    def test_summary_carries_zone_violence_and_entities_carry_map(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(td)
            d = date(2026, 10, 27)
            sink.write_json(f"stories/{d:%Y/%m/%d}/summary.json", {"day": d.isoformat(), "entities": {"13_Sudan": {"stories": 5}}})
            sink.write_json(f"stories/{d:%Y/%m/%d}/countries.json", {"day": d.isoformat(), "countries": {},
                            "zones": {"13_Sudan": {"events": 9, "articles": 6, "named": 4, "named_score": {"z": 2.1}}}})
            st, body = api.handle("GET", "/summary", {"day": "2026-10-27"}, None, sink, ai_on=False, today=date(2026, 10, 28))
            self.assertEqual((st, body["entities"]["13_Sudan"]["violence"]["named"]), (200, 4))
            st, body = api.handle("GET", "/entities", {}, None, sink, ai_on=False, today=date(2026, 10, 28))
            sudan = next(z for z in body["zones"] if z["id"] == "13_Sudan")
            self.assertEqual((sudan["map"], sudan["countries"]), ([15.5, 30.5], ["SU"]))


if __name__ == "__main__":
    unittest.main()
