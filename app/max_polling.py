"""Run the actual MAX chat bot locally through development Long Polling."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from threading import Thread
from urllib.error import HTTPError, URLError

from .max_bot import MaxClient, MaxDialog, event_key
from .service import RequestService
from .storage import TicketStore


class MaxPollingError(RuntimeError):
    pass


class MaxPoller:
    def __init__(self, client: MaxClient, dialog: MaxDialog, store: TicketStore):
        self.client = client
        self.dialog = dialog
        self.store = store

    def check_ready(self):
        bot = self.client.get_me()
        if not isinstance(bot, dict) or not bot.get("is_bot"):
            raise MaxPollingError("MAX token does not belong to a bot")
        subscriptions = self.client.get_subscriptions()
        if not isinstance(subscriptions, dict):
            raise MaxPollingError("MAX returned an invalid subscriptions response")
        if subscriptions.get("subscriptions"):
            raise MaxPollingError(
                "This bot has an active webhook. MAX does not deliver Long Polling events "
                "while a webhook is active. Use a new demo bot or disable its webhook in MAX."
            )
        return bot

    def poll_once(self):
        response = self.client.get_updates(marker=self.store.get_max_marker())
        if not isinstance(response, dict) or not isinstance(response.get("updates"), list):
            raise MaxPollingError("MAX returned an invalid updates response")
        updates = response["updates"]
        for update in updates:
            if not isinstance(update, dict):
                raise MaxPollingError("MAX returned an invalid update")
            reply = self.dialog.handle(update)
            if reply:
                self.client.send_text(*reply)
                self.store.mark_update_delivered(event_key(update))
        marker = response.get("marker")
        if marker is not None:
            self.store.set_max_marker(marker)
        return len(updates)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Run the Moscow ЖКХ demo bot inside MAX using development Long Polling."
    )
    parser.add_argument("--check", action="store_true",
                        help="verify the MAX bot token and webhook state, then exit")
    args = parser.parse_args(argv)

    token = os.environ.get("MAX_BOT_TOKEN")
    if not token:
        if not sys.stdin.isatty():
            parser.error("set MAX_BOT_TOKEN or run interactively to enter the token securely")
        token = getpass.getpass("MAX bot token (hidden): ").strip()
    if not token:
        parser.error("MAX bot token is empty")

    from .service import DATA

    store = TicketStore(DATA / "demo.sqlite3")
    client = MaxClient(token)
    poller = MaxPoller(client, MaxDialog(RequestService(store), store), store)
    try:
        bot = poller.check_ready()
    except HTTPError as exc:
        if exc.code == 401:
            parser.exit(1, "MAX rejected the bot token (HTTP 401).\n")
        parser.exit(1, f"MAX API returned HTTP {exc.code} during bot check.\n")
    except (URLError, TimeoutError, OSError, ValueError, MaxPollingError) as exc:
        parser.exit(1, f"Cannot start MAX demo: {exc}\n")

    name = bot.get("username")
    print(f"MAX bot ready: {bot.get('first_name') or name or bot['user_id']}", flush=True)
    if name:
        print(f"Open in MAX: https://max.ru/{name}", flush=True)
    if args.check:
        return 0
    from .server import build_server

    host = os.environ.get("APP_HOST", "127.0.0.1")
    port = int(os.environ.get("APP_PORT", "8000"))
    os.environ.setdefault("APP_ADMIN_KEY", "hackathon-demo")
    try:
        server = build_server(host, port, max_token=token)
    except OSError as exc:
        parser.exit(1, f"Cannot start local dashboard on {host}:{port}: {exc}. "
                         "Stop the other server or set APP_PORT.\n")
    Thread(target=server.serve_forever, daemon=True).start()
    print(f"Local dispatcher dashboard: http://{host}:{port}/admin", flush=True)
    if os.environ["APP_ADMIN_KEY"] == "hackathon-demo":
        print("Local demo admin key: hackathon-demo", flush=True)
    else:
        print("Use the APP_ADMIN_KEY value from your environment in the dashboard.", flush=True)
    print("Send /start in MAX. Keep this terminal open; Ctrl+C stops the bot.", flush=True)

    try:
        while True:
            try:
                count = poller.poll_once()
                if count == 0:
                    time.sleep(1)
            except HTTPError as exc:
                if exc.code in {401, 403}:
                    parser.exit(1, f"MAX rejected the bot request (HTTP {exc.code}).\n")
                print(f"MAX API error HTTP {exc.code}; retrying.", file=sys.stderr, flush=True)
                time.sleep(3)
            except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                print(f"MAX connection error: {exc}; retrying.", file=sys.stderr, flush=True)
                time.sleep(3)
    except KeyboardInterrupt:
        print("\nMAX demo stopped.")
        return 0
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
