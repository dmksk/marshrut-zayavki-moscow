import json
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DatasetTests(unittest.TestCase):
    def test_dataset_provenance_and_balance(self):
        with (ROOT / "data" / "requests_6000.jsonl").open(encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        self.assertEqual(len(rows), 6000)
        self.assertEqual(len({r["text_ru"] for r in rows}), 6000)
        self.assertEqual(set(Counter(r["category"] for r in rows).values()), {1000})
        self.assertTrue(all(r["city"] == "Москва" and r["is_real_resident_message"] is False for r in rows))
        groups = {}
        for row in rows:
            key = row["seed_phrase_group"]
            groups.setdefault(key, set()).add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))


if __name__ == "__main__":
    unittest.main()
