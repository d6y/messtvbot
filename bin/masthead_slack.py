"""
masthead_slack.py

Slack ingestion for Masthead: pure message-classification and
state-management helpers, plus a thin urllib-based Slack Web API
client. Imported by masthead-refresh.py; also unit-tested directly.
"""
from __future__ import annotations

import html
import json
import logging
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

log = logging.getLogger("masthead.slack")

IMAGE_FILETYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
PDF_FILETYPE = "pdf"
CANCEL_WORDS = ("cancel", "delete", "undo")

# Slack "subtype" values for channel housekeeping events (joins, topic
# changes, pins, edits, ...) rather than actual posted content. These
# carry non-empty "text" but aren't things a person meant to put on the
# display, and Slack won't let a bot thread-reply to most of them anyway.
SYSTEM_SUBTYPES = {
    "channel_join", "channel_leave", "channel_topic", "channel_purpose",
    "channel_name", "channel_archive", "channel_unarchive",
    "group_join", "group_leave", "group_topic", "group_purpose", "group_name",
    "group_archive", "group_unarchive",
    "pinned_item", "unpinned_item", "bot_add", "bot_remove",
    "message_changed", "message_deleted", "message_replied", "thread_broadcast",
    "reminder_add",
}


class SlackAPIError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Pure helpers (no network) -- unit tested directly.
# --------------------------------------------------------------------------

def classify_message(msg: dict) -> str:
    """Return 'attachment', 'text', or 'ignored' for a raw Slack message dict."""
    if msg.get("subtype") in SYSTEM_SUBTYPES:
        return "ignored"
    if extract_attachment(msg) is not None:
        return "attachment"
    if (msg.get("text") or "").strip():
        return "text"
    return "ignored"


def extract_attachment(msg: dict) -> dict | None:
    """Return {'url', 'filetype', 'name'} for the first image/PDF file on
    the message, or None if it has no recognized attachment."""
    for f in msg.get("files", []) or []:
        filetype = (f.get("filetype") or "").lower()
        if filetype in IMAGE_FILETYPES or filetype == PDF_FILETYPE:
            return {
                "url": f.get("url_private_download") or f.get("url_private"),
                "filetype": filetype,
                "name": f.get("name", "file"),
            }
    return None


def is_cancel_reply(text: str) -> bool:
    lowered = (text or "").lower()
    return any(word in lowered for word in CANCEL_WORDS)


def local_filename(ts: str, filetype: str) -> str:
    return f"slack-{ts}.{filetype}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        log.error("Corrupt Slack state file %s: %s -- starting from empty state", path, exc)
        return {}


def save_state(state: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".slack-state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(state, fh, indent=2)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)


def sweep_expired(state: dict, ttl_days: int, now: datetime) -> list[str]:
    """Mark active entries older than ttl_days as 'expired' in place.
    Returns local_files paths whose entries just expired, for the
    caller to delete from disk."""
    cutoff = now - timedelta(days=ttl_days)
    files_to_delete: list[str] = []
    for entry in state.values():
        if entry["status"] != "active":
            continue
        posted_at = datetime.fromisoformat(entry["posted_at"])
        if posted_at < cutoff:
            entry["status"] = "expired"
            files_to_delete.extend(entry.get("local_files", []))
    return files_to_delete


def sorted_active_entries(state: dict) -> list[tuple[str, dict]]:
    """Active entries as (ts, entry) pairs, oldest posted_at first."""
    active = [(ts, entry) for ts, entry in state.items() if entry["status"] == "active"]
    active.sort(key=lambda pair: pair[1]["posted_at"])
    return active


# --------------------------------------------------------------------------
# Slack Web API client and poll orchestration.
# --------------------------------------------------------------------------

@dataclass
class SlackConfig:
    token: str
    channel: str
    ttl_days: int


class SlackAPI(Protocol):
    def history(self, channel: str, oldest: str) -> list[dict]: ...
    def replies(self, channel: str, thread_ts: str) -> list[dict]: ...
    def user_name(self, user_id: str) -> str: ...
    def download(self, url: str, dest_path: Path) -> None: ...
    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> None: ...


class SlackWebAPI:
    """urllib-based Slack Web API client. No pip dependencies."""

    BASE_URL = "https://slack.com/api/"

    def __init__(self, token: str):
        self.token = token
        self._user_cache: dict[str, str] = {}

    def _call(self, method: str, params: dict) -> dict:
        url = self.BASE_URL + method
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read())
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise SlackAPIError(f"{method} request failed: {exc}") from exc
        if not payload.get("ok"):
            raise SlackAPIError(f"{method} failed: {payload.get('error')}")
        return payload

    def history(self, channel: str, oldest: str) -> list[dict]:
        messages: list[dict] = []
        cursor = ""
        while True:
            params = {"channel": channel, "oldest": oldest, "limit": "200"}
            if cursor:
                params["cursor"] = cursor
            payload = self._call("conversations.history", params)
            messages.extend(payload.get("messages", []))
            cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
        return messages

    def replies(self, channel: str, thread_ts: str) -> list[dict]:
        payload = self._call("conversations.replies", {"channel": channel, "ts": thread_ts})
        return payload.get("messages", [])[1:]  # first item is the parent message itself

    def user_name(self, user_id: str) -> str:
        if user_id in self._user_cache:
            return self._user_cache[user_id]
        payload = self._call("users.info", {"user": user_id})
        user = payload.get("user", {})
        name = user.get("real_name") or user.get("name") or user_id
        self._user_cache[user_id] = name
        return name

    def download(self, url: str, dest_path: Path) -> None:
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
        except (urllib.error.URLError, OSError) as exc:
            raise SlackAPIError(f"download failed: {exc}") from exc
        Path(dest_path).write_bytes(data)

    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> None:
        params = {"channel": channel, "text": text}
        if thread_ts:
            params["thread_ts"] = thread_ts
        self._call("chat.postMessage", params)


