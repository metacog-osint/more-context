import io
import unittest
import zipfile

from pipeline import gdelt


def gkg_row(**over) -> list[str]:
    f = [""] * gdelt.GKG_FIELDS
    f[0] = "20261026163000-123"
    f[1] = "20261026162500"
    f[3] = "example.com"
    f[4] = "https://example.com/world/ukraine-strike-kills-six"
    f[7] = "ARMEDCONFLICT;KILL;"
    f[9] = "1#Ukraine#UP#UP#49#32#UP;"
    f[15] = "-4.2,1.1,5.3,6.4,20.1,0,512"
    f[26] = "<PAGE_TITLE>Strike in Zaporizhzhia kills six &amp; injures 12</PAGE_TITLE>"
    for k, v in over.items():
        f[int(k[1:])] = v
    return f


class ParseRowTests(unittest.TestCase):
    def test_parses_fields(self):
        a = gdelt.parse_row(gkg_row(), "english")
        self.assertEqual(a.domain, "example.com")
        self.assertEqual(a.title, "Strike in Zaporizhzhia kills six & injures 12")
        self.assertAlmostEqual(a.tone, -4.2)
        self.assertEqual(a.lang, "eng")
        self.assertEqual(a.published.isoformat(), "2026-10-26T16:25:00+00:00")

    def test_translation_language(self):
        a = gdelt.parse_row(gkg_row(f25="srclc:rus;eng:GT-RUS 1.0;"), "translation")
        self.assertEqual(a.lang, "rus")

    def test_short_or_bad_rows_skipped(self):
        self.assertIsNone(gdelt.parse_row(["x"] * 5, "english"))
        self.assertIsNone(gdelt.parse_row(gkg_row(f1="not-a-date"), "english"))

    def test_missing_title_and_tone(self):
        a = gdelt.parse_row(gkg_row(f26="", f15=""), "english")
        self.assertEqual(a.title, "")
        self.assertIsNone(a.tone)

    def test_parse_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("x.gkg.csv", "\t".join(gkg_row()) + "\n" + "\t".join(gkg_row(f0="b")) + "\n")
        self.assertEqual(len(list(gdelt.parse_zip(buf.getvalue(), "english"))), 2)


class WindowTests(unittest.TestCase):
    def test_window_stamps(self):
        s = gdelt.window_stamps("20261026003000", 1)
        self.assertEqual(s, ["20261026003000", "20261026001500", "20261026000000", "20261025234500"])


if __name__ == "__main__":
    unittest.main()
