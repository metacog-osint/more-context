"""Where a cycle writes: a local folder (testing) or a Cloud Storage bucket (production).

Each cycle writes two objects: its data rows (JSON lines) and the state file. Keeping writes to two per
run keeps Cloud Storage operations near its free allowance.
"""
from __future__ import annotations

import json
from pathlib import Path


def _lines(rows: list[dict]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


class LocalSink:
    def __init__(self, root: Path):
        self.root = Path(root)

    def read_json(self, key: str) -> dict | None:
        p = self.root / key
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

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


class GCSSink:
    def __init__(self, bucket: str):
        from google.cloud import storage  # only needed in the cloud

        self.bucket = storage.Client().bucket(bucket)

    def read_json(self, key: str) -> dict | None:
        blob = self.bucket.blob(key)
        return json.loads(blob.download_as_text()) if blob.exists() else None

    def write_json(self, key: str, obj: dict) -> None:
        self.bucket.blob(key).upload_from_string(json.dumps(obj, ensure_ascii=False),
                                                 content_type="application/json")

    def write_lines(self, key: str, rows: list[dict]) -> None:
        self.bucket.blob(key).upload_from_string(_lines(rows), content_type="application/x-ndjson")
