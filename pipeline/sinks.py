"""Where a cycle writes: a local folder (testing) or a Cloud Storage bucket (production).

A run writes two objects: its cycle file (article rows and Events records, JSON lines) and the state file (twice
on the run that builds a day). Writes and lists are Class A operations, the ones a 15-minute schedule uses up:
5,000 a month are free.

The bucket sink gzips every object it writes (added 30 Oct 2026) (stored with Content-Encoding: gzip). Cycle files
shrink 4.6x, which keeps the record inside the free 5 GB for months instead of weeks. Reads take gzip or plain
(older objects, backfill uploads), told apart by gzip's first two bytes; the keys and the text are unchanged.
scripts/recompress.py converts plain objects already in the bucket. Local folders stay plain.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path

GZIP_MAGIC = b"\x1f\x8b"  # every gzip stream starts with these; JSON text never does


def _lines(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def gz(data: bytes) -> bytes:
    """gzip with no timestamp in the header, so the same text always gives the same bytes."""
    return gzip.compress(data, compresslevel=6, mtime=0)


def _text(data: bytes) -> str:
    """UTF-8 text from stored bytes, gzip or plain."""
    return (gzip.decompress(data) if data[:2] == GZIP_MAGIC else data).decode("utf-8")


def _parse(text: str, prefix: str = "") -> list[dict]:
    """JSON lines; with `prefix`, only the lines that start with it (the rest are never parsed). Split on "\\n"
    only: splitlines() also breaks at U+2028 inside JSON strings."""
    return [json.loads(line) for line in text.split("\n") if line.strip() and line.startswith(prefix)]


class LocalSink:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _read(self, key: str) -> str:
        # Plain or gzip (a raw copy of a bucket object); "\r\n" back to "\n" as read_text did for Windows files.
        return _text((self.root / key).read_bytes()).replace("\r\n", "\n")

    def read_json(self, key: str) -> dict | None:
        p = self.root / key
        return json.loads(self._read(key)) if p.exists() else None

    def write_json(self, key: str, obj: dict) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)

    def write_lines(self, key: str, rows: list[dict]) -> None:
        p = self.root / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_lines(rows), encoding="utf-8")

    def list(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file())

    def read_lines(self, key: str, prefix: str = "") -> list[dict]:
        return _parse(self._read(key), prefix)

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def _version(self, key: str) -> str | int:
        p = self.root / key
        return hashlib.sha1(p.read_bytes()).hexdigest() if p.exists() else 0

    def read_json_versioned(self, key: str) -> tuple[dict | None, str | int]:
        """(object or None, version); version 0 means the object does not exist."""
        return self.read_json(key), self._version(key)

    def write_json_if(self, key: str, obj: dict, version: str | int) -> bool:
        """Write only if the object is still at `version` (single-process check; GCS does it atomically)."""
        if self._version(key) != version:
            return False
        self.write_json(key, obj)
        return True

    def read_lines_versioned(self, key: str) -> tuple[list[dict], str | int]:
        """(rows, version) of a JSON-lines object; ([], 0) when it does not exist."""
        p = self.root / key
        return (self.read_lines(key), self._version(key)) if p.exists() else ([], 0)

    def write_lines_if(self, key: str, rows: list[dict], version: str | int) -> bool:
        if self._version(key) != version:
            return False
        self.write_lines(key, rows)
        return True


class GCSSink:
    def __init__(self, bucket: str):
        from google.cloud import storage  # only needed in the cloud

        self.bucket = storage.Client().bucket(bucket)

    def _put(self, key: str, text: str, content_type: str, **kw) -> None:
        blob = self.bucket.blob(key)
        blob.content_encoding = "gzip"
        blob.upload_from_string(gz(text.encode("utf-8")), content_type=content_type, **kw)

    @staticmethod
    def _get(blob) -> str:
        # raw_download: the stored bytes as they are (the checksum is on those); _text unzips gzip ones.
        return _text(blob.download_as_bytes(raw_download=True))

    def read_json(self, key: str) -> dict | None:
        blob = self.bucket.blob(key)
        return json.loads(self._get(blob)) if blob.exists() else None

    def write_json(self, key: str, obj: dict) -> None:
        self._put(key, json.dumps(obj, ensure_ascii=False), "application/json")

    def write_lines(self, key: str, rows: list[dict]) -> None:
        self._put(key, _lines(rows), "application/x-ndjson")

    def list(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self.bucket.client.list_blobs(self.bucket, prefix=prefix))

    def read_lines(self, key: str, prefix: str = "") -> list[dict]:
        return _parse(self._get(self.bucket.blob(key)), prefix)

    def exists(self, key: str) -> bool:
        return self.bucket.blob(key).exists()

    def read_json_versioned(self, key: str) -> tuple[dict | None, int]:
        """(object or None, generation); generation 0 means the object does not exist."""
        blob = self.bucket.get_blob(key)
        if blob is None:
            return None, 0
        return json.loads(self._get(blob)), blob.generation

    def write_json_if(self, key: str, obj: dict, version: int) -> bool:
        """Atomic compare-and-swap: Cloud Storage refuses the write if the generation moved on."""
        from google.api_core.exceptions import PreconditionFailed

        try:
            self._put(key, json.dumps(obj, ensure_ascii=False), "application/json", if_generation_match=version)
            return True
        except PreconditionFailed:
            return False

    def read_lines_versioned(self, key: str) -> tuple[list[dict], int]:
        """(rows, generation) of a JSON-lines object; ([], 0) when it does not exist."""
        blob = self.bucket.get_blob(key)
        if blob is None:
            return [], 0
        return _parse(self._get(blob)), blob.generation

    def write_lines_if(self, key: str, rows: list[dict], version: int) -> bool:
        from google.api_core.exceptions import PreconditionFailed

        try:
            self._put(key, _lines(rows), "application/x-ndjson", if_generation_match=version)
            return True
        except PreconditionFailed:
            return False
