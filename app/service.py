"""Ticket creation is gated by clarification and deterministic safety rules."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from pathlib import Path

from .core import CATEGORIES, triage
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
            raise ValidationError("Ожидались данные заявки в формате JSON.")
        text = payload.get("text")
        if not isinstance(text, str) or not 2 <= len(text.strip()) <= 1500:
            raise ValidationError("Опишите проблему: от 2 до 1500 символов.")
        house_id = payload.get("house_id", "demo_1")
        answers = payload.get("answers") or {}
        if not isinstance(answers, dict):
            raise ValidationError("Ответы на вопросы имеют неверный формат.")
        try:
            return triage(text.strip(), house_id, answers)
        except ValueError as exc:
            if str(exc) == "unknown house_id":
                raise ValidationError("Выберите дом из списка.") from exc
            raise ValidationError("Не удалось определить маршрут. Проверьте описание и ответы.") from exc

    def create(self, payload, *, max_user_id=None, max_photo_token=None, require_mini_answers=False):
        result = self.classify(payload)
        if require_mini_answers:
            answers = payload.get("answers") or {}
            if payload.get("house_id") not in self.houses():
                raise ValidationError("Выберите дом из списка.")
            if answers.get("location") not in {"квартира", "подъезд", "двор", "улица"}:
                raise ValidationError("Укажите, где возникла проблема.")
            if answers.get("danger") not in {"да", "нет", "не знаю"}:
                raise ValidationError("Ответьте на вопрос об опасности.")
            if answers.get("selected_category") not in CATEGORIES:
                raise ValidationError("Подтвердите тему обращения.")
            if result["category"] == "yard" and answers.get("territory_owner") not in {"территория дома", "городская"}:
                raise ValidationError("Уточните, кому принадлежит территория двора.")
            if result["category"] == "trash" and answers.get("trash_context") not in {"дом/двор", "контейнеры", "не знаю"}:
                raise ValidationError("Уточните, где возникла проблема с мусором.")
        if result["route_card"] is None or result["category"] is None:
            raise ValidationError("Уточните ответы перед созданием заявки.")
        seconds = payload.get("seconds_to_create")
        if seconds is not None:
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 86400:
                raise ValidationError("Не удалось измерить время создания. Начните новую заявку.")
            seconds = round(seconds)
        photo_path = None
        if payload.get("photo_data_url"):
            photo_path = self._save_photo(payload["photo_data_url"])
        return self.store.create(
            house_id=payload.get("house_id", "demo_1"), text=payload["text"].strip(),
            category=result["category"], answers=payload.get("answers") or {},
            route=result["route_card"], photo_path=photo_path,
            max_user_id=str(max_user_id) if max_user_id is not None else None,
            max_photo_token=max_photo_token, seconds_to_create=seconds,
        )

    def _save_photo(self, data_url):
        if not isinstance(data_url, str) or "," not in data_url:
            raise ValidationError("Не удалось прочитать фото. Выберите его ещё раз.")
        header, encoded = data_url.split(",", 1)
        formats = {"data:image/jpeg;base64": (".jpg", b"\xff\xd8\xff"),
                   "data:image/png;base64": (".png", b"\x89PNG\r\n\x1a\n")}
        if header not in formats:
            raise ValidationError("Поддерживаются только фото JPG и PNG.")
        if len(encoded) > MAX_PHOTO_BYTES * 4 // 3 + 8:
            raise ValidationError("Фото должно быть не больше 3 МБ.")
        try:
            content = base64.b64decode(encoded, validate=True)
        except binascii.Error as exc:
            raise ValidationError("Не удалось прочитать фото. Выберите его ещё раз.") from exc
        suffix, signature = formats[header]
        if len(content) > MAX_PHOTO_BYTES or not content.startswith(signature):
            raise ValidationError("Фото повреждено или превышает 3 МБ.")
        self.uploads.mkdir(parents=True, exist_ok=True)
        name = uuid.uuid4().hex + suffix
        (self.uploads / name).write_bytes(content)
        return name
