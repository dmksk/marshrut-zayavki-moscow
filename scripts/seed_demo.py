"""Seed three visibly different synthetic tickets for the demo cabinet."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.service import RequestService  # noqa: E402
from app.storage import TicketStore  # noqa: E402

store = TicketStore(ROOT / "data" / "demo.sqlite3")
service = RequestService(store)
examples = [
    ("В подъезде на третьем этаже не горит свет", {"location": "подъезд", "danger": "нет"}),
    ("В квартире холодные батареи, у соседей тоже", {"location": "квартира", "danger": "нет"}),
    ("Во дворе после снегопада не очистили дорожку", {"location": "двор", "danger": "нет", "territory_owner": "городская"}),
]
if store.summary()["total"]:
    print("В базе уже есть заявки; демо-примеры не добавлены повторно.")
else:
    tickets = [service.create({"house_id": "demo_1", "text": text, "answers": answers,
                               "seconds_to_create": 25 + index * 12})
               for index, (text, answers) in enumerate(examples)]
    store.set_status(tickets[1]["id"], "assigned")
    store.set_status(tickets[2]["id"], "assigned")
    store.set_status(tickets[2]["id"], "done")
    print("Созданы демо-заявки:", ", ".join(t["id"] for t in tickets))
