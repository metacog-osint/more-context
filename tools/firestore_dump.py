#!/usr/bin/env python3
"""firestore_dump.py: copy every document of a Firestore database to JSON Lines files, for the weekly backup.

Why (ideas#196, 23 Nov 2026): Firestore `(default)` in context-484804 holds Context's whole zone history
(`snapshots`, since 19 Jan) and Watchfloor's state, with point-in-time recovery off and no backup or export, so it
was a single copy. The weekly workflow (.github/workflows/weekly-backup.yml) runs this, then puts the folder into
TIC's private archive (tools/tic_archive.py, lane context-firestore). No TIC program loses data;
this only reads.

Output, one folder per collection path (a subcollection's path keeps its parent document, `/` becomes `~`):
    <out>/<collection>/<YYYY-MM>.jsonl   documents whose id starts with a date (Context's run ids)
    <out>/<collection>/other.jsonl       every other document
    <out>/counts.json                    documents per collection and in all
Each line is {"name", "createTime", "updateTime", "fields"} exactly as Firestore's REST API returns it (typed
values, so bytes and timestamps restore unchanged). Lines are sorted by name and keys sorted, so a month that did
not change gives the same bytes and the archive stores it once.

Reads: one per document plus one per listCollectionIds call (one per document when --subcollections is on). About
7,000 documents on 24 Nov 2026, so about 14,000 reads a week against Firestore's 50,000 free a day.

Logs of public repos are public: this prints collection names and counts only, never document contents or ids.

    python -I tools/firestore_dump.py --project context-484804 --out work/firestore [--no-subcollections]

Credentials: Application Default Credentials (in Actions, google-github-actions/auth sets them; the service account
needs only roles/datastore.viewer).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

API = "https://firestore.googleapis.com/v1"
PAGE = 300
MONTH_RE = re.compile(r"^(\d{4}-\d{2})-\d{2}")


class DumpError(RuntimeError):
    pass


def month_file(doc_id: str) -> str:
    m = MONTH_RE.match(doc_id)
    return m.group(1) if m else "other"


def folder_name(collection_path: str) -> str:
    return collection_path.replace("/", "~")


class Firestore:
    """Firestore over REST. `session` is requests-style (google.auth AuthorizedSession, or a fake in tests)."""

    def __init__(self, project: str, session, database: str = "(default)"):
        self.session = session
        self.root = f"projects/{project}/databases/{database}/documents"

    def _call(self, method: str, url: str, **kw) -> dict:
        r = self.session.request(method, url, timeout=60, **kw)
        if r.status_code != 200:
            raise DumpError(f"Firestore {method} returned HTTP {r.status_code}")
        return r.json()

    def collection_ids(self, parent: str) -> list[str]:
        ids, token = [], None
        while True:
            body = {"pageSize": PAGE}
            if token:
                body["pageToken"] = token
            j = self._call("POST", f"{API}/{parent}:listCollectionIds", json=body)
            ids += j.get("collectionIds", [])
            token = j.get("nextPageToken")
            if not token:
                return sorted(ids)

    def documents(self, parent: str, collection: str):
        token = None
        while True:
            params = {"pageSize": PAGE}
            if token:
                params["pageToken"] = token
            j = self._call("GET", f"{API}/{parent}/{collection}", params=params)
            yield from j.get("documents", [])
            token = j.get("nextPageToken")
            if not token:
                return


def dump(fs: Firestore, out: Path, subcollections: bool = True) -> dict:
    """Write every document under `out`; return {collection path: count}."""
    prefix = fs.root + "/"
    groups: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    counts: dict[str, int] = defaultdict(int)
    queue = [(fs.root, cid) for cid in fs.collection_ids(fs.root)]
    while queue:
        parent, cid = queue.pop(0)
        for doc in fs.documents(parent, cid):
            name = doc["name"]
            if not name.startswith(prefix):
                raise DumpError("a document name is outside the database root")
            rel = name[len(prefix):]
            coll_path, doc_id = rel.rsplit("/", 1)
            line = {"name": rel, "createTime": doc.get("createTime"), "updateTime": doc.get("updateTime"),
                    "fields": doc.get("fields", {})}
            groups[coll_path][month_file(doc_id)].append(line)
            counts[coll_path] += 1
            if subcollections:
                queue += [(name, sub) for sub in fs.collection_ids(name)]
    out.mkdir(parents=True, exist_ok=True)
    for coll_path, months in groups.items():
        d = out / folder_name(coll_path)
        d.mkdir(parents=True, exist_ok=True)
        for month, lines in months.items():
            lines.sort(key=lambda x: x["name"])
            with open(d / f"{month}.jsonl", "w", encoding="utf-8", newline="\n") as f:
                for line in lines:
                    f.write(json.dumps(line, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n")
    summary = {"collections": dict(sorted(counts.items())), "documents": sum(counts.values())}
    (out / "counts.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def check(out: Path) -> dict:
    """Recount a dump folder (a fresh one or a restored one) from its files; raise if counts.json disagrees."""
    summary = json.loads((out / "counts.json").read_text(encoding="utf-8"))
    seen: dict[str, int] = defaultdict(int)
    for f in sorted(out.glob("*/*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for raw in fh:
                rec = json.loads(raw)
                seen[rec["name"].rsplit("/", 1)[0]] += 1
    if dict(sorted(seen.items())) != summary["collections"]:
        raise DumpError("document counts in the files differ from counts.json")
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--project")
    ap.add_argument("--database", default="(default)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-subcollections", action="store_true")
    ap.add_argument("--check-only", action="store_true", help="recount an existing dump folder (after a restore)")
    a = ap.parse_args(argv)
    out = Path(a.out)
    try:
        if a.check_only:
            s = check(out)
            print(f"firestore-dump: check passed, {s['documents']} documents in {len(s['collections'])} collections")
            return 0
        if not a.project:
            raise DumpError("--project is required")
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/datastore"])
        s = dump(Firestore(a.project, AuthorizedSession(creds), a.database), out, not a.no_subcollections)
        check(out)
        for c, n in s["collections"].items():
            print(f"firestore-dump: {c}: {n}")
        print(f"firestore-dump: {s['documents']} documents in {len(s['collections'])} collections")
        return 0
    except DumpError as e:
        print(f"::error::firestore-dump: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
