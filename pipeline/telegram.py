"""Public Telegram channels through their web preview (https://t.me/s/<channel>): no account, no API key.

The preview page lists a channel's latest ~20 posts. Each becomes an item shaped like an RSS item (title,
url, published, summary), so the feed poller, health tracking and dedup treat it like any other source.
Title = the post's first line; summary = its text, trimmed. Posts with no text (photo or video only) are skipped.
"""
from __future__ import annotations

from html.parser import HTMLParser

from .rss import SUMMARY_CHARS, clean_text, parse_date

TITLE_CHARS = 200


class _Preview(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.posts: list[dict] = []
        self._cur: dict | None = None
        self._text_depth = 0  # >0 while inside the message-text div
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class") or ""
        if tag == "div" and "tgme_widget_message " in cls + " " and a.get("data-post"):
            self._cur = {"post": a["data-post"], "text": "", "time": None}
            self.posts.append(self._cur)
            return
        if self._cur is None:
            return
        if self._text_depth:
            if tag == "div":
                self._text_depth += 1
            elif tag == "br":
                self._buf.append("\n")
            return
        if tag == "div" and "tgme_widget_message_text" in cls:
            self._text_depth, self._buf = 1, []
        elif tag == "time" and a.get("datetime") and self._cur["time"] is None:
            self._cur["time"] = a["datetime"]

    def handle_endtag(self, tag):
        if self._text_depth and tag == "div":
            self._text_depth -= 1
            if not self._text_depth and self._cur is not None and not self._cur["text"]:
                self._cur["text"] = "".join(self._buf)

    def handle_data(self, data):
        if self._text_depth:
            self._buf.append(data)


def parse_preview(body: bytes) -> list[dict]:
    """Items from a t.me/s/ page, oldest first as the page lists them."""
    p = _Preview()
    p.feed(body.decode("utf-8", "replace"))
    items = []
    for post in p.posts:
        text = post["text"].strip()
        if not text:
            continue
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        items.append({
            "title": clean_text(first, TITLE_CHARS),
            "url": f"https://t.me/{post['post']}",
            "published": parse_date(post["time"]),
            "summary": clean_text(text, SUMMARY_CHARS),
        })
    return items
