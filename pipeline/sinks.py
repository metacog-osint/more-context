"""Where a cycle writes: a local folder (testing) or a Cloud Storage bucket (production).

Each cycle writes two objects: its data rows (JSON lines) and the state file. Keeping writes to two per
run keeps Cloud Storage operations near its free allowance.
"""
from __future__ import annotations

import hashlib
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

    def list(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)).replace("\\", "/") for p in base.rglob("*") if p.is_file())

    def read_lines(self, key: str) -> list[dict]:
        p = self.root / key
        return [json.loads(line) for line in p.read_text(encoding="utf-8").split("\n") if line.strip()]

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

    def list(self, prefix: str) -> list[str]:
        return sorted(b.name for b in self.bucket.client.list_blobs(self.bucket, prefix=prefix))

    def read_lines(self, key: str) -> list[dict]:
        text = self.bucket.blob(key).download_as_text()
        return [json.loads(line) for line in text.split("\n") if line.strip()]

    def exists(self, key: str) -> bool:
        return self.bucket.blob(key).exists()

    def read_json_versioned(self, key: str) -> tuple[dict | None, int]:
        """(object or None, generation); generation 0 means the object does not exist."""
        blob = self.bucket.get_blob(key)
        if blob is None:
            return None, 0
        return json.loads(blob.download_as_text()), blob.generation

    def write_json_if(self, key: str, obj: dict, version: int) -> bool:
        """Atomic compare-and-swap: Cloud Storage refuses the write if the generation moved on."""
        from google.api_core.exceptions import PreconditionFailed

        try:
            self.bucket.blob(key).upload_from_string(json.dumps(obj, ensure_ascii=False),
                                                     content_type="application/json", if_generation_match=version)
            return True
        except PreconditionFailed:
            return False
