import json as jsonlib
import os
import tempfile
import unittest
from datetime import date
from unittest import mock

from pipeline import api, health, statestore
from pipeline.sinks import LocalSink


class FakeResponse:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = jsonlib.dumps(self._body)

    def json(self):
        return self._body


class FakeFirestore:
    """The two REST calls statestore makes: GET a document and POST a commit."""

    def __init__(self):
        self.docs, self.calls, self.fail = {}, [], None

    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url.rsplit("/", 1)[-1], len((json or {}).get("writes", []))))
        if self.fail:
            return FakeResponse(self.fail, {"error": {"status": "PERMISSION_DENIED"}})
        if method == "GET":
            name = url.split("/v1/", 1)[1]
            return FakeResponse(200, {"name": name, "fields": self.docs[name]}) if name in self.docs else FakeResponse(404)
        assert url.endswith(":commit")
        for w in json["writes"]:
            self.docs[w["update"]["name"]] = w["update"]["fields"]
        return FakeResponse(200, {"writeResults": [{}] * len(json["writes"])})


def sample_state(feeds=3, per_feed=50):
    return {"gdelt": {"english": {"last_stamp": "20261029230000"}}, "first_data_day": "2026-10-26",
            "rss": {f"feed{i}": {"seen_fp": [health.fingerprint(f"https://x/{i}/{j}") for j in range(per_feed)],
                                 "max_items": per_feed} for i in range(feeds)}}


class FirestoreStateTests(unittest.TestCase):
    def test_round_trip_is_one_commit(self):
        fs = FakeFirestore()
        store = statestore.FirestoreState("p", fs)
        st = sample_state()
        store.write(st)
        self.assertEqual(fs.calls, [("POST", "documents:commit", 1)])
        head = fs.docs["projects/p/databases/(default)/documents/mc_state/ingest"]
        self.assertEqual(head["parts"], {"integerValue": "1"})
        self.assertEqual(store.read(), st)

    def test_a_large_state_is_split_and_rejoined(self):
        # Firestore holds 1 MiB a document; a state over PART_BYTES compressed spans several, written atomically.
        fs = FakeFirestore()
        store = statestore.FirestoreState("p", fs)
        st = sample_state(feeds=20, per_feed=400)
        with mock.patch.object(statestore, "PART_BYTES", 5000):
            store.write(st)
            n = int(fs.docs["projects/p/databases/(default)/documents/mc_state/ingest"]["parts"]["integerValue"])
            self.assertGreater(n, 3)
            self.assertEqual(fs.calls, [("POST", "documents:commit", n)])
            self.assertEqual(store.read(), st)
            store.write(sample_state())  # shrinks to one part; the stale parts are ignored
            self.assertEqual(store.read(), sample_state())

    def test_first_read_falls_back_to_the_bucket_copy(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_json(statestore.STATE_KEY, sample_state())
            store = statestore.FirestoreState("p", FakeFirestore(), statestore.SinkState(sink))
            self.assertEqual(store.read(), sample_state())
            self.assertIsNone(statestore.FirestoreState("p", FakeFirestore()).read())

    def test_other_errors_stop_the_run(self):
        # Permission denied must not fall back to the bucket copy: it may be a day old.
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_json(statestore.STATE_KEY, sample_state())
            fs = FakeFirestore()
            fs.fail = 403
            store = statestore.FirestoreState("p", fs, statestore.SinkState(sink))
            with self.assertRaises(statestore.FirestoreError):
                store.read()
            with self.assertRaises(statestore.FirestoreError):
                store.write({})

    def test_backup_writes_the_bucket_copy(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            store = statestore.FirestoreState("p", FakeFirestore(), statestore.SinkState(sink))
            store.write({"a": 1})
            self.assertFalse(sink.exists(statestore.STATE_KEY))
            store.write({"a": 2}, backup=True)
            self.assertEqual(sink.read_json(statestore.STATE_KEY), {"a": 2})

    def test_bucket_state_without_the_setting(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"MC_STATE": ""}):
            self.assertIsInstance(statestore.from_env(LocalSink(d)), statestore.SinkState)

    def test_api_status_reads_the_store(self):
        with tempfile.TemporaryDirectory() as d:
            fs = FakeFirestore()
            store = statestore.FirestoreState("p", fs)
            store.write({"last_run": {"run_at": "2026-10-30T00:05:00Z", "written": {"rows": 12}},
                         "stories": {"last_day": "2026-10-29"}})
            api._CACHE.clear()  # /status caches the ingest block for a minute
            st, body = api.handle("GET", "/status", {}, None, LocalSink(d), ai_on=False, today=date(2026, 10, 30),
                                  read_state=store.read)
            self.assertEqual(st, 200)
            self.assertEqual(body["ingest"]["last_run"], "2026-10-30T00:05:00Z")
            self.assertEqual(body["ingest"]["last_story_day"], "2026-10-29")


if __name__ == "__main__":
    unittest.main()
