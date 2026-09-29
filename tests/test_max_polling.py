import io
import json
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from app.max_bot import MaxClient, MaxDialog, event_key
from app.max_polling import MaxPoller, MaxPollingError
from app.service import RequestService
from app.storage import TicketStore


def update(mid="mid-1", text="/start"):
    return {
        "update_type": "message_created",
        "timestamp": 123,
        "message": {"sender": {"user_id": 101, "is_bot": False},
                    "recipient": {"chat_type": "dialog"},
                    "body": {"mid": mid, "text": text}},
    }


class FakeClient:
    def __init__(self):
        self.sent = []
        self.fail_send = False
        self.marker_seen = []
        self.response = {"updates": [update()], "marker": 42}
        self.subscriptions = {"subscriptions": []}

    def get_me(self):
        return {"is_bot": True, "username": "demo_bot", "user_id": 999}

    def get_subscriptions(self):
        return self.subscriptions

    def get_updates(self, *, marker):
        self.marker_seen.append(marker)
        return self.response

    def send_text(self, user_id, text):
        if self.fail_send:
            raise URLError("temporary connection failure")
        self.sent.append((user_id, text))


class MaxPollingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = TicketStore(root / "demo.sqlite3")
        service = RequestService(self.store, root / "uploads")
        self.client = FakeClient()
        self.poller = MaxPoller(self.client, MaxDialog(service, self.store), self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sends_reply_and_persists_marker_without_duplicates(self):
        self.assertEqual(self.poller.check_ready()["username"], "demo_bot")
        self.assertEqual(self.poller.poll_once(), 1)
        self.assertEqual(self.client.marker_seen, [None])
        self.assertEqual(self.store.get_max_marker(), "42")
        self.assertEqual(len(self.client.sent), 1)
        self.assertIn("Выберите демо-дом", self.client.sent[0][1])
        self.client.response["marker"] = 43
        self.poller.poll_once()
        self.assertEqual(self.client.marker_seen, [None, "42"])
        self.assertEqual(self.store.get_max_marker(), "43")
        self.assertEqual(len(self.client.sent), 1)

    def test_failed_delivery_retries_before_advancing_marker(self):
        self.client.fail_send = True
        with self.assertRaises(URLError):
            self.poller.poll_once()
        self.assertIsNone(self.store.get_max_marker())
        self.assertEqual(self.store.get_update(event_key(update()))["delivered"], 0)
        self.client.fail_send = False
        self.poller.poll_once()
        self.assertEqual(len(self.client.sent), 1)
        self.assertEqual(self.store.get_max_marker(), "42")
        self.assertEqual(self.store.get_update(event_key(update()))["delivered"], 1)

    def test_webhook_subscription_blocks_polling(self):
        self.client.subscriptions = {"subscriptions": [{"url": "https://example.ru/max"}]}
        with self.assertRaises(MaxPollingError):
            self.poller.check_ready()

    def test_max_client_uses_official_updates_endpoint_and_header(self):
        seen = {}

        def fake_urlopen(request, timeout, context):
            seen["url"] = request.full_url
            seen["token"] = request.get_header("Authorization")
            seen["timeout"] = timeout
            seen["context"] = context
            return io.BytesIO(json.dumps({"updates": [], "marker": 84}).encode())

        with patch("app.max_bot.urllib.request.urlopen", side_effect=fake_urlopen):
            response = MaxClient("test-token").get_updates(marker="42")
        parsed = urllib.parse.urlparse(seen["url"])
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "platform-api2.max.ru")
        self.assertEqual(parsed.path, "/updates")
        self.assertEqual(params["marker"], ["42"])
        self.assertEqual(params["types"], ["message_created,bot_started"])
        self.assertEqual(seen["token"], "test-token")
        self.assertGreater(seen["timeout"], int(params["timeout"][0]))
        self.assertTrue(seen["context"].verify_mode)
        self.assertEqual(response["marker"], 84)


if __name__ == "__main__":
    unittest.main()
