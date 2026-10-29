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

    def test_remember_keeps_fingerprints_not_links(self):
        e = {}
        health.remember(e, ["https://example.com/news/2026/10/29/a-long-headline-slug"])
        self.assertNotIn("seen", e)
        self.assertEqual(len(e["seen_fp"]), 1)
        self.assertEqual(len(e["seen_fp"][0]), 8)

    def test_link_listed_twice_in_one_fetch_is_new_once(self):
        self.assertEqual(health.remember({}, ["a", "b", "a"]), ["a", "b"])

    def test_list_size_follows_the_feed(self):
        small = {}
        for n in range(30):  # a 10-item feed, 300 links over time
            health.remember(small, [f"s{n}-{i}" for i in range(10)])
        self.assertEqual(len(small["seen_fp"]), health.SEEN_MIN)
        self.assertEqual(health.remember(small, ["s29-9"]), [])        # recent: still known
        self.assertEqual(health.remember(small, ["s0-0"]), ["s0-0"])   # oldest: forgotten
        big = {}
        health.remember(big, [f"b{i}" for i in range(150)])
        health.remember(big, [f"c{i}" for i in range(400)])
        self.assertEqual(big["max_items"], 400)
        self.assertEqual(len(big["seen_fp"]), 550)                      # under 3 x 400
        huge = {}
        health.remember(huge, [f"h{i}" for i in range(900)])
        health.remember(huge, [f"k{i}" for i in range(900)])
        health.remember(huge, [f"m{i}" for i in range(900)])
        self.assertEqual(len(huge["seen_fp"]), health.SEEN_MAX)

    def test_old_link_lists_are_upgraded(self):
        # state.json before 29 Oct 2026: tass_ru held 1,000 full links for a 95-item feed.
        links = [f"https://tass.ru/item/{i}" for i in range(1000)]
        e = {"seen": links, "last_items": 95}
        health.upgrade_seen(e)
        self.assertNotIn("seen", e)
        self.assertEqual((e["max_items"], len(e["seen_fp"])), (95, 1000))  # trimmed by the next fetch, not here
        self.assertEqual(health.remember(e, links[-95:]), [])               # the feed's current items stay known
        self.assertEqual(len(e["seen_fp"]), 285)
        self.assertEqual(health.remember(e, [links[0]]), [links[0]])

    def test_sticky_item_is_never_forgotten(self):
        # Feeds keep some items listed for months (tribune_pk, 29 Oct 2026: one 238 days old).
        e = {}
        for n in range(100):  # 10 items a fetch: the sticky one plus 9 new; 900 links pass through a 200 list
            new = health.remember(e, ["sticky"] + [f"n{n}-{i}" for i in range(9)])
            self.assertNotIn("sticky", new[1:] if n == 0 else new)
        self.assertEqual(len(e["seen_fp"]), health.SEEN_MIN)
        self.assertEqual(health.remember(e, ["sticky"]), [])

    def test_upgrade_keeps_sticky_items(self):
        links = ["https://x.pk/sticky"] + [f"https://x.pk/{i}" for i in range(999)]  # sticky seen first
        e = {"seen": links, "last_items": 10}
        health.upgrade_seen(e)
        self.assertEqual(health.remember(e, [links[0]] + links[-9:]), [])

    def test_record_success_keeps_newest(self):
        e = {}
        health.record_success(e, NOW, 5, NOW - timedelta(hours=1), "etag1", None)
        health.record_success(e, NOW, 5, NOW - timedelta(hours=3), None, None)
        self.assertEqual(e["newest_item"], health.iso(NOW - timedelta(hours=1)))
        self.assertEqual(e["etag"], "etag1")


if __name__ == "__main__":
    unittest.main()
