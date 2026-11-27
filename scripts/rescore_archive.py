"""Keep the original of every object a rescore, relabel or backfill is about to overwrite (retention fix M4, 18 Nov 2026).

Rule (18 Nov 2026): no program loses data. A re-score replaces scores in place; the values computed under the
previous method must survive it. Before any overwrite, each original goes to `archive/rescore/<UTC stamp>/<path>`:

- in the bucket (`archive_bucket`): a server-side copy (Cloud Storage `rewrite`), pinned to the generation the script
  fetched (`ifSourceGenerationMatch`), so the copy is the exact object the new values were computed from. The copy
  keeps the object's gzip encoding. The archive object is never replaced (`ifGenerationMatch=0`);
- in a local folder (`archive_local`): a file copy under `<root's parent>/archive/rescore/<stamp>/<path>`.

Either one raises ArchiveError on any failure, and the callers stop before they write: no archive, no write.
Archive copies are one Class A operation per object; a full re-score of 112 days is about 224 operations.
"""
from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PREFIX = "archive/rescore"
API = "https://storage.googleapis.com"


class ArchiveError(RuntimeError):
    pass


def stamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def archive_key(stamp: str, key: str) -> str:
    return f"{PREFIX}/{stamp}/{key}"


def _quote(key: str) -> str:
    return urllib.parse.quote(key, safe="")


def copy_object(bucket: str, key: str, opener, stamp: str, generation=None) -> str:
    """Server-side copy of `key` to its archive key. `opener(request)` returns a response context manager (it adds
    the authorisation). `generation` pins the source version. Returns the archive key; raises ArchiveError."""
    dest = archive_key(stamp, key)
    params = {"ifGenerationMatch": 0}  # never replace an archive object
    if generation is not None:
        params["ifSourceGenerationMatch"] = generation
    token = None
    for _ in range(50):  # a rewrite of a small object finishes in one call; large ones return a token
        q = dict(params)
        if token:
            q["rewriteToken"] = token
        url = (f"{API}/storage/v1/b/{bucket}/o/{_quote(key)}/rewriteTo/b/{bucket}/o/{_quote(dest)}?"
               + urllib.parse.urlencode(q))
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={"Content-Type": "application/json"})
        try:
            with opener(req) as r:
                body = json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            raise ArchiveError(f"archive copy of {key} failed: HTTP {e.code}") from e
        except Exception as e:  # noqa: BLE001
            raise ArchiveError(f"archive copy of {key} failed: {e}") from e
        if body.get("done"):
            return dest
        token = body.get("rewriteToken")
        if not token:
            raise ArchiveError(f"archive copy of {key} did not finish")
    raise ArchiveError(f"archive copy of {key} did not finish")


def archive_bucket(bucket: str, keys, generations: dict, opener, stamp: str | None = None) -> list[str]:
    """Copy every key (once) before anything is overwritten. Raises ArchiveError at the first failure."""
    stamp = stamp or stamp_now()
    done = []
    for key in dict.fromkeys(keys):
        done.append(copy_object(bucket, key, opener, stamp, generations.get(key)))
    return done


def archive_local(root: Path, keys, stamp: str | None = None) -> list[Path]:
    """Copy each existing file under `root` to <root.parent>/archive/rescore/<stamp>/<key>. A key with no file yet
    has nothing to lose and is skipped. Raises ArchiveError on any failure."""
    root = Path(root)
    stamp = stamp or stamp_now()
    out = []
    for key in dict.fromkeys(keys):
        src = root / key
        if not src.exists():
            continue
        dest = root.parent / "archive" / "rescore" / stamp / key
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                raise FileExistsError(str(dest))
            shutil.copy2(src, dest)
            if dest.stat().st_size != src.stat().st_size:
                raise OSError("size differs after copy")
        except OSError as e:
            raise ArchiveError(f"archive copy of {key} failed: {e}") from e
        out.append(dest)
    return out
