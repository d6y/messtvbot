import sys
import unittest
from pathlib import Path
import json
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import masthead_slack as ms


class ClassifyMessageTests(unittest.TestCase):
    def test_message_with_image_file_is_attachment(self):
        msg = {"text": "", "files": [{"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"}]}
        self.assertEqual(ms.classify_message(msg), "attachment")

    def test_message_with_pdf_file_is_attachment(self):
        msg = {"text": "flyer", "files": [{"filetype": "pdf", "url_private_download": "https://x/a.pdf", "name": "a.pdf"}]}
        self.assertEqual(ms.classify_message(msg), "attachment")

    def test_message_with_non_image_file_and_text_is_text(self):
        msg = {"text": "see attached", "files": [{"filetype": "zip", "url_private_download": "https://x/a.zip", "name": "a.zip"}]}
        self.assertEqual(ms.classify_message(msg), "text")

    def test_plain_text_message_is_text(self):
        msg = {"text": "Pizza in the kitchen at 1pm!", "files": []}
        self.assertEqual(ms.classify_message(msg), "text")

    def test_empty_message_is_ignored(self):
        msg = {"text": "", "files": []}
        self.assertEqual(ms.classify_message(msg), "ignored")

    def test_whitespace_only_text_is_ignored(self):
        msg = {"text": "   ", "files": []}
        self.assertEqual(ms.classify_message(msg), "ignored")

    def test_channel_join_message_is_ignored_despite_having_text(self):
        msg = {"text": "<@U123> has joined the channel", "subtype": "channel_join", "files": []}
        self.assertEqual(ms.classify_message(msg), "ignored")

    def test_channel_topic_change_message_is_ignored(self):
        msg = {"text": "set the channel topic", "subtype": "channel_topic", "files": []}
        self.assertEqual(ms.classify_message(msg), "ignored")

    def test_message_from_bot_user_id_is_ignored(self):
        msg = {"text": "I've removed: ...", "files": [], "user": "UBOT1"}
        self.assertEqual(ms.classify_message(msg, bot_user_id="UBOT1"), "ignored")

    def test_message_with_bot_id_is_ignored_regardless_of_user(self):
        msg = {"text": "I've removed: ...", "files": [], "bot_id": "B123"}
        self.assertEqual(ms.classify_message(msg), "ignored")


class ExtractAttachmentTests(unittest.TestCase):
    def test_returns_none_when_no_files(self):
        self.assertIsNone(ms.extract_attachment({"text": "hi", "files": []}))

    def test_returns_none_when_only_non_image_files(self):
        msg = {"files": [{"filetype": "zip", "url_private_download": "https://x/a.zip", "name": "a.zip"}]}
        self.assertIsNone(ms.extract_attachment(msg))

    def test_returns_first_image_file(self):
        msg = {"files": [{"filetype": "jpg", "url_private_download": "https://x/a.jpg", "name": "a.jpg"}]}
        result = ms.extract_attachment(msg)
        self.assertEqual(result, {"url": "https://x/a.jpg", "filetype": "jpg", "name": "a.jpg"})

    def test_falls_back_to_url_private_when_no_download_url(self):
        msg = {"files": [{"filetype": "png", "url_private": "https://x/b.png", "name": "b.png"}]}
        result = ms.extract_attachment(msg)
        self.assertEqual(result["url"], "https://x/b.png")


