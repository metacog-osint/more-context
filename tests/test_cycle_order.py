import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from pipeline import cycle, daily, health, statestore
from pipeline.sinks import LocalSink


class SaveBeforeBuildTests(unittest.TestCase):
    def test_state_is_saved_before_the_day_build(self):
        # 28 Oct 2026: a build that died (out of memory) left state unsaved, so every later run repeated the ingest.
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-26"}})
            seen = {}

            def fake_build(s, day):
                seen["state_at_build"] = s.read_json(cycle.STATE_KEY)
                raise RuntimeError("build died")

            now = datetime(2026, 10, 28, 5, 0, tzinfo=timezone.utc)
            with mock.patch.object(daily, "build_day", fake_build):
                summary = cycle.run_cycle(sink, now=now, streams=(), poll_rss=False, ai_on=False)
            self.assertEqual(seen["state_at_build"]["last_run"]["run_at"], "2026-10-28T05:00:00Z")
            self.assertIn("build died", summary["stories_error"])
            self.assertEqual(sink.read_json(cycle.STATE_KEY)["stories"]["last_day"], "2026-10-26")  # retried next run


class CountingSink(LocalSink):
    def __init__(self, root):
        super().__init__(root)
        self.state_writes = 0
        self.keys_written = []

    def write_json(self, key, obj):
        self.state_writes += key == cycle.STATE_KEY
        self.keys_written.append(key)
        super().write_json(key, obj)

    def write_lines(self, key, rows):
        self.keys_written.append(key)
        super().write_lines(key, rows)


class StateWritesTests(unittest.TestCase):
    # Every state write leaves a copy the bucket keeps for a week (soft delete): write once unless slow work follows.
    def test_a_plain_run_writes_state_once(self):
        with tempfile.TemporaryDirectory() as d:
            sink = CountingSink(d)
            now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)  # 28 Oct is not built until 29 Oct 03:15
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-27"}})
            sink.state_writes = 0
            cycle.run_cycle(sink, now=now, streams=(), poll_rss=False, ai_on=False)
            self.assertEqual(sink.state_writes, 1)
            self.assertEqual(sink.read_json(cycle.STATE_KEY)["last_run"]["run_at"], "2026-10-28T15:00:00Z")

    def test_pending_ai_work_saves_state_first(self):
        with tempfile.TemporaryDirectory() as d:
            sink = CountingSink(d)
            now = datetime(2026, 10, 28, 15, 0, tzinfo=timezone.utc)
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-27"},
                                              "ai": {"pending": [{"entity": "15_Cuba", "day": "2026-10-27",
                                                                  "reasons": ["attention z 3.2"], "tries": 0}],
                                                     "done": []}})
            sink.state_writes = 0
            writes_at_call = []

            def code(s, entity, day, why):
                writes_at_call.append(s.state_writes)
                return {"entity": entity, "day": day.isoformat(), "coded": 1, "already_coded": 0, "cost_usd": 0.001}

            cycle.run_cycle(sink, now=now, streams=(), poll_rss=False, ai_on=True, code_alarm=code)
            self.assertEqual(writes_at_call, [1])
            self.assertEqual(sink.state_writes, 2)

    def test_a_full_run_writes_two_objects(self):
        # GKG, Events and feeds in one run: one cycle file (articles and Events records) and the state, nothing else.
        # Writes are Class A operations; 5,000 a month are free (cost audit in CLAUDE.md).
        from tests.test_events import row, zipped

        with tempfile.TemporaryDirectory() as d:
            sink = CountingSink(d)
            now = datetime(2026, 10, 28, 15, 5, tzinfo=timezone.utc)
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-27"},
                                              "gdelt": {"english": {"last_stamp": "20261028143000"}}})
            sink.keys_written = []
            feed_row = {"url": "https://a/feed-1", "title": "t", "fetched": "2026-10-28T15:05:00Z", "source": "x"}
            summary = cycle.run_cycle(
                sink, now=now, streams=("english",), ai_on=False, latest=lambda s: "20261028150000",
                download=lambda st, s: zipped([]), download_events=lambda st, s: zipped([row("1", "ET", "https://a/1")]),
                poll=lambda state, now: ([dict(feed_row)], []))
            self.assertEqual(sink.keys_written, ["cycles/2026/10/28/150500.jsonl", cycle.STATE_KEY])
            self.assertEqual(summary["written"]["rows"], 1)
            self.assertEqual(summary["written"]["events_files"], 2)  # 14:45 and 15:00

    def test_firestore_state_leaves_one_bucket_write_a_run(self):
        # MC_STATE=firestore (30 Oct 2026): the state moves out of the bucket, which keeps the cycle file; the run
        # that builds a day also refreshes the bucket copy (the fallback).
        from tests.test_statestore import FakeFirestore

        with tempfile.TemporaryDirectory() as d:
            sink = CountingSink(d)
            sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-27"}})
            fs = FakeFirestore()
            store = statestore.FirestoreState("p", fs, statestore.SinkState(sink))
            sink.keys_written = []
            feed = lambda state, now: ([{"url": f"https://a/{now:%H%M}", "title": "t", "fetched": health.iso(now)}], [])
            plain = datetime(2026, 10, 28, 15, 5, tzinfo=timezone.utc)  # 28 Oct is built after 29 Oct 03:15
            cycle.run_cycle(sink, now=plain, streams=(), ai_on=False, poll=feed, store=store)
            self.assertEqual(sink.keys_written, ["cycles/2026/10/28/150500.jsonl"])  # state read from the bucket copy
            self.assertEqual(store.read()["last_run"]["run_at"], "2026-10-28T15:05:00Z")
            sink.keys_written = []
            build = datetime(2026, 10, 29, 3, 20, tzinfo=timezone.utc)
            with mock.patch.object(daily, "build_day", lambda s, day: {"day": day.isoformat(), "alarms": {}}), \
                    mock.patch("pipeline.countries.build_day", lambda s, day: {"day": day.isoformat()}):
                cycle.run_cycle(sink, now=build, streams=(), ai_on=False, poll=feed, store=store)
            self.assertEqual(sink.keys_written, ["cycles/2026/10/29/032000.jsonl", cycle.STATE_KEY])
            self.assertEqual(sink.read_json(cycle.STATE_KEY)["stories"]["last_day"], "2026-10-28")
            self.assertEqual(store.read()["stories"]["last_day"], "2026-10-28")


if __name__ == "__main__":
    unittest.main()
