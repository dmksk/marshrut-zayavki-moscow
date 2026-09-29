"""MAX webhook dialog, kept separate from local HTTP/UI code."""

from __future__ import annotations

import json
import os
import ssl
import urllib.parse
import urllib.request
from pathlib import Path

from .service import RequestService, ValidationError
from .storage import TicketStore

API_ROOT = "https://platform-api2.max.ru"
DEFAULT_MAX_CA = Path(__file__).resolve().parents[1] / "certs" / "russian_trusted_root_ca.pem"
STATUS_RU = {"accepted": "принято", "assigned": "назначен исполнитель", "done": "выполнено"}


def event_key(update):
    message = update.get("message") or {}
    body = message.get("body") or {}
    sender = message.get("sender") or update.get("user") or {}
    return str(body.get("mid") or f"{update.get('update_type')}:{sender.get('user_id')}:{update.get('timestamp')}")


class MaxClient:
    def __init__(self, token=None, ca_bundle=None):
        self.token = token or os.environ.get("MAX_BOT_TOKEN")
        self.ca_bundle = ca_bundle or os.environ.get("MAX_CA_BUNDLE") or str(DEFAULT_MAX_CA)
        self.ssl_context = ssl.create_default_context()
        if self.ca_bundle:
            self.ssl_context.load_verify_locations(cafile=self.ca_bundle)

    def _get(self, path, *, params=None, timeout=10):
        if not self.token:
            raise RuntimeError("MAX_BOT_TOKEN is not configured")
        url = API_ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"Authorization": self.token})
        with urllib.request.urlopen(request, timeout=timeout, context=self.ssl_context) as response:
            return json.load(response)

    def get_me(self):
        return self._get("/me")

    def get_subscriptions(self):
        return self._get("/subscriptions")

    def get_updates(self, *, marker=None, timeout=20):
        params = {"limit": 100, "timeout": timeout, "types": "message_created,bot_started"}
        if marker is not None:
            params["marker"] = marker
        return self._get("/updates", params=params, timeout=timeout + 10)

    def send_text(self, user_id, text):
        if not self.token:
            raise RuntimeError("MAX_BOT_TOKEN is not configured")
        url = API_ROOT + "/messages?" + urllib.parse.urlencode({"user_id": int(user_id)})
        request = urllib.request.Request(
            url, data=json.dumps({"text": text[:4000]}, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": self.token, "Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(request, timeout=8, context=self.ssl_context) as response:
            return json.load(response)


def _photo_token(message):
    for attachment in (message.get("body") or {}).get("attachments") or []:
        if attachment.get("type") == "image":
            payload = attachment.get("payload") or {}
            return payload.get("token") or payload.get("photo_id")
    return None


def _route_text(result):
    card = result["route_card"]
    if card is None:
        return "Нужно уточнение: " + "; ".join(result["follow_up_questions"])
    lines = [f"Тема: {result['category_name']}", f"Куда: {card['recipient']}"]
    if result["immediate_action"]:
        lines.insert(0, "⚠️ " + result["immediate_action"])
    lines += ["Сейчас: " + card["what_now"], "Приложите: " + ", ".join(card["attach"]),
              "Срок: " + card["response_expectation"]]
    return "\n".join(lines)


class MaxDialog:
    def __init__(self, service: RequestService, store: TicketStore):
        self.service, self.store = service, store

    def handle(self, update):
        kind = update.get("update_type")
        if kind not in {"message_created", "bot_started"}:
            return None
        message = update.get("message") or {}
        chat_type = (message.get("recipient") or {}).get("chat_type")
        if chat_type and chat_type != "dialog":
            return None
        sender = message.get("sender") or update.get("user") or {}
        user_id = sender.get("user_id")
        if user_id is None:
            return None
        key = event_key(update)
        cached = self.store.get_update(key)
        if cached:
            return None if cached["delivered"] else (cached["reply_user_id"], cached["reply_text"])
        reply = self._apply(update)
        if reply:
            self.store.save_update(key, reply)
        return reply

    def _apply(self, update):
        kind = update.get("update_type")
        if kind not in {"message_created", "bot_started"}:
            return None
        message = update.get("message") or {}
        sender = message.get("sender") or update.get("user") or {}
        if sender.get("is_bot"):
            return None
        user_id = sender.get("user_id")
        if user_id is None:
            return None
        body = message.get("body") or {}
        text = (body.get("text") or "").strip()
        state = self.store.get_session(user_id) or {"stage": "house"}
        photo_token = _photo_token(message)
        if photo_token:
            state["photo_token"] = photo_token
            if not text:
                self.store.put_session(user_id, state)
                return user_id, "Фото добавлено. Продолжим: " + self._prompt(state)
        if kind == "bot_started" or text.lower() in {"/start", "старт", "новая заявка"}:
            state = {"stage": "house"}
            self.store.put_session(user_id, state)
            if os.environ.get("MAX_MINIAPP_URL"):
                return user_id, ("Привет! Откройте мини-приложение кнопкой «Открыть» в чате: "
                                 "там можно описать проблему, создать заявку и смотреть статус. "
                                 "Если хотите пройти сценарий сообщениями, выберите демо-дом: 1 или 2.")
            return user_id, "Привет! Помогу направить заявку по ЖКХ Москвы. Выберите демо-дом: 1 или 2."
        if text.lower().startswith("/status "):
            ticket_id = text.split(maxsplit=1)[1].strip().upper()
            ticket = self.store.get(ticket_id)
            if ticket and ticket["max_user_id"] == str(user_id):
                return user_id, f"{ticket_id}: {STATUS_RU[ticket['status']]}"
            return user_id, "Не нашёл вашу заявку. Проверьте номер."
        stage = state.get("stage", "house")
        if stage == "house":
            house = {"1": "demo_1", "2": "demo_2"}.get(text)
            if not house:
                return user_id, "Выберите дом цифрой: 1 или 2."
            state.update({"house_id": house, "stage": "description", "answers": {}})
            reply = "Опишите проблему одним сообщением. Можно добавить фото."
        elif stage == "description":
            if len(text) < 2:
                return user_id, "Опишите проблему словами, чтобы определить тему заявки."
            state.update({"text": text[:1500], "stage": "location"})
            reply = "Где проблема? 1 — квартира, 2 — подъезд, 3 — двор, 4 — улица."
        elif stage == "location":
            location = {"1": "квартира", "2": "подъезд", "3": "двор", "4": "улица"}.get(text)
            if not location:
                return user_id, "Укажите место цифрой: 1, 2, 3 или 4."
            state["answers"]["location"] = location
            state["stage"] = "danger"
            reply = "Есть сейчас опасность для людей? Ответьте да или нет."
        elif stage == "danger":
            if text.lower() not in {"да", "нет"}:
                return user_id, "Ответьте да или нет. При непосредственной опасности звоните 112."
            state["answers"]["danger"] = text.lower()
            result = self.service.classify(state)
            if result["category"] == "yard" or state["answers"].get("location") == "двор":
                state["stage"] = "territory"
                reply = "Чья территория? 1 — дома, 2 — городская, 3 — не знаю."
            else:
                reply = self._after_questions(state, result)
        elif stage == "territory":
            territory = {"1": "территория дома", "2": "городская", "3": "не знаю"}.get(text)
            if not territory:
                return user_id, "Ответьте 1, 2 или 3."
            state["answers"]["territory_owner"] = territory
            result = self.service.classify(state)
            reply = self._after_questions(state, result)
        elif stage == "category":
            selected = {"1": "leak", "2": "lift", "3": "heating", "4": "entrance_electricity",
                        "5": "trash", "6": "yard"}.get(text)
            if not selected:
                return user_id, "Выберите тему цифрой от 1 до 6."
            state["answers"]["selected_category"] = selected
            result = self.service.classify(state)
            if selected == "yard" and state["answers"].get("territory_owner") not in {"территория дома", "городская"}:
                state["stage"] = "territory"
                reply = "Чья территория? 1 — дома, 2 — городская, 3 — не знаю."
            else:
                reply = self._after_questions(state, result)
        elif stage == "confirm":
            if text.lower() == "да":
                try:
                    ticket = self.service.create(state, max_user_id=user_id,
                                                 max_photo_token=state.get("photo_token"))
                except ValidationError as exc:
                    state["stage"] = "category"
                    reply = f"Нужно уточнение: {exc}. Выберите тему: 1 протечка, 2 лифт, 3 отопление, 4 свет, 5 мусор, 6 двор."
                else:
                    state = {"stage": "house", "last_ticket_id": ticket["id"]}
                    reply = f"Заявка {ticket['id']} создана. Статус: принято. Проверка: /status {ticket['id']}. Для новой заявки напишите /start."
            elif text.lower() == "нет":
                state = {"stage": "house"}
                reply = "Хорошо. Чтобы начать заново, выберите дом: 1 или 2."
            else:
                return user_id, "Создать демо-заявку? Ответьте да или нет. Фото можно отправить сейчас."
        else:
            state = {"stage": "house"}
            reply = "Выберите демо-дом: 1 или 2."
        self.store.put_session(user_id, state)
        return user_id, reply

    def _after_questions(self, state, result):
        if result["route_card"] is None:
            state["stage"] = "category"
            return "Уточните тему: 1 протечка, 2 лифт, 3 отопление, 4 свет в подъезде, 5 мусор, 6 двор."
        state["stage"] = "confirm"
        return _route_text(result) + "\n\nСоздать демо-заявку? Ответьте да или нет."

    @staticmethod
    def _prompt(state):
        return {"house": "Выберите дом: 1 или 2.", "description": "Опишите проблему.",
                "location": "Где проблема? 1 квартира, 2 подъезд, 3 двор, 4 улица.",
                "danger": "Есть опасность? да/нет.", "territory": "Чья территория? 1 дома, 2 городская, 3 не знаю.",
                "category": "Выберите тему цифрой 1–6.", "confirm": "Создать заявку? да/нет."}.get(state.get("stage"), "Продолжим.")
