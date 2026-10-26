import unittest
from datetime import datetime, timedelta, timezone

from pipeline import rss

RSS2 = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>X</title>
<item><title>Strike hits &lt;b&gt;Kharkiv&lt;/b&gt; overnight</title><link>https://x.com/a</link>
<pubDate>Mon, 26 Oct 2026 15:00:00 GMT</pubDate><description>&lt;p&gt;Six injured, officials say.&lt;/p&gt;</description></item>
<item><title></title><link>https://x.com/empty-title</link></item>
<item><title>No link</title></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Y</title>
<entry><title>Talks resume</title><link rel="alternate" href="https://y.com/b"/><updated>2026-10-26T14:30:00Z</updated>
<summary>Envoys meet in Geneva.</summary></entry></feed>"""

RDF = b"""<?xml version="1.0"?><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<item><title>Port reopens</title><link>https://z.com/c</link><dc:date>2026-10-26T12:00:00+01:00</dc:date>
<description>Shipping resumes.</description></item></rdf:RDF>"""


class ParseTests(unittest.TestCase):
    def test_rss2(self):
        items = rss.parse_feed(RSS2)
        self.assertEqual(len(items), 1)  # empty title and missing link are dropped
        i = items[0]
        self.assertEqual(i["title"], "Strike hits Kharkiv overnight")
        self.assertEqual(i["summary"], "Six injured, officials say.")
        self.assertEqual(i["published"], datetime(2026, 10, 26, 15, 0, tzinfo=timezone.utc))

    def test_atom(self):
        (i,) = rss.parse_feed(ATOM)
        self.assertEqual((i["title"], i["url"]), ("Talks resume", "https://y.com/b"))
        self.assertEqual(i["published"].hour, 14)

    def test_rdf(self):
        (i,) = rss.parse_feed(RDF)
        self.assertEqual(i["url"], "https://z.com/c")
        self.assertEqual(i["published"], datetime(2026, 10, 26, 11, 0, tzinfo=timezone.utc))

    def test_junk_after_root_is_trimmed(self):
        self.assertEqual(len(rss.parse_feed(RSS2 + b"\n<!-- cache -->\n<div>x</div>")), 1)

    def test_not_xml(self):
        with self.assertRaises(ValueError):
            rss.parse_feed(b"<html><body>blocked</body>")

    def test_summary_truncated(self):
        long = "word " * 200
        self.assertLessEqual(len(rss.clean_text(long, rss.SUMMARY_CHARS)), rss.SUMMARY_CHARS)


class ClockTests(unittest.TestCase):
    def test_correct_clock_and_warning(self):
        now = datetime(2026, 10, 26, 16, 45, tzinfo=timezone.utc)
        items = [{"published": now + timedelta(hours=7, minutes=45)}, {"published": None}]
        self.assertEqual(rss.future_skew_hours(items, now), 8)
        rss.correct_clock(items, 8)
        self.assertEqual(rss.future_skew_hours(items, now), 0)
        self.assertEqual(items[0]["published"], now - timedelta(minutes=15))


if __name__ == "__main__":
    unittest.main()
