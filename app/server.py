"""Zero-framework local demo server; MAX webhook can sit behind HTTPS reverse proxy."""

from __future__ import annotations

import hmac
import json
import mimetypes
import os
import re
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError

from .max_bot import MaxClient, MaxDialog, STATUS_RU, event_key
from .max_webapp import MaxWebAppAuthError, verify_init_data
from .service import RequestService, ValidationError
from .storage import TicketStore

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
DATA = ROOT / "data"
MAX_BODY = 5 * 1024 * 1024
TICKET_PATH = re.compile(r"^/api/tickets/(M-[A-F0-9]{10})(?:/(photo|status))?$")
MINI_TICKET_PATH = re.compile(r"^/api/max/mini/tickets/(M-[A-F0-9]{10})$")


def build_server(host="127.0.0.1", port=8000, db_path=None, max_token=None):
    store_path = Path(db_path or DATA / "demo.sqlite3")
    store = TicketStore(store_path)
    service = RequestService(store, store_path.parent / "uploads")
    dialog = MaxDialog(service, store)
    max_client = MaxClient(max_token)

    class Handler(BaseHTTPRequestHandler):
        server_version = "MarshrutZayavki/1.0"

        def _send(self, code, body, content_type="application/json; charset=utf-8"):
            if isinstance(body, (dict, list)):
                payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                payload = body.encode("utf-8")
            else:
                payload = body
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(payload)

        def _json(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValidationError("Неверный размер запроса.") from exc
            if not 0 < size <= MAX_BODY:
                raise ValidationError("Данные заявки должны быть не больше 5 МБ.")
            try:
                return json.loads(self.rfile.read(size))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValidationError("Не удалось прочитать данные заявки.") from exc

        def _error(self, code, message):
            self._send(code, {"error": message})

        def _admin_ok(self):
            secret = os.environ.get("APP_ADMIN_KEY", "")
            candidate = self.headers.get("X-Admin-Key", "")
            return bool(secret) and hmac.compare_digest(candidate, secret)

        def _mini_user(self):
            if (self.headers.get("X-Mini-Preview") == "1"
                    and os.environ.get("APP_PUBLIC") != "1"
                    and not max_client.token
                    and self.server.server_address[0] in {"127.0.0.1", "::1"}
                    and self.client_address[0] in {"127.0.0.1", "::1"}):
                return "preview-user"
            return verify_init_data(self.headers.get("X-Max-Init-Data", ""), max_client.token)

        def _legacy_ok(self):
            return os.environ.get("APP_PUBLIC") != "1" or self._admin_ok()

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/api/health":
                return self._send(200, {"ok": True, "city": "Москва", "model": "TF-IDF + LogisticRegression"})
            if path == "/api/houses":
                return self._send(200, service.houses())
            if path == "/api/max/mini/session":
                try:
                    user_id = self._mini_user()
                except MaxWebAppAuthError as exc:
                    return self._error(401, str(exc))
                return self._send(200, {"mode": "preview" if user_id == "preview-user" else "max",
                                        "notifications_available": user_id != "preview-user" and bool(max_client.token)})
            if path == "/api/max/mini/tickets" or MINI_TICKET_PATH.fullmatch(path):
                try:
                    user_id = self._mini_user()
                except MaxWebAppAuthError as exc:
                    return self._error(401, str(exc))
                if path == "/api/max/mini/tickets":
                    return self._send(200, store.list_for_max_user(user_id))
                ticket = store.get(MINI_TICKET_PATH.fullmatch(path).group(1))
                if ticket is None or ticket["max_user_id"] != user_id:
                    return self._error(404, "ticket not found")
                return self._send(200, ticket)
            if path == "/api/summary":
                if not self._legacy_ok():
                    return self._error(403, "admin key required")
                return self._send(200, store.summary())
            if path == "/api/tickets":
                if not self._legacy_ok():
                    return self._error(403, "admin key required")
                return self._send(200, store.list())
            match = TICKET_PATH.fullmatch(path)
            if match:
                if not self._legacy_ok():
                    return self._error(403, "admin key required")
                ticket = store.get(match.group(1))
                if ticket is None:
                    return self._error(404, "ticket not found")
                if match.group(2) == "photo":
                    name = ticket["photo_path"]
                    if not name:
                        return self._error(404, "photo not found")
                    photo = service.uploads / name
                    if not photo.is_file():
                        return self._error(404, "photo not found")
                    return self._send(200, photo.read_bytes(), mimetypes.guess_type(name)[0] or "image/jpeg")
                return self._send(200, ticket)
            static = {"/": "mini.html" if os.environ.get("APP_PUBLIC") == "1" else "index.html",
                      "/admin": "index.html", "/mini": "mini.html",
                      "/styles.css": "styles.css", "/app.js": "app.js",
                      "/mini.css": "mini.css", "/mini.js": "mini.js"}.get(path)
            if static:
                file = WEB / static
                return self._send(200, file.read_bytes(), mimetypes.guess_type(static)[0] or "text/plain")
            return self._error(404, "not found")

        def do_HEAD(self):
            return self.do_GET()

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            try:
                payload = self._json()
                if not isinstance(payload, dict):
                    raise ValidationError("JSON object expected")
                if path == "/api/triage":
                    return self._send(200, service.classify(payload))
                if path == "/api/max/mini/tickets":
                    try:
                        user_id = self._mini_user()
                    except MaxWebAppAuthError as exc:
                        return self._error(401, str(exc))
                    return self._send(201, service.create(payload, max_user_id=user_id,
                                                          require_mini_answers=True))
                if path == "/api/tickets":
                    if not self._legacy_ok():
                        return self._error(403, "admin key required")
                    return self._send(201, service.create(payload))
                if path == "/api/demo/max":
                    if os.environ.get("APP_PUBLIC") == "1" or self.client_address[0] not in {"127.0.0.1", "::1"}:
                        return self._error(403, "demo simulator is local only")
                    user_id = int(payload.get("user_id", 1001))
                    update = {"update_type": "message_created", "timestamp": int(time.time() * 1000),
                              "message": {"sender": {"user_id": user_id, "is_bot": False},
                                          "body": {"mid": uuid.uuid4().hex, "text": payload.get("text", "")}}}
                    reply = dialog.handle(update)
                    if reply:
                        store.mark_update_delivered(event_key(update))
                    return self._send(200, {"reply": reply[1] if reply else ""})
                if path == "/webhook/max":
                    secret = os.environ.get("MAX_WEBHOOK_SECRET", "")
                    if not secret or not max_client.token:
                        return self._error(503, "MAX integration is not configured")
                    if not hmac.compare_digest(self.headers.get("X-Max-Bot-Api-Secret", ""), secret):
                        return self._error(403, "invalid webhook secret")
                    reply = dialog.handle(payload)
                    if reply:
                        max_client.send_text(*reply)
                        store.mark_update_delivered(event_key(payload))
                    return self._send(200, {"ok": True})
                return self._error(404, "not found")
            except (ValidationError, ValueError, TypeError) as exc:
                return self._error(400, str(exc))
            except (HTTPError, URLError, TimeoutError) as exc:
                print(f"MAX delivery failed: {exc}", file=sys.stderr)
                return self._error(502, "MAX delivery failed")

        def do_PATCH(self):
            path = self.path.split("?", 1)[0]
            match = TICKET_PATH.fullmatch(path)
            if not match or match.group(2) != "status":
                return self._error(404, "not found")
            if not self._admin_ok():
                return self._error(403, "set APP_ADMIN_KEY and provide X-Admin-Key")
            try:
                payload = self._json()
                if not isinstance(payload, dict):
                    raise ValidationError("JSON object expected")
                ticket = store.set_status(match.group(1), payload.get("status"))
                if ticket is None:
                    return self._error(404, "ticket not found")
                notification = "not_applicable"
                if ticket["max_user_id"]:
                    notification = "not_configured"
                    if max_client.token:
                        try:
                            max_client.send_text(ticket["max_user_id"],
                                                 f"Заявка {ticket['id']}: {STATUS_RU[ticket['status']]}")
                            notification = "sent"
                        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
                            print(f"MAX status notification failed: {exc}", file=sys.stderr)
                            notification = "failed"
                return self._send(200, {"ticket": ticket, "max_notification": notification})
            except (ValidationError, ValueError, TypeError) as exc:
                return self._error(400, str(exc))

        def log_message(self, format, *args):
            print("%s %s" % (self.address_string(), format % args), file=sys.stderr)

    return ThreadingHTTPServer((host, port), Handler)


def main():
    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT") or os.environ.get("PORT", "8000"))
    server = build_server(host, port)
    print(f"Мини-приложение: http://{host}:{port}/mini")
    print(f"Кабинет диспетчера: http://{host}:{port}/admin")
    if not os.environ.get("APP_ADMIN_KEY"):
        print("APP_ADMIN_KEY не задан: смена статуса через API отключена.")
    server.serve_forever()


if __name__ == "__main__":
    main()
