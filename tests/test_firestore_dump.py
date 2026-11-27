"""tools/firestore_dump.py: paging, subcollections, month files, stable bytes and the recount check."""
import json
import tempfile
import unittest
from pathlib import Path

from tools import firestore_dump as fd

ROOT = "projects/p/databases/(default)/documents"


class Resp:
    def __init__(self, body, code=200):
        self.status_code, self._b = code, body

    def json(self):
        return self._b


class FakeSession:
    """Two root collections; `snapshots` pages in two; one document has a subcollection."""

    def __init__(self):
        self.calls = 0

    def request(self, method, url, timeout=None, json=None, params=None):
        self.calls += 1
        path = url.split("/v1/", 1)[1]
        if method == "POST":
            parent = path[: -len(":listCollectionIds")]
            if parent == ROOT:
                return Resp({"collectionIds": ["snapshots", "mc_state"]})
            if parent == f"{ROOT}/mc_state/ingest":
                return Resp({"collectionIds": ["parts"]})
            return Resp({})
        token = (params or {}).get("pageToken")
        if path == f"{ROOT}/snapshots":
            if not token:
                return Resp({"documents": [self.doc("snapshots/2026-11-02_0000Z_01"),
                                           self.doc("snapshots/2026-10-30_1200Z_01")], "nextPageToken": "t"})
            return Resp({"documents": [self.doc("snapshots/2026-11-01_0000Z_02")]})
        if path == f"{ROOT}/mc_state":
            return Resp({"documents": [self.doc("mc_state/ingest")]})
        if path == f"{ROOT}/mc_state/ingest/parts":
            return Resp({"documents": [self.doc("mc_state/ingest/parts/1")]})
        return Resp({}, 404)

    @staticmethod
    def doc(rel):
        return {"name": f"{ROOT}/{rel}", "createTime": "2026-11-01T00:00:00Z", "updateTime": "2026-11-01T00:00:00Z",
                "fields": {"v": {"stringValue": rel}, "b": {"bytesValue": "AAE="}}}


class ContextSession(FakeSession):
    """Context's live pages: `current_data/_metadata` is a document, `current_data/regional` is not (only its
    `entities` subcollection is written), so Firestore lists `regional` only when showMissing is sent."""

    def request(self, method, url, timeout=None, json=None, params=None):
        self.calls += 1
        path = url.split("/v1/", 1)[1]
        if method == "POST":
            parent = path[: -len(":listCollectionIds")]
            if parent == ROOT:
                return Resp({"collectionIds": ["current_data"]})
            if parent == f"{ROOT}/current_data/regional":
                return Resp({"collectionIds": ["entities"]})
            return Resp({})
        if path == f"{ROOT}/current_data":
            docs = [self.doc("current_data/_metadata")]
            if (params or {}).get("showMissing") == "true":
                docs.append({"name": f"{ROOT}/current_data/regional"})
            return Resp({"documents": docs})
        if path == f"{ROOT}/current_data/regional/entities":
            return Resp({"documents": [self.doc("current_data/regional/entities/Sudan"),
                                       self.doc("current_data/regional/entities/Myanmar")]})
        return Resp({}, 404)


class DumpTest(unittest.TestCase):
    def run_dump(self, out):
        return fd.dump(fd.Firestore("p", FakeSession()), out)

    def test_dump_layout_and_counts(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            s = self.run_dump(out)
            self.assertEqual(s["documents"], 5)
            self.assertEqual(s["collections"], {"mc_state": 1, "mc_state/ingest/parts": 1, "snapshots": 3})
            self.assertEqual(sorted(p.name for p in (out / "snapshots").iterdir()), ["2026-10.jsonl", "2026-11.jsonl"])
            self.assertTrue((out / "mc_state~ingest~parts" / "other.jsonl").exists())
            nov = (out / "snapshots" / "2026-11.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(x)["name"] for x in nov],
                             ["snapshots/2026-11-01_0000Z_02", "snapshots/2026-11-02_0000Z_01"])
            self.assertEqual(json.loads(nov[0])["fields"]["b"], {"bytesValue": "AAE="})
            self.assertEqual(fd.check(out)["documents"], 5)

    def test_same_data_same_bytes(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.run_dump(Path(a))
            self.run_dump(Path(b))
            for f in sorted(Path(a).rglob("*.jsonl")):
                self.assertEqual(f.read_bytes(), (Path(b) / f.relative_to(a)).read_bytes())

    def test_check_catches_a_lost_line(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            self.run_dump(out)
            f = out / "snapshots" / "2026-11.jsonl"
            f.write_text(f.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
            with self.assertRaises(fd.DumpError):
                fd.check(out)

    def test_http_error_stops(self):
        class Bad:
            def request(self, *a, **k):
                return Resp({}, 403)
        with tempfile.TemporaryDirectory() as t, self.assertRaises(fd.DumpError):
            fd.dump(fd.Firestore("p", Bad()), Path(t))

    def test_subcollection_under_a_missing_parent(self):
        with tempfile.TemporaryDirectory() as t:
            out = Path(t)
            s = fd.dump(fd.Firestore("p", ContextSession()), out)
            self.assertEqual(s["collections"], {"current_data": 1, "current_data/regional/entities": 2})
            self.assertEqual(s["documents"], 3)
            self.assertEqual(s["missing_parents"], 1)
            # The missing parent itself is not written as a document
            meta = (out / "current_data" / "other.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(x)["name"] for x in meta], ["current_data/_metadata"])
            ents = (out / "current_data~regional~entities" / "other.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual([json.loads(x)["name"] for x in ents],
                             ["current_data/regional/entities/Myanmar", "current_data/regional/entities/Sudan"])
            self.assertEqual(fd.check(out)["documents"], 3)

    def test_month_file(self):
        self.assertEqual(fd.month_file("2026-01-19_1200Z_04_Iran"), "2026-01")
        self.assertEqual(fd.month_file("ingest"), "other")


class WeeklyBackupWorkflowTest(unittest.TestCase):
    def test_bucket_listing_comes_before_the_copy(self):
        # Copying first fails the week whenever an object is written between the copy and the listing
        wf = (Path(__file__).resolve().parents[1] / ".github" / "workflows" / "weekly-backup.yml").read_text(
            encoding="utf-8")
        listing = wf.index('gcloud storage objects list "gs://more-context-484804/**"')
        copy = wf.index('gcloud storage cp -r --do-not-decompress')
        self.assertLess(listing, copy)


if __name__ == "__main__":
    unittest.main()
