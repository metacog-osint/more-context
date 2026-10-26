"""GDELT GKG 2.1 raw files: list the 15-minute files, download them, parse rows.

GDELT publishes one GKG file per 15 minutes for English sources and one for its machine-translated
stream. Downloads are free; nothing here touches BigQuery.
"""
from __future__ import annotations

import html
import io
import re
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

BASE = "https://data.gdeltproject.org/gdeltv2/"
FILE_NAMES = {
    "english": "{stamp}.gkg.csv.zip",
    "translation": "{stamp}.translation.gkg.csv.zip",
}
INDEX_NAMES = {"english": "lastupdate.txt", "translation": "lastupdate-translation.txt"}
USER_AGENT = "MORE-CONTEXT/0.1 (+https://context.theintelligence.company)"
GKG_FIELDS = 27

_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_SRC_LANG = re.compile(r"srclc:([a-z]{3})")
_STAMP = re.compile(r"/(\d{14})\.")


@dataclass
class Article:
    record_id: str
    published: datetime  # GKG DATE, UTC
    domain: str
    url: str
    themes: str  # V1 themes, ';'-separated
    locations: str  # V1 locations, ';'-separated TYPE#NAME#CC#ADM1#LAT#LON#FEATURE
    tone: float | None
    title: str  # PAGE_TITLE from the extras field; '' when GDELT had none
    lang: str  # 'eng', or the source language code for the translation stream
    stream: str

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["published"] = self.published.strftime("%Y-%m-%dT%H:%M:%SZ")
        return d


def fetch(url: str, timeout: float = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def latest_stamp(stream: str = "english") -> str:
    """Timestamp (YYYYMMDDHHMMSS, UTC) of the newest GKG file in a stream."""
    index = fetch(BASE + INDEX_NAMES[stream], timeout=30).decode("utf-8", "replace")
    for line in index.splitlines():
        if line.strip().endswith(".gkg.csv.zip"):
            m = _STAMP.search(line)
            if m:
                return m.group(1)
    raise RuntimeError(f"no GKG entry in {INDEX_NAMES[stream]}")


def window_stamps(end_stamp: str, hours: float) -> list[str]:
    """The 15-minute stamps covering `hours` and ending at `end_stamp`, newest first."""
    end = datetime.strptime(end_stamp, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    return [(end - timedelta(minutes=15 * i)).strftime("%Y%m%d%H%M%S") for i in range(int(hours * 4))]


def file_url(stamp: str, stream: str) -> str:
    return BASE + FILE_NAMES[stream].format(stamp=stamp)


def download(stamp: str, stream: str) -> bytes | None:
    """The zipped file's bytes, or None when GDELT has no file for that slot (it happens)."""
    try:
        return fetch(file_url(stamp, stream))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def _decode(field: bytes) -> str:
    # Most fields are UTF-8, but some page titles arrive in Windows-1252 ("K\xf6nig").
    try:
        return field.decode("utf-8")
    except UnicodeDecodeError:
        return field.decode("cp1252", errors="replace")


def parse_zip(data: bytes, stream: str) -> Iterator[Article]:
    """GKG files are tab-separated with no quoting, so each line splits cleanly on tabs."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for name in zf.namelist():
            with zf.open(name) as raw:
                for line in raw:
                    fields = [_decode(f) for f in line.rstrip(b"\r\n").split(b"\t")]
                    art = parse_row(fields, stream)
                    if art:
                        yield art


def parse_row(fields: list[str], stream: str) -> Article | None:
    if len(fields) < GKG_FIELDS:
        return None
    try:
        published = datetime.strptime(fields[1], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    tone = None
    if fields[15]:
        try:
            tone = float(fields[15].split(",")[0])
        except ValueError:
            pass
    m = _TITLE.search(fields[26])
    title = html.unescape(m.group(1)).strip() if m else ""
    lm = _SRC_LANG.search(fields[25])
    return Article(
        record_id=fields[0],
        published=published,
        domain=fields[3],
        url=fields[4],
        themes=fields[7],
        locations=fields[9],
        tone=tone,
        title=title,
        lang=lm.group(1) if lm else "eng",
        stream=stream,
    )
