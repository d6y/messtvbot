"""
slack_source.py

Slack ingestion for Mess TV Bot: pure message-classification and
state-management helpers, plus a thin urllib-based Slack Web API
client. Imported by refresh.py; also unit-tested directly.
"""
from __future__ import annotations

import dateparser
import emoji
import fcntl
import html
import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo

log = logging.getLogger("kiosk.slack")

IMAGE_FILETYPES = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}
PDF_FILETYPE = "pdf"
COMMAND_WORDS = ("cancel", "delete", "undo", "remove")

# A short new top-level message starting with "help" or "remove" is almost
# certainly someone testing the bot or confused about how to remove a post,
# not content meant for the display -- see is_help_trigger().
HELP_TRIGGER_RE = re.compile(r"^(help|remove)\b", re.IGNORECASE)
HELP_TRIGGER_MAX_LEN = 30

# Dates/times shown to humans (Slack messages) are always in this zone,
# switching between GMT/BST automatically -- everything is still stored
# internally as UTC-aware datetimes/ISO strings.
LOCAL_TZ = ZoneInfo("Europe/London")

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

def classify_message(msg: dict, bot_user_id: str = "") -> str:
    """Return 'attachment', 'text', or 'ignored' for a raw Slack message dict."""
    if msg.get("bot_id"):
        return "ignored"
    if bot_user_id and msg.get("user") == bot_user_id:
        return "ignored"
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
    attachments = extract_attachments(msg)
    return attachments[0] if attachments else None


def extract_attachments(msg: dict) -> list[dict]:
    """Return {'url', 'filetype', 'name'} for every image/PDF file on the
    message, in Slack's own order. Empty list if it has none."""
    attachments = []
    for f in msg.get("files", []) or []:
        filetype = (f.get("filetype") or "").lower()
        if filetype in IMAGE_FILETYPES or filetype == PDF_FILETYPE:
            attachments.append({
                "url": f.get("url_private_download") or f.get("url_private"),
                "filetype": filetype,
                "name": f.get("name", "file"),
            })
    return attachments


@dataclass
class RemovalCommand:
    remove_at: datetime


def parse_command(text: str, now: datetime) -> RemovalCommand | None:
    """Return a RemovalCommand if `text` contains a removal trigger word,
    else None. A trigger word with no (or an unparseable) time phrase
    after it means "remove now"."""
    if not text:
        return None
    lowered = text.lower()
    match = None
    for word in COMMAND_WORDS:
        m = re.search(rf"\b{word}\b", lowered)
        if m and (match is None or m.start() < match.start()):
            match = m
    if match is None:
        return None

    rest = (text[:match.start()] + text[match.end():]).strip()
    if not rest:
        return RemovalCommand(remove_at=now)

    # Replies name dates/times with no timezone, and mean London time when
    # they do -- parse relative to (and localize into) LOCAL_TZ rather than
    # UTC, so "remove 10am" means 10am in London, not 10am UTC.
    naive_local_now = now.astimezone(LOCAL_TZ).replace(tzinfo=None)
    parsed = dateparser.parse(rest, settings={
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": naive_local_now,
    })
    if parsed is None:
        return RemovalCommand(remove_at=now)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TZ)
    # Stored/compared as UTC like every other timestamp in this app --
    # LOCAL_TZ only decides how bare text like "10am" is interpreted.
    return RemovalCommand(remove_at=parsed.astimezone(timezone.utc))


def is_help_trigger(text: str) -> bool:
    """True for a short new message that starts with 'help' or 'remove' --
    almost certainly someone testing the bot or trying (in the wrong
    place) to remove a post, not real signage content. A longer message
    that happens to start with one of these words is left alone."""
    stripped = (text or "").strip()
    if not stripped or len(stripped) > HELP_TRIGGER_MAX_LEN:
        return False
    return bool(HELP_TRIGGER_RE.match(stripped))


