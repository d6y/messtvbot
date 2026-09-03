import json
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import masthead_slack as ms
import importlib
admin = importlib.import_module("masthead-admin-server")


def _entry(status="active", remove_at="2026-12-31T00:00:00+00:00"):
    return {"status": status, "kind": "text", "text": "Pizza!", "author": "Jane",
            "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": remove_at,
            "remove_reason": "ttl", "local_files": []}


class AdminServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.masthead_dir = self.tmp_dir / "masthead-data"
        (self.masthead_dir).mkdir()
        self.state_path = self.masthead_dir / "data" / "slack-state.json"
        self.audit_path = self.masthead_dir / "data" / "audit.jsonl"
        ms.save_state({"100.1": _entry()}, self.state_path)

        handler_cls = admin.make_handler(self.masthead_dir, self.state_path, self.audit_path)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}") as resp:
            return resp.status, json.loads(resp.read())

    def _post(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method="POST", data=b"")
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def test_get_entries_lists_active_entry(self):
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 1)
        self.assertEqual(body[0]["ts"], "100.1")
        self.assertEqual(body[0]["author"], "Jane")
        self.assertEqual(body[0]["remove_at"], "2026-12-31T00:00:00+00:00")

    def test_get_entries_excludes_non_active(self):
        ms.save_state({"100.1": _entry(status="cancelled")}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(body, [])

    def test_post_remove_cancels_the_entry(self):
        status, body = self._post("/api/entries/100.1/remove")
        self.assertEqual(status, 200)
        state = ms.load_state(self.state_path)
        self.assertEqual(state["100.1"]["status"], "cancelled")

    def test_post_remove_writes_an_audit_line(self):
        self._post("/api/entries/100.1/remove")
        lines = self.audit_path.read_text().splitlines()
        self.assertEqual(len(lines), 1)
        event = json.loads(lines[0])
        self.assertEqual(event["action"], "removed")
        self.assertEqual(event["author"], "admin-ui")

    def test_post_remove_unknown_ts_returns_404(self):
        status, _ = self._post("/api/entries/no-such-ts/remove")
        self.assertEqual(status, 404)

    def test_post_remove_already_cancelled_entry_returns_404(self):
        ms.save_state({"100.1": _entry(status="cancelled")}, self.state_path)
        status, _ = self._post("/api/entries/100.1/remove")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
