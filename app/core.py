"""Russian ML topic detection plus Moscow demo routing for a MAX bot backend."""

import json
from pathlib import Path
import re
from functools import lru_cache
import joblib

HERE = Path(__file__).resolve().parents[1] / "data"
CATEGORIES = {
    "leak": "Протечка",
    "lift": "Лифт",
    "heating": "Отопление и горячая вода",
    "entrance_electricity": "Электричество в общих зонах",
    "trash": "Мусор",
    "yard": "Двор",
}
THRESHOLD = 0.45
DOMAIN_PATTERN = re.compile(
    r"протеч|теч[её]т|течью|залив|затоп|труб|стояк|крыша|вода|"
    r"лифт|кабин|отоплен|батаре|радиатор|тепл|"
    r"подъезд|лестниц|щит|провод|свет|ламп|"
    r"мусор|контейнер|бак|отход|"
    r"двор|асфальт|голол[её]д|снег|дерев|люк|площадк|дорожк",
    re.I,
)

QUESTIONS = [
    {"key": "location", "text": "Где возникла проблема?", "options": ["квартира", "подъезд", "двор", "улица"]},
    {"key": "danger", "text": "Есть ли сейчас опасность для людей?", "options": ["да", "нет", "не знаю"]},
    {"key": "scope", "text": "Кого затронуло?", "options": ["одна квартира", "подъезд", "весь дом", "двор"]},
    {"key": "territory_owner", "text": "Если проблема во дворе: территория дома или города?", "options": ["территория дома", "городская", "не знаю"]},
    {"key": "has_photo", "text": "Можете приложить фото?", "options": ["да", "нет"]},
]

EMERGENCY_PATTERNS = [
    (re.compile(r"запах\s+газа|утечк[а-я]*\s+газа", re.I), "Выйдите из опасной зоны и позвоните 112 и в аварийную службу. Не включайте электроприборы."),
    (re.compile(r"(люди|реб[её]нок|человек).{0,35}(застрял|застряли).{0,25}лифт|лифт.{0,35}(застрял|застряли).{0,25}(люди|реб[её]нок|человек)", re.I), "Если в лифте люди, звоните 112 и в диспетчерскую. Не пытайтесь открыть двери самостоятельно."),
    (re.compile(r"дым|пожар|горит\s+проводк|искрит\s+щит", re.I), "Отойдите от опасного места и позвоните 112 и в аварийную службу."),
    (re.compile(r"вода.{0,35}(щит|провод|розет)|затоп.{0,35}(щит|провод|розет)|залива[а-я]*.{0,35}электрощит", re.I), "Не приближайтесь к электрооборудованию и позвоните 112 и в диспетчерскую."),
]
LOW_CONFIDENCE_RULES = [
    (re.compile(r"затопил|залило|залива[ею]|протеч|теч[её]т\s+вода", re.I), "leak"),
    (re.compile(r"мусоропровод|контейнер|мусор", re.I), "trash"),
    (re.compile(r"детск[а-я]*\s+площадк|калитк|выбоин|асфальт|\bяма\b", re.I), "yard"),
    (re.compile(r"в\s+подъезде\s+темно|на\s+лестнице\s+темно|щиток|электрощит", re.I), "entrance_electricity"),
]


@lru_cache(maxsize=1)
def _model():
    return joblib.load(HERE / "issue_model.joblib")


@lru_cache(maxsize=1)
def _houses():
    return json.loads((HERE / "demo_houses.json").read_text(encoding="utf-8"))


