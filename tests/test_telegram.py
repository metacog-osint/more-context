import unittest

from pipeline import feeds, telegram

PAGE = """<html><body><section class="tgme_channel_history js-message_history">
<div class="tgme_widget_message_wrap js-widget_message_wrap"><div class="tgme_widget_message text_not_supported_wrap js-widget_message" data-post="kpszsu/9001" data-view="x">
  <div class="tgme_widget_message_bubble">
    <div class="tgme_widget_message_text js-message_text" dir="auto"><b>У ніч на 27 жовтня</b> противник атакував 152 ударними БпЛА<br/>Збито/подавлено 131 <a href="#">БпЛА</a> &amp; 4 ракети<div class="inner">deep</div></div>
    <div class="tgme_widget_message_footer"><a class="tgme_widget_message_date" href="https://t.me/kpszsu/9001"><time datetime="2026-10-27T06:12:00+00:00" class="time">06:12</time></a></div>
  </div></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="kpszsu/9002">
  <div class="tgme_widget_message_bubble"><a class="tgme_widget_message_photo_wrap" href="#"></a>
  <div class="tgme_widget_message_footer"><time datetime="2026-10-27T07:00:00+00:00">07:00</time></div></div></div></div>
<div class="tgme_widget_message_wrap"><div class="tgme_widget_message js-widget_message" data-post="kpszsu/9003">
  <div class="tgme_widget_message_text js-message_text">

Повітряна тривога в Києві</div>
  <div class="tgme_widget_message_footer"><time datetime="2026-10-27T08:30:00+00:00">08:30</time></div></div></div>
</section></body></html>"""


class TelegramTests(unittest.TestCase):
    def test_parse_preview(self):
        items = telegram.parse_preview(PAGE.encode("utf-8"))
        self.assertEqual([i["url"] for i in items], ["https://t.me/kpszsu/9001", "https://t.me/kpszsu/9003"])
        first = items[0]
        self.assertEqual(first["title"], "У ніч на 27 жовтня противник атакував 152 ударними БпЛА")
        self.assertIn("131 БпЛА & 4 ракети", first["summary"])
        self.assertIn("deep", first["summary"])  # nested div inside the text stays in the text
        self.assertEqual(first["published"].isoformat(), "2026-10-27T06:12:00+00:00")
        self.assertEqual(items[1]["title"], "Повітряна тривога в Києві")  # leading blank lines skipped

    def test_photo_only_posts_skipped_and_empty_page(self):
        self.assertEqual(telegram.parse_preview(b"<html></html>"), [])

    def test_poller_routes_telegram_sources(self):
        class Res:
            ok, status, not_modified, etag, last_modified, error = True, 200, False, None, None, ""
            body = PAGE.encode("utf-8")

        import pipeline.rss as rss
        real = rss.fetch
        rss.fetch = lambda url, etag=None, last_modified=None: Res()
        try:
            _res, items, err = feeds._fetch_one({"url": "https://t.me/s/kpszsu", "format": "telegram"}, {})
        finally:
            rss.fetch = real
        self.assertEqual((len(items), err), (2, ""))

    def test_catalog_has_telegram_sources(self):
        tg = [s for s in feeds.load_sources() if s.get("format") == "telegram"]
        self.assertGreaterEqual(len(tg), 7)
        self.assertTrue(all(s["url"].startswith("https://t.me/s/") for s in tg))


if __name__ == "__main__":
    unittest.main()
