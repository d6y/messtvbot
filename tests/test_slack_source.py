import email.message
import io
import sys
import unittest
import urllib.error
from pathlib import Path
import json
import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))
import slack_source as ms


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


class ExtractAttachmentsTests(unittest.TestCase):
    def test_returns_empty_list_when_no_files(self):
        self.assertEqual(ms.extract_attachments({"files": []}), [])

    def test_returns_empty_list_when_only_non_image_files(self):
        msg = {"files": [{"filetype": "zip", "url_private_download": "https://x/a.zip", "name": "a.zip"}]}
        self.assertEqual(ms.extract_attachments(msg), [])

    def test_returns_all_recognized_files_in_order(self):
        msg = {"files": [
            {"filetype": "jpg", "url_private_download": "https://x/a.jpg", "name": "a.jpg"},
            {"filetype": "zip", "url_private_download": "https://x/b.zip", "name": "b.zip"},
            {"filetype": "png", "url_private_download": "https://x/c.png", "name": "c.png"},
        ]}
        result = ms.extract_attachments(msg)
        self.assertEqual(result, [
            {"url": "https://x/a.jpg", "filetype": "jpg", "name": "a.jpg"},
            {"url": "https://x/c.png", "filetype": "png", "name": "c.png"},
        ])

    def test_falls_back_to_url_private_when_no_download_url(self):
        msg = {"files": [{"filetype": "png", "url_private": "https://x/b.png", "name": "b.png"}]}
        result = ms.extract_attachments(msg)
        self.assertEqual(result[0]["url"], "https://x/b.png")

    def test_recognizes_heic_and_heif(self):
        msg = {"files": [
            {"filetype": "heic", "url_private_download": "https://x/a.heic", "name": "a.heic"},
            {"filetype": "heif", "url_private_download": "https://x/b.heif", "name": "b.heif"},
        ]}
        result = ms.extract_attachments(msg)
        self.assertEqual([a["filetype"] for a in result], ["heic", "heif"])

    def test_recognizes_video_filetypes(self):
        msg = {"files": [
            {"filetype": "mp4", "url_private_download": "https://x/a.mp4", "name": "a.mp4"},
            {"filetype": "mov", "url_private_download": "https://x/b.mov", "name": "b.mov"},
        ]}
        result = ms.extract_attachments(msg)
        self.assertEqual([a["filetype"] for a in result], ["mp4", "mov"])


class UnsupportedAttachmentReasonTests(unittest.TestCase):
    def test_no_files_is_none(self):
        self.assertIsNone(ms._unsupported_attachment_reason({"files": []}))

    def test_all_displayable_files_is_none(self):
        msg = {"files": [{"filetype": "png"}, {"filetype": "pdf"}]}
        self.assertIsNone(ms._unsupported_attachment_reason(msg))

    def test_single_unknown_filetype(self):
        msg = {"files": [{"filetype": "tiff"}]}
        self.assertEqual(ms._unsupported_attachment_reason(msg), ".tiff isn't supported")

    def test_video_filetype_has_its_own_wording(self):
        msg = {"files": [{"filetype": "mp4"}]}
        self.assertEqual(ms._unsupported_attachment_reason(msg), "video isn't supported yet")

    def test_unknown_filetype_alongside_a_displayable_image_still_flagged(self):
        msg = {"files": [{"filetype": "png"}, {"filetype": "tiff"}]}
        self.assertEqual(ms._unsupported_attachment_reason(msg), ".tiff isn't supported")

    def test_multiple_unknown_filetypes(self):
        msg = {"files": [{"filetype": "tiff"}, {"filetype": "psd"}]}
        self.assertEqual(ms._unsupported_attachment_reason(msg), ".psd/.tiff aren't supported")

    def test_video_and_unknown_filetype_together(self):
        msg = {"files": [{"filetype": "mp4"}, {"filetype": "tiff"}]}
        self.assertEqual(
            ms._unsupported_attachment_reason(msg),
            "video isn't supported yet and .tiff isn't supported",
        )

    def test_missing_filetype_field_is_treated_as_unsupported(self):
        msg = {"files": [{}]}
        self.assertEqual(ms._unsupported_attachment_reason(msg), ".unknown isn't supported")

    def test_oversized_displayable_file_is_rejected(self):
        msg = {"files": [{"filetype": "png", "size": 30 * 1024 * 1024}]}
        reason = ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024)
        self.assertIn("too large", reason)
        self.assertIn("25MB", reason)

    def test_file_within_size_limit_is_not_rejected(self):
        msg = {"files": [{"filetype": "png", "size": 10 * 1024 * 1024}]}
        self.assertIsNone(ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024))

    def test_missing_size_field_is_not_treated_as_oversized(self):
        # Don't reject on missing/unreliable metadata -- only act when
        # Slack actually told us a size and it's over the limit.
        msg = {"files": [{"filetype": "png"}]}
        self.assertIsNone(ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024))

    def test_oversized_unsupported_filetype_only_mentions_the_type_not_size(self):
        # Avoid a redundant/confusing double reason for a file that's
        # already going to be rejected for being the wrong type.
        msg = {"files": [{"filetype": "tiff", "size": 100 * 1024 * 1024}]}
        self.assertEqual(
            ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024),
            ".tiff isn't supported",
        )

    def test_oversized_video_only_mentions_video_not_size(self):
        msg = {"files": [{"filetype": "mp4", "size": 100 * 1024 * 1024}]}
        self.assertEqual(
            ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024),
            "video isn't supported yet",
        )

    def test_oversized_file_alongside_unsupported_type_combines_reasons(self):
        msg = {"files": [
            {"filetype": "png", "size": 30 * 1024 * 1024},
            {"filetype": "tiff"},
        ]}
        reason = ms._unsupported_attachment_reason(msg, max_bytes=25 * 1024 * 1024)
        self.assertIn(".tiff isn't supported", reason)
        self.assertIn("too large", reason)


