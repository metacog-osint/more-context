import unittest
from datetime import date, timedelta

from scripts import relations_probe as rp


def row(eid, day, a1, a2, quad, gold, tone, url, *, n=1, root="1", t1="", t2="", geo=""):
    """An Events 2.0 row (61 fields) with only the fields the probe reads filled in."""
    r = [""] * 61
    r[0], r[1] = str(eid), day
    r[rp.A1CC], r[rp.A1T1], r[rp.A2CC], r[rp.A2T1] = a1, t1, a2, t2
    r[25], r[29], r[30], r[33], r[34] = root, str(quad), str(gold), str(n), str(tone)
    r[53], r[60] = geo, url
    return r


class Outlets(rp.Outlets):
    def __init__(self):
        self.table = {"yna.co.kr": "KS", "nknews.org": "XX"}


class DayTests(unittest.TestCase):
    def setUp(self):
        self.day = rp.Day(date(2026, 11, 13), "PRK", "KN", Outlets())

    def vec(self, table, key):
        return dict(zip(rp.VEC, self.day.result()[table][key]))

    def test_one_article_counts_once_per_pair_whatever_its_event_count(self):
        u = "https://www.yna.co.kr/a"
        self.day.add_file([row(1, "20261113", "PRK", "KOR", 3, -4.0, -6.0, u, n=4),
                           row(2, "20261113", "PRK", "KOR", 1, 2.0, -2.0, u, n=4),
                           row(3, "20261113", "PRK", "KOR", 4, -10.0, -8.0, "https://b.example/x", n=2)],
                          "english", "20261113000000")
        v = self.vec("dyads", "PRK|KOR")
        self.assertEqual((v["ev"], v["art"], v["urls"]), (3, 10, 2))
        self.assertEqual((v["u1"], v["u3"], v["u4"], v["uconf"]), (1, 1, 1, 2))
        self.assertAlmostEqual(v["ugs"], -1.0 + -10.0)  # first URL's mean Goldstein (-4 + 2) / 2, then -10
        self.assertAlmostEqual(v["utn"], -4.0 + -8.0)

    def test_same_country_events_split_by_actor_type(self):
        self.day.add_file([row(1, "20261113", "PRK", "PRK", 4, -7.0, -5.0, "https://c/1", t1="MIL", t2="CVL"),
                           row(2, "20261113", "PRK", "PRK", 1, 3.0, 1.0, "https://c/2", t1="REF", t2="GOV"),
                           row(3, "20261113", "PRK", "PRK", 1, 3.0, 1.0, "https://c/3")],
                          "english", "20261113000000")
        res = self.day.result()
        self.assertEqual(sorted(res["within"]), ["PRK|N>N", "PRK|P>S", "PRK|S>P"])
        self.assertNotIn("PRK|PRK", res["dyads"])

    def test_references_to_the_past_are_skipped_and_focus_rows_kept(self):
        self.day.add_file([row(1, "20261101", "PRK", "KOR", 4, -10.0, -8.0, "https://a/1"),
                           row(2, "20261113", "USA", "JPN", 1, 3.0, 1.0, "https://a/2"),
                           row(3, "20261113", "", "", 1, 3.0, 1.0, "https://a/3", geo="KN")],
                          "translation", "20261113001500")
        res = self.day.result()
        self.assertEqual(res["skipped_old"], 1)
        self.assertEqual(list(res["dyads"]), ["USA|JPN"])
        self.assertEqual(len(self.day.rows_kept), 1)  # the KN-placed row; the old PRK row was skipped first

    def test_press_counts_each_article_once_per_subject_with_its_outlet_country(self):
        self.day.add_file([row(1, "20261113", "PRK", "KOR", 3, -4.0, -6.0, "https://www.yna.co.kr/a"),
                           row(2, "20261113", "PRK", "USA", 1, 2.0, -2.0, "https://www.yna.co.kr/a"),
                           row(3, "20261113", "PRK", "", 1, 2.0, 4.0, "https://nknews.org/b")],
                          "english", "20261113000000")
        press = self.day.result()["press"]
        self.assertEqual(press["KS>PRK"], [1, -4.0, 1])  # mean tone of its two events, one conflict event
        self.assertEqual(press["KS>USA"], [1, -4.0, 0])
        self.assertEqual(press["XX>PRK"], [1, 4.0, 0])


class SeriesTests(unittest.TestCase):
    def test_window_z_compares_a_week_with_the_four_weeks_before_it(self):
        d0 = date(2026, 10, 1)
        values = {d0 + timedelta(days=i): (0.1 if i % 2 else 0.2) for i in range(40)}
        last = d0 + timedelta(days=39)
        values[last] = 0.5
        z = rp.window_z(values, last, floor=0.03)
        self.assertAlmostEqual(z["baseline"], 0.15, places=3)
        self.assertAlmostEqual(z["z"], round((0.5 - 0.15) / 0.05, 2))
        self.assertIsNone(rp.window_z(values, d0 + timedelta(days=10), floor=0.03))

    def test_outlet_country_matches_the_longest_known_suffix(self):
        o = Outlets()
        self.assertEqual(o.country("https://www.yna.co.kr/view/1"), "KS")
        self.assertEqual(o.country("https://en.yna.co.kr/view/1"), "KS")
        self.assertEqual(o.country("https://unknown.example/x"), "?")


if __name__ == "__main__":
    unittest.main()
