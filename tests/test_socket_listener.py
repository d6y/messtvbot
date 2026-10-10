import importlib
import json
import shutil
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bin"))

refresh = importlib.import_module("refresh")
slack_source = importlib.import_module("slack_source")
socket_listener = importlib.import_module("socket_listener")


class FakeSlackAPI:
    """Minimal SlackAPI double -- enough for the one event/reconcile pass
    each test drives, no network."""

    def __init__(self, messages=None, replies_by_ts=None):
        self.messages = messages or []
        self.replies_by_ts = replies_by_ts or {}
        self.posted_messages = []

    def history(self, channel, oldest):
        return self.messages

    def replies(self, channel, thread_ts):
        return self.replies_by_ts.get(thread_ts, [])

    def user_name(self, user_id):
        return user_id

    def channel_name(self, channel_id):
        return channel_id

    def download(self, url, dest_path):
        Path(dest_path).write_bytes(b"x")

    def post_message(self, channel, text, thread_ts=None):
        self.posted_messages.append({"channel": channel, "text": text, "thread_ts": thread_ts})

    def auth_test(self):
        return ""


class SocketListenerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.kiosk_dir = self.tmp_dir / "kiosk-data"
        (self.kiosk_dir / "data").mkdir(parents=True)
        (self.kiosk_dir / "rendered").mkdir()
        self.source_dir = self.kiosk_dir / "source"
        self.source_dir.mkdir()
        self.state_path = self.kiosk_dir / "data" / "slack-state.json"
        self.audit_path = self.kiosk_dir / "data" / "audit.jsonl"
        self.manifest_path = self.kiosk_dir / "data" / "manifest.json"
        self.cfg = refresh.Config(
            slack_token="xoxb-test", slack_channel="C1", slack_ttl_days=30,
            kiosk_dir=self.kiosk_dir, repo_dir=self.tmp_dir, render_width=1920,
            slide_seconds=8, poll_seconds=30, skip_slack_poll=True,
            server_url="http://localhost:8420", admin_contact="@richard",
            max_images=6, max_pdf_pages=15, max_attachment_mb=25,
        )
        self.slack_cfg = slack_source.SlackConfig(token="xoxb-test", channel="C1", ttl_days=30)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _manifest_items(self):
        return json.loads(self.manifest_path.read_text())["items"]


class HandleEventEnvelopeTests(SocketListenerTestCase):
    def test_new_message_is_ingested_and_manifest_rebuilt(self):
        api = FakeSlackAPI()
        event = {"ts": "100.1", "text": "Pizza today!", "user": "U1"}
        socket_listener.handle_event_envelope(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, event, api,
        )
        state = slack_source.load_state(self.state_path)
        self.assertEqual(state["100.1"]["status"], "active")
        self.assertEqual(len(self._manifest_items()), 1)

    def test_no_op_event_does_not_rebuild_manifest(self):
        api = FakeSlackAPI()
        event = {"ts": "100.1", "thread_ts": "999.9", "text": "remove now", "user": "U2"}
        socket_listener.handle_event_envelope(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, event, api,
        )
        self.assertFalse(self.manifest_path.exists())


class ReconcileTests(SocketListenerTestCase):
    def test_reconcile_ingests_and_writes_manifest(self):
        api = FakeSlackAPI(messages=[{"ts": "100.1", "text": "Pizza!", "user": "U1"}])
        socket_listener.reconcile(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        self.assertEqual(len(self._manifest_items()), 1)

    def test_reconcile_persists_state_to_disk(self):
        api = FakeSlackAPI(messages=[{"ts": "100.1", "text": "Pizza!", "user": "U1"}])
        socket_listener.reconcile(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        self.assertTrue(self.state_path.exists())
        self.assertIn("100.1", slack_source.load_state(self.state_path))


class ReconciliationLoopTests(SocketListenerTestCase):
    def test_runs_reconcile_until_stopped(self):
        calls = []
        stop_event = threading.Event()

        def fake_reconcile(*args):
            calls.append(args)
            stop_event.set()

        original = socket_listener.reconcile
        socket_listener.reconcile = fake_reconcile
        try:
            socket_listener.reconciliation_loop(0.01, stop_event, "a", "b")
        finally:
            socket_listener.reconcile = original
        self.assertEqual(calls, [("a", "b")])

    def test_a_failing_pass_does_not_raise(self):
        stop_event = threading.Event()
        call_count = {"n": 0}

        def failing_reconcile(*args):
            call_count["n"] += 1
            stop_event.set()
            raise RuntimeError("boom")

        original = socket_listener.reconcile
        socket_listener.reconcile = failing_reconcile
        try:
            socket_listener.reconciliation_loop(0.01, stop_event)
        finally:
            socket_listener.reconcile = original
        self.assertEqual(call_count["n"], 1)


class MakeRequestListenerTests(SocketListenerTestCase):
    class FakeClient:
        def __init__(self):
            self.acked = []

        def send_socket_mode_response(self, response):
            self.acked.append(response)

    class FakeRequest:
        def __init__(self, type, payload, envelope_id="e1"):
            self.type = type
            self.payload = payload
            self.envelope_id = envelope_id

    def test_events_api_message_for_our_channel_is_handled(self):
        api = FakeSlackAPI()
        listener = socket_listener.make_request_listener(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        client = self.FakeClient()
        req = self.FakeRequest("events_api",
                                {"event": {"type": "message", "ts": "100.1", "text": "hi", "user": "U1", "channel": "C1"}})
        listener(client, req)
        self.assertEqual(len(client.acked), 1)
        state = slack_source.load_state(self.state_path)
        self.assertIn("100.1", state)

    def test_message_for_a_different_channel_is_acked_but_ignored(self):
        api = FakeSlackAPI()
        listener = socket_listener.make_request_listener(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        client = self.FakeClient()
        req = self.FakeRequest("events_api",
                                {"event": {"type": "message", "ts": "100.1", "text": "hi", "user": "U1", "channel": "C2"}})
        listener(client, req)
        self.assertEqual(len(client.acked), 1)
        self.assertFalse(self.state_path.exists())

    def test_non_message_event_type_is_acked_but_ignored(self):
        # e.g. app_mention -- subscribed events other than "message" must
        # not be misread as a new top-level post.
        api = FakeSlackAPI()
        listener = socket_listener.make_request_listener(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        client = self.FakeClient()
        req = self.FakeRequest("events_api",
                                {"event": {"type": "app_mention", "ts": "100.1", "text": "hi", "channel": "C1"}})
        listener(client, req)
        self.assertEqual(len(client.acked), 1)
        self.assertFalse(self.state_path.exists())

    def test_non_events_api_request_is_ignored(self):
        api = FakeSlackAPI()
        listener = socket_listener.make_request_listener(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        client = self.FakeClient()
        req = self.FakeRequest("hello", {})
        listener(client, req)
        self.assertEqual(len(client.acked), 0)

    def test_handler_exception_does_not_propagate(self):
        class ExplodingAPI(FakeSlackAPI):
            def post_message(self, channel, text, thread_ts=None):
                raise RuntimeError("boom")

        api = ExplodingAPI()
        listener = socket_listener.make_request_listener(
            self.cfg, self.slack_cfg, self.state_path, self.source_dir, self.audit_path, api,
        )
        client = self.FakeClient()
        req = self.FakeRequest("events_api",
                                {"event": {"type": "message", "ts": "100.1", "text": "hi", "user": "U1", "channel": "C1"}})
        listener(client, req)  # must not raise
        self.assertEqual(len(client.acked), 1)


if __name__ == "__main__":
    unittest.main()
