#!/usr/bin/env python3
"""
masthead-admin-server.py

Serves the Masthead site (same static files masthead-serve.sh used to
serve via `python -m http.server`) plus two small JSON endpoints backed
directly by slack-state.json, for the no-auth admin page at /admin/:

  GET  /api/entries              -- active entries, oldest first
  POST /api/entries/<ts>/remove  -- immediately remove one entry

Runs as a long-lived process (systemd service / launchd agent), separate
from masthead-refresh.py's periodic tick. Both processes write
slack-state.json, guarded by masthead_slack.state_lock.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import masthead_slack as ms


def make_handler(masthead_dir: Path, state_path: Path, audit_path: Path):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(masthead_dir), **kwargs)

        def log_message(self, fmt, *args):
            pass  # quiet; errors still surface via send_error/exceptions

        def _json(self, status: int, payload) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/entries":
                with ms.state_lock(state_path):
                    state = ms.load_state(state_path)
                entries = [
                    {
                        "ts": ts, "kind": entry["kind"], "author": entry["author"],
                        "posted_at": entry["posted_at"], "remove_at": entry.get("remove_at"),
                        "summary": ms._describe_entry(entry),
                    }
                    for ts, entry in ms.sorted_active_entries(state)
                ]
                self._json(200, entries)
                return
            super().do_GET()

        def do_POST(self):
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
    masthead_dir = Path(os.path.expandvars(os.environ.get("MASTHEAD_DIR", "~/masthead-data"))).expanduser()
    port = int(os.environ.get("MASTHEAD_PORT", "8420"))
    state_path = masthead_dir / "data" / "slack-state.json"
    audit_path = masthead_dir / "data" / "audit.jsonl"

    handler_cls = make_handler(masthead_dir, state_path, audit_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    print(f"masthead-admin-server: serving {masthead_dir} on http://127.0.0.1:{port}/ (admin at /admin/)")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
