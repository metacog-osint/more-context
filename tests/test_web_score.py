"""web/score.js: how a score's ratio and z read in one cell, and which sample headlines the Rising page shows.

The module is plain JavaScript with no DOM; these tests run it in Node (present on GitHub's runners, so CI fails
rather than skips when it is missing). Fixtures are scores as the API serves them (`/summary`, `/countries`).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
NODE = shutil.which("node")

RUNNER = """
import * as m from "./score.mjs";
let raw = "";
process.stdin.on("data", (c) => { raw += c; });
process.stdin.on("end", () => {
  const out = JSON.parse(raw).map(([fn, args]) => (m[fn] ?? (() => { throw new Error(fn); }))(...args));
  process.stdout.write(JSON.stringify(out));
});
"""

# A topic on 22 Nov 2026: 1 story, nothing expected, ratio shown against the floor of 3 (the "0.33x (z 1.05)" cell).
GNSS_22 = {"z": 1.05, "expected": 0.0, "ratio": None, "ratio_shown": 0.33, "floored": True, "baseline_days": 26,
           "weekday_adjusted": True, "z_method": "pred-1"}
GNSS_25 = {"z": 0.99, "expected": 1.5, "ratio": 2.59, "ratio_shown": 1.33, "floored": True, "baseline_days": 26,
           "weekday_adjusted": True, "z_method": "pred-1"}
# A zone's attention: the ratio and the z both against the expected count.
UKRAINE_ATT = {"z": 1.34, "expected": 2744.4, "ratio": 1.26, "ratio_shown": 1.26, "floored": False,
               "baseline_days": 28, "weekday_adjusted": True, "z_method": "pred-1"}
# A zone's violence: the 90-day median (135) is above the expected (117.6), so the ratio is against the median.
UKRAINE_VIOL = {"z": 1.69, "expected": 117.6, "ratio": 1.71, "z_method": "pred-1", "median90": 135.0,
                "ratio90": 1.49, "ratio_shown": 1.49, "floored": False}
# A country where ratio and ratio_shown differ only by rounding: the median (3.0) is not above the expected (3.2).
LIBERIA_VIOL = {"z": 1.31, "expected": 3.2, "ratio": 2.49, "z_method": "robust-1", "median90": 3.0, "ratio90": 2.67,
                "ratio_shown": 2.5, "floored": False}


def run(calls: list) -> list:
    """Each (function name, args) evaluated by web/score.js in Node."""
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copyfile(WEB / "score.js", Path(tmp) / "score.mjs")
        (Path(tmp) / "run.mjs").write_text(RUNNER, encoding="utf-8")
        p = subprocess.run([NODE, "run.mjs"], cwd=tmp, input=json.dumps(calls), capture_output=True, text=True,
                           encoding="utf-8", timeout=60)
    if p.returncode:
        raise AssertionError(p.stderr)
    return json.loads(p.stdout)


def one(fn: str, *args):
    return run([[fn, list(args)]])[0]


@unittest.skipIf(not NODE and not os.environ.get("CI"), "Node is not installed here (CI has it)")
class RatioAndZ(unittest.TestCase):
    def test_low_count_topic_is_too_few_to_judge(self):
        for s, count in ((GNSS_22, 1), (GNSS_25, 4), (GNSS_22, 0)):
            with self.subTest(count=count):
                self.assertTrue(one("tooFew", s, count))
                note = one("baselineNote", s, count, "stories")
                self.assertIn("too few to judge", note)
                self.assertNotIn("z ", note.replace("ratio or z", ""))  # no z value, in the cell or its tooltip
                self.assertNotIn(str(s["ratio_shown"]), note)
        self.assertTrue(one("baselineNote", GNSS_22, 1, "stories").startswith("1 story; "))
        self.assertTrue(one("baselineNote", GNSS_25, 1, "articles").startswith("1 article; "))

    def test_floored_ratio_is_never_a_number(self):
        # The floor-of-3 ratio ("0.33x") read as a third of normal; a floored score shows the count instead.
        self.assertEqual(one("ratioText", GNSS_22, 1), "1 (usually ≤3)")
        self.assertEqual(one("ratioText", GNSS_22), "usually ≤3")
        self.assertNotIn("×", one("ratioText", GNSS_25, 4))

    def test_floored_with_enough_stories_keeps_its_z_and_names_both_baselines(self):
        s = {**GNSS_25, "z": 2.4}
        self.assertFalse(one("tooFew", s, 8))
        self.assertEqual(one("ratioText", s, 8), "8 (usually ≤3)")
        note = one("baselineNote", s, 8, "stories")
        self.assertIn("usually 3 or fewer a day", note)
        self.assertIn("z 2.4 against the last 26 days (expected 1.5)", note)

    def test_same_baseline_says_so(self):
        self.assertEqual(one("ratioBase", UKRAINE_ATT), "expected")
        self.assertEqual(one("ratioText", UKRAINE_ATT, 3465), "1.26×")
        self.assertEqual(one("baselineNote", UKRAINE_ATT, 3465, "stories"),
                         "1.26× the expected 2744.4; z 1.34 against the last 28 days (expected 2744.4): "
                         "the ratio and the z use the same baseline")

    def test_median_baseline_is_named_in_the_cell_and_the_tooltip(self):
        self.assertEqual(one("ratioBase", UKRAINE_VIOL), "median")
        self.assertEqual(one("ratioText", UKRAINE_VIOL), "1.49× 90-day median")
        note = one("baselineNote", UKRAINE_VIOL, 201, "articles")
        self.assertIn("1.49× the median of the last 90 days (135)", note)
        self.assertIn("z 1.69 against the last 28 days (expected 117.6)", note)

    def test_rounding_alone_does_not_switch_the_baseline(self):
        self.assertEqual(one("ratioBase", LIBERIA_VIOL), "expected")
        self.assertEqual(one("ratioText", LIBERIA_VIOL, 8), "2.5×")

    def test_every_cell_names_the_baseline_of_what_it_shows(self):
        cases = []
        for expected in (0.0, 1.5, 2.9, 3.0, 8.0, 120.0):
            for median in (None, 0.0, 2.0, 6.0, 150.0):
                for count in (0, 1, 4, 5, 12, 400):
                    ref = max(expected, median or 0.0)
                    s = {"z": 1.2, "expected": expected, "ratio": round(count / expected, 2) if expected else None,
                         "ratio_shown": round(count / max(ref, 3.0), 2), "floored": ref < 3.0, "baseline_days": 28}
                    if median is not None:
                        s["median90"] = median
                    cases.append((s, count))
        calls = [c for s, n in cases for c in (["tooFew", [s, n]], ["ratioBase", [s]], ["ratioText", [s, n]],
                                                ["baselineNote", [s, n, "stories"]])]
        out = run(calls)
        for i, (s, n) in enumerate(cases):
            few, base, text, note = out[4 * i: 4 * i + 4]
            with self.subTest(score=s, count=n):
                if few:
                    self.assertIn("too few to judge", note)
                    continue
                self.assertIn("z 1.2 against the last 28 days", note)
                if base == "floor":
                    self.assertNotIn("×", text)
                    self.assertIn("3 or fewer", note)
                elif base == "median":
                    self.assertIn("90-day median", text)
                    self.assertIn("median of the last 90 days", note)
                else:
                    self.assertIn("same baseline", note)


@unittest.skipIf(not NODE and not os.environ.get("CI"), "Node is not installed here (CI has it)")
class SampleHeadlines(unittest.TestCase):
    def test_links_without_a_readable_title_are_left_out(self):
        # Finland on 25 Nov 2026: both shown links had no title, so the page printed two site names.
        samples = [{"url": "https://www.facenews.ua/news/2026/546319/", "title": ""},
                   {"url": "https://www.kouvolansanomat.fi/uutissuomalainen/9983561", "title": ""},
                   {"url": "https://example.fi/a", "title": "   "},
                   {"url": "https://yle.fi/a/finland-raises-border-alert-level", "title": "finland raises border alert level"},
                   {"url": "javascript:alert(1)", "title": "not a link"},
                   {"url": "https://hs.fi/b", "title": "second real headline here"},
                   {"url": "https://hs.fi/c", "title": "third real headline here"}]
        heads = one("readableHeads", samples)
        self.assertEqual([h["title"] for h in heads], ["finland raises border alert level", "second real headline here"])

    def test_no_readable_title_leaves_the_cell_empty(self):
        self.assertEqual(one("readableHeads", [{"url": "https://ria.ru/20261125/kushner-2133743899.html", "title": ""}]), [])
        self.assertEqual(one("readableHeads", None), [])


class PageUsesTheRules(unittest.TestCase):
    """The page builds its cells from web/score.js and never prints a site name as a headline."""

    def test_app_reads_score_js(self):
        app = (WEB / "app.js").read_text(encoding="utf-8")
        self.assertIn('from "./score.js"', app)
        rows = app[app.index("function countryRows"):app.index("function countryTable")]
        self.assertIn("readableHeads(data.samples[cc])", rows)
        self.assertNotIn("hostname", rows)
        self.assertNotIn("Sample headlines", app)


if __name__ == "__main__":
    unittest.main()
