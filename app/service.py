"""Ticket creation is gated by clarification and deterministic safety rules."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from pathlib import Path

from .core import triage
from .storage import TicketStore

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MAX_PHOTO_BYTES = 3 * 1024 * 1024


class ValidationError(ValueError):
    pass


class RequestService:
    def __init__(self, store: TicketStore, uploads: Path | None = None):
        self.store = store
        self.uploads = uploads or DATA / "uploads"

    def houses(self):
        return json.loads((DATA / "demo_houses.json").read_text(encoding="utf-8"))

    def classify(self, payload):
        if not isinstance(payload, dict):
            raise ValidationError("JSON object expected")
        text = payload.get("text")
        if not isinstance(text, str) or not 2 <= len(text.strip()) <= 1500:
            raise ValidationError("text must contain 2–1500 characters")
        house_id = payload.get("house_id", "demo_1")
        answers = payload.get("answers") or {}
        if not isinstance(answers, dict):
            raise ValidationError("answers must be an object")
        try:
            return triage(text.strip(), house_id, answers)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

    def create(self, payload, *, max_user_id=None, max_photo_token=None):
        result = self.classify(payload)
        if result["route_card"] is None or result["category"] is None:
            raise ValidationError("answer clarification questions before creating a ticket")
        photo_path = None
        if payload.get("photo_data_url"):
            photo_path = self._save_photo(payload["photo_data_url"])
        seconds = payload.get("seconds_to_create")
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 86400:
                raise ValidationError("seconds_to_create must be 0–86400")
            seconds = round(seconds)
        return self.store.create(
            house_id=payload.get("house_id", "demo_1"), text=payload["text"].strip(),
            category=result["category"], answers=payload.get("answers") or {},
            route=result["route_card"], photo_path=photo_path,
            max_user_id=str(max_user_id) if max_user_id is not None else None,
            max_photo_token=max_photo_token, seconds_to_create=seconds,
        )

    def _save_photo(self, data_url):
        if not isinstance(data_url, str) or "," not in data_url:
            raise ValidationError("invalid photo data URL")
        header, encoded = data_url.split(",", 1)
        formats = {"data:image/jpeg;base64": (".jpg", b"\xff\xd8\xff"),
                   "data:image/png;base64": (".png", b"\x89PNG\r\n\x1a\n")}
        if header not in formats:
            raise ValidationError("only PNG or JPEG photos are supported")
        if len(encoded) > MAX_PHOTO_BYTES * 4 // 3 + 8:
            raise ValidationError("photo is too large (3 MB maximum)")
        try:
            content = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValidationError("invalid photo encoding") from exc
        suffix, signature = formats[header]
        if len(content) > MAX_PHOTO_BYTES or not content.startswith(signature):
            raise ValidationError("invalid or oversized image")
        self.uploads.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + suffix
        (self.uploads / name).write_bytes(content)
        return name