class IsHelpTriggerTests(unittest.TestCase):
    def test_bare_help_is_a_trigger(self):
        self.assertTrue(ms.is_help_trigger("help"))

    def test_bare_remove_is_a_trigger(self):
        self.assertTrue(ms.is_help_trigger("remove"))

    def test_help_is_case_insensitive(self):
        self.assertTrue(ms.is_help_trigger("HELP"))

    def test_help_with_short_trailing_text_is_a_trigger(self):
        self.assertTrue(ms.is_help_trigger("help me please?"))

    def test_help_with_punctuation_immediately_after_is_a_trigger(self):
        self.assertTrue(ms.is_help_trigger("Help!"))

    def test_word_that_merely_starts_with_remove_is_not_a_trigger(self):
        self.assertFalse(ms.is_help_trigger("removing the old poster"))

    def test_long_message_starting_with_remove_is_not_a_trigger(self):
        # A real notice, not an accidental command -- length is the signal.
        text = "Remove your shoes before entering the office please and thank you"
        self.assertFalse(ms.is_help_trigger(text))

    def test_unrelated_text_is_not_a_trigger(self):
        self.assertFalse(ms.is_help_trigger("Pizza in the kitchen at 1pm!"))

    def test_empty_text_is_not_a_trigger(self):
        self.assertFalse(ms.is_help_trigger(""))

    def test_none_text_is_not_a_trigger(self):
        self.assertFalse(ms.is_help_trigger(None))


class BuildHelpTextTests(unittest.TestCase):
    def setUp(self):
        self.cfg = ms.SlackConfig(
            token="xoxb-test", channel="C1", ttl_days=30,
            server_url="http://kiosk.local:8420", admin_contact="@richard",
        )
        self.posted_at_dt = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)

    def test_mentions_mess_tv(self):
        text = ms.build_help_text(self.cfg, self.posted_at_dt)
        self.assertIn("Mess TV", text)

    def test_includes_ttl_interval(self):
        text = ms.build_help_text(self.cfg, self.posted_at_dt)
        self.assertIn("30 days", text)

    def test_includes_remove_now_and_example_date(self):
        text = ms.build_help_text(self.cfg, self.posted_at_dt)
        self.assertIn("`remove now`", text)
        example_local = (self.posted_at_dt + timedelta(days=1)).astimezone(ms.LOCAL_TZ)
        self.assertIn(f"`remove {example_local:%-d %b %Y}`", text)

    def test_includes_admin_url(self):
        text = ms.build_help_text(self.cfg, self.posted_at_dt)
        self.assertIn("http://kiosk.local:8420/admin", text)

    def test_includes_contact(self):
        text = ms.build_help_text(self.cfg, self.posted_at_dt)
        self.assertIn("`@richard`", text)

    def test_singular_day_when_ttl_is_one(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=1)
        text = ms.build_help_text(cfg, self.posted_at_dt)
        self.assertIn("1 day.", text)
        self.assertNotIn("1 days", text)

    def test_example_date_does_not_match_the_real_ttl_expiry(self):
        # Regression: the example used to be hardcoded to +7 days, which
        # collided with (and looked redundant next to) a 7-day TTL.
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=7)
        text = ms.build_help_text(cfg, self.posted_at_dt)
        real_expiry = (self.posted_at_dt + timedelta(days=7)).astimezone(ms.LOCAL_TZ)
        self.assertNotIn(f"`remove {real_expiry:%-d %b %Y}`", text)


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
        self.assertEqual(result.remove_at.astimezone(ms.LOCAL_TZ).strftime("%A"), "Thursday")

    def test_remove_with_explicit_date(self):
        # A bare date with no time means midnight at the start of that day
        # in London, which the test checks in local terms (it may be the
        # previous UTC calendar day).
        result = ms.parse_command("remove 10 Sept", self.NOW)
        self.assertEqual(result.remove_at.astimezone(ms.LOCAL_TZ).date().isoformat(), "2026-09-10")

    def test_remove_with_explicit_date_and_time(self):
        # 10 Sept 2026 is British Summer Time (UTC+1) -- "10am" with no
        # explicit zone means 10am in London (09:00 UTC), not 10am UTC.
        result = ms.parse_command("remove 10 Sept 10am", self.NOW)
        self.assertEqual(result.remove_at.isoformat(), "2026-09-10T09:00:00+00:00")

    def test_remove_with_explicit_time_in_winter_is_gmt(self):
        # December is GMT (UTC+0), so no DST offset applies.
        now = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
        result = ms.parse_command("remove 10 Dec 10am", now)
        self.assertEqual(result.remove_at.isoformat(), "2026-12-10T10:00:00+00:00")

    def test_remove_with_unparseable_phrase_falls_back_to_now(self):
        result = ms.parse_command("remove pronto pronto pronto", self.NOW)
        self.assertEqual(result.remove_at, self.NOW)

    def test_unrelated_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command("nice!", self.NOW))

    def test_empty_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command("", self.NOW))

    def test_none_reply_does_not_match(self):
        self.assertIsNone(ms.parse_command(None, self.NOW))