def _post_safe(api: SlackAPI, channel: str, text: str, thread_ts: str | None = None) -> None:
    """post_message wrapper that never raises -- a failed acknowledgement
    shouldn't break the poll tick."""
    try:
        api.post_message(channel, text, thread_ts=thread_ts)
    except SlackAPIError as exc:
        log.error("Failed to post Slack acknowledgement: %s", exc)


def _describe_entry(entry: dict) -> str:
    if entry["kind"] == "text":
        text = entry.get("text", "")
        return text if len(text) <= 80 else text[:77] + "..."
    if entry.get("local_files"):
        return Path(entry["local_files"][0]).name
    return "attachment"


def poll_slack(cfg: SlackConfig, state: dict, source_dir: Path, now: datetime, api: SlackAPI) -> dict:
    """One polling tick: fetch new messages, ingest them, check active
    entries for cancel replies, sweep expirations. Mutates and returns
    `state`. Never raises on API failures -- logs and returns state
    unchanged so a bad tick doesn't blank the display."""
    newest_ts = max((ts for ts in state), default=None)
    oldest = newest_ts if newest_ts else str((now - timedelta(days=cfg.ttl_days)).timestamp())

    try:
        messages = api.history(cfg.channel, oldest)
    except SlackAPIError as exc:
        log.error("Slack history fetch failed: %s", exc)
        return state

    pre_existing_ts = set(state)

    for msg in messages:
        ts = msg.get("ts")
        if not ts or ts in state:
            continue
        kind = classify_message(msg)
        if kind == "ignored":
            log.info("Ignoring Slack message %s: no recognized content", ts)
            continue

        posted_at = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat(timespec="seconds")
        if msg.get("user"):
            try:
                author = api.user_name(msg["user"])
            except SlackAPIError as exc:
                log.error("Failed to resolve Slack user name for %s: %s", msg["user"], exc)
                author = msg["user"]
        else:
            author = "Unknown"
        entry = {
            "ts": ts, "posted_at": posted_at, "status": "active", "kind": kind,
            "text": "", "author": author, "local_files": [],
        }

        if kind == "attachment":
            attachment = extract_attachment(msg)
            dest = source_dir / local_filename(ts, attachment["filetype"])
            try:
                api.download(attachment["url"], dest)
            except SlackAPIError as exc:
                log.error("Failed to download Slack attachment for %s: %s", ts, exc)
                entry["status"] = "failed"
                state[ts] = entry
                continue
            entry["local_files"] = [str(dest)]
        else:
            entry["text"] = html.unescape(msg.get("text", ""))

        state[ts] = entry
        _post_safe(api, cfg.channel, "Added to the display.", thread_ts=ts)

    for ts, entry in state.items():
        if entry["status"] != "active":
            continue
        try:
            replies = api.replies(cfg.channel, ts)
        except SlackAPIError as exc:
            log.error("Failed to fetch replies for %s: %s", ts, exc)
            continue
        if any(is_cancel_reply(r.get("text", "")) for r in replies):
            entry["status"] = "cancelled"
            for f in entry.get("local_files", []):
                Path(f).unlink(missing_ok=True)
            _post_safe(api, cfg.channel, "Removed from the display.", thread_ts=ts)

    # Only sweep entries that existed before this tick: a message's `ts` is
    # its real Slack post time, but `history()` is queried with `oldest` set
    # to the TTL cutoff, so a message freshly ingested this tick can never
    # actually be older than the TTL in production. Excluding just-added
    # entries here avoids any accidental same-tick expiry from a
    # clock/timestamp mismatch.
    sweep_target = {ts: entry for ts, entry in state.items() if ts in pre_existing_ts}
    previously_active = {ts for ts, entry in sweep_target.items() if entry["status"] == "active"}
    expired_files = sweep_expired(sweep_target, cfg.ttl_days, now)
    for f in expired_files:
        Path(f).unlink(missing_ok=True)
    for ts in previously_active:
        entry = sweep_target[ts]
        if entry["status"] != "expired":
            continue
        _post_safe(
            api, cfg.channel,
            f'I\'ve removed: "{_describe_entry(entry)}" by {entry["author"]} '
            f"(expired after {cfg.ttl_days} days)",
        )

    return state
