"""RSS / Atom / RDF feeds: fetch politely (ETag, Last-Modified), parse, keep title + short lead.

Only headlines, links and the feed's own short summary are kept, never full article text.
"""
from __future__ import annotations

import gzip
import html
import math
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

USER_AGENT = "MORE-CONTEXT/0.1 (+https://context.theintelligence.company; feed reader)"
MAX_BYTES = 5_000_000
SUMMARY_CHARS = 400

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "rss1": "http://purl.org/rss/1.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "content": "http://purl.org/rss/1.0/modules/content/",
}
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


class FetchResult:
    def __init__(self, status: int, body: bytes = b"", etag: str | None = None,
                 last_modified: str | None = None, error: str = ""):
        self.status, self.body, self.etag, self.last_modified, self.error = status, body, etag, last_modified, error

    @property
    def ok(self) -> bool:
        return self.status == 200

    @property
    def not_modified(self) -> bool:
        return self.status == 304


def fetch(url: str, etag: str | None = None, last_modified: str | None = None, timeout: float = 20) -> FetchResult:
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip",
               "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return FetchResult(0, error="feed larger than 5 MB")
            if resp.headers.get("Content-Encoding") == "gzip":
                body = gzip.decompress(body)
            return FetchResult(200, body, resp.headers.get("ETag"), resp.headers.get("Last-Modified"))
    except urllib.error.HTTPError as e:
        if e.code == 304:
            return FetchResult(304)
        return FetchResult(e.code, error=f"HTTP {e.code}")
    except Exception as e:  # DNS, TLS, timeout, reset
        return FetchResult(0, error=f"{type(e).__name__}: {e}"[:200])


def clean_text(s: str | None, limit: int | None = None) -> str:
    if not s:
        return ""
    t = _WS.sub(" ", _TAG.sub(" ", html.unescape(html.unescape(s)))).strip()
    if limit and len(t) > limit:
        t = t[: limit - 1].rsplit(" ", 1)[0] + "…"
    return t


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def _text(el, path: str) -> str | None:
    found = el.find(path, NS)
    return found.text if found is not None and found.text else None


def correct_clock(items: list[dict], skew_hours: float) -> None:
    """Subtract a known clock error from a feed that labels local time as UTC."""
    if skew_hours:
        for i in items:
            if i["published"]:
                i["published"] -= timedelta(hours=skew_hours)


def future_skew_hours(items: list[dict], now: datetime, tolerance_min: float = 15) -> int:
    """Whole hours by which the newest item is dated in the future (0 if none): a clock-label warning."""
    newest = max((i["published"] for i in items if i["published"]), default=None)
    if not newest or (newest - now).total_seconds() <= tolerance_min * 60:
        return 0
    return math.ceil((newest - now).total_seconds() / 3600)


_ROOT_END = (b"</rss>", b"</feed>", b"</rdf:RDF>")


def _parse_xml(body: bytes):
    try:
        return ET.fromstring(body)
    except ET.ParseError as e:
        # Some feeds append stray markup after the closing root tag; cut it and retry once.
        if "junk after document element" in str(e):
            ends = [body.rfind(t) + len(t) for t in _ROOT_END if body.rfind(t) != -1]
            if ends:
                try:
                    return ET.fromstring(body[: max(ends)])
                except ET.ParseError:
                    pass
        raise ValueError(f"not XML: {e}") from None


def parse_feed(body: bytes) -> list[dict]:
    """Items as dicts: title, url, published (datetime or None), summary. Raises ValueError on bad XML."""
    root = _parse_xml(body)
    items = []
    if root.tag.endswith("rss") or root.find("channel") is not None:
        for it in root.iter("item"):
            items.append({
                "title": clean_text(_text(it, "title")),
                "url": (_text(it, "link") or _text(it, "guid") or "").strip(),
                "published": parse_date(_text(it, "pubDate") or _text(it, "dc:date")),
                "summary": clean_text(_text(it, "description") or _text(it, "content:encoded"), SUMMARY_CHARS),
            })
    elif root.tag == f"{{{NS['atom']}}}feed":
        for it in root.findall("atom:entry", NS):
            link = ""
            for ln in it.findall("atom:link", NS):
                if ln.get("rel", "alternate") == "alternate" and ln.get("href"):
                    link = ln.get("href")
                    break
            items.append({
                "title": clean_text(_text(it, "atom:title")),
                "url": link.strip(),
                "published": parse_date(_text(it, "atom:published") or _text(it, "atom:updated")),
                "summary": clean_text(_text(it, "atom:summary") or _text(it, "atom:content"), SUMMARY_CHARS),
            })
    else:  # RSS 1.0 / RDF
        for it in root.findall("rss1:item", NS):
            items.append({
                "title": clean_text(_text(it, "rss1:title")),
                "url": (_text(it, "rss1:link") or "").strip(),
                "published": parse_date(_text(it, "dc:date")),
                "summary": clean_text(_text(it, "rss1:description"), SUMMARY_CHARS),
            })
    return [i for i in items if i["title"] and i["url"].startswith("http")]
