import gzip
import unittest

from pipeline import sinks
from scripts import recompress
from tests.test_sinks import ARTICLES, FakeBucket, fake_google, gcs_sink

KEY = "cycles/2026/10/29/230506.jsonl"


def listed(bucket):
    return [bucket.get_blob(n) for n in sorted(bucket.objects)]


class RecompressTests(unittest.TestCase):
    def test_only_plain_objects_of_some_size_are_rewritten(self):
        bucket = FakeBucket()
        bucket.put_plain(KEY, sinks._lines(ARTICLES), "application/x-ndjson")
        bucket.put_plain("stories/2026/10/29/tiny.json", '{"n": 1}')
        gcs_sink(bucket).write_json("stories/2026/10/30/day.json", {"day": "2026-10-30", "rows": ARTICLES})
        self.assertEqual([b.name for b in recompress.candidates(listed(bucket))], [KEY])

    def test_rewrite_is_lossless_and_marked_gzip(self):
        bucket = FakeBucket()
        text = sinks._lines(ARTICLES)
        bucket.put_plain(KEY, text, "application/x-ndjson")
        (blob,) = listed(bucket)
        with fake_google():
            before, after = recompress.recompress(bucket, blob)
        o = bucket.objects[KEY]
        self.assertEqual((before, o["content_encoding"], o["content_type"]),
                         (len(text.encode("utf-8")), "gzip", "application/x-ndjson"))
        self.assertLess(after, before / 4)
        self.assertEqual(gzip.decompress(o["data"]), text.encode("utf-8"))
        self.assertEqual(gcs_sink(bucket).read_lines(KEY), ARTICLES)
        with fake_google():
            self.assertIsNone(recompress.recompress(bucket, bucket.get_blob(KEY)))  # already gzip: no second write
        self.assertEqual(bucket.uploads, [KEY])

    def test_an_object_changed_after_listing_is_left_alone(self):
        bucket = FakeBucket()
        bucket.put_plain(KEY, sinks._lines(ARTICLES), "application/x-ndjson")
        (blob,) = listed(bucket)
        bucket.put_plain(KEY, '{"rewritten": true}\n', "application/x-ndjson")  # e.g. a build rewrote it meanwhile
        with fake_google():
            self.assertIsNone(recompress.recompress(bucket, blob))
        self.assertEqual(bucket.objects[KEY]["data"], b'{"rewritten": true}\n')


if __name__ == "__main__":
    unittest.main()
