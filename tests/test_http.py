import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.server import build_server


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.previous_key = os.environ.get("APP_ADMIN_KEY")
        os.environ["APP_ADMIN_KEY"] = "test-admin-key"
        self.server = build_server("127.0.0.1", 0, Path(self.tmp.name) / "tickets.sqlite3")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        if self.previous_key is None:
            os.environ.pop("APP_ADMIN_KEY", None)
        else:
            os.environ["APP_ADMIN_KEY"] = self.previous_key
        self.tmp.cleanup()

    def request(self, path, method="GET", data=None, headers=None):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
        request = urllib.request.Request(
            self.base + path, data=body, method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def test_end_to_end_http(self):
        self.assertEqual(self.request("/api/health")[1]["city"], "Москва")
        payload = {"house_id": "demo_1", "text": "В подъезде не горит свет",
                   "answers": {"location": "подъезд", "danger": "нет"}}
        triage = self.request("/api/triage", "POST", payload)[1]
        self.assertEqual(triage["category"], "entrance_electricity")
        code, ticket = self.request("/api/tickets", "POST", payload)
        self.assertEqual(code, 201)
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.request(f"/api/tickets/{ticket['id']}/status", "PATCH", {"status": "assigned"})
        self.assertEqual(context.exception.code, 403)
        code, changed = self.request(f"/api/tickets/{ticket['id']}/status", "PATCH", {"status": "assigned"},
                                     {"X-Admin-Key": "test-admin-key"})
        self.assertEqual(code, 200)
        self.assertEqual(changed["ticket"]["status"], "assigned")
        self.assertEqual(self.request("/api/summary")[1]["assigned"], 1)

    def test_head_checks_public_page_without_body(self):
        request = urllib.request.Request(self.base + "/mini", method="HEAD")
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers.get("Content-Type"), "text/html")
            self.assertGreater(int(response.headers["Content-Length"]), 0)
            self.assertEqual(response.read(), b"")


if __name__ == "__main__":
    unittest.main()
