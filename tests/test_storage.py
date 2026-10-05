import tempfile
import unittest
from pathlib import Path

from sentinel.storage import CaseStore


class StorageTests(unittest.TestCase):
    def test_save_feedback_export_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CaseStore(Path(directory) / "cases.db")
            case = store.save({"message": "Check this"}, {"fraud": {"level": "review"}})
            self.assertEqual(len(store.list_cases()), 1)
            store.feedback(case["id"], "incorrect", "Known legitimate message")
            saved = store.get(case["id"])
            self.assertEqual(saved["feedback"], "incorrect")
            self.assertEqual(saved["feedback_note"], "Known legitimate message")
            self.assertEqual(store.export(case["id"])["input"]["message"], "Check this")
            self.assertTrue(store.delete(case["id"]))
            self.assertIsNone(store.get(case["id"]))


if __name__ == "__main__":
    unittest.main()