def build_help_text(cfg: SlackConfig, posted_at_dt: datetime) -> str:
    interval = "1 day" if cfg.ttl_days == 1 else f"{cfg.ttl_days} days"
    example_remove_at = (posted_at_dt + timedelta(days=7)).astimezone(LOCAL_TZ)
    return (
        "Messages posted here appear on the Mess TV. You can send text, "
        "images or a combination of both.\n\n"
        f"Each notice is shown for {interval}. To remove sooner or later, "
        f"reply to the notice with `remove now` or `remove {example_remove_at:%-d %b %Y}`.\n\n"
        f"There's also a simple admin interface at {cfg.server_url}/admin.\n\n"
        f"If I'm broken, please contact `{cfg.admin_contact}`."
    )


def local_filename(ts: str, filetype: str, index: int | None = None) -> str:
    if index is None:
        return f"slack-{ts}.{filetype}"
    return f"slack-{ts}-{index}.{filetype}"


# Slack skin-tone shortcodes (":skin-tone-2:" through ":skin-tone-6:") are
# sent as a separate code immediately after the base emoji's shortcode
# rather than as part of one combined unicode sequence; `emoji` doesn't
# know this Slack-specific convention, so it's applied as a second pass.
_SKIN_TONE_MODIFIERS = {
    "2": "\U0001f3fb", "3": "\U0001f3fc", "4": "\U0001f3fd",
    "5": "\U0001f3fe", "6": "\U0001f3ff",
}
_SKIN_TONE_RE = re.compile(r":skin-tone-([2-6]):")


def convert_emoji_shortcodes(text: str) -> str:
    """Convert Slack-style `:shortcode:` emoji (including `:skin-tone-N:`
    modifiers) into real unicode emoji. Unrecognized shortcodes are left
    as-is rather than dropped."""
    text = emoji.emojize(text, language="alias")
    return _SKIN_TONE_RE.sub(lambda m: _SKIN_TONE_MODIFIERS[m.group(1)], text)


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