class DescribeEntryTests(unittest.TestCase):
    def test_text_entry_shows_the_text(self):
        entry = {"kind": "text", "text": "Pizza in the kitchen!"}
        self.assertEqual(ms._describe_entry(entry), "Pizza in the kitchen!")

    def test_attachment_without_caption_shows_filename_only(self):
        entry = {"kind": "attachment", "text": "", "local_files": ["/x/slack-1.png"]}
        self.assertEqual(ms._describe_entry(entry), "slack-1.png")

    def test_attachment_with_caption_shows_both(self):
        entry = {"kind": "attachment", "text": "Free pizza today!", "local_files": ["/x/slack-1.png"]}
        self.assertEqual(ms._describe_entry(entry), "Free pizza today! (slack-1.png)")

    def test_attachment_caption_is_truncated_like_text_entries(self):
        long_caption = "x" * 100
        entry = {"kind": "attachment", "text": long_caption, "local_files": ["/x/slack-1.png"]}
        result = ms._describe_entry(entry)
        self.assertTrue(result.startswith("x" * 77 + "..."))
        self.assertTrue(result.endswith("(slack-1.png)"))

    def test_attachment_without_local_files_falls_back(self):
        entry = {"kind": "attachment", "text": "", "local_files": []}
        self.assertEqual(ms._describe_entry(entry), "attachment")


class LocalFilenameTests(unittest.TestCase):
    def test_builds_expected_filename(self):
        self.assertEqual(ms.local_filename("1735300000.000100", "pdf"), "slack-1735300000.000100.pdf")

    def test_builds_expected_filename_with_index(self):
        self.assertEqual(
            ms.local_filename("1735300000.000100", "png", index=2),
            "slack-1735300000.000100-2.png",
        )


class ConvertEmojiShortcodesTests(unittest.TestCase):
    def test_plain_shortcode_becomes_unicode(self):
        self.assertEqual(ms.convert_emoji_shortcodes(":bangbang:"), "‼️")

    def test_shortcode_with_skin_tone_modifier_becomes_unicode(self):
        self.assertEqual(
            ms.convert_emoji_shortcodes(":raised_hands::skin-tone-2:"),
            "\U0001f64c\U0001f3fb",
        )

    def test_unknown_shortcode_is_left_as_is(self):
        self.assertEqual(ms.convert_emoji_shortcodes(":not_a_real_emoji:"), ":not_a_real_emoji:")

    def test_plain_text_is_unchanged(self):
        self.assertEqual(ms.convert_emoji_shortcodes("Pizza in the kitchen!"), "Pizza in the kitchen!")

    def test_empty_string_is_unchanged(self):
        self.assertEqual(ms.convert_emoji_shortcodes(""), "")

    def test_slack_specific_shortcode_name_divergence_is_handled(self):
        # Regression: Slack's shortcode uses a numeral ("3"), the `emoji`
        # package only recognizes the spelled-out alias ("three") -- found
        # live when a message with ~50 shortcodes had exactly this one
        # left as literal text while everything else converted fine.
        self.assertEqual(ms.convert_emoji_shortcodes(":smiling_face_with_3_hearts:"), "\U0001f970")

    def test_slack_specific_alias_also_resolves_when_followed_by_a_skin_tone_code(self):
        # The base shortcode must still resolve even with a trailing
        # :skin-tone-N: right after it (same regex pass handles both).
        self.assertEqual(
            ms.convert_emoji_shortcodes(":smiling_face_with_3_hearts::skin-tone-2:"),
            "\U0001f970\U0001f3fb",
        )


