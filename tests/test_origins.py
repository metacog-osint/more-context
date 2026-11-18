import unittest

from pipeline import origins


def tk(url, title=""):
    return (url, origins.text_tokens(url, title))


class OriginsTest(unittest.TestCase):
    def test_syndicated_copies_are_one_origin(self):
        # One Newsquest story under one slug on three domains, plus an unrelated story.
        urls = [f"https://www.{d}/news/national/26655274.fairford-shows-us-has-own-defence-needs-says-rubio/"
                for d in ("greenocktelegraph.co.uk", "surreycomet.co.uk", "hamhigh.co.uk")]
        urls.append("https://example.com/2026/10/20/ukraine-power-grid-hit-overnight-strikes-kyiv/")
        s = origins.summarise(urls)
        self.assertEqual(s["articles"], 4)
        self.assertEqual(s["origins"], 2)
        self.assertEqual(s["sizes"][:2], [3, 1])
        self.assertEqual(s["outlets"], 4)

    def test_retitled_wire_copy_joins_at_80_percent(self):
        a = "https://a.com/bahrain-intercepts-iranian-aerial-attacks-as-tehran-says-it-attacked-us-base"
        b = "https://b.com/bahrain-intercepts-iranian-drone-attacks-as-tehran-says-it-attacked-us-base"
        self.assertGreaterEqual(origins.overlap(tk(a)[1], tk(b)[1]), 0.8)
        self.assertEqual(len(origins.cluster([tk(a), tk(b)])), 1)

    def test_different_stories_stay_apart(self):
        a = "https://a.com/bahrain-intercepts-iranian-drone-attacks-on-us-base"
        b = "https://b.com/bahrain-signs-health-workforce-agreement-with-who"
        self.assertEqual(len(origins.cluster([tk(a), tk(b)])), 2)

    def test_group_average_stops_chains(self):
        # b overlaps a2 at 80% but a at 60%: the cluster's average (70%) keeps b out, where single linkage
        # would chain it in through a2.
        w = "iran drones radar base bahrain sirens shelters interior ministry warning".split()
        a = "https://a.com/" + "-".join(w)
        a2 = "https://b.com/" + "-".join(w[:8] + ["tanker", "hormuz"])
        b = "https://c.com/" + "-".join(w[:6] + ["tanker", "hormuz", "mines", "insurers"])
        cl = origins.cluster([tk(a), tk(a.replace("a.com", "d.com")), tk(a2), tk(b)])
        self.assertEqual(sorted(len(c) for c in cl), [1, 3])

    def test_short_and_missing_text(self):
        # Under MIN_TOKENS words, only an identical text joins; numeric-id URLs are each their own origin.
        a = "https://a.com/iran-bahrain-attack"
        b = "https://b.com/iran-bahrain-attack-claims"
        n1, n2 = "https://c.ir/fa/news/123456", "https://d.ir/fa/news/123457"
        cl = origins.cluster([tk(a), tk(a.replace("a.com", "e.com")), tk(b), tk(n1), tk(n2)])
        self.assertEqual(sorted(len(c) for c in cl), [1, 1, 1, 2])
        self.assertEqual(origins.summarise([n1, n2])["no_text"], 2)

    def test_domain_and_aggregators(self):
        self.assertEqual(origins.domain("https://www.bbc.co.uk/news/x"), "bbc.co.uk")
        self.assertEqual(origins.domain("https://mobile.naharnet.com/stories/en/1"), "naharnet.com")
        s = origins.summarise(["https://www.msn.com/en-us/news/world/iran-drones-hit-radar-base-bahrain",
                               "https://www.reuters.com/world/iran-drones-hit-radar-base-bahrain"])
        self.assertEqual((s["origins"], s["outlets"]), (1, 1))

    def test_title_wins_over_slug(self):
        s = origins.summarise(["https://a.com/p/1", "https://b.com/p/2"],
                              {"https://a.com/p/1": "Iran says drones hit US radar base in Bahrain",
                               "https://b.com/p/2": "Iran says its drones hit US radar base in Bahrain - Reuters"})
        self.assertEqual(s["origins"], 1)


if __name__ == "__main__":
    unittest.main()