@contextmanager
def state_lock(path: Path):
    """Exclusive lock guarding read-modify-write access to `path` (e.g.
    slack-state.json) across the refresh tick and the admin server, which
    run as separate processes and can both write it."""
    lock_path = path.parent / (path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def append_audit(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(event) + "\n")


def sweep_expired(state: dict, now: datetime) -> list[str]:
    """Mark active entries whose remove_at has passed as 'expired' in place.
    Returns local_files paths whose entries just expired, for the
    caller to delete from disk."""
    files_to_delete: list[str] = []
    for entry in state.values():
        if entry["status"] != "active":
            continue
        remove_at = datetime.fromisoformat(entry["remove_at"])
        if remove_at <= now:
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
    bot_user_id: str = ""
    server_url: str = "http://localhost:8420"
    admin_contact: str = "@richard"


class SlackAPI(Protocol):
    def history(self, channel: str, oldest: str) -> list[dict]: ...
    def replies(self, channel: str, thread_ts: str) -> list[dict]: ...
    def user_name(self, user_id: str) -> str: ...
    def download(self, url: str, dest_path: Path) -> None: ...
    def post_message(self, channel: str, text: str, thread_ts: str | None = None) -> None: ...
    def auth_test(self) -> str: ...


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

    def auth_test(self) -> str:
        payload = self._call("auth.test", {})
        return payload.get("user_id", "")


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


def backfill_entries(state: dict, ttl_days: int) -> dict:
    """Fill in fields added after an entry may have been written, so state
    files from older versions don't crash this tick. Mutates and returns
    `state`. Currently: remove_at/remove_reason (added alongside scheduled
    removal); computed exactly as a freshly-ingested entry gets them."""
    for ts, entry in state.items():
        if "remove_at" in entry:
            continue
        posted_at = entry.get("posted_at")
        if not posted_at:
            continue
        try:
            posted_at_dt = datetime.fromisoformat(posted_at)
        except ValueError:
            log.error("Entry %s has an unparseable posted_at %r -- skipping backfill", ts, posted_at)
            continue
        entry["remove_at"] = (posted_at_dt + timedelta(days=ttl_days)).isoformat(timespec="seconds")
        entry.setdefault("remove_reason", "ttl")
    return state


def poll_slack(cfg: SlackConfig, state: dict, source_dir: Path, now: datetime, api: SlackAPI,
                audit_path: Path) -> dict:
    """One polling tick: fetch new messages, ingest them, check active
    entries for cancel replies, sweep expirations. Mutates and returns
    `state`. Never raises on API failures -- logs and returns state
    unchanged so a bad tick doesn't blank the display."""
    backfill_entries(state, cfg.ttl_days)

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
        kind = classify_message(msg, bot_user_id=cfg.bot_user_id)
        author_for_audit = msg.get("user", "unknown")
        posted_at_dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        posted_at = posted_at_dt.isoformat(timespec="seconds")

        if kind == "ignored":
            log.info("Ignoring Slack message %s: no recognized content", ts)
            append_audit(audit_path, {
                "at": now.isoformat(timespec="seconds"), "ts": ts,
                "author": author_for_audit, "kind": "ignored", "action": "ignored",
                "summary": (msg.get("text") or "")[:80],
            })
            # Record a marker so this message isn't refetched and re-audited on
            # every future tick. Never active, so it's invisible to the display,
            # the sweep, and the admin UI.
            state[ts] = {"ts": ts, "status": "ignored", "posted_at": posted_at}
            continue

        if kind == "text" and is_help_trigger(msg.get("text")):
            log.info("Replying with help text for Slack message %s: looks like a help/remove request", ts)
            _post_safe(api, cfg.channel, build_help_text(cfg, posted_at_dt), thread_ts=ts)
            append_audit(audit_path, {
                "at": now.isoformat(timespec="seconds"), "ts": ts,
                "author": author_for_audit, "kind": "ignored", "action": "help_reply",
                "summary": (msg.get("text") or "")[:80],
            })
            # Same marker pattern as the "ignored" branch above -- never
            # active, never re-processed, never shown on the display.
            state[ts] = {"ts": ts, "status": "ignored", "posted_at": posted_at}
            continue
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
            "remove_at": (posted_at_dt + timedelta(days=cfg.ttl_days)).isoformat(timespec="seconds"),
            "remove_reason": "ttl",
        }

        entry["text"] = convert_emoji_shortcodes(html.unescape(msg.get("text", "")))
        if kind == "attachment":
            attachments = extract_attachments(msg)
            has_pdf = any(a["filetype"] == PDF_FILETYPE for a in attachments)
            # PDF + multi-image mixing is out of scope -- fall back to the
            # single-attachment behavior (first recognized file) whenever a
            # PDF is involved.
            to_download = attachments[:1] if has_pdf else attachments
            multi = len(to_download) > 1
            downloaded = []
            for i, attachment in enumerate(to_download):
                dest = source_dir / local_filename(ts, attachment["filetype"], i if multi else None)
                try:
                    api.download(attachment["url"], dest)
                except SlackAPIError as exc:
                    log.error("Failed to download Slack attachment for %s (%s): %s",
                              ts, attachment["name"], exc)
                else:
                    downloaded.append(str(dest))
            entry["local_files"] = downloaded
            if not downloaded:
                entry["status"] = "failed"

        state[ts] = entry
        append_audit(audit_path, {
            "at": now.isoformat(timespec="seconds"), "ts": ts, "author": entry["author"],
            "kind": kind, "action": "ingested" if entry["status"] == "active" else entry["status"],
            "summary": _describe_entry(entry),
        })
        if entry["status"] == "active":
            remove_at_local = datetime.fromisoformat(entry["remove_at"]).astimezone(LOCAL_TZ)
            example_remove_at_local = (posted_at_dt + timedelta(days=7)).astimezone(LOCAL_TZ)
            _post_safe(
                api, cfg.channel,
                f"Added to the Skiff TV, until {remove_at_local:%-d %b %Y %H:%M}. "
                f"To remove, reply with `remove now` or `remove {example_remove_at_local:%-d %b %Y}` for example",
                thread_ts=ts,
            )

    for ts, entry in state.items():
        if entry["status"] != "active":
            continue
        try:
            replies = api.replies(cfg.channel, ts)
        except SlackAPIError as exc:
            log.error("Failed to fetch replies for %s: %s", ts, exc)
            continue
        human_replies = [r for r in replies if not r.get("bot_id")]
        command = None
        command_ts = None
        reply_user = None
        for reply in human_replies:  # last match wins
            parsed = parse_command(reply.get("text", ""), now)
            if parsed is not None:
                command = parsed
                command_ts = reply.get("ts")
                reply_user = reply.get("user")
        if command is None:
            continue

        # A scheduled removal deliberately leaves the entry active, so the same
        # reply is still there next tick. Applying it again would recompute a
        # relative remove_at ("in 1 week") forward forever and re-post/re-audit
        # every tick, so skip a reply we've already fully applied.
        if command_ts is not None and entry.get("remove_command_ts") == command_ts:
            continue

        if reply_user:
            try:
                requested_by = api.user_name(reply_user)
            except SlackAPIError as exc:
                log.error("Failed to resolve Slack user name for %s: %s", reply_user, exc)
                requested_by = reply_user
        else:
            requested_by = "someone"

        entry["remove_reason"] = "command"
        entry["remove_requested_by"] = requested_by
        entry["remove_command_ts"] = command_ts
        append_audit(audit_path, {
            "at": now.isoformat(timespec="seconds"), "ts": ts, "author": requested_by,
            "kind": "command", "action": "removed" if command.remove_at <= now else "scheduled_removal",
            "summary": f"remove -> {command.remove_at.isoformat(timespec='seconds')}",
        })
        if command.remove_at <= now:
            entry["status"] = "cancelled"
            entry["remove_at"] = command.remove_at.isoformat(timespec="seconds")
            for f in entry.get("local_files", []):
                Path(f).unlink(missing_ok=True)
            _post_safe(api, cfg.channel, "Removed from the display.", thread_ts=ts)
        else:
            entry["remove_at"] = command.remove_at.isoformat(timespec="seconds")
            remove_at_local = command.remove_at.astimezone(LOCAL_TZ)
            _post_safe(
                api, cfg.channel,
                f"Scheduled for removal on {remove_at_local:%-d %b %Y %H:%M}.",
                thread_ts=ts,
            )

    # Only sweep entries that existed before this tick: a message's `ts` is
    # its real Slack post time, but `history()` is queried with `oldest` set
    # to the TTL cutoff, so a message freshly ingested this tick can never
    # actually be older than the TTL in production. Excluding just-added
    # entries here avoids any accidental same-tick expiry from a
    # clock/timestamp mismatch.
    sweep_target = {ts: entry for ts, entry in state.items() if ts in pre_existing_ts}
    previously_active = {ts for ts, entry in sweep_target.items() if entry["status"] == "active"}
    expired_files = sweep_expired(sweep_target, now)
    for f in expired_files:
        Path(f).unlink(missing_ok=True)
    for ts in previously_active:
        entry = sweep_target[ts]
        if entry["status"] != "expired":
            continue
        if entry.get("remove_reason") == "command":
            who = entry.get("remove_requested_by", entry["author"])
            message = (f'I\'ve removed: "{_describe_entry(entry)}" by {entry["author"]} '
                       f"(requested by {who})")
        else:
            message = (f'I\'ve removed: "{_describe_entry(entry)}" by {entry["author"]} '
                       f"(expired after {cfg.ttl_days} days)")
        _post_safe(api, cfg.channel, message)

    return state
