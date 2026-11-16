"""A failed country build is kept and retried, not lost (suite review 15 Nov 2026)."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from pipeline import countries, cycle, daily, relations
from pipeline.sinks import LocalSink


def fake_story_build(s, day):
    return {"day": day.isoformat(), "alarms": {}}


class CountryRetryTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.sink = LocalSink(self.td.name)
        self.sink.write_json(cycle.STATE_KEY, {"first_data_day": "2026-10-26", "stories": {"last_day": "2026-10-27"}})
        self.calls = []
        self.fail = True

    def tearDown(self):
        self.td.cleanup()

    def run_at(self, now):
        def build(s, day, recs=None):
            self.calls.append(day.isoformat())
            if self.fail:
                raise RuntimeError("country build died")
            return {"day": day.isoformat()}

        with mock.patch.object(daily, "build_day", fake_story_build), \
                mock.patch.object(countries, "day_records_and_press", lambda s, day: ([], [])), \
                mock.patch.object(countries, "build_day", build), \
                mock.patch.object(relations, "build_day", lambda s, day, r, p: {"day": day.isoformat()}):
            summary = cycle.run_cycle(self.sink, now=now, streams=(), poll_rss=False, ai_on=False)
        return summary, self.sink.read_json(cycle.STATE_KEY)["stories"]

    def test_failed_day_is_kept_then_rebuilt_on_a_later_run(self):
        t0 = datetime(2026, 10, 29, 3, 20, tzinfo=timezone.utc)
        summary, st = self.run_at(t0)
        self.assertEqual(st["last_day"], "2026-10-28")  # the story build still moves on
        self.assertIn("country build died", summary["countries_error"])
        self.assertNotIn("relations_built", summary)
        self.assertEqual(st["countries_retry"]["2026-10-28"]["attempts"], 1)

        # 15 minutes later: too soon to retry.
        summary, st = self.run_at(t0 + timedelta(minutes=15))
        self.assertEqual(self.calls, ["2026-10-28"])
        self.assertIn("2026-10-28", st["countries_retry"])

        # An hour later the build works: the day is rebuilt with its relations and leaves the list.
        self.fail = False
        summary, st = self.run_at(t0 + timedelta(hours=1))
        self.assertEqual(self.calls, ["2026-10-28", "2026-10-28"])
        self.assertEqual(summary["countries_retried"], "2026-10-28")
        self.assertEqual(summary["relations_built"], [{"day": "2026-10-28"}])
        self.assertEqual(st["countries_retry"], {})

    def test_gives_up_after_the_cap(self):
        t = datetime(2026, 10, 29, 3, 20, tzinfo=timezone.utc)
        for _ in range(cycle.COUNTRY_RETRIES + 2):
            summary, st = self.run_at(t)
            t += cycle.COUNTRY_RETRY_EVERY
        self.assertEqual(len(self.calls), cycle.COUNTRY_RETRIES)
        self.assertEqual(st["countries_retry"], {})
        self.assertEqual(st["countries_failed"][0]["day"], "2026-10-28")
        self.assertEqual(st["countries_failed"][0]["attempts"], cycle.COUNTRY_RETRIES)

    def test_no_retry_on_a_run_that_builds_a_day(self):
        st = self.sink.read_json(cycle.STATE_KEY)
        st["stories"]["countries_retry"] = {"2026-10-20": {"attempts": 1, "last": "2026-10-21T00:00:00Z"}}
        self.sink.write_json(cycle.STATE_KEY, st)
        self.fail = False
        summary, st = self.run_at(datetime(2026, 10, 29, 3, 20, tzinfo=timezone.utc))
        self.assertEqual(self.calls, ["2026-10-28"])  # the new day only
        self.assertIn("2026-10-20", st["countries_retry"])
        summary, st = self.run_at(datetime(2026, 10, 29, 3, 35, tzinfo=timezone.utc))
        self.assertEqual(self.calls, ["2026-10-28", "2026-10-20"])
        self.assertEqual(st["countries_retry"], {})


if __name__ == "__main__":
    unittest.main()