class ResolveMentionsTests(unittest.TestCase):
    def test_user_mention_without_label_is_resolved_via_api(self):
        api = FakeSlackAPI(user_names={"U0C5206CBK6": "Jane"})
        self.assertEqual(ms.resolve_mentions("<@U0C5206CBK6> nice!", api), "@Jane nice!")

    def test_user_mention_with_embedded_label_skips_api_lookup(self):
        class NoLookupAPI(FakeSlackAPI):
            def user_name(self, user_id):
                raise AssertionError("should not call user_name when a label is embedded")

        api = NoLookupAPI()
        self.assertEqual(ms.resolve_mentions("<@U123|janedoe> hi", api), "@janedoe hi")

    def test_user_mention_lookup_failure_falls_back_to_raw_id(self):
        class FailingAPI(FakeSlackAPI):
            def user_name(self, user_id):
                raise ms.SlackAPIError("users.info boom")

        api = FailingAPI()
        self.assertEqual(ms.resolve_mentions("<@U0C5206CBK6> hi", api), "@U0C5206CBK6 hi")

    def test_channel_mention_uses_embedded_name(self):
        api = FakeSlackAPI()
        self.assertEqual(
            ms.resolve_mentions("see <#C0123456|general> for details", api),
            "see #general for details",
        )

    def test_special_mentions_become_at_forms(self):
        api = FakeSlackAPI()
        self.assertEqual(ms.resolve_mentions("<!here> urgent", api), "@here urgent")
        self.assertEqual(ms.resolve_mentions("<!channel> all hands", api), "@channel all hands")
        self.assertEqual(ms.resolve_mentions("<!everyone> hi", api), "@everyone hi")

    def test_subteam_mention_uses_embedded_label(self):
        api = FakeSlackAPI()
        self.assertEqual(
            ms.resolve_mentions("ping <!subteam^S123|@eng-team>", api),
            "ping @eng-team",
        )

    def test_url_link_is_left_untouched(self):
        # <url|label>/<url> are handled client-side (web/app.js); this
        # function only touches @/#/! mention syntax.
        api = FakeSlackAPI()
        text = "<https://example.com|Sign up> here"
        self.assertEqual(ms.resolve_mentions(text, api), text)

    def test_plain_text_is_unchanged(self):
        api = FakeSlackAPI()
        self.assertEqual(ms.resolve_mentions("Pizza in the kitchen!", api), "Pizza in the kitchen!")


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


