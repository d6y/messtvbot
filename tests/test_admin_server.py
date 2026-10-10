import base64
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
import refresh
import slack_source as ms
import importlib
admin = importlib.import_module("admin_server")


def _cfg(kiosk_dir, tmp_dir):
    return refresh.Config(
        slack_token="xoxb-test", slack_channel="C1", slack_ttl_days=30,
        kiosk_dir=kiosk_dir, repo_dir=tmp_dir, render_width=1920,
        slide_seconds=8, poll_seconds=30, skip_slack_poll=True,
        server_url="http://localhost:8420", admin_contact="@richard",
        max_images=6, max_pdf_pages=15, max_attachment_mb=25,
    )


def _entry(status="active", remove_at="2026-12-31T00:00:00+00:00"):
    return {"status": status, "kind": "text", "text": "Pizza!", "author": "Jane",
            "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": remove_at,
            "remove_reason": "ttl", "local_files": []}


class AdminServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.kiosk_dir = self.tmp_dir / "kiosk-data"
        (self.kiosk_dir).mkdir()
        self.state_path = self.kiosk_dir / "data" / "slack-state.json"
        self.audit_path = self.kiosk_dir / "data" / "audit.jsonl"
        ms.save_state({"100.1": _entry()}, self.state_path)

        handler_cls = admin.make_handler(
            self.kiosk_dir, self.state_path, self.audit_path, _cfg(self.kiosk_dir, self.tmp_dir),
        )
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

    def test_get_entries_text_entry_has_no_thumbnail(self):
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertIsNone(body[0]["thumb"])

    def test_get_entries_image_entry_has_thumbnail_path(self):
        image_path = self.kiosk_dir / "source" / "slack-100.2.png"
        image_path.parent.mkdir(parents=True)
        image_path.write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(image_path)]}
        ms.save_state({"100.2": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["thumb"], "source/slack-100.2.png")

    def test_get_entries_pdf_entry_has_rendered_first_page_as_thumbnail(self):
        pdf_path = self.kiosk_dir / "source" / "slack-100.3.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        page_path = self.kiosk_dir / "rendered" / "slack-100.3" / "page-1.png"
        page_path.parent.mkdir(parents=True)
        page_path.write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(pdf_path)]}
        ms.save_state({"100.3": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["thumb"], "rendered/slack-100.3/page-1.png")

    def test_get_entries_pdf_with_zero_padded_page_names_has_first_page_as_thumbnail(self):
        # Regression: pdftoppm zero-pads page numbers to the document's
        # total page count once a PDF has 10+ pages (page-01.png, not
        # page-1.png) -- a hardcoded "page-1.png" lookup silently finds
        # nothing and the admin row shows no thumbnail at all.
        pdf_path = self.kiosk_dir / "source" / "slack-100.5.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        render_dir = self.kiosk_dir / "rendered" / "slack-100.5"
        render_dir.mkdir(parents=True)
        for n in range(1, 13):
            (render_dir / f"page-{n:02d}.png").write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(pdf_path)]}
        ms.save_state({"100.5": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["thumb"], "rendered/slack-100.5/page-01.png")

    def test_get_entries_heic_entry_has_converted_jpg_as_thumbnail(self):
        heic_path = self.kiosk_dir / "source" / "slack-100.4.heic"
        heic_path.parent.mkdir(parents=True)
        heic_path.write_bytes(b"x")
        jpg_path = self.kiosk_dir / "rendered" / "heic" / "slack-100.4.jpg"
        jpg_path.parent.mkdir(parents=True)
        jpg_path.write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(heic_path)]}
        ms.save_state({"100.4": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertEqual(body[0]["thumb"], "rendered/heic/slack-100.4.jpg")

    def test_get_entries_heic_entry_without_conversion_has_no_thumbnail(self):
        heic_path = self.kiosk_dir / "source" / "slack-100.5.heic"
        heic_path.parent.mkdir(parents=True)
        heic_path.write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(heic_path)]}
        ms.save_state({"100.5": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertIsNone(body[0]["thumb"])

    def test_get_entries_pdf_entry_without_rendered_page_has_no_thumbnail(self):
        pdf_path = self.kiosk_dir / "source" / "slack-100.4.pdf"
        pdf_path.parent.mkdir(parents=True)
        pdf_path.write_bytes(b"x")
        entry = {"status": "active", "kind": "attachment", "text": "", "author": "Jane",
                  "posted_at": "2026-08-01T00:00:00+00:00", "remove_at": "2026-12-31T00:00:00+00:00",
                  "remove_reason": "ttl", "local_files": [str(pdf_path)]}
        ms.save_state({"100.4": entry}, self.state_path)
        status, body = self._get("/api/entries")
        self.assertEqual(status, 200)
        self.assertIsNone(body[0]["thumb"])

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

    def test_post_remove_rebuilds_manifest_immediately(self):
        # Nothing else is running a timer anymore (socket_listener.py's
        # reconciliation pass can be minutes away) -- the admin UI must
        # trigger its own manifest rebuild so a removal doesn't sit on
        # screen waiting for that.
        self._post("/api/entries/100.1/remove")
        manifest = json.loads((self.kiosk_dir / "data" / "manifest.json").read_text())
        self.assertEqual(manifest["items"], [])

    def test_post_remove_unknown_ts_returns_404(self):
        status, _ = self._post("/api/entries/no-such-ts/remove")
        self.assertEqual(status, 404)

    def test_post_remove_already_cancelled_entry_returns_404(self):
        ms.save_state({"100.1": _entry(status="cancelled")}, self.state_path)
        status, _ = self._post("/api/entries/100.1/remove")
        self.assertEqual(status, 404)


class AdminServerAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.kiosk_dir = self.tmp_dir / "kiosk-data"
        self.kiosk_dir.mkdir()
        (self.kiosk_dir / "index.html").write_text("<html>slideshow</html>")
        self.state_path = self.kiosk_dir / "data" / "slack-state.json"
        self.audit_path = self.kiosk_dir / "data" / "audit.jsonl"
        ms.save_state({"100.1": _entry()}, self.state_path)

        handler_cls = admin.make_handler(
            self.kiosk_dir, self.state_path, self.audit_path, _cfg(self.kiosk_dir, self.tmp_dir),
            admin_user="alice", admin_pass="secret",
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _auth_header(self, user, password):
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        return {"Authorization": f"Basic {token}"}

    def _get(self, path, headers=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, exc.read()

    def test_api_without_credentials_is_rejected(self):
        status, _ = self._get("/api/entries")
        self.assertEqual(status, 401)

    def test_admin_page_without_credentials_is_rejected(self):
        status, _ = self._get("/admin/")
        self.assertEqual(status, 401)

    def test_api_with_wrong_password_is_rejected(self):
        status, _ = self._get("/api/entries", self._auth_header("alice", "wrong"))
        self.assertEqual(status, 401)

    def test_api_with_correct_credentials_is_allowed(self):
        status, body = self._get("/api/entries", self._auth_header("alice", "secret"))
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)[0]["ts"], "100.1")

    def test_slideshow_root_never_requires_auth(self):
        status, _ = self._get("/")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
