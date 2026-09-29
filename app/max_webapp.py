"""Verify MAX Mini App launch data before identifying a resident."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class MaxWebAppAuthError(ValueError):
    pass


def verify_init_data(raw: str, bot_token: str, *, now: int | None = None) -> str:
    """Return the signed MAX user id; reject modified, stale, or ambiguous data."""
    if not bot_token:
        raise MaxWebAppAuthError("Бот MAX пока не настроен.")
    if not isinstance(raw, str) or not raw or len(raw) > 8192:
        raise MaxWebAppAuthError("Откройте мини-приложение из бота MAX.")
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise MaxWebAppAuthError("Не удалось проверить запуск MAX. Откройте приложение снова.") from exc
    values = dict(pairs)
    if len(values) != len(pairs) or not values.get("hash"):
        raise MaxWebAppAuthError("Не удалось проверить запуск MAX. Откройте приложение снова.")
    supplied = values.pop("hash")
    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, launch_params.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied):
        raise MaxWebAppAuthError("Не удалось подтвердить аккаунт MAX. Откройте приложение снова.")
    try:
        auth_date = int(values["auth_date"])
        user = json.loads(values["user"])
        user_id = user["id"]
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise MaxWebAppAuthError("Не удалось получить данные пользователя MAX.") from exc
    clock = int(time.time()) if now is None else now
    if auth_date < clock - 3600 or auth_date > clock + 60:
        raise MaxWebAppAuthError("Сессия MAX истекла. Откройте мини-приложение снова.")
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise MaxWebAppAuthError("Не удалось подтвердить пользователя MAX.")
    return str(user_id)
