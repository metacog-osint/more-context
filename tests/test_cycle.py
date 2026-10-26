import io
import tempfile
import unittest
import zipfile
from datetime import datetime, timezone

from pipeline import cycle
from pipeline.sinks import LocalSink
from tests.test_gdelt import gkg_row

NOW = datetime(2026, 10, 26, 17, 0, tzinfo=timezone.utc)


def zipped(*rows) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("x.gkg.csv", "".join("\t".join(r) + "\n" for r in rows))
    return buf.getvalue()


UKRAINE = gkg_row(f3="news.cn", f4="https://english.news.cn/ukraine-strike")
UNMATCHED = gkg_row(f0="b", f7="TAX_FNCACT_FARMER;", f4="https://x.com/farm")


class StampTests(unittest.TestCase):
    def test_stamps_after(self):
        self.assertEqual(cycle.stamps_after("20261026160000", "20261026164500"),
                         ["20261026161500", "20261026163000", "20261026164500"])

    def test_first_run_starts_back(self):
        s = cycle.stamps_after(None, "20261026164500", cap=4)
        self.assertEqual(s, ["20261026160000", "20261026161500", "20261026163000", "20261026164500"])

    def test_cap_keeps_most_recent(self):
        s = cycle.stamps_after("20261026000000", "20261026164500", cap=2)
        self.assertEqual(s, ["20261026163000", "20261026164500"])


class CycleTests(unittest.TestCase):
    def run_cycle(self, root, files, latest="20261026164500", now=NOW):
        sink = LocalSink(root)
        return sink, cycle.run_cycle(
            sink, now=now, streams=("translation",), poll_rss=False,
            latest=lambda stream: latest,
            download=lambda stamp, stream: files.get(stamp))

    def test_unpublished_files_retried_without_blocking(self):
        with tempfile.TemporaryDirectory() as d:
            # 16:00 is up; 16:15-16:45 are listed but not downloadable yet (as seen on 26 Oct).
            files = {"20261026160000": zipped(UKRAINE, UNMATCHED)}
            sink, s1 = self.run_cycle(d, files)
            t = s1["gdelt"]["translation"]
            self.assertEqual(t["ok"], 1)
            self.assertIn("20261026161500", t["waiting"])
            self.assertEqual(t["through"], "20261026164500")
            pending = sink.read_json(cycle.STATE_KEY)["gdelt"]["translation"]["pending"]
            self.assertIn("20261026161500", pending)
            files["20261026161500"] = zipped(UKRAINE)  # it arrives
            _, s2 = self.run_cycle(d, files)
            self.assertEqual(s2["gdelt"]["translation"]["ok"], 1)
            pending = sink.read_json(cycle.STATE_KEY)["gdelt"]["translation"]["pending"]
            self.assertNotIn("20261026161500", pending)

    def test_old_missing_file_is_given_up(self):
        with tempfile.TemporaryDirectory() as d:
            LocalSink(d).write_json(cycle.STATE_KEY, {"gdelt": {"translation": {"last_stamp": "20261026113000"}}})
            later = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)
            _, s = self.run_cycle(d, {"20261026120000": zipped(UKRAINE)}, latest="20261026120000", now=later)
            t = s["gdelt"]["translation"]
            self.assertEqual(t["missing"], ["20261026114500"])  # 6 h old: gave up on it
            self.assertEqual((t["ok"], t["waiting"], t["through"]), (1, [], "20261026120000"))

    def test_rows_tagged_with_labels_and_group(self):
        with tempfile.TemporaryDirectory() as d:
            sink, s = self.run_cycle(d, {"20261026160000": zipped(UKRAINE, UNMATCHED)})
            key = s["written"]["key"]
            rows = (sink.root / key).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            self.assertIn('"group": "chinese_state"', rows[0])
            self.assertIn('"labels": ["01_Ukraine_Conflict"]', rows[0])


if __name__ == "__main__":
    unittest.main()
