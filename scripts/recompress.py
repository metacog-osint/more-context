"""Recompress plain objects already in the bucket, in place: gzip, stored with Content-Encoding: gzip, the way the
bucket sink writes every object (added 30 Oct 2026, pipeline/sinks.py). Lossless: each object is checked to unzip
back to its original bytes before upload, and the stored MD5 is checked against the bytes sent.

Each rewrite is one Class A write (5,000 a month free, shared with the 15-minute ingest), so run the dry run first:
it only lists and sizes (one list call per 1,000 objects). The old plain copy stays in soft delete for 7 days,
counted as storage, then goes.

    python -I scripts/recompress.py --bucket more-context-484804                     # dry run
    python -I scripts/recompress.py --bucket more-context-484804 --run --limit 800   # rewrite (needs Tom's yes)

Rewrites are conditional on the object's generation: an object changed since the listing is skipped, never
overwritten. Re-running skips objects already gzip. Run it again after a backfill upload (gcloud storage rsync
stores files plain). Needs google-cloud-storage (requirements.txt).
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline.sinks import GZIP_MAGIC, gz  # noqa: E402

PREFIXES = ("cycles/", "stories/")  # 99% of the bytes on 30 Oct 2026; events/ (12 MiB, 182 objects) is left plain


def candidates(blobs, min_bytes: int = 1024) -> list:
    """Plain objects worth a write: not gzip already and at least min_bytes (tiny files gain almost nothing)."""
    return [b for b in blobs if b.content_encoding != "gzip" and (b.size or 0) >= min_bytes]


def recompress(bucket, blob) -> tuple[int, int] | None:
    """Rewrite one listed object as gzip: (bytes before, bytes after), or None when skipped (already gzip, or
    changed since it was listed)."""
    from google.api_core.exceptions import PreconditionFailed

    data = blob.download_as_bytes(raw_download=True)
    if data[:2] == GZIP_MAGIC:
        return None
    packed = gz(data)
    if gzip.decompress(packed) != data:
        raise RuntimeError(f"{blob.name}: gzip round trip differs")  # stop before writing anything
    new = bucket.blob(blob.name)
    new.content_encoding = "gzip"
    try:
        new.upload_from_string(packed, content_type=blob.content_type, if_generation_match=blob.generation)
    except PreconditionFailed:
        return None
    if new.md5_hash != base64.b64encode(hashlib.md5(packed).digest()).decode("ascii"):
        raise RuntimeError(f"{blob.name}: stored MD5 differs from the bytes sent")
    return len(data), len(packed)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--prefix", action="append", help="repeatable; default cycles/ and stories/")
    ap.add_argument("--run", action="store_true", help="rewrite (without it: dry run, lists only)")
    ap.add_argument("--limit", type=int, default=0, help="at most this many rewrites, oldest first (0: all)")
    a = ap.parse_args()
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(a.bucket)
    todo = []
    for p in a.prefix or PREFIXES:
        todo += candidates(client.list_blobs(bucket, prefix=p))
    if a.limit:
        todo = todo[: a.limit]
    raw = sum(b.size for b in todo)
    print(f"{len(todo)} plain objects, {raw / 2**20:.1f} MiB: {len(todo)} Class A writes")
    if not a.run:
        print("dry run: nothing written (add --run)")
        return
    done = skipped = before = after = 0
    for i, b in enumerate(todo, 1):
        r = recompress(bucket, b)
        if r is None:
            skipped += 1
        else:
            done, before, after = done + 1, before + r[0], after + r[1]
        if i % 50 == 0 or i == len(todo):
            print(f"{i}/{len(todo)}: rewrote {done}, skipped {skipped}, {before / 2**20:.1f} -> {after / 2**20:.1f} MiB",
                  flush=True)


if __name__ == "__main__":
    main()
