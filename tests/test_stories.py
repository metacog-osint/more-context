import unittest

from pipeline.stories import build_stories, group_titles, normalize_title, title_from_url


def art(url, title, domain, t="2026-10-26T10:00:00Z", lang="eng"):
    return {"url": url, "title": title, "domain": domain, "published": t, "lang": lang}


class NormalizeTests(unittest.TestCase):
    def test_strips_site_suffix_and_punctuation(self):
        self.assertEqual(normalize_title("Musk speaks: Starlink service in Ukraine restored - Wiltshire Times"),
                         "musk speaks starlink service in ukraine restored")
        self.assertEqual(normalize_title("Ukraine says Starlink is back | NPR"), "ukraine says starlink is back")

    def test_keeps_long_tail(self):
        # A long last segment is part of the headline, not a site name.
        self.assertIn("talks restart in november", normalize_title("Ukraine war briefing - trilateral talks restart in november as envoys meet"))

    def test_title_from_url(self):
        self.assertEqual(title_from_url("https://x.com/news/national/26667668.musk-speaks-starlink-service-ukraine-restored/"),
                         "musk speaks starlink service ukraine restored")


class GroupingTests(unittest.TestCase):
    def test_syndicated_copies_merge(self):
        titles = [
            "musk speaks starlink service ukraine restored",
            "musk speaks starlink service in ukraine restored",
            "musk speaks starlink service ukraine restored after outage",
            "russian strikes on zaporizhzhia injure six officials say",
        ]
        ids = group_titles(titles)
        self.assertEqual(ids[0], ids[1])
        self.assertEqual(ids[0], ids[2])
        self.assertNotEqual(ids[0], ids[3])

    def test_short_titles_only_merge_exactly(self):
        ids = group_titles(["ukraine latest", "ukraine latest", "ukraine news"])
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])


class BuildStoriesTests(unittest.TestCase):
    def test_counts(self):
        arts = [
            art("https://a.co.uk/1", "Musk speaks: Starlink service in Ukraine restored - A Times", "a.co.uk"),
            art("https://b.co.uk/1", "Musk speaks: Starlink service in Ukraine restored - B News", "b.co.uk"),
            art("https://b.co.uk/1", "duplicate URL is counted once", "b.co.uk"),
            art("https://c.com/x", "Six injured in Russian strikes on Zaporizhzhia and Chernihiv", "c.com"),
        ]
        stories = build_stories(arts)
        self.assertEqual(len(stories), 2)
        self.assertEqual(stories[0]["articles"], 2)
        self.assertEqual(stories[0]["outlets"], 2)


if __name__ == "__main__":
    unittest.main()
