import base64
import tempfile
import unittest
from pathlib import Path

from app.max_bot import MaxDialog, event_key
from app.service import RequestService, ValidationError
from app.storage import TicketStore


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.store = TicketStore(root / "demo.sqlite3")
        self.service = RequestService(self.store, root / "uploads")

    def tearDown(self):
        self.tmp.cleanup()

    def test_moscow_routes_and_safety(self):
        basic = {"house_id": "demo_1"}
        leak = self.service.classify({**basic, "text": "Из потолка течёт вода"})
        self.assertIn("Единый диспетчерский центр Москвы", leak["route_card"]["recipient"])
        yard = self.service.classify({**basic, "text": "Во дворе не убрали снег"})
        self.assertIsNone(yard["route_card"])
        city = self.service.classify({**basic, "text": "Во дворе не убрали снег",
                                      "answers": {"territory_owner": "городская"}})
        self.assertIn("gorod.mos.ru", city["route_card"]["recipient"])
        trapped = self.service.classify({**basic, "text": "В лифте застрял человек"})
        self.assertIn("112", trapped["immediate_action"])
        other = self.service.classify({**basic, "text": "Как поменять паспорт?"})
        self.assertIsNone(other["category"])
        self.assertIsNone(other["route_card"])

    def test_ticket_status_and_photo(self):
        png = b"\x89PNG\r\n\x1a\n" + b"demo-image-data"
        payload = {"house_id": "demo_1", "text": "В подъезде не горит свет",
                   "answers": {"location": "подъезд", "danger": "нет"},
                   "photo_data_url": "data:image/png;base64," + base64.b64encode(png).decode(),
                   "seconds_to_create": 42}
        ticket = self.service.create(payload)
        self.assertEqual(ticket["status"], "accepted")
        self.assertEqual(ticket["seconds_to_create"], 42)
        self.assertTrue((self.service.uploads / ticket["photo_path"]).is_file())
        ticket = self.store.set_status(ticket["id"], "assigned")
        self.assertEqual(len(ticket["events"]), 2)
        with self.assertRaises(ValueError):
            self.store.set_status(ticket["id"], "accepted")
        ticket = self.store.set_status(ticket["id"], "done")
        self.assertEqual(ticket["status"], "done")
        self.assertEqual(self.store.summary()["done"], 1)

    def test_unknown_territory_blocks_ticket(self):
        with self.assertRaises(ValidationError):
            self.service.create({"house_id": "demo_1", "text": "Во дворе сломаны качели"})

    def test_max_dialog_creates_one_ticket_on_retry(self):
        bot = MaxDialog(self.service, self.store)
        texts = ["/start", "1", "В подъезде не горит свет", "2", "нет", "да"]
        last = None
        for index, text in enumerate(texts):
            update = {"update_type": "message_created", "timestamp": index,
                      "message": {"sender": {"user_id": 101}, "body": {"mid": f"mid-{index}", "text": text}}}
            last = bot.handle(update)
            self.store.mark_update_delivered(event_key(update))
        self.assertIn("Заявка M-", last[1])
        self.assertEqual(self.store.summary()["total"], 1)
        self.assertIsNone(bot.handle(update))
        self.assertEqual(self.store.summary()["total"], 1)


if __name__ == "__main__":
    unittest.main()