class ParseCommandTests(unittest.TestCase):
    NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)  # a Thursday

    def test_bare_cancel_means_now(self):
        result = ms.parse_command("please cancel this", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_bare_delete_means_now(self):
        result = ms.parse_command("DELETE", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_bare_undo_means_now(self):
        result = ms.parse_command("undo please", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_bare_remove_means_now(self):
        result = ms.parse_command("remove", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_remove_now_means_now(self):
        result = ms.parse_command("remove now", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_remove_in_one_week(self):
        result = ms.parse_command("remove in 1 week", self.NOW)
        self.assertEqual(result.remove_at, self.NOW + timedelta(weeks=1))

    def test_remove_next_thursday_resolves_to_the_future(self):
        result = ms.parse_command("remove thursday", self.NOW)
        self.assertGreater(result.remove_at, self.NOW)
        self.assertEqual(result.remove_at.strftime("%A"), "Thursday")

    def test_remove_with_explicit_date(self):
        result = ms.parse_command("remove 10 Sept", self.NOW)
        self.assertEqual(result.remove_at.date().isoformat(), "2026-09-10")

    def test_remove_with_explicit_date_and_time(self):
        result = ms.parse_command("remove 10 Sept 10am", self.NOW)
        self.assertEqual(result.remove_at.isoformat(), "2026-09-10T10:00:00+00:00")

    def test_remove_with_unparseable_phrase_falls_back_to_now(self):
        result = ms.parse_command("remove pronto pronto pronto", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_unrelated_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command("nice!", self.NOW))

    def test_empty_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command("", self.NOW))

    def test_none_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command(None, self.NOW))


class LocalFilenameTests(unittest.TestCase):
    def test_builds_expected_filename(self):
        self.assertEqual(ms.local_filename("1735300000.000100", "pdf"), "slack-1735300000.000100.pdf")


class StateLoadSaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_load_state_missing_file_returns_empty_dict(self):
        result = ms.load_state(self.tmp_dir / "data" / "slack-state.json")
        self.assertEqual(result, {})

    def test_save_then_load_round_trips(self):
        state = {"123.456": {"status": "active", "kind": "text", "text": "hi",
                              "author": "Jane", "posted_at": "2026-08-01T00:00:00+00:00",
                              "local_files": [], "remove_at": "2026-08-01T00:00:00+00:00", "remove_reason": "ttl"}}
        path = self.tmp_dir / "data" / "slack-state.json"
        ms.save_state(state, path)
        self.assertEqual(ms.load_state(path), state)

    def test_save_creates_parent_directory(self):
        path = self.tmp_dir / "nested" / "data" / "slack-state.json"
        ms.save_state({}, path)
        self.assertTrue(path.exists())

    def test_save_leaves_no_temp_files_behind(self):
        path = self.tmp_dir / "data" / "slack-state.json"
        ms.save_state({"a": 1}, path)
        leftovers = list(path.parent.glob(".slack-state-*"))
        self.assertEqual(leftovers, [])

    def test_load_state_corrupt_json_returns_empty_dict(self):
        path = self.tmp_dir / "data" / "slack-state.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json")
        result = ms.load_state(path)
        self.assertEqual(result, {})


class SlackWebAPICallTests(unittest.TestCase):
    def test_malformed_json_response_raises_slack_api_error(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = b"not json{"
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            with self.assertRaises(ms.SlackAPIError):
                api._call("conversations.history", {"channel": "C1", "oldest": "0"})

    def test_history_paginates_until_next_cursor_is_empty(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        pages = [
            {"ok": True, "messages": [{"ts": "1"}, {"ts": "2"}],
             "response_metadata": {"next_cursor": "abc"}},
            {"ok": True, "messages": [{"ts": "3"}],
             "response_metadata": {"next_cursor": ""}},
        ]
        calls = []

        def fake_call(method, params):
            calls.append(params)
            return pages[len(calls) - 1]

        with mock.patch.object(api, "_call", side_effect=fake_call):
            messages = api.history("C1", "0")

        self.assertEqual([m["ts"] for m in messages], ["1", "2", "3"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("cursor", calls[0])
        self.assertEqual(calls[1]["cursor"], "abc")

    def test_auth_test_returns_bot_user_id(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        with mock.patch.object(api, "_call", return_value={"ok": True, "user_id": "UBOT1"}):
            self.assertEqual(api.auth_test(), "UBOT1")


def _entry(status, posted_at, kind="text", local_files=None, remove_at=None, remove_reason="ttl"):
    return {"status": status, "kind": kind, "text": "x", "author": "A",
            "posted_at": posted_at, "local_files": local_files or [],
            "remove_at": remove_at or posted_at, "remove_reason": remove_reason}


class SweepExpiredTests(unittest.TestCase):
    def test_active_entry_past_remove_at_is_expired(self):
        state = {"1": _entry("active", "2026-01-01T00:00:00+00:00",
                              remove_at="2026-01-31T00:00:00+00:00")}
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        ms.sweep_expired(state, now=now)
        self.assertEqual(state["1"]["status"], "expired")

    def test_active_entry_before_remove_at_stays_active(self):
        state = {"1": _entry("active", "2026-07-30T00:00:00+00:00",
                              remove_at="2026-08-29T00:00:00+00:00")}
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        ms.sweep_expired(state, now=now)
        self.assertEqual(state["1"]["status"], "active")

    def test_already_cancelled_entry_is_left_alone(self):
        state = {"1": _entry("cancelled", "2020-01-01T00:00:00+00:00",
                              remove_at="2020-01-31T00:00:00+00:00")}
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        ms.sweep_expired(state, now=now)
        self.assertEqual(state["1"]["status"], "cancelled")

    def test_returns_local_files_of_newly_expired_entries(self):
        state = {"1": _entry("active", "2020-01-01T00:00:00+00:00", kind="attachment",
                              local_files=["/tmp/a.png"], remove_at="2020-01-31T00:00:00+00:00")}
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        result = ms.sweep_expired(state, now=now)
        self.assertEqual(result, ["/tmp/a.png"])

    def test_does_not_return_files_for_entries_still_active(self):
        state = {"1": _entry("active", "2026-07-30T00:00:00+00:00", kind="attachment",
                              local_files=["/tmp/a.png"], remove_at="2026-08-29T00:00:00+00:00")}
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        result = ms.sweep_expired(state, now=now)
        self.assertEqual(result, [])


class SortedActiveEntriesTests(unittest.TestCase):
    def test_filters_out_non_active(self):
        state = {"1": _entry("active", "2026-01-01T00:00:00+00:00"),
                  "2": _entry("expired", "2026-01-02T00:00:00+00:00")}
        result = ms.sorted_active_entries(state)
        self.assertEqual([ts for ts, _ in result], ["1"])

    def test_sorts_by_posted_at_ascending(self):
        state = {"1": _entry("active", "2026-01-03T00:00:00+00:00"),
                  "2": _entry("active", "2026-01-01T00:00:00+00:00"),
                  "3": _entry("active", "2026-01-02T00:00:00+00:00")}
        result = ms.sorted_active_entries(state)
        self.assertEqual([ts for ts, _ in result], ["2", "3", "1"])

    def test_empty_state_returns_empty_list(self):
        self.assertEqual(ms.sorted_active_entries({}), [])


class FakeSlackAPI:
    """Test double for SlackAPI -- no network."""

    def __init__(self, messages=None, replies_by_ts=None, user_names=None, downloads_fail_for=None,
                 posts_fail=False):
        self.messages = messages or []
        self.replies_by_ts = replies_by_ts or {}
        self.user_names = user_names or {}
        self.downloads_fail_for = downloads_fail_for or set()
        self.posts_fail = posts_fail
        self.downloaded = {}
        self.posted_messages = []

    def history(self, channel, oldest):
        return self.messages

    def replies(self, channel, thread_ts):
        return self.replies_by_ts.get(thread_ts, [])

    def user_name(self, user_id):
        return self.user_names.get(user_id, user_id)

    def download(self, url, dest_path):
        if url in self.downloads_fail_for:
            raise ms.SlackAPIError("download failed")
        Path(dest_path).write_bytes(b"fake-bytes")
        self.downloaded[url] = str(dest_path)

    def post_message(self, channel, text, thread_ts=None):
        if self.posts_fail:
            raise ms.SlackAPIError("chat.postMessage failed")
        self.posted_messages.append({"channel": channel, "text": text, "thread_ts": thread_ts})

    def auth_test(self):
        return ""


class AppendAuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_appends_one_json_line_per_call(self):
        path = self.tmp_dir / "audit.jsonl"
        ms.append_audit(path, {"a": 1})
        ms.append_audit(path, {"a": 2})
        lines = path.read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0]), {"a": 1})
        self.assertEqual(json.loads(lines[1]), {"a": 2})

    def test_creates_parent_directory(self):
        path = self.tmp_dir / "nested" / "audit.jsonl"
        ms.append_audit(path, {"a": 1})
        self.assertTrue(path.exists())


class PollSlackTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.source_dir = self.tmp_dir / "source"
        self.source_dir.mkdir()
        self.now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        self.cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30)
        self.audit_path = self.tmp_dir / "audit.jsonl"

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_new_text_message_is_added_to_state(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.1"]["kind"], "text")
        self.assertEqual(state["100.1"]["text"], "Pizza today!")
        self.assertEqual(state["100.1"]["author"], "Jane")
        self.assertEqual(state["100.1"]["status"], "active")

    def test_new_attachment_message_downloads_file(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.2", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.2"]["kind"], "attachment")
        expected_path = str(self.source_dir / "slack-100.2.png")
        self.assertEqual(state["100.2"]["local_files"], [expected_path])
        self.assertTrue(Path(expected_path).exists())

    def test_ignored_message_is_not_added(self):
        api = FakeSlackAPI(messages=[{"ts": "100.3", "text": "", "user": "U1", "files": []}])
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state, {})

    def test_channel_join_message_is_not_added_or_acknowledged(self):
        api = FakeSlackAPI(messages=[{
            "ts": "100.8", "text": "<@U1> has joined the channel",
            "subtype": "channel_join", "user": "U1", "files": [],
        }])
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state, {})
        self.assertEqual(api.posted_messages, [])

    def test_already_seen_message_is_not_reprocessed(self):
        existing = {"100.1": {"status": "active", "kind": "text", "text": "old",
                               "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                               "local_files": [], "remove_at": "2026-08-31T00:00:00+00:00", "remove_reason": "ttl"}}
        api = FakeSlackAPI(messages=[{"ts": "100.1", "text": "new text!", "user": "U1", "files": []}])
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.1"]["text"], "old")

    def test_cancel_reply_marks_entry_cancelled_and_deletes_file(self):
        local_file = self.source_dir / "slack-100.2.png"
        local_file.write_bytes(b"x")
        existing = {"100.2": {"status": "active", "kind": "attachment", "text": "",
                               "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                               "remove_at": "2026-07-31T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": [str(local_file)]}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.2": [{"text": "please cancel", "user": "U2"}]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.2"]["status"], "cancelled")
        self.assertFalse(local_file.exists())

    def test_non_cancel_reply_leaves_entry_active(self):
        existing = {"100.1": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.1": [{"text": "nice!", "user": "U2"}]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.1"]["status"], "active")

    def test_remove_with_future_phrase_schedules_removal_without_cancelling(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [{"text": "remove in 1 week", "user": "U2"}]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["status"], "active")
        self.assertEqual(state["100.9"]["remove_at"], (self.now + timedelta(weeks=1)).isoformat(timespec="seconds"))
        self.assertEqual(state["100.9"]["remove_reason"], "command")

    def test_scheduled_removal_reply_confirms_the_date(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [{"text": "remove in 1 week", "user": "U2"}]})
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.9"]
        self.assertEqual(len(replies), 1)
        self.assertIn("Scheduled for removal", replies[0]["text"])

    def test_most_recent_reply_wins_over_an_earlier_one(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [
            {"text": "remove in 1 week", "user": "U2"},
            {"text": "remove now", "user": "U3"},
        ]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["status"], "cancelled")

    def test_bot_own_reply_is_not_treated_as_a_command(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [
            {"text": "Added to the display.", "bot_id": "B1"},
        ]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["status"], "active")

    def test_bot_own_top_level_message_is_not_ingested(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30, bot_user_id="UBOT1")
        api = FakeSlackAPI(messages=[{"ts": "200.1", "text": "I've removed: ... by Jane",
                                       "user": "UBOT1", "files": []}])
        state = ms.poll_slack(cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state, {})

    def test_expired_entry_is_swept_and_file_deleted(self):
        local_file = self.source_dir / "slack-1.png"
        local_file.write_bytes(b"x")
        existing = {"1": {"status": "active", "kind": "attachment", "text": "",
                           "author": "Jane", "posted_at": "2020-01-01T00:00:00+00:00",
                           "local_files": [str(local_file)], "remove_at": "2020-01-31T00:00:00+00:00", "remove_reason": "ttl"}}
        api = FakeSlackAPI(messages=[])
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["1"]["status"], "expired")
        self.assertFalse(local_file.exists())

    def test_history_failure_returns_state_unchanged(self):
        class FailingHistoryAPI(FakeSlackAPI):
            def history(self, channel, oldest):
                raise ms.SlackAPIError("boom")

        existing = {"1": {"status": "active", "kind": "text", "text": "hi",
                           "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                           "local_files": [], "remove_at": "2026-08-31T00:00:00+00:00", "remove_reason": "ttl"}}
        state = ms.poll_slack(self.cfg, dict(existing), self.source_dir, self.now, FailingHistoryAPI(),
                               audit_path=self.audit_path)
        self.assertEqual(state, existing)

    def test_user_name_failure_falls_back_and_does_not_raise(self):
        class FailingUserNameAPI(FakeSlackAPI):
            def user_name(self, user_id):
                raise ms.SlackAPIError("users.info boom")

        api = FailingUserNameAPI(
            messages=[{"ts": "100.5", "text": "Pizza today!", "user": "U1", "files": []}],
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertIn("100.5", state)
        self.assertEqual(state["100.5"]["author"], "U1")

    def test_download_failure_skips_message_without_raising(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.4", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/bad.png", "name": "bad.png"}]}],
            downloads_fail_for={"https://x/bad.png"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertIn("100.4", state)
        self.assertEqual(state["100.4"]["status"], "failed")

    def test_html_entities_in_text_are_unescaped(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.7", "text": "Coffee &amp; cake", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.7"]["text"], "Coffee & cake")

    def test_download_failure_records_ts_with_failed_status_and_excludes_from_rotation(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.6", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/bad2.png", "name": "bad2.png"}]}],
            downloads_fail_for={"https://x/bad2.png"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertIn("100.6", state)
        self.assertEqual(state["100.6"]["status"], "failed")
        self.assertEqual(state["100.6"]["local_files"], [])
        active_ts = [ts for ts, _ in ms.sorted_active_entries(state)]
        self.assertNotIn("100.6", active_ts)

    def test_accepted_text_message_gets_thread_reply(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.1"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0]["channel"], "C1")

    def test_ignored_message_gets_no_reply(self):
        api = FakeSlackAPI(messages=[{"ts": "100.3", "text": "", "user": "U1", "files": []}])
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.posted_messages, [])

    def test_failed_download_gets_no_accepted_reply(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.4", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/bad.png", "name": "bad.png"}]}],
            downloads_fail_for={"https://x/bad.png"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.posted_messages, [])

    def test_cancel_reply_gets_thread_reply_confirming_removal(self):
        local_file = self.source_dir / "slack-100.2.png"
        local_file.write_bytes(b"x")
        existing = {"100.2": {"status": "active", "kind": "attachment", "text": "",
                               "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                               "local_files": [str(local_file)], "remove_at": "2026-08-31T00:00:00+00:00", "remove_reason": "ttl"}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.2": [{"text": "please cancel"}]})
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.2"]
        self.assertEqual(len(replies), 1)

    def test_expired_entry_gets_new_top_level_removal_message(self):
        local_file = self.source_dir / "slack-1.png"
        local_file.write_bytes(b"x")
        existing = {"1": {"status": "active", "kind": "text", "text": "Old announcement",
                           "author": "Jane", "posted_at": "2020-01-01T00:00:00+00:00",
                           "local_files": [], "remove_at": "2020-01-31T00:00:00+00:00", "remove_reason": "ttl"}}
        api = FakeSlackAPI(messages=[])
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        top_level = [p for p in api.posted_messages if p["thread_ts"] is None]
        self.assertEqual(len(top_level), 1)
        self.assertIn("Old announcement", top_level[0]["text"])
        self.assertIn("Jane", top_level[0]["text"])

    def test_post_message_failure_does_not_raise(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
            posts_fail=True,
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertIn("100.1", state)

    def _audit_events(self):
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text().splitlines()]

    def test_ingested_text_message_is_audited(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["ts"], "100.1")
        self.assertEqual(event["author"], "Jane")
        self.assertEqual(event["kind"], "text")
        self.assertEqual(event["action"], "ingested")
        self.assertEqual(event["summary"], "Pizza today!")
        self.assertEqual(event["at"], self.now.isoformat(timespec="seconds"))

    def test_ignored_message_is_audited(self):
        api = FakeSlackAPI(messages=[{"ts": "100.3", "text": "", "user": "U1", "files": []}])
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["ts"], "100.3")
        self.assertEqual(events[0]["author"], "U1")
        self.assertEqual(events[0]["kind"], "ignored")
        self.assertEqual(events[0]["action"], "ignored")

    def test_failed_download_is_audited_as_failed(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.4", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/bad.png", "name": "bad.png"}]}],
            downloads_fail_for={"https://x/bad.png"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["ts"], "100.4")
        self.assertEqual(events[0]["kind"], "attachment")
        self.assertEqual(events[0]["action"], "failed")

    def test_cancel_command_is_audited_as_removed(self):
        existing = {"100.2": {"status": "active", "kind": "attachment", "text": "",
                               "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                               "remove_at": "2026-07-31T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.2": [{"text": "please cancel", "user": "U2"}]})
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["ts"], "100.2")
        self.assertEqual(event["author"], "U2")
        self.assertEqual(event["kind"], "command")
        self.assertEqual(event["action"], "removed")

    def test_future_removal_command_is_audited_as_scheduled(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [{"text": "remove in 1 week", "user": "U2"}]})
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        events = self._audit_events()
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["ts"], "100.9")
        self.assertEqual(event["author"], "U2")
        self.assertEqual(event["kind"], "command")
        self.assertEqual(event["action"], "scheduled_removal")
        self.assertIn((self.now + timedelta(weeks=1)).isoformat(timespec="seconds"), event["summary"])


if __name__ == "__main__":
    unittest.main()
