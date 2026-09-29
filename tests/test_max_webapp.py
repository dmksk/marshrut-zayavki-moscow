import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app.max_webapp import MaxWebAppAuthError, verify_init_data
from app.server import build_server

TOKEN = "test-bot-token"


def signed_data(user_id=101, auth_date=None):
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "sample-query",
        "user": json.dumps({"id": user_id, "first_name": "Житель"}, ensure_ascii=False, separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


class MaxWebAppTests(unittest.TestCase):
    def test_verifies_signature_and_age(self):
        raw = signed_data()
        self.assertEqual(verify_init_data(raw, TOKEN), "101")
        with self.assertRaises(MaxWebAppAuthError):
            verify_init_data(raw.replace("101", "102"), TOKEN)
        with self.assertRaises(MaxWebAppAuthError):
            verify_init_data(raw + "&hash=another", TOKEN)
        with self.assertRaises(MaxWebAppAuthError):
            verify_init_data(signed_data(auth_date=int(time.time()) - 4000), TOKEN)

    def test_mini_app_ticket_belongs_to_verified_max_user(self):
        tmp = tempfile.TemporaryDirectory()
        old_public = os.environ.get("APP_PUBLIC")
        old_admin = os.environ.get("APP_ADMIN_KEY")
        os.environ["APP_PUBLIC"] = "1"
        os.environ["APP_ADMIN_KEY"] = "test-admin"
        server = build_server("127.0.0.1", 0, Path(tmp.name) / "tickets.sqlite3", max_token=TOKEN)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"

        def request(path, method="GET", payload=None, headers=None):
            body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
            req = urllib.request.Request(base + path, data=body, method=method,
                                         headers={"Content-Type": "application/json", **(headers or {})})
            with urllib.request.urlopen(req, timeout=5) as response:
                return response.status, json.load(response)

        try:
            with urllib.request.urlopen(base + "/mini", timeout=5) as page:
                html = page.read().decode()
            self.assertIn("max-web-app.js", html)
            self.assertIn('id="myTickets"', html)
            payload = {"house_id": "demo_1", "text": "В подъезде не горит свет",
                       "answers": {"location": "подъезд", "danger": "нет"}}
            signed = {"X-Max-Init-Data": signed_data(101)}
            with self.assertRaises(urllib.error.HTTPError) as no_auth:
                request("/api/max/mini/tickets", "POST", payload)
            self.assertEqual(no_auth.exception.code, 401)
            code, ticket = request("/api/max/mini/tickets", "POST", payload, signed)
            self.assertEqual(code, 201)
            self.assertEqual(ticket["max_user_id"], "101")
            self.assertEqual(len(request("/api/max/mini/tickets", headers=signed)[1]), 1)
            self.assertEqual(request(f"/api/max/mini/tickets/{ticket['id']}", headers=signed)[1]["id"], ticket["id"])
            with self.assertRaises(urllib.error.HTTPError) as other_user:
                request(f"/api/max/mini/tickets/{ticket['id']}", headers={"X-Max-Init-Data": signed_data(102)})
            self.assertEqual(other_user.exception.code, 404)
            with self.assertRaises(urllib.error.HTTPError) as exposed:
                request("/api/tickets")
            self.assertEqual(exposed.exception.code, 403)
            with self.assertRaises(urllib.error.HTTPError) as simulator:
                request("/api/demo/max", "POST", {"text": "/start"})
            self.assertEqual(simulator.exception.code, 403)
            with patch("app.max_bot.MaxClient.send_text") as send:
                code, changed = request(f"/api/tickets/{ticket['id']}/status", "PATCH",
                                        {"status": "assigned"}, {"X-Admin-Key": "test-admin"})
                self.assertEqual(code, 200)
                self.assertEqual(changed["max_notification"], "sent")
                send.assert_called_once_with("101", f"Заявка {ticket['id']}: назначен исполнитель")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            if old_public is None:
                os.environ.pop("APP_PUBLIC", None)
            else:
                os.environ["APP_PUBLIC"] = old_public
            if old_admin is None:
                os.environ.pop("APP_ADMIN_KEY", None)
            else:
                os.environ["APP_ADMIN_KEY"] = old_admin
            tmp.cleanup()

    def test_local_preview_cannot_be_used_in_public_mode(self):
        tmp = tempfile.TemporaryDirectory()
        old_public = os.environ.get("APP_PUBLIC")
        old_token = os.environ.get("MAX_BOT_TOKEN")
        os.environ.pop("APP_PUBLIC", None)
        os.environ.pop("MAX_BOT_TOKEN", None)
        server = build_server("127.0.0.1", 0, Path(tmp.name) / "tickets.sqlite3")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/api/max/mini/tickets"
        headers = {"Content-Type": "application/json", "X-Mini-Preview": "1"}
        payload = {"house_id": "demo_1", "text": "В подъезде не горит свет",
                   "answers": {"location": "подъезд", "danger": "нет"}}
        try:
            request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                             method="POST", headers=headers)
            with urllib.request.urlopen(request, timeout=5) as response:
                self.assertEqual(json.load(response)["max_user_id"], "preview-user")
            os.environ["APP_PUBLIC"] = "1"
            with self.assertRaises(urllib.error.HTTPError) as blocked:
                urllib.request.urlopen(request, timeout=5)
            self.assertEqual(blocked.exception.code, 401)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)
            if old_public is None:
                os.environ.pop("APP_PUBLIC", None)
            else:
                os.environ["APP_PUBLIC"] = old_public
            if old_token is None:
                os.environ.pop("MAX_BOT_TOKEN", None)
            else:
                os.environ["MAX_BOT_TOKEN"] = old_token
            tmp.cleanup()
