"""Small SQLite store for local hackathon tickets and MAX dialog state."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


STATUSES = ("accepted", "assigned", "done")
NEXT_STATUS = {"accepted": "assigned", "assigned": "done"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class TicketStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    house_id TEXT NOT NULL,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    status TEXT NOT NULL,
                    answers_json TEXT NOT NULL,
                    route_json TEXT NOT NULL,
                    photo_path TEXT,
                    max_photo_token TEXT,
                    max_user_id TEXT,
                    seconds_to_create INTEGER
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id TEXT NOT NULL REFERENCES tickets(id),
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS bot_sessions (
                    user_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS processed_updates (
                    event_key TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    reply_user_id TEXT NOT NULL,
                    reply_text TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS bot_cursors (
                    name TEXT PRIMARY KEY,
                    marker TEXT NOT NULL
                );
            """)

    @staticmethod
    def _row(row):
        if row is None:
            return None
        item = dict(row)
        item["answers"] = json.loads(item.pop("answers_json"))
        item["route"] = json.loads(item.pop("route_json"))
        return item

    def create(self, *, house_id, text, category, answers, route, photo_path=None,
               max_photo_token=None, max_user_id=None, seconds_to_create=None):
        ticket_id = "M-" + uuid.uuid4().hex[:10].upper()
        now = now_iso()
        with self._connect() as db:
            db.execute("""
                INSERT INTO tickets(id,created_at,updated_at,house_id,text,category,status,
                                    answers_json,route_json,photo_path,max_photo_token,max_user_id,
                                    seconds_to_create)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (ticket_id, now, now, house_id, text, category, "accepted",
                  json.dumps(answers, ensure_ascii=False), json.dumps(route, ensure_ascii=False),
                  photo_path, max_photo_token, max_user_id, seconds_to_create))
            db.execute("INSERT INTO events(ticket_id,status,created_at,note) VALUES(?,?,?,?)",
                       (ticket_id, "accepted", now, "Заявка создана"))
        return self.get(ticket_id)

    def get(self, ticket_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                return None
            item = self._row(row)
            item["events"] = [dict(event) for event in db.execute(
                "SELECT status,created_at,note FROM events WHERE ticket_id=? ORDER BY id",
                (ticket_id,),
            )]
            return item

    def list(self, limit=50):
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            rows = db.execute("SELECT * FROM tickets ORDER BY created_at DESC,id DESC LIMIT ?", (limit,))
            return [self._row(row) for row in rows]

    def list_for_max_user(self, user_id, limit=30):
        limit = max(1, min(int(limit), 100))
        with self._connect() as db:
            rows = db.execute("""SELECT * FROM tickets WHERE max_user_id=?
                ORDER BY created_at DESC,id DESC LIMIT ?""", (str(user_id), limit))
            return [self._row(row) for row in rows]

    def set_status(self, ticket_id, status):
        if status not in STATUSES:
            raise ValueError("unknown status")
        with self._connect() as db:
            row = db.execute("SELECT status FROM tickets WHERE id=?", (ticket_id,)).fetchone()
            if row is None:
                return None
            if NEXT_STATUS.get(row["status"]) != status:
                raise ValueError(f"invalid status transition: {row['status']} → {status}")
            now = now_iso()
            db.execute("UPDATE tickets SET status=?,updated_at=? WHERE id=?", (status, now, ticket_id))
            db.execute("INSERT INTO events(ticket_id,status,created_at,note) VALUES(?,?,?,?)",
                       (ticket_id, status, now, "Статус изменён в демо-кабинете"))
        return self.get(ticket_id)

    def summary(self):
        with self._connect() as db:
            counts = {row["status"]: row["n"] for row in db.execute(
                "SELECT status,COUNT(*) AS n FROM tickets GROUP BY status")}
            seconds = db.execute("SELECT AVG(seconds_to_create) FROM tickets WHERE seconds_to_create IS NOT NULL").fetchone()[0]
        return {"total": sum(counts.values()), **{status: counts.get(status, 0) for status in STATUSES},
                "avg_seconds_to_create": round(seconds) if seconds is not None else None}

    def get_session(self, user_id):
        with self._connect() as db:
            row = db.execute("SELECT state_json FROM bot_sessions WHERE user_id=?", (str(user_id),)).fetchone()
        return json.loads(row[0]) if row else None

    def put_session(self, user_id, state):
        with self._connect() as db:
            db.execute("""INSERT INTO bot_sessions(user_id,state_json,updated_at) VALUES(?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at""",
                (str(user_id), json.dumps(state, ensure_ascii=False), now_iso()))

    def get_update(self, event_key):
        with self._connect() as db:
            row = db.execute("SELECT reply_user_id,reply_text,delivered FROM processed_updates WHERE event_key=?",
                             (event_key,)).fetchone()
        return dict(row) if row else None

    def save_update(self, event_key, reply):
        with self._connect() as db:
            db.execute("""INSERT OR IGNORE INTO processed_updates
                (event_key,created_at,reply_user_id,reply_text,delivered) VALUES(?,?,?,?,0)""",
                (event_key, now_iso(), str(reply[0]), reply[1]))

    def mark_update_delivered(self, event_key):
        with self._connect() as db:
            db.execute("UPDATE processed_updates SET delivered=1 WHERE event_key=?", (event_key,))

    def get_max_marker(self):
        with self._connect() as db:
            row = db.execute("SELECT marker FROM bot_cursors WHERE name='max'").fetchone()
        return row[0] if row else None

    def set_max_marker(self, marker):
        marker = str(marker)
        if not marker.isdecimal():
            raise ValueError("MAX marker must be a non-negative integer")
        with self._connect() as db:
            db.execute("""INSERT INTO bot_cursors(name,marker) VALUES('max',?)
                ON CONFLICT(name) DO UPDATE SET marker=excluded.marker""", (marker,))
