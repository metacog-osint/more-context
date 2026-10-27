import tempfile
import unittest

from pipeline.sinks import LocalSink


class JsonLinesTests(unittest.TestCase):
    def test_unicode_line_separators_stay_inside_records(self):
        # json.dumps(ensure_ascii=False) leaves U+2028, U+2029 and U+0085 raw; str.splitlines() would cut there.
        rows = [{"title": "Sudan strike\x85report end", "n": 1}, {"title": "plain", "n": 2}]
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            sink.write_lines("cycles/x.jsonl", rows)
            self.assertEqual(sink.read_lines("cycles/x.jsonl"), rows)

    def test_versioned_write(self):
        with tempfile.TemporaryDirectory() as d:
            sink = LocalSink(d)
            obj, v = sink.read_json_versioned("state/x.json")
            self.assertEqual((obj, v), (None, 0))
            self.assertTrue(sink.write_json_if("state/x.json", {"a": 1}, 0))
            self.assertFalse(sink.write_json_if("state/x.json", {"a": 2}, 0))  # someone else wrote first
            obj, v = sink.read_json_versioned("state/x.json")
            self.assertTrue(sink.write_json_if("state/x.json", {"a": 3}, v))


if __name__ == "__main__":
    unittest.main()
