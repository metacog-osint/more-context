import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

from pipeline import api, budget, cycle, measures, ondemand
from pipeline.sinks import LocalSink

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=NOW):
        self.t = t

    def __call__(self):
        return self.t


def ledger(sink, clock=None, **kw):
    return budget.Ledger(sink, cap_usd=kw.get("cap", 5.0), alarm_reserve=kw.get("reserve", 1.0),
                         view_daily=kw.get("daily", 0.5), now=clock or Clock())


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = LocalSink(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reserve_settle_counts_actual(self):
        led = ledger(self.sink)
        rid = led.reserve(0.10, "view")
        self.assertEqual(led.status()["held_usd"], 0.1)
        led.settle(rid, 0.04)
        st = led.status()
        self.assertEqual((st["spent_usd"], st["held_usd"]), (0.04, 0.0))
        self.assertEqual(st["left_usd"], 4.96)

    def test_view_daily_limit_and_alarm_reserve(self):
        clock = Clock()
        led = ledger(self.sink, clock)
        led.settle(led.reserve(0.45, "view"), 0.45)
        with self.assertRaises(budget.BudgetExceeded):
            led.reserve(0.10, "view")  # $0.55 > $0.50 today
        led.reserve(0.10, "alarm")  # alarms are not bound by the daily view limit
        # Fill the month to $3.88 over earlier days (+ the $0.10 alarm hold, counted as spent once stale = $3.98);
        # view work must leave the last $1 for alarms
        for i in range(1, 8):
            clock.t = NOW - timedelta(days=i)
            led.settle(led.reserve(0.49, "view"), 0.49)
        clock.t = NOW + timedelta(days=1)
        with self.assertRaises(budget.BudgetExceeded):
            led.reserve(0.10, "view")
        led.settle(led.reserve(0.80, "alarm"), 0.80)  # alarms may use the reserve: $4.78 spent
        with self.assertRaises(budget.BudgetExceeded):
            led.reserve(0.30, "alarm")  # but never pass the $5 cap ($5.08)
        led.reserve(0.20, "alarm")  # $4.98 still fits

    def test_new_month_starts_fresh(self):
        clock = Clock()
        led = ledger(self.sink, clock)
        led.settle(led.reserve(4.9, "alarm"), 4.9)
        clock.t = datetime(2026, 12, 1, 0, 5, tzinfo=timezone.utc)
        self.assertEqual(led.status()["spent_usd"], 0.0)
        led.reserve(0.2, "view")

    def test_stale_reservation_counts_as_spent(self):
        clock = Clock()
        led = ledger(self.sink, clock)
        led.reserve(0.30, "view")  # never settled
        clock.t = NOW + timedelta(minutes=20)
        st = led.status()
        led.reserve(0.01, "alarm")  # any update expires it
        st = led.status()
        self.assertEqual((st["spent_usd"], st["held_usd"]), (0.3, 0.01))

    def test_compare_and_swap_retries(self):
        class Flaky(LocalSink):
            fails = 2

            def write_json_if(self, key, obj, version):
                if self.fails:
                    self.fails -= 1
                    return False
                return super().write_json_if(key, obj, version)

        led = ledger(Flaky(self.tmp.name))
        led.settle(led.reserve(0.05, "view"), 0.05)
        self.assertEqual(led.status()["spent_usd"], 0.05)


def coding_for(sid, entity):
    return {"story_id": sid, "entity": entity, "relevance": "on", "event_type": "ASSAULT", "quad": "material_conflict",
            "direction": "escalating", "indicator_ids": [], "frame": "military_action", "confidence": "moderate",
            "gist": "x", "model": "fake"}


class FakeCoder:
    calls = 0

    def __init__(self, model=None, spend_cap_usd=None):
        self.spent = 0.0

    def run(self, plan, pause_s=0):
        for req in plan.requests:
            FakeCoder.calls += 1
            self.spent += 0.003
            yield req, [coding_for(s, req["entity"]) for s in req["story_ids"]], []


def write_day(sink, day, entity="13_Sudan", n=30):
    rows = [{"day": day.isoformat(), "entity": entity, "kind": "gdelt", "story_id": f"s{i:02d}", "title": f"t{i}",
             "articles": 1, "outlets": 1, "languages": ["eng"], "groups": {}, "sample_urls": [f"https://a/{i}"]}
            for i in range(n)]
    sink.write_lines(f"stories/{day:%Y/%m/%d}/stories.jsonl", rows)


class OnDemandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = LocalSink(self.tmp.name)
        self.day = date(2026, 11, 19)
        write_day(self.sink, self.day)
        FakeCoder.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def test_codes_top_25_once_and_caches(self):
        led = ledger(self.sink)
        r = ondemand.code_entity_day(self.sink, "13_Sudan", self.day, "view", ledger=led, coder_factory=FakeCoder)
        self.assertEqual((r["stories"], r["coded"], r["already_coded"]), (25, 25, 0))
        self.assertEqual(FakeCoder.calls, 1)
        again = ondemand.code_entity_day(self.sink, "13_Sudan", self.day, "view", ledger=led, coder_factory=FakeCoder)
        self.assertEqual((again["coded"], again["already_coded"], FakeCoder.calls), (0, 25, 1))
        self.assertEqual(led.status()["spent_usd"], 0.003)
        self.assertEqual(len(ondemand.load_codings(self.sink, "13_Sudan", self.day)), 25)

    def test_budget_refusal_sends_nothing(self):
        led = ledger(self.sink, cap=0.0001, reserve=0.0)
        with self.assertRaises(budget.BudgetExceeded):
            ondemand.code_entity_day(self.sink, "13_Sudan", self.day, "view", ledger=led, coder_factory=FakeCoder)
        self.assertEqual(FakeCoder.calls, 0)
        self.assertFalse(self.sink.exists(ondemand.codings_key("13_Sudan", self.day)))

    def test_unbuilt_day_reads_cycles(self):
        d = date(2026, 11, 20)
        self.sink.write_lines("cycles/2026/11/20/100500.jsonl", [
            {"kind": "gdelt", "url": "https://a.com/1", "title": "RSF drones hit power station in Kassala",
             "published": "2026-11-20T10:00:00Z", "labels": ["13_Sudan"], "domain": "a.com", "lang": "eng"}])
        stories = ondemand.day_stories(self.sink, "13_Sudan", d)
        self.assertEqual(len(stories), 1)


class AlarmTests(unittest.TestCase):
    def test_alarm_reasons(self):
        e = {"stories": 10, "attention": {"z": 2.4}, "casualty": {"anomaly": {"z": 1.0}}}
        self.assertEqual(measures.alarm_reasons(e), ["attention z 2.4"])
        self.assertEqual(measures.alarm_reasons({**e, "stories": 3}), [])
        h = {date(2026, 11, 19) - timedelta(days=i): 0.10 + (i % 2) * 0.01 for i in range(20)}
        self.assertGreater(measures.share_anomaly(h, date(2026, 11, 19), 0.30)["z"], 2)

    def test_run_alarms_queue_and_budget(self):
        state, summary = {}, {"stories_built": [{"day": "2026-11-19", "alarms": {"13_Sudan": ["attention z 3"],
                                                                                  "01_Ukraine_Conflict": ["x"],
                                                                                  "02_Taiwan_Strait": ["y"]}}]}
        cycle.run_alarms(None, state, summary, False, None)  # AI off: queued only
        self.assertEqual(len(state["ai"]["pending"]), 3)
        calls = []

        def code(sink, eid, day, source):
            calls.append((eid, source))
            if eid == "01_Ukraine_Conflict":
                raise budget.BudgetExceeded("cap")
            return {"entity": eid, "day": day.isoformat(), "coded": 25, "already_coded": 0, "cost_usd": 0.005}

        summary2 = {}
        cycle.run_alarms(None, state, summary2, True, code)
        self.assertEqual(len(calls), 2)  # MAX_ALARMS_PER_RUN
        self.assertEqual(calls[0][1], "alarm")
        self.assertEqual(len(state["ai"]["pending"]), 1)
        self.assertEqual(summary2["ai_alarms"][1]["skipped"], "budget")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = LocalSink(self.tmp.name)
        self.day = date(2026, 11, 19)
        write_day(self.sink, self.day)
        self.led = ledger(self.sink)
        FakeCoder.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, path, params=None, body=None, ai_on=True):
        def code(sink, eid, day, source, ledger):
            return ondemand.code_entity_day(sink, eid, day, source, ledger=ledger, coder_factory=FakeCoder)
        return api.handle(method, path, params or {}, body, self.sink, ai_on=ai_on, ledger=self.led, code=code,
                          today=date(2026, 11, 20))

    def test_zone_then_code_then_zone(self):
        st, out = self.call("GET", "/zone", {"entity": "13_Sudan", "day": "2026-11-19"})
        self.assertEqual((st, len(out["stories"]), out["coded"]), (200, 25, 0))
        self.assertIsNone(out["stories"][0]["coding"])
        st, out = self.call("POST", "/code", body={"entity": "13_Sudan", "day": "2026-11-19"})
        self.assertEqual((st, out["coded"]), (200, 25))
        st, out = self.call("GET", "/zone", {"entity": "13_Sudan", "day": "2026-11-19"})
        self.assertEqual(out["stories"][0]["coding"]["event_type"], "ASSAULT")
        st, out = self.call("GET", "/status")
        self.assertEqual((out["ai"], out["budget"]["spent_usd"]), ("on", 0.003))

    def test_errors(self):
        self.assertEqual(self.call("GET", "/zone", {"entity": "nope"})[0], 400)
        self.assertEqual(self.call("GET", "/zone", {"entity": "13_Sudan", "day": "2026-11-21"})[0], 400)
        self.assertEqual(self.call("GET", "/zone", {"entity": "13_Sudan", "day": "2025-01-01"})[0], 400)
        self.assertEqual(self.call("GET", "/elsewhere")[0], 404)
        self.assertEqual(self.call("POST", "/code", body={"entity": "13_Sudan", "day": "2026-11-19"}, ai_on=False)[0], 503)
        self.led.cap = 0.0001
        self.led.alarm_reserve = 0.0
        st, out = self.call("POST", "/code", body={"entity": "13_Sudan", "day": "2026-11-19"})
        self.assertEqual(st, 429)
        self.assertEqual(FakeCoder.calls, 0)


if __name__ == "__main__":
    unittest.main()
