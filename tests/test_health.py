import unittest
from datetime import datetime, timedelta, timezone

from pipeline import health

NOW = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)


def entry(newest_minutes_ago=None, failures=0, ok=True):
    e = {"consecutive_failures": failures}
    if ok:
        e["last_ok"] = health.iso(NOW)
    if newest_minutes_ago is not None:
        e["newest_item"] = health.iso(NOW - timedelta(minutes=newest_minutes_ago))
    return e


class StatusTests(unittest.TestCase):
    def test_bands(self):
        self.assertEqual(health.status(entry(100), 60, NOW), "fresh")   # <= 2x
        self.assertEqual(health.status(entry(300), 60, NOW), "late")    # <= 6x
        self.assertEqual(health.status(entry(400), 60, NOW), "stale")

    def test_never_and_failing(self):
        self.assertEqual(health.status(None, 60, NOW), "never")
        self.assertEqual(health.status(entry(ok=False, failures=1), 60, NOW), "never")
        self.assertEqual(health.status(entry(ok=False, failures=3), 60, NOW), "failing")
        self.assertEqual(health.status(entry(10, failures=3), 60, NOW), "failing")

    def test_remember_returns_only_new(self):
        e = {}
        self.assertEqual(health.remember(e, ["a", "b"]), ["a", "b"])
        self.assertEqual(health.remember(e, ["b", "c"]), ["c"])

    def test_record_success_keeps_newest(self):
        e = {}
        health.record_success(e, NOW, 5, NOW - timedelta(hours=1), "etag1", None)
        health.record_success(e, NOW, 5, NOW - timedelta(hours=3), None, None)
        self.assertEqual(e["newest_item"], health.iso(NOW - timedelta(hours=1)))
        self.assertEqual(e["etag"], "etag1")


if __name__ == "__main__":
    unittest.main()
