import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from pipeline import cycle, daily
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


if __name__ == "__main__":
    unittest.main()
