"""Retention fixes M1, M4, M5 (18 Nov 2026): the per-run health record, originals kept before a re-score, full feed text."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from pipeline import cycle, healthlog, rss, telegram
from pipeline.sinks import LocalSink

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts import rescore_archive as ra  # noqa: E402


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


T0 = datetime(2026, 11, 18, 10, 5, tzinfo=timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_state(i, base=T0):
    t = base + timedelta(minutes=15 * i)
    return {"feed_health": {"at": iso(t), "sources": [{"id": "s1", "status": "fresh", "http": 200, "items": 10, "new": i}]}}, \
           {"run_at": iso(t), "gdelt": {"english": {"ok": 1}}, "rss": {"new": i}}


class HealthLogTests(unittest.TestCase):
    def test_lines_wait_then_go_to_the_day_file_together(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            state = {}
            for i in range(healthlog.FLUSH_RUNS - 1):
                fh, summary = run_state(i)
                state["feed_health"] = fh["feed_health"]
                healthlog.record(sink, state, summary)
            self.assertFalse(sink.exists("health/2026-11-18.jsonl"))  # no bucket write yet: Class A budget
            self.assertEqual(len(state["health_pending"]), healthlog.FLUSH_RUNS - 1)
            fh, summary = run_state(healthlog.FLUSH_RUNS - 1)
            state["feed_health"] = fh["feed_health"]
            healthlog.record(sink, state, summary)
            rows = sink.read_lines("health/2026-11-18.jsonl")
            self.assertEqual(len(rows), healthlog.FLUSH_RUNS)
            self.assertEqual(rows[0]["feed_health"]["sources"][0]["id"], "s1")
            self.assertEqual(rows[2]["summary"]["rss"]["new"], 2)
            self.assertEqual(state["health_pending"], [])

    def test_a_second_flush_never_rewrites_or_duplicates_lines(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            lines = []
            for i in range(3):
                fh, s = run_state(i)
                lines.append(healthlog.make_line(fh, s))
            self.assertTrue(healthlog.append_day(sink, "2026-11-18", lines))
            self.assertTrue(healthlog.append_day(sink, "2026-11-18", lines))  # the same run_at values again
            more = healthlog.make_line(*run_state(5))
            self.assertTrue(healthlog.append_day(sink, "2026-11-18", [lines[0], more]))
            rows = sink.read_lines("health/2026-11-18.jsonl")
            self.assertEqual([r["run_at"] for r in rows], [ln["run_at"] for ln in lines] + [more["run_at"]])

    def test_a_closed_utc_day_is_flushed_at_the_next_run_and_lines_land_in_their_own_day(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            state = {}
            late = datetime(2026, 11, 18, 23, 50, tzinfo=timezone.utc)
            fh, s = run_state(0, late)
            state["feed_health"] = fh["feed_health"]
            healthlog.record(sink, state, s)
            fh, s = run_state(1, late)  # 00:05 next day
            state["feed_health"] = fh["feed_health"]
            healthlog.record(sink, state, s)
            self.assertEqual([r["run_at"][:10] for r in sink.read_lines("health/2026-11-18.jsonl")], ["2026-11-18"])
            self.assertFalse(sink.exists("health/2026-11-19.jsonl"))  # the new day's first line waits: no extra write
            self.assertEqual([ln["run_at"][:10] for ln in state["health_pending"]], ["2026-11-19"])

    def test_a_lost_race_is_retried_with_the_new_generation(self):
        class Racy(LocalSink):
            raced = 0

            def write_lines_if(self, key, rows, version):
                if not self.raced:
                    self.raced = 1
                    # another writer appends between our read and our write
                    super().write_lines(key, [{"run_at": "2026-11-18T09:00:00Z", "summary": {}, "feed_health": None}])
                return super().write_lines_if(key, rows, version)

        with tempfile.TemporaryDirectory() as d:
            sink = Racy(d)
            line = healthlog.make_line(*run_state(0))
            self.assertTrue(healthlog.append_day(sink, "2026-11-18", [line]))
            self.assertEqual([r["run_at"] for r in sink.read_lines("health/2026-11-18.jsonl")],
                             ["2026-11-18T09:00:00Z", line["run_at"]])  # the other writer's line survived

    def test_a_bucket_failure_never_stops_a_run_and_the_lines_stay_pending(self):
        class Down(LocalSink):
            def read_lines_versioned(self, key):
                raise OSError("bucket unreachable")

        with tempfile.TemporaryDirectory() as d:
            sink = Down(d)
            state, summary = {}, None
            for i in range(healthlog.FLUSH_RUNS):
                fh, summary = run_state(i)
                state["feed_health"] = fh["feed_health"]
                healthlog.record(sink, state, summary)
            self.assertEqual(len(state["health_pending"]), healthlog.FLUSH_RUNS)
            self.assertIn("bucket unreachable", summary["health_log_error"])

    def test_pending_is_capped(self):
        with tempfile.TemporaryDirectory() as d:
            class Down(LocalSink):
                def read_lines_versioned(self, key):
                    raise OSError("down")

            sink, state = Down(d), {}
            for i in range(healthlog.PENDING_CAP + 20):
                fh, s = run_state(i, datetime(2026, 11, 18, 0, 0, tzinfo=timezone.utc))
                state["feed_health"] = fh["feed_health"]
                healthlog.record(sink, state, s)
            self.assertLessEqual(len(state["health_pending"]), healthlog.PENDING_CAP)

    def test_run_cycle_keeps_its_live_state_and_records_every_run(self):
        from tests.test_cycle import NOW, UKRAINE, zipped

        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            for i in range(healthlog.FLUSH_RUNS):
                now = NOW + timedelta(minutes=15 * i)
                s = cycle.run_cycle(sink, now=now, streams=("translation",), poll_rss=False,
                                    latest=lambda stream: "20261026164500",
                                    download=lambda stamp, stream: zipped(UKRAINE) if stamp == "20261026160000" else None)
            state = sink.read_json(cycle.STATE_KEY)
            self.assertEqual(state["last_run"]["run_at"], s["run_at"])  # the live document still holds the latest run
            rows = sink.read_lines(f"health/{NOW:%Y-%m-%d}.jsonl")
            self.assertEqual(len(rows), healthlog.FLUSH_RUNS)
            self.assertEqual(rows[0]["summary"]["gdelt"]["translation"]["ok"], 1)
            self.assertEqual(rows[-1]["run_at"], s["run_at"])


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class ArchiveTests(unittest.TestCase):
    def opener(self, log, fail_on=None):
        def op(req):
            log.append((req.get_method(), req.full_url))
            if fail_on and fail_on in req.full_url:
                raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)
            return FakeResp(b'{"done": true}')
        return op

    def test_bucket_copy_is_pinned_to_the_fetched_generation_and_never_replaces_an_archive(self):
        log = []
        out = ra.archive_bucket("b", ["stories/2026/11/01/countries.json"], {"stories/2026/11/01/countries.json": 77},
                                self.opener(log), "20261118T120000Z")
        self.assertEqual(out, ["archive/rescore/20261118T120000Z/stories/2026/11/01/countries.json"])
        url = log[0][1]
        self.assertIn("ifSourceGenerationMatch=77", url)
        self.assertIn("ifGenerationMatch=0", url)
        self.assertIn("rewriteTo/b/b/o/archive%2Frescore%2F20261118T120000Z%2Fstories", url)

    def test_a_failed_copy_raises(self):
        with self.assertRaises(ra.ArchiveError):
            ra.archive_bucket("b", ["k"], {}, self.opener([], fail_on="rewriteTo"), "s")

    def test_local_copy_keeps_the_original_and_skips_files_that_do_not_exist(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "root"
            (root / "stories").mkdir(parents=True)
            (root / "stories" / "a.json").write_text('{"old": 1}', encoding="utf-8")
            out = ra.archive_local(root, ["stories/a.json", "stories/new.json"], "S1")
            self.assertEqual(len(out), 1)
            self.assertEqual(out[0].read_text(encoding="utf-8"), '{"old": 1}')
            self.assertEqual(out[0], Path(d) / "archive" / "rescore" / "S1" / "stories" / "a.json")
            with self.assertRaises(ra.ArchiveError):  # an archive file is never replaced
                ra.archive_local(root, ["stories/a.json"], "S1")

    def test_upload_archives_every_original_before_writing_any_file(self):
        rt = load_script("rescore_terms")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            keys = ["stories/2026/11/01/summary.json", "stories/2026/11/01/countries.json"]
            for k in keys:
                (root / k).parent.mkdir(parents=True, exist_ok=True)
                (root / k).write_text("{}", encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({keys[0]: 5, keys[1]: 6}), encoding="utf-8")
            log = []

            def urlopen(req, timeout=None):
                log.append(req.full_url)
                return FakeResp(b'{"done": true, "generation": "9"}')

            with mock.patch.object(rt, "_token", return_value="t"), mock.patch("sys.stdout", new=io.StringIO()):
                rt.upload(root, keys + [keys[0]], urlopen=urlopen, stamp="S")
            kinds = ["copy" if "rewriteTo" in u else "write" for u in log]
            self.assertEqual(kinds, ["copy", "copy", "write", "write"])  # deduplicated; copies first

    def test_upload_refuses_to_write_when_a_copy_fails(self):
        rt = load_script("rescore_terms")
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            key = "stories/2026/11/01/summary.json"
            (root / key).parent.mkdir(parents=True)
            (root / key).write_text("{}", encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({key: 5}), encoding="utf-8")
            log = []

            def urlopen(req, timeout=None):
                log.append(req.full_url)
                raise urllib.error.HTTPError(req.full_url, 403, "no", {}, None)

            with mock.patch.object(rt, "_token", return_value="t"):
                with self.assertRaises(SystemExit) as cm:
                    rt.upload(root, [key], urlopen=urlopen, stamp="S")
            self.assertIn("REFUSING", str(cm.exception))
            self.assertTrue(all("rewriteTo" in u for u in log))  # no upload was attempted

    def test_every_rescore_script_that_writes_goes_through_the_archive(self):
        for name in ("rescore_z", "rescore_zone_scope", "rescore_terms"):
            src = (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
            self.assertIn("upload(", src)
            self.assertIn("upload", src.split("from scripts.rescore_terms import")[1].split("\n")[0] if name != "rescore_terms" else "upload")
        for name in ("relabel", "backfill", "backfill_relations"):
            self.assertIn("archive_local", (ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8"))

    def test_backfill_relations_copies_an_existing_object_first(self):
        br = load_script("backfill_relations")
        log = []

        def urlopen(req, timeout):
            log.append((req.get_method(), req.full_url))
            return FakeResp(b'{"done": true}' if "rewriteTo" in req.full_url else b"{}")

        s = br.TokenSink("b", fetch_token=lambda: "t", urlopen=urlopen, clock=lambda: 0.0)
        s.archive("relations/series.json", "S")
        self.assertTrue(any("rewriteTo" in u for _, u in log))


class FeedTextTests(unittest.TestCase):
    def test_long_feed_items_are_stored_past_400_characters(self):
        self.assertGreater(rss.SUMMARY_CHARS, 400)
        self.assertEqual(rss.DISPLAY_SUMMARY_CHARS, 400)  # anything that shows a summary still cuts to this
        long = "word " * 300
        self.assertGreater(len(rss.clean_text(long, rss.SUMMARY_CHARS)), 400)
        self.assertLessEqual(len(rss.clean_text(long, rss.SUMMARY_CHARS)), rss.SUMMARY_CHARS)

    def test_the_story_build_does_not_carry_the_summary(self):
        # BUILD_FIELDS keeps the 512 MiB build lean: a longer stored summary costs it nothing
        from pipeline import daily
        self.assertNotIn("summary", daily.BUILD_FIELDS)

    def test_telegram_posts_use_the_same_stored_length(self):
        self.assertIs(telegram.SUMMARY_CHARS, rss.SUMMARY_CHARS)


if __name__ == "__main__":
    unittest.main()
