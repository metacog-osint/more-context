import base64
import gzip
import hashlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from pipeline import sinks
from pipeline.sinks import GCSSink, LocalSink


class PreconditionFailed(Exception):
    pass


def fake_google():
    """google.api_core.exceptions for the compare-and-swap, without the library (CI installs none)."""
    exc = types.ModuleType("google.api_core.exceptions")
    exc.PreconditionFailed = PreconditionFailed
    return mock.patch.dict(sys.modules, {"google": types.ModuleType("google"),
                                         "google.api_core": types.ModuleType("google.api_core"),
                                         "google.api_core.exceptions": exc})


class FakeBucket:
    """The parts of a google.cloud.storage bucket and blob that the sink and scripts/recompress.py use."""

    def __init__(self):
        self.objects, self.gen, self.uploads = {}, 0, []

    def blob(self, name):
        return FakeBlob(self, name)

    def get_blob(self, name):
        return FakeBlob(self, name) if name in self.objects else None

    def put_plain(self, name, text, content_type="application/json"):
        """An object as written before 30 Oct 2026 (or by a backfill upload): plain text, no encoding."""
        self.store(name, text.encode("utf-8"), content_type, None)

    def store(self, name, data, content_type, encoding):
        self.gen += 1
        self.objects[name] = {"data": data, "content_type": content_type, "content_encoding": encoding,
                              "generation": self.gen}
        return self.gen


class FakeBlob:
    def __init__(self, bucket, name):
        self._b, self.name = bucket, name
        o = bucket.objects.get(name) or {}
        self.content_encoding = o.get("content_encoding")
        self.content_type = o.get("content_type")
        self.generation = o.get("generation")
        self.size = len(o["data"]) if o else None
        self.md5_hash = None

    def exists(self):
        return self.name in self._b.objects

    def download_as_bytes(self, raw_download=False):
        assert raw_download, "read the stored bytes; the client would otherwise unzip some objects itself"
        return self._b.objects[self.name]["data"]

    def upload_from_string(self, data, content_type=None, if_generation_match=None):
        cur = self._b.objects.get(self.name)
        if if_generation_match is not None and (cur["generation"] if cur else 0) != if_generation_match:
            raise PreconditionFailed(self.name)
        data = data.encode("utf-8") if isinstance(data, str) else data
        self.generation = self._b.store(self.name, data, content_type, self.content_encoding)
        self.md5_hash = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
        self._b.uploads.append(self.name)


def gcs_sink(bucket):
    s = GCSSink.__new__(GCSSink)  # skip __init__: no client, no credentials
    s.bucket = bucket
    return s


ROWS = [{"title": "Sudan strike\x85report end", "n": 1}, {"title": "plain", "n": 2}]
ARTICLES = [{"url": f"https://example.org/news/2026/10/30/story-{i}", "title": f"Strike reported near Kharkiv {i}",
             "source": "example.org", "zone": "01_Ukraine_Conflict", "tone": -3.2} for i in range(300)]