class SlackWebAPIRateLimitTests(unittest.TestCase):
    def _http_429(self, retry_after=None):
        headers = email.message.Message()
        if retry_after is not None:
            headers.add_header("Retry-After", str(retry_after))
        return urllib.error.HTTPError(
            url="https://slack.com/api/conversations.history", code=429,
            msg="Too Many Requests", hdrs=headers, fp=io.BytesIO(b""),
        )

    def test_429_raises_rate_limited_error_with_retry_after(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        with mock.patch("urllib.request.urlopen", side_effect=self._http_429(retry_after=30)):
            with self.assertRaises(ms.SlackRateLimitedError) as ctx:
                api._call("conversations.history", {"channel": "C1", "oldest": "0"})
        self.assertEqual(ctx.exception.retry_after, 30)

    def test_429_without_retry_after_header_has_none(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        with mock.patch("urllib.request.urlopen", side_effect=self._http_429()):
            with self.assertRaises(ms.SlackRateLimitedError) as ctx:
                api._call("conversations.history", {"channel": "C1", "oldest": "0"})
        self.assertIsNone(ctx.exception.retry_after)

    def test_ratelimited_error_field_raises_rate_limited_error(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        fake_resp = mock.MagicMock()
        fake_resp.read.return_value = json.dumps({"ok": False, "error": "ratelimited"}).encode()
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            with self.assertRaises(ms.SlackRateLimitedError):
                api._call("conversations.history", {"channel": "C1", "oldest": "0"})

    def test_non_rate_limit_http_error_is_plain_slack_api_error(self):
        api = ms.SlackWebAPI(token="xoxb-test")
        err = urllib.error.HTTPError(
            url="https://slack.com/api/conversations.history", code=500,
            msg="Internal Server Error", hdrs=email.message.Message(), fp=io.BytesIO(b""),
        )
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(ms.SlackAPIError) as ctx:
                api._call("conversations.history", {"channel": "C1", "oldest": "0"})
        self.assertNotIsInstance(ctx.exception, ms.SlackRateLimitedError)


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
        self.history_oldest_calls = []
        self.replies_calls = []

    def history(self, channel, oldest):
        self.history_oldest_calls.append(oldest)
        return self.messages

    def replies(self, channel, thread_ts):
        self.replies_calls.append(thread_ts)
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


class StateLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_lock_is_reentrant_across_sequential_uses(self):
        path = self.tmp_dir / "data" / "slack-state.json"
        with ms.state_lock(path):
            pass
        with ms.state_lock(path):
            pass  # would hang/deadlock if the first lock weren't released

    def test_lock_creates_parent_directory(self):
        path = self.tmp_dir / "nested" / "data" / "slack-state.json"
        with ms.state_lock(path):
            pass
        self.assertTrue(path.parent.exists())


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

    def test_multi_image_message_downloads_all_images(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.20", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": "https://x/a.jpg", "name": "a.jpg"},
                {"filetype": "png", "url_private_download": "https://x/b.png", "name": "b.png"},
                {"filetype": "png", "url_private_download": "https://x/c.png", "name": "c.png"},
            ]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.20"]["kind"], "attachment")
        expected = [
            str(self.source_dir / "slack-100.20-0.jpg"),
            str(self.source_dir / "slack-100.20-1.png"),
            str(self.source_dir / "slack-100.20-2.png"),
        ]
        self.assertEqual(state["100.20"]["local_files"], expected)
        for path in expected:
            self.assertTrue(Path(path).exists())

    def test_images_beyond_max_images_are_ignored(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30, max_images=3)
        api = FakeSlackAPI(
            messages=[{"ts": "100.26", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": f"https://x/{i}.jpg", "name": f"{i}.jpg"}
                for i in range(5)
            ]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(len(state["100.26"]["local_files"]), 3)

    def test_reply_notes_when_images_were_truncated(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30, max_images=3)
        api = FakeSlackAPI(
            messages=[{"ts": "100.27", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": f"https://x/{i}.jpg", "name": f"{i}.jpg"}
                for i in range(5)
            ]}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.27"]
        self.assertIn("Only the first 3 of 5 images were used", replies[0]["text"])

    def test_reply_does_not_mention_truncation_when_within_max_images(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.28", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": "https://x/a.jpg", "name": "a.jpg"},
                {"filetype": "png", "url_private_download": "https://x/b.png", "name": "b.png"},
            ]}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.28"]
        self.assertNotIn("Only the first", replies[0]["text"])

    def test_multi_image_message_with_one_failed_download_keeps_the_rest(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.21", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": "https://x/a.jpg", "name": "a.jpg"},
                {"filetype": "png", "url_private_download": "https://x/bad.png", "name": "bad.png"},
            ]}],
            user_names={"U1": "Jane"},
            downloads_fail_for={"https://x/bad.png"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.21"]["status"], "active")
        self.assertEqual(state["100.21"]["local_files"], [str(self.source_dir / "slack-100.21-0.jpg")])

    def test_multi_image_message_with_all_downloads_failed_is_marked_failed(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.22", "text": "", "user": "U1", "files": [
                {"filetype": "jpg", "url_private_download": "https://x/bad1.jpg", "name": "bad1.jpg"},
                {"filetype": "png", "url_private_download": "https://x/bad2.png", "name": "bad2.png"},
            ]}],
            user_names={"U1": "Jane"},
            downloads_fail_for={"https://x/bad1.jpg", "https://x/bad2.png"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.22"]["status"], "failed")
        self.assertEqual(state["100.22"]["local_files"], [])

    def test_pdf_and_image_together_only_downloads_the_pdf(self):
        # PDF + multi-image mixing is out of scope -- fall back to the
        # existing single-attachment behavior (first recognized file).
        api = FakeSlackAPI(
            messages=[{"ts": "100.23", "text": "", "user": "U1", "files": [
                {"filetype": "pdf", "url_private_download": "https://x/a.pdf", "name": "a.pdf"},
                {"filetype": "png", "url_private_download": "https://x/b.png", "name": "b.png"},
            ]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.23"]["local_files"], [str(self.source_dir / "slack-100.23.pdf")])

    # Video attachments are rejected outright now -- see
    # test_video_message_is_rejected_not_shown and
    # test_image_and_video_together_is_still_rejected below (video isn't
    # supported, not just "falls back to single-file" like PDF).

    def test_heic_image_downloads_like_any_other_image(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.25", "text": "", "user": "U1", "files": [
                {"filetype": "heic", "url_private_download": "https://x/a.heic", "name": "a.heic"},
            ]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.25"]["kind"], "attachment")
        self.assertEqual(state["100.25"]["local_files"], [str(self.source_dir / "slack-100.25.heic")])

    def test_new_attachment_message_with_caption_stores_text(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.9", "text": "Free pizza today!", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["kind"], "attachment")
        self.assertEqual(state["100.9"]["text"], "Free pizza today!")

    def test_new_attachment_message_without_caption_has_empty_text(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.10", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.10"]["text"], "")

    def test_ignored_message_is_not_added_as_an_active_entry(self):
        api = FakeSlackAPI(messages=[{"ts": "100.3", "text": "", "user": "U1", "files": []}])
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.3"]["status"], "ignored")
        self.assertEqual(ms.sorted_active_entries(state), [])

    def test_bare_remove_message_is_not_shown_and_gets_a_help_reply(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.30", "text": "remove", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(state["100.30"]["status"], "ignored")
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.30"]
        self.assertEqual(len(replies), 1)
        self.assertIn("Mess TV", replies[0]["text"])

    def test_bare_help_message_is_not_shown_and_gets_a_help_reply(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.31", "text": "help?", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.31"]
        self.assertEqual(len(replies), 1)

    def test_help_trigger_is_not_reprocessed_on_a_later_tick(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.32", "text": "remove", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        api2 = FakeSlackAPI(messages=[{"ts": "100.32", "text": "remove", "user": "U1", "files": []}])
        ms.poll_slack(self.cfg, state, self.source_dir, self.now, api2, audit_path=self.audit_path)
        self.assertEqual(api2.posted_messages, [])

    def test_long_message_starting_with_remove_is_shown_normally(self):
        text = "Remove your shoes before entering the office please and thank you"
        api = FakeSlackAPI(
            messages=[{"ts": "100.33", "text": text, "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.33"]["kind"], "text")
        self.assertEqual(state["100.33"]["status"], "active")

    def test_attachment_with_short_remove_caption_is_shown_normally(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.34", "text": "remove", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.34"]["kind"], "attachment")
        self.assertEqual(state["100.34"]["status"], "active")

    def test_video_message_is_rejected_not_shown(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.35", "text": "", "user": "U1",
                       "files": [{"filetype": "mp4", "url_private_download": "https://x/a.mp4", "name": "a.mp4"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(state["100.35"]["status"], "ignored")
        self.assertEqual(api.downloaded, {})

    def test_video_message_gets_a_rejection_reply(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.36", "text": "check this out", "user": "U1",
                       "files": [{"filetype": "mov", "url_private_download": "https://x/a.mov", "name": "a.mov"}]}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.36"]
        self.assertEqual(len(replies), 1)
        self.assertIn("video", replies[0]["text"].lower())

    def test_video_message_with_text_is_rejected_entirely_not_shown_as_text(self):
        # A video + caption is rejected as a whole -- showing just the
        # caption without the video the poster actually sent would be
        # misleading, not a reasonable fallback.
        api = FakeSlackAPI(
            messages=[{"ts": "100.37", "text": "Team outing highlights!", "user": "U1",
                       "files": [{"filetype": "mp4", "url_private_download": "https://x/a.mp4", "name": "a.mp4"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])

    def test_image_and_video_together_is_still_rejected(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.38", "text": "", "user": "U1", "files": [
                {"filetype": "png", "url_private_download": "https://x/a.png", "name": "a.png"},
                {"filetype": "mp4", "url_private_download": "https://x/b.mp4", "name": "b.mp4"},
            ]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(api.downloaded, {})

    def test_unsupported_filetype_with_no_caption_is_rejected_not_silently_ignored(self):
        # Before this: a TIFF with no caption fell through to the generic
        # "ignored" path -- no reply at all, poster left guessing why.
        api = FakeSlackAPI(
            messages=[{"ts": "100.39", "text": "", "user": "U1",
                       "files": [{"filetype": "tiff", "url_private_download": "https://x/a.tiff", "name": "a.tiff"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.39"]
        self.assertEqual(len(replies), 1)
        self.assertIn(".tiff isn't supported", replies[0]["text"])

    def test_unsupported_filetype_with_caption_is_rejected_not_shown_as_bare_text(self):
        # Before this: the caption would show as a text-only slide with
        # the TIFF silently dropped -- exactly the misleading partial
        # content problem video rejection was built to avoid.
        api = FakeSlackAPI(
            messages=[{"ts": "100.40", "text": "Check out this scan", "user": "U1",
                       "files": [{"filetype": "tiff", "url_private_download": "https://x/a.tiff", "name": "a.tiff"}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(api.downloaded, {})

    def test_oversized_attachment_is_rejected_not_downloaded(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30, max_attachment_bytes=1024 * 1024)
        api = FakeSlackAPI(
            messages=[{"ts": "100.41", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png",
                                  "name": "a.png", "size": 5 * 1024 * 1024}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(api.downloaded, {})
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.41"]
        self.assertEqual(len(replies), 1)
        self.assertIn("too large", replies[0]["text"])

    def test_file_within_size_limit_is_shown_normally(self):
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30, max_attachment_bytes=25 * 1024 * 1024)
        api = FakeSlackAPI(
            messages=[{"ts": "100.42", "text": "", "user": "U1",
                       "files": [{"filetype": "png", "url_private_download": "https://x/a.png",
                                  "name": "a.png", "size": 1024 * 1024}]}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.42"]["status"], "active")

    def test_channel_join_message_is_not_added_or_acknowledged(self):
        api = FakeSlackAPI(messages=[{
            "ts": "100.8", "text": "<@U1> has joined the channel",
            "subtype": "channel_join", "user": "U1", "files": [],
        }])
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(api.posted_messages, [])

    def test_already_seen_message_is_not_reprocessed(self):
        existing = {"100.1": {"status": "active", "kind": "text", "text": "old",
                               "author": "Jane", "posted_at": "2026-07-01T00:00:00+00:00",
                               "local_files": [], "remove_at": "2026-08-31T00:00:00+00:00", "remove_reason": "ttl"}}
        api = FakeSlackAPI(messages=[{"ts": "100.1", "text": "new text!", "user": "U1", "files": []}])
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.1"]["text"], "old")

    def test_history_oldest_is_the_ttl_cutoff_even_with_existing_state(self):
        # Always re-fetches the full TTL window (not just "since the newest
        # ts seen") so reply_count/latest_reply on existing active entries'
        # parent messages stay fresh -- see the reply-skipping tests below.
        existing = {"999999999.000001": {
            "status": "active", "kind": "text", "text": "hi", "author": "Jane",
            "posted_at": "2026-07-15T00:00:00+00:00",
            "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
            "local_files": [],
        }}
        api = FakeSlackAPI(messages=[])
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        expected_oldest = str((self.now - timedelta(days=self.cfg.ttl_days)).timestamp())
        self.assertEqual(api.history_oldest_calls, [expected_oldest])

    def test_active_entry_with_no_replies_is_not_checked_via_replies_api(self):
        existing = {"100.40": {"status": "active", "kind": "text", "text": "hi",
                                "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                                "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                                "local_files": []}}
        api = FakeSlackAPI(messages=[{"ts": "100.40", "reply_count": 0}])
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.replies_calls, [])

    def test_active_entry_with_unchanged_latest_reply_is_not_rechecked(self):
        existing = {"100.41": {"status": "active", "kind": "text", "text": "hi",
                                "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                                "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                                "local_files": [], "last_seen_latest_reply": "100.41.9"}}
        api = FakeSlackAPI(messages=[{"ts": "100.41", "reply_count": 1, "latest_reply": "100.41.9"}])
        ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.replies_calls, [])

    def test_active_entry_with_new_latest_reply_is_rechecked_and_applied(self):
        existing = {"100.42": {"status": "active", "kind": "attachment", "text": "",
                                "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                                "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                                "local_files": [], "last_seen_latest_reply": "100.42.1"}}
        api = FakeSlackAPI(
            messages=[{"ts": "100.42", "reply_count": 2, "latest_reply": "100.42.9"}],
            replies_by_ts={"100.42": [{"text": "please cancel", "user": "U2"}]},
        )
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.replies_calls, ["100.42"])
        self.assertEqual(state["100.42"]["status"], "cancelled")
        self.assertEqual(state["100.42"]["last_seen_latest_reply"], "100.42.9")

    def test_entry_whose_parent_message_is_outside_the_fetched_window_falls_back_to_checking(self):
        # Defensive fallback: if we can't see this tick's reply_count for
        # some reason, check anyway rather than silently missing a removal.
        existing = {"100.43": {"status": "active", "kind": "text", "text": "hi",
                                "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                                "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                                "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.43": [{"text": "please cancel", "user": "U2"}]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(api.replies_calls, ["100.43"])
        self.assertEqual(state["100.43"]["status"], "cancelled")

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
        self.assertEqual(ms.sorted_active_entries(state), [])
        self.assertEqual(state["200.1"]["status"], "ignored")

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

    def test_user_mention_in_text_is_resolved_on_ingestion(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.50", "text": "<@U0C5206CBK6> this is cool", "user": "U1",
                       "files": []}],
            user_names={"U1": "Jane", "U0C5206CBK6": "Bob"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.50"]["text"], "@Bob this is cool")

    def test_emoji_shortcodes_in_text_are_converted_to_unicode(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.11", "text": "Drinks :bangbang: 5pm!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.11"]["text"], "Drinks ‼️ 5pm!")

    def test_emoji_shortcode_with_skin_tone_is_converted_to_unicode(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.12", "text": "See you there :raised_hands::skin-tone-2:",
                       "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.12"]["text"], "See you there \U0001f64c\U0001f3fb")

    def test_unknown_shortcode_is_left_as_is(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.13", "text": "Not an emoji: :this_is_not_real:",
                       "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        self.assertEqual(state["100.13"]["text"], "Not an emoji: :this_is_not_real:")

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

    def test_accepted_message_reply_names_display_and_expiry_and_remove_examples(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.1"]
        text = replies[0]["text"]
        self.assertIn("Skiff TV", text)
        remove_at_local = datetime.fromisoformat(state["100.1"]["remove_at"]).astimezone(ms.LOCAL_TZ)
        self.assertIn(f"{remove_at_local:%-d %b %Y %H:%M}", text)
        self.assertIn("`remove now`", text)
        posted_at = datetime.fromisoformat(state["100.1"]["posted_at"])
        example_date_local = (posted_at + timedelta(days=1)).astimezone(ms.LOCAL_TZ)
        self.assertIn(f"`remove {example_date_local:%-d %b %Y}`", text)

    def test_accepted_message_reply_does_not_mention_utc(self):
        api = FakeSlackAPI(
            messages=[{"ts": "100.1", "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.1"]
        self.assertNotIn("UTC", replies[0]["text"])

    def test_accepted_message_reply_uses_bst_in_summer(self):
        # 1 Aug is British Summer Time (UTC+1); the reply should show the
        # locally-correct wall-clock time, not the raw UTC one.
        cfg = ms.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30)
        now = datetime(2026, 8, 1, tzinfo=timezone.utc)
        ts = str(datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc).timestamp())
        api = FakeSlackAPI(
            messages=[{"ts": ts, "text": "Pizza today!", "user": "U1", "files": []}],
            user_names={"U1": "Jane"},
        )
        ms.poll_slack(cfg, {}, self.source_dir, now, api, audit_path=self.audit_path)
        replies = [p for p in api.posted_messages if p["thread_ts"] == ts]
        self.assertIn("13:00", replies[0]["text"])

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

    # -- Finding 1: scheduled removals must be applied exactly once ---------

    def test_scheduled_removal_is_applied_once_across_repeated_ticks(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [
            {"ts": "200.1", "text": "remove in 1 week", "user": "U2"},
        ]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api,
                               audit_path=self.audit_path)
        remove_at_after_first = state["100.9"]["remove_at"]

        later = self.now + timedelta(minutes=2)
        state = ms.poll_slack(self.cfg, state, self.source_dir, later, api,
                               audit_path=self.audit_path)

        # (a) remove_at is not recomputed/pushed forward by the second tick
        self.assertEqual(state["100.9"]["remove_at"], remove_at_after_first)
        self.assertEqual(remove_at_after_first,
                          (self.now + timedelta(weeks=1)).isoformat(timespec="seconds"))
        self.assertEqual(state["100.9"]["status"], "active")
        # (b) only one Slack reply posted across both ticks
        replies = [p for p in api.posted_messages if p["thread_ts"] == "100.9"]
        self.assertEqual(len(replies), 1)
        # (c) only one audit line for the command
        command_events = [e for e in self._audit_events() if e["kind"] == "command"]
        self.assertEqual(len(command_events), 1)

    def test_a_newer_reply_supersedes_an_already_applied_command(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [
            {"ts": "200.1", "text": "remove in 1 week", "user": "U2"},
        ]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api,
                               audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["remove_command_ts"], "200.1")

        api.replies_by_ts["100.9"].append({"ts": "200.2", "text": "remove now", "user": "U3"})
        later = self.now + timedelta(minutes=2)
        state = ms.poll_slack(self.cfg, state, self.source_dir, later, api,
                               audit_path=self.audit_path)

        self.assertEqual(state["100.9"]["status"], "cancelled")
        self.assertEqual(state["100.9"]["remove_command_ts"], "200.2")
        self.assertEqual(state["100.9"]["remove_at"], later.isoformat(timespec="seconds"))

    # -- Finding 2: state written before remove_at existed -----------------

    def test_legacy_entry_without_remove_at_is_backfilled_and_does_not_raise(self):
        legacy = {"1": {"status": "active", "kind": "text", "text": "Old announcement",
                         "author": "Jane", "posted_at": "2026-07-25T00:00:00+00:00",
                         "local_files": []}}
        api = FakeSlackAPI(messages=[])
        state = ms.poll_slack(self.cfg, legacy, self.source_dir, self.now, api,
                               audit_path=self.audit_path)
        self.assertEqual(state["1"]["remove_reason"], "ttl")
        self.assertEqual(state["1"]["remove_at"], "2026-08-24T00:00:00+00:00")
        self.assertEqual(state["1"]["status"], "active")

    def test_backfill_leaves_existing_remove_at_untouched(self):
        state = {"1": _entry("active", "2026-07-25T00:00:00+00:00",
                              remove_at="2026-07-26T00:00:00+00:00", remove_reason="command")}
        ms.backfill_entries(state, ttl_days=30)
        self.assertEqual(state["1"]["remove_at"], "2026-07-26T00:00:00+00:00")
        self.assertEqual(state["1"]["remove_reason"], "command")

    # -- Finding 3: ignored messages must not be re-audited every tick ------

    def test_ignored_message_is_audited_only_once_across_ticks(self):
        api = FakeSlackAPI(messages=[{"ts": "100.3", "text": "", "user": "U1", "files": []}])
        state = ms.poll_slack(self.cfg, {}, self.source_dir, self.now, api, audit_path=self.audit_path)
        state = ms.poll_slack(self.cfg, state, self.source_dir, self.now + timedelta(minutes=2), api,
                               audit_path=self.audit_path)
        events = [e for e in self._audit_events() if e["ts"] == "100.3"]
        self.assertEqual(len(events), 1)

    # -- Finding 5: the requester's name is resolved, not a raw user ID -----

    def test_remove_requested_by_is_a_resolved_display_name(self):
        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FakeSlackAPI(messages=[], replies_by_ts={"100.9": [
            {"ts": "200.1", "text": "remove in 1 week", "user": "U2"},
        ]}, user_names={"U2": "Priya"})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api,
                               audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["remove_requested_by"], "Priya")
        command_events = [e for e in self._audit_events() if e["kind"] == "command"]
        self.assertEqual(command_events[0]["author"], "Priya")

    def test_requested_by_falls_back_to_user_id_when_lookup_fails(self):
        class FailingUserNameAPI(FakeSlackAPI):
            def user_name(self, user_id):
                raise ms.SlackAPIError("users.info boom")

        existing = {"100.9": {"status": "active", "kind": "text", "text": "hi",
                               "author": "Jane", "posted_at": "2026-07-15T00:00:00+00:00",
                               "remove_at": "2026-08-14T00:00:00+00:00", "remove_reason": "ttl",
                               "local_files": []}}
        api = FailingUserNameAPI(messages=[], replies_by_ts={"100.9": [
            {"ts": "200.1", "text": "remove in 1 week", "user": "U2"},
        ]})
        state = ms.poll_slack(self.cfg, existing, self.source_dir, self.now, api,
                               audit_path=self.audit_path)
        self.assertEqual(state["100.9"]["remove_requested_by"], "U2")


if __name__ == "__main__":
    unittest.main()
