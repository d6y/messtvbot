#!/usr/bin/env python3
"""
admin_server.py

Serves the Mess TV Bot site (same static files serve.sh used to
serve via `python -m http.server`) plus two small JSON endpoints backed
directly by slack-state.json, for the no-auth admin page at /admin/:

  GET  /api/entries              -- active entries, oldest first
  POST /api/entries/<ts>/remove  -- immediately remove one entry

Runs as a long-lived process (systemd service / launchd agent), separate
from refresh.py's periodic tick. Both processes write
slack-state.json, guarded by slack_source.state_lock.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import slack_source as ms


def _requires_auth(path: str) -> bool:
    return path == "/admin" or path.startswith("/admin/") or path.startswith("/api/")


def _thumb_path(kiosk_dir: Path, entry: dict) -> str | None:
    """Path (relative to kiosk_dir, servable as-is) to a thumbnail image
    for this entry, or None if there isn't one (text entries, or a PDF
    that hasn't been rendered yet)."""
    if entry.get("kind") != "attachment" or not entry.get("local_files"):
        return None
    file_path = Path(entry["local_files"][0])
    filetype = file_path.suffix.lstrip(".").lower()
    if filetype in ms.IMAGE_FILETYPES:
        candidate = file_path
    elif filetype == ms.PDF_FILETYPE:
        candidate = kiosk_dir / "rendered" / file_path.stem / "page-1.png"
    else:
        return None
    if not candidate.exists():
        return None
    try:
        return candidate.relative_to(kiosk_dir).as_posix()
    except ValueError:
        return None


def make_handler(kiosk_dir: Path, state_path: Path, audit_path: Path,
                  admin_user: str | None = None, admin_pass: str | None = None):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(kiosk_dir), **kwargs)

        def log_message(self, fmt, *args):
            pass  # quiet; errors still surface via send_error/exceptions

        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _unauthorized(self) -> None:
            body = b"Authentication required"
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="messtvbot admin"')
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if not admin_user:
                return True  # no credentials configured -- auth disabled
            header = self.headers.get("Authorization", "")
            if not header.startswith("Basic "):
                return False
            try:
                decoded = base64.b64decode(header[len("Basic "):]).decode()
                user, _, password = decoded.partition(":")
            except (ValueError, UnicodeDecodeError):
                return False
            return hmac.compare_digest(user, admin_user) and hmac.compare_digest(password, admin_pass or "")

        def do_GET(self):
            if _requires_auth(self.path.split("?", 1)[0]) and not self._authorized():
                self._unauthorized()
                return
            if self.path == "/api/entries":
                # Unlocked read: save_state writes atomically (temp file +
                # os.replace), so a concurrent reader always sees either the
                # whole old file or the whole new one, never a torn write.
                # Taking the lock here would block this read behind the
                # refresh tick's Slack network I/O.
                state = ms.load_state(state_path)
                entries = [
                    {
                        "ts": ts, "kind": entry["kind"], "author": entry["author"],
                        "posted_at": entry["posted_at"], "remove_at": entry.get("remove_at"),
                        "summary": ms._describe_entry(entry),
                        "thumb": _thumb_path(kiosk_dir, entry),
                    }
                    for ts, entry in ms.sorted_active_entries(state)
                ]
                self._json(200, entries)
                return
            super().do_GET()

        def do_POST(self):
            if _requires_auth(self.path.split("?", 1)[0]) and not self._authorized():
                self._unauthorized()
                return
            prefix, suffix = "/api/entries/", "/remove"
            if self.path.startswith(prefix) and self.path.endswith(suffix):
                ts = self.path[len(prefix):-len(suffix)]
                with ms.state_lock(state_path):
                    state = ms.load_state(state_path)
                    entry = state.get(ts)
                    if entry is None or entry["status"] != "active":
                        self._json(404, {"error": "not found"})
                        return
                    entry["status"] = "cancelled"
                    entry["remove_reason"] = "admin"
                    for f in entry.get("local_files", []):
                        Path(f).unlink(missing_ok=True)
                    ms.save_state(state, state_path)
                ms.append_audit(audit_path, {
                    "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "ts": ts, "author": "admin-ui", "kind": "command",
                    "action": "removed", "summary": "removed via admin UI",
                })
                self._json(200, {"status": "cancelled"})
                return
            self.send_error(404)

    return Handler


def main() -> int:
    kiosk_dir = Path(os.path.expandvars(os.environ.get("KIOSK_DIR", "~/kiosk-data"))).expanduser()
    port = int(os.environ.get("KIOSK_PORT", "8420"))
    bind_host = os.environ.get("KIOSK_BIND_HOST", "127.0.0.1")
    admin_user = os.environ.get("ADMIN_USER", "").strip()
    admin_pass = os.environ.get("ADMIN_PASS", "")
    state_path = kiosk_dir / "data" / "slack-state.json"
    audit_path = kiosk_dir / "data" / "audit.jsonl"

    if bind_host != "127.0.0.1" and not admin_user:
        print(
            "kiosk-admin-server: WARNING -- KIOSK_BIND_HOST is not 127.0.0.1 but "
            "ADMIN_USER/ADMIN_PASS aren't set, so /admin and /api are open to "
            "anyone who can reach this host.",
            file=sys.stderr,
        )

    handler_cls = make_handler(kiosk_dir, state_path, audit_path, admin_user or None, admin_pass)
    server = ThreadingHTTPServer((bind_host, port), handler_cls)
    print(f"kiosk-admin-server: serving {kiosk_dir} on http://{bind_host}:{port}/ (admin at /admin/)")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
