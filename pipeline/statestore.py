"""Where the ingest state lives: the bucket object `state/state.json`, or a Firestore document (MC_STATE=firestore).

Why Firestore (29 Oct 2026): every bucket write is a Class A operation and 5,000 a month are free; a run every
15 minutes writes its cycle file and the state, ~5,850 a month. Firestore's free tier allows 20,000 document writes
a day in the project's `(default)` database (Native, nam5), so the state moves there and the bucket keeps one write
a run. MORE CONTEXT's collections carry the `mc_` prefix; v4.3's share the database.

The state is gzip-compressed JSON in a bytes field: 95 KB on 29 Oct (182 KB raw), ~140 KB once every feed's
fingerprint list is full, against Firestore's 1 MiB document limit. A larger state is split across documents of
PART_BYTES (`mc_state/ingest`, `mc_state/ingest.1`, ...), written in one atomic commit; the first holds the count.

The bucket copy stays as a fallback and backup: the first Firestore read finds no document and reads the bucket
(the switch), and the run that builds a day also writes the bucket copy (one write a day), so a lost document or a
switch back costs at most a day's fingerprints (repeat feed rows the build drops) and a two-hour GDELT re-read.
Only a missing document falls back; any other Firestore error stops the run, so stale state is never used.
"""
from __future__ import annotations

import base64
import gzip
import json
import os
from datetime import datetime, timezone

STATE_KEY = "state/state.json"
COLLECTION, DOC = "mc_state", "ingest"
PART_BYTES = 900_000
API = "https://firestore.googleapis.com/v1"


class SinkState:
    """State as one JSON object in the sink (local folder or bucket)."""

    def __init__(self, sink, key: str = STATE_KEY):
        self.sink, self.key = sink, key

    def read(self) -> dict | None:
        return self.sink.read_json(self.key)

    def write(self, state: dict, backup: bool = False) -> None:
        self.sink.write_json(self.key, state)


class FirestoreError(RuntimeError):
    pass


class FirestoreState:
    """State in Firestore over its REST API. `session` is an authorised requests-style session
    (google.auth.transport.requests.AuthorizedSession in the cloud; a fake in tests)."""

    def __init__(self, project: str, session, fallback: SinkState | None = None, database: str = "(default)"):
        self.session, self.fallback = session, fallback
        self.root = f"projects/{project}/databases/{database}/documents"

    def _name(self, part: int) -> str:
        return f"{self.root}/{COLLECTION}/{DOC}" + (f".{part}" if part else "")

    def _get(self, part: int) -> dict | None:
        r = self.session.request("GET", f"{API}/{self._name(part)}", timeout=30)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise FirestoreError(f"read {COLLECTION}/{DOC} part {part}: HTTP {r.status_code} {r.text[:200]}")
        return r.json().get("fields", {})

    def read(self) -> dict | None:
        head = self._get(0)
        if head is None:  # not switched yet (or the document was lost): the bucket copy
            return self.fallback.read() if self.fallback else None
        blobs = [head]
        for i in range(1, int(head["parts"]["integerValue"])):
            part = self._get(i)
            if part is None:
                raise FirestoreError(f"{COLLECTION}/{DOC} part {i} is missing")
            blobs.append(part)
        data = b"".join(base64.b64decode(b["data"]["bytesValue"]) for b in blobs)
        return json.loads(gzip.decompress(data))

    def write(self, state: dict, backup: bool = False) -> None:
        data = gzip.compress(json.dumps(state, ensure_ascii=False).encode("utf-8"), 6)
        parts = [data[i:i + PART_BYTES] for i in range(0, len(data), PART_BYTES)] or [b""]
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        writes = []
        for i, chunk in enumerate(parts):
            fields = {"data": {"bytesValue": base64.b64encode(chunk).decode("ascii")}}
            if i == 0:
                fields.update(parts={"integerValue": str(len(parts))}, written_at={"timestampValue": now},
                              gzip_bytes={"integerValue": str(len(data))})
            writes.append({"update": {"name": self._name(i), "fields": fields}})
        r = self.session.request("POST", f"{API}/{self.root}:commit", json={"writes": writes}, timeout=60)
        if r.status_code != 200:
            raise FirestoreError(f"write {COLLECTION}/{DOC}: HTTP {r.status_code} {r.text[:200]}")
        if backup and self.fallback:
            self.fallback.write(state)


def from_env(sink):
    """MC_STATE=firestore: Firestore with the bucket as fallback and daily backup; otherwise the bucket object."""
    if os.environ.get("MC_STATE", "").lower() != "firestore":
        return SinkState(sink)
    import google.auth  # in the cloud only (comes with google-cloud-storage)
    from google.auth.transport.requests import AuthorizedSession

    creds, project = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
    return FirestoreState(os.environ.get("MC_PROJECT") or project, AuthorizedSession(creds), SinkState(sink))
