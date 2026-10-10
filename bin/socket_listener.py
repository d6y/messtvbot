#!/usr/bin/env python3
"""
socket_listener.py

Real-time Slack ingestion for Mess TV Bot: connects to Slack's Socket Mode
websocket and reacts to new messages/replies the moment they arrive,
instead of waiting for the next polling tick. A periodic reconciliation
pass (the same bulk slack_source.poll_slack used by refresh.py) keeps
running underneath it to catch anything missed during a disconnect and to
handle TTL expiry/sweeps, which single real-time events never check for.

This is the production ingestion path (see systemd/kiosk-socket.service).
refresh.py remains available as a manual/debug entrypoint -- e.g. rebuilding
the manifest from a hand-edited slack-state.json fixture, or a one-off real
poll -- but is no longer run on a timer in production.

All actual Slack REST calls (history, replies, download, post_message,
user_name) go through the existing slack_source.SlackWebAPI; slack_sdk is
used here only for the Socket Mode websocket connection itself. The
message-processing logic (ingest_message/apply_reply_command/
handle_realtime_event in slack_source.py, build_and_write_manifest in
refresh.py) is shared with refresh.py -- don't duplicate it here.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

import refresh
import slack_source

log = logging.getLogger("kiosk.socket")

DEFAULT_RECONCILE_SECONDS = 300

# slack_sdk dispatches Socket Mode request listeners on its own thread pool,
# so a real-time event and the reconciliation thread (or two real-time
# events) can enter handle_event_envelope/reconcile concurrently.
# state_lock (a flock) only serializes the load/mutate/save of
# slack-state.json -- it's released before rendering/writing the manifest,
# so without this lock two overlapping passes could render with stale state,
# write manifest.json out of order, or race on rendered/<stem> cleanup
# (cleanup_stale_renders deletes directories a concurrent pass is still
# populating). This lock serializes the whole load-through-render sequence
# in-process instead.
render_lock = threading.Lock()


def load_app_token() -> str:
    app_token = os.environ.get("KIOSK_SLACK_APP_TOKEN", "").strip()
    if not app_token:
        log.error("KIOSK_SLACK_APP_TOKEN must be set to run socket_listener.py "
                   "(the xapp-... app-level token -- see docs/SETUP.md).")
        sys.exit(2)
    return app_token


def build_slack_cfg(cfg: refresh.Config, bot_user_id: str) -> slack_source.SlackConfig:
    return slack_source.SlackConfig(
        cfg.slack_token, cfg.slack_channel, cfg.slack_ttl_days, bot_user_id,
        server_url=cfg.server_url, admin_contact=cfg.admin_contact, max_images=cfg.max_images,
        max_attachment_bytes=cfg.max_attachment_mb * 1024 * 1024,
    )


def handle_event_envelope(cfg: refresh.Config, slack_cfg: slack_source.SlackConfig, state_path: Path,
                           source_dir: Path, audit_path: Path, event: dict, api: slack_source.SlackAPI) -> None:
    """Process one Slack `message` event under the state lock, and rebuild
    the manifest immediately if it changed anything. The route-independent
    logic itself lives in slack_source.handle_realtime_event -- this is
    just the state-lock/load/save/manifest-rebuild wiring around it."""
    now = datetime.now(timezone.utc)
    with render_lock:
        with slack_source.state_lock(state_path):
            state = slack_source.load_state(state_path)
            changed = slack_source.handle_realtime_event(
                slack_cfg, state, source_dir, event, now, api, audit_path,
            )
            if changed:
                slack_source.save_state(state, state_path)
        if changed:
            refresh.build_and_write_manifest(cfg, state)


def reconcile(cfg: refresh.Config, slack_cfg: slack_source.SlackConfig, state_path: Path,
              source_dir: Path, audit_path: Path, api: slack_source.SlackAPI) -> None:
    """One full bulk-poll reconciliation pass -- same mechanism refresh.py
    uses for its manual runs. Catches anything Socket Mode missed (a
    disconnect) and handles TTL expiry/sweeps."""
    now = datetime.now(timezone.utc)
    with render_lock:
        with slack_source.state_lock(state_path):
            state = slack_source.load_state(state_path)
            state = slack_source.poll_slack(slack_cfg, state, source_dir, now, api, audit_path=audit_path)
            slack_source.save_state(state, state_path)
        refresh.build_and_write_manifest(cfg, state)


def reconciliation_loop(interval_seconds: float, stop_event: threading.Event, *reconcile_args) -> None:
    """Runs `reconcile(*reconcile_args)` every `interval_seconds` until
    `stop_event` is set. A failed pass is logged and retried next interval
    rather than killing the background thread."""
    while not stop_event.wait(interval_seconds):
        try:
            reconcile(*reconcile_args)
        except Exception:  # noqa: BLE001 -- never let the background loop die
            log.exception("Reconciliation pass failed")


def make_request_listener(cfg: refresh.Config, slack_cfg: slack_source.SlackConfig, state_path: Path,
                           source_dir: Path, audit_path: Path, api: slack_source.SlackAPI):
    """Builds the slack_sdk SocketModeClient request listener: acks every
    events_api envelope immediately (required by Slack's Socket Mode
    protocol), then hands the event off to handle_event_envelope."""
    def process(client: SocketModeClient, req: SocketModeRequest) -> None:
        if req.type != "events_api":
            return
        client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        event = req.payload.get("event", {})
        if event.get("type") != "message":
            return
        if event.get("channel") != slack_cfg.channel:
            return
        try:
            handle_event_envelope(cfg, slack_cfg, state_path, source_dir, audit_path, event, api)
        except Exception:  # noqa: BLE001 -- one bad event must never kill the connection
            log.exception("Failed to handle real-time event %s", event.get("ts"))

    return process


def main(argv: list[str]) -> int:
    logging.basicConfig(
        level=os.environ.get("KIOSK_LOG_LEVEL", "INFO"),
        format="%(asctime)s kiosk-socket %(levelname)s: %(message)s",
    )
    cfg = refresh.load_config(argv)
    app_token = load_app_token()
    refresh.ensure_dirs(cfg)
    refresh.copy_site_assets(cfg.repo_dir, cfg.kiosk_dir)

    state_path = cfg.data_dir / "slack-state.json"
    audit_path = cfg.data_dir / "audit.jsonl"
    reconcile_seconds = int(os.environ.get("KIOSK_RECONCILE_SECONDS", str(DEFAULT_RECONCILE_SECONDS)))

    api = slack_source.SlackWebAPI(cfg.slack_token)
    try:
        bot_user_id = api.auth_test()
    except slack_source.SlackAPIError as exc:
        log.error("Failed to resolve bot's own user ID (auth.test): %s -- "
                   "bot messages won't be excluded from ingestion", exc)
        bot_user_id = ""
    slack_cfg = build_slack_cfg(cfg, bot_user_id)
    reconcile_args = (cfg, slack_cfg, state_path, cfg.source_dir, audit_path, api)

    log.info("Running initial reconciliation pass before going live")
    reconcile(*reconcile_args)

    stop_event = threading.Event()
    reconciler = threading.Thread(
        target=reconciliation_loop, args=(reconcile_seconds, stop_event, *reconcile_args), daemon=True,
    )
    reconciler.start()

    web_client = WebClient(token=cfg.slack_token)
    client = SocketModeClient(app_token=app_token, web_client=web_client)
    client.socket_mode_request_listeners.append(
        make_request_listener(cfg, slack_cfg, state_path, cfg.source_dir, audit_path, api)
    )

    log.info("Connecting to Slack Socket Mode")
    client.connect()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        stop_event.set()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