class JsonLinesTests(unittest.TestCase):
    def test_unicode_line_separators_stay_inside_records(self):
        # json.dumps(ensure_ascii=False) leaves U+2028, U+2029 and U+0085 raw; str.splitlines() would cut there.
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_lines("cycles/x.jsonl", ROWS)
            self.assertEqual(sink.read_lines("cycles/x.jsonl"), ROWS)

    def test_versioned_write(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            obj, v = sink.read_json_versioned("state/x.json")
            self.assertEqual((obj, v), (None, 0))
            self.assertTrue(sink.write_json_if("state/x.json", {"a": 1}, 0))
            self.assertFalse(sink.write_json_if("state/x.json", {"a": 2}, 0))  # someone else wrote first
            obj, v = sink.read_json_versioned("state/x.json")
            self.assertTrue(sink.write_json_if("state/x.json", {"a": 3}, v))


class BucketGzipTests(unittest.TestCase):
    # 30 Oct 2026: gzip keeps the record inside the free 5 GB (cycle files 4.6x smaller, measured on 29 Oct).
    def test_bucket_writes_are_gzip(self):
        bucket = FakeBucket()
        sink = gcs_sink(bucket)
        sink.write_lines("cycles/2026/10/30/150500.jsonl", ROWS + ARTICLES)
        o = bucket.objects["cycles/2026/10/30/150500.jsonl"]
        self.assertEqual(o["content_encoding"], "gzip")
        self.assertEqual(o["content_type"], "application/x-ndjson")
        self.assertEqual(gzip.decompress(o["data"]).decode("utf-8"), sinks._lines(ROWS + ARTICLES))
        self.assertLess(len(o["data"]), len(sinks._lines(ARTICLES).encode("utf-8")) / 4)
        self.assertEqual(sink.read_lines("cycles/2026/10/30/150500.jsonl"), ROWS + ARTICLES)
        self.assertEqual(sink.read_lines("cycles/2026/10/30/150500.jsonl", '{"title": "plain"'), [ROWS[1]])
        sink.write_json("stories/2026/10/30/day.json", {"day": "2026-10-30", "rows": ROWS})
        self.assertEqual(bucket.objects["stories/2026/10/30/day.json"]["content_encoding"], "gzip")
        self.assertEqual(sink.read_json("stories/2026/10/30/day.json"), {"day": "2026-10-30", "rows": ROWS})
        self.assertIsNone(sink.read_json("stories/2026/10/31/day.json"))

    def test_older_plain_objects_still_read(self):
        bucket = FakeBucket()
        bucket.put_plain("stories/2026/10/29/day.json", '{"day": "2026-10-29"}')
        bucket.put_plain("cycles/2026/10/29/230506.jsonl", sinks._lines(ROWS), "application/x-ndjson")
        sink = gcs_sink(bucket)
        self.assertEqual(sink.read_json("stories/2026/10/29/day.json"), {"day": "2026-10-29"})
        self.assertEqual(sink.read_lines("cycles/2026/10/29/230506.jsonl"), ROWS)
        self.assertEqual(sink.read_json_versioned("stories/2026/10/29/day.json")[0], {"day": "2026-10-29"})

    def test_versioned_write_on_the_bucket(self):
        bucket = FakeBucket()
        sink = gcs_sink(bucket)
        with fake_google():
            self.assertEqual(sink.read_json_versioned("ai/ledger.json"), (None, 0))
            self.assertTrue(sink.write_json_if("ai/ledger.json", {"a": 1}, 0))
            self.assertFalse(sink.write_json_if("ai/ledger.json", {"a": 2}, 0))  # someone else wrote first
            obj, v = sink.read_json_versioned("ai/ledger.json")
            self.assertEqual(obj, {"a": 1})
            self.assertTrue(sink.write_json_if("ai/ledger.json", {"a": 3}, v))
        self.assertEqual(sink.read_json("ai/ledger.json"), {"a": 3})
        self.assertEqual(bucket.objects["ai/ledger.json"]["content_encoding"], "gzip")

    def test_same_text_same_bytes(self):
        self.assertEqual(sinks.gz(b'{"a": 1}'), sinks.gz(b'{"a": 1}'))  # no timestamp in the gzip header


class LocalCopyTests(unittest.TestCase):
    def test_local_folder_reads_gzip_and_windows_line_ends(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "cycles").mkdir()
            (root / "cycles/raw.jsonl").write_bytes(sinks.gz(sinks._lines(ROWS).encode("utf-8")))  # raw bucket copy
            (root / "cycles/crlf.jsonl").write_bytes(b'{"n": 1}\r\n{"n": 2}\r\n')
            (root / "s.json").write_bytes(sinks.gz('{"day": "2026-10-30"}'.encode("utf-8")))
            sink = LocalSink(d)
            self.assertEqual(sink.read_lines("cycles/raw.jsonl"), ROWS)
            self.assertEqual(sink.read_lines("cycles/crlf.jsonl"), [{"n": 1}, {"n": 2}])
            self.assertEqual(sink.read_json("s.json"), {"day": "2026-10-30"})
            sink.write_lines("cycles/new.jsonl", ROWS)  # local folders stay plain
            self.assertNotEqual((root / "cycles/new.jsonl").read_bytes()[:2], sinks.GZIP_MAGIC)


if __name__ == "__main__":
    unittest.main()