def triage(text, house_id="demo_1", answers=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    answers = answers or {}
    if not isinstance(answers, dict):
        raise ValueError("answers must be an object")
    house = _houses().get(house_id)
    if house is None:
        raise ValueError("unknown house_id")

    model = _model()
    probabilities = model.predict_proba([text])[0]
    ranked = sorted(zip(model.classes_, probabilities), key=lambda pair: pair[1], reverse=True)
    predicted, confidence = ranked[0]
    chosen = answers.get("selected_category")
    rule_category = None
    if confidence < THRESHOLD:
        rule_category = next((label for pattern, label in LOW_CONFIDENCE_RULES if pattern.search(text)), None)
    if chosen in CATEGORIES:
        category = chosen
        category_source = "resident_confirmation"
    elif rule_category:
        category = rule_category
        category_source = "keyword_rule_after_low_ml_confidence"
    elif predicted == "entrance_electricity" and answers.get("location") == "двор":
        category = "yard"
        category_source = "location_rule"
    else:
        category = predicted
        category_source = "ml_model"

    urgent_note = next((message for pattern, message in EMERGENCY_PATTERNS if pattern.search(text)), None)
    if not urgent_note and answers.get("danger") == "да":
        urgent_note = "При непосредственной опасности отойдите от места происшествия, позвоните 112 и в аварийную службу дома."

    recipient = "Единый диспетчерский центр Москвы: +7 (495) 539-53-53"
    recipient_kind = "ЕДЦ принимает заявки по ЖКХ дома; исполнитель определяется по выбранному дому"
    if category == "yard" and answers.get("territory_owner") == "городская" and not urgent_note:
        recipient = "Портал «Наш город»: https://gorod.mos.ru/"
        recipient_kind = "сообщение о проблеме на городской территории"

    extra_questions = []
    if category == "yard" and answers.get("territory_owner") not in {"территория дома", "городская"}:
        extra_questions.append("Уточните, входит ли проблемный участок в территорию дома или это городская территория.")
    if category == "trash" and not answers.get("trash_context"):
        extra_questions.append("Мусор скопился в доме/во дворе или не вывезены контейнеры?")
    outside_scope = not DOMAIN_PATTERN.search(text)
    provisional = (confidence < THRESHOLD or outside_scope) and not (chosen or rule_category)
    if category == "yard" and answers.get("territory_owner") not in {"территория дома", "городская"}:
        provisional = True
    if provisional:
        extra_questions.append("Уточните тип проблемы из шести поддерживаемых категорий.")

    attach = ["выбранный дом", "точное место", "краткое описание", "время обнаружения"]
    if category in {"leak", "trash", "yard", "entrance_electricity", "lift"}:
        attach.append("фото, если безопасно и возможно")
    if category == "heating":
        attach.append("есть ли тепло и горячая вода в соседних квартирах")

    card = {
        "recipient": recipient,
        "recipient_kind": recipient_kind,
        "responsible_for_house": house["manager"] if recipient.startswith("Единый диспетчерский") else None,
        "what_now": urgent_note or "Создайте заявку и приложите данные. При аварии звоните в ЕДЦ Москвы по номеру +7 (495) 539-53-53; при непосредственной угрозе жизни — 112.",
        "attach": attach,
        "response_expectation": "Демо-статусы: принято → назначен исполнитель → выполнено. Фактический срок реакции и устранения сообщает диспетчер или официальный сервис после регистрации; бот его не обещает.",
        "sources": ["https://www.mos.ru/assets/vyzov-mastera/static/documents/rules.pdf", "https://gorod.mos.ru/"],
    }
    if provisional and not urgent_note:
        card = None

    display_category = None if outside_scope and not chosen else category
    return {
        "category": display_category,
        "category_name": CATEGORIES[display_category] if display_category else "Требуется уточнение",
        "category_source": category_source,
        "confidence": round(float(confidence), 3),
        "provisional": provisional,
        "immediate_action": urgent_note,
        "alternatives": [{"category": str(c), "probability": round(float(p), 3)} for c, p in ranked[:3]],
        "needs_clarification": bool(extra_questions),
        "questions": QUESTIONS,
        "follow_up_questions": extra_questions,
        "route_card": card,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(triage(" ".join(sys.argv[1:]) or "В подъезде не горит свет"), ensure_ascii=False, indent=2))
