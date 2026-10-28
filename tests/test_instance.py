import signal
import unittest

from pipeline import feeds, instance

REFUSED = {"rss": {"searches_refused": True}}
CLOUD = {"K_SERVICE": "mc-ingest"}


class RestartTests(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def start(self, delay, fn, args):
        self.calls.append((delay, fn, args))

    def test_refused_run_on_cloud_run_stops_the_parent_server(self):
        self.assertTrue(instance.restart_if_refused(REFUSED, env=CLOUD, ppid=1, start=self.start))
        delay, fn, args = self.calls[0]
        self.assertEqual((delay, args), (instance.DELAY_S, (1, signal.SIGTERM)))

    def test_nothing_when_searches_got_through(self):
        self.assertFalse(instance.restart_if_refused({"rss": {"searches_refused": False}}, env=CLOUD, ppid=1, start=self.start))
        self.assertFalse(instance.restart_if_refused({}, env=CLOUD, ppid=1, start=self.start))
        self.assertEqual(self.calls, [])

    def test_never_off_cloud_run(self):
        # Run locally, the parent could be the user's shell.
        self.assertFalse(instance.restart_if_refused(REFUSED, env={}, ppid=1, start=self.start))
        self.assertEqual(self.calls, [])


class SearchesRefusedTests(unittest.TestCase):
    def row(self, http, group="search", **kw):
        return {"id": "x", "group": group, "http": http, **kw}

    def test_refused_probe_with_the_rest_held(self):
        probe = [self.row(503), self.row(None, skipped=True, held="..."), self.row(200, group="western_public")]
        self.assertTrue(feeds.searches_refused(probe))

    def test_any_search_through_is_not_refused(self):
        self.assertFalse(feeds.searches_refused([self.row(200), self.row(503)]))
        self.assertFalse(feeds.searches_refused([self.row(304)]))

    def test_no_search_tried_this_run_is_not_refused(self):
        # Searches not due (hourly) or none in the catalog: nothing to judge.
        self.assertFalse(feeds.searches_refused([self.row(None, skipped=True), self.row(403, group="israeli")]))
        self.assertFalse(feeds.searches_refused([]))


if __name__ == "__main__":
    unittest.main()
