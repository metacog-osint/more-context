"""scripts/backfill_relations.py: token refresh, a day's line after its write, and the series end (16 Nov 2026)."""
import importlib.util
import io
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from pipeline import relations
from pipeline.sinks import LocalSink

_spec = importlib.util.spec_from_file_location(
    "backfill_relations", Path(__file__).resolve().parent.parent / "scripts" / "backfill_relations.py")
br = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(br)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class TokenTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.tokens = iter(["t1", "t2", "t3"])
        self.seen = []  # the token on each request

    def sink(self, reject=()):
        def urlopen(req, timeout):
            tok = req.get_header("Authorization").split()[-1]
            self.seen.append(tok)
            if tok in reject:
                raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
            return FakeResponse(b'{"ok": 1}')

        return br.TokenSink("b", fetch_token=lambda: next(self.tokens), urlopen=urlopen, clock=lambda: self.now)

    def test_token_is_fetched_again_before_it_expires(self):
        s = self.sink()
        s.read_json("a")
        self.now = br.TOKEN_MAX_AGE - 1
        s.read_json("a")
        self.now = br.TOKEN_MAX_AGE + 1
        s.write_json("a", {"x": 1})
        self.assertEqual(self.seen, ["t1", "t1", "t2"])

    def test_a_401_fetches_a_new_token_and_tries_once_more(self):
        s = self.sink(reject={"t1"})
        self.assertEqual(s.read_json("a"), {"ok": 1})
        s.write_json("a", {"x": 1})
        self.assertEqual(self.seen, ["t1", "t2", "t2"])

    def test_a_second_401_is_raised(self):
        s = self.sink(reject={"t1", "t2"})
        with self.assertRaises(urllib.error.HTTPError):
            s.read_json("a")


def day_rec(d: date) -> dict:
    return {"day": d.isoformat(), "partial": False, "files": 192, "pairs": {}}


class SeriesEndTests(unittest.TestCase):
    def test_a_rerun_of_an_earlier_day_keeps_the_series_to_the_last_stored_day(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(Path(td))
            start, last = date(2026, 11, 1), date(2026, 11, 15)
            d = start
            while d <= last:
                sink.write_json(f"stories/{d:%Y/%m/%d}/relations.json", day_rec(d))
                d += timedelta(days=1)
            relations.rebuild_series(sink, date(2026, 11, 14))  # the series one build behind the stored days
            self.assertEqual(br.series_end(sink, date(2026, 11, 5), date(2026, 11, 16)), last)
            self.assertEqual(br.series_end(sink, date(2026, 11, 5), date(2026, 11, 15)), last)
            # Re-run 5 Nov alone (no downloads: the day's files come back empty, so it is rebuilt as partial).
            out = io.StringIO()
            argv = ["backfill_relations.py", "--root", td, "--start", "2026-11-05", "--end", "2026-11-05", "--force"]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(br, "day_recs", lambda ex, d, u: ([], 0)), \
                    redirect_stdout(out):
                br.main()
            series = sink.read_json(relations.SERIES_KEY)
            self.assertEqual(max(series["days"]), "2026-11-15")
            self.assertEqual(min(series["days"]), "2026-11-01")
            self.assertIn("series to 2026-11-15", out.getvalue())
            self.assertIn("2026-11-05:", out.getvalue())
            self.assertIn("written", out.getvalue())

    def test_line_prints_only_after_the_write(self):
        with tempfile.TemporaryDirectory() as td:
            sink = LocalSink(Path(td))

            def failing_write(self, key, obj):
                raise urllib.error.HTTPError(key, 401, "Unauthorized", {}, None)

            out = io.StringIO()
            argv = ["backfill_relations.py", "--root", td, "--start", "2026-11-05", "--end", "2026-11-05"]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(br, "day_recs", lambda ex, d, u: ([], 0)), \
                    mock.patch.object(LocalSink, "write_json", failing_write), redirect_stdout(out), \
                    self.assertRaises(urllib.error.HTTPError):
                br.main()
            self.assertNotIn("2026-11-05", out.getvalue())
            self.assertFalse(sink.exists("stories/2026/11/05/relations.json"))


if __name__ == "__main__":
    unittest.main()
