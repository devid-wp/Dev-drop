import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main


class TransferHistoryTests(unittest.TestCase):
    def test_history_persists_and_keeps_last_twenty_transfers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_file = Path(temporary_directory) / "transfer_history.json"
            with patch.object(main, "HISTORY_PATH", history_file):
                for index in range(21):
                    main.record_transfers([(f"file-{index}.txt", index + 1)], "192.168.0.15")

                history = main.load_transfer_history()
                self.assertEqual(len(history), 20)
                self.assertEqual(history[0]["filename"], "file-1.txt")
                self.assertEqual(history[-1]["filename"], "file-20.txt")
                self.assertEqual(history[-1]["size"], 21)
                self.assertEqual(history[-1]["sender_ip"], "192.168.0.15")
                self.assertIn("timestamp", history[-1])

                reloaded = json.loads(history_file.read_text(encoding="utf-8"))
                self.assertEqual(reloaded, history)

    def test_clear_history_removes_saved_transfers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_file = Path(temporary_directory) / "transfer_history.json"
            with patch.object(main, "HISTORY_PATH", history_file):
                main.record_transfers([("photo.jpg", 12 * 1024 * 1024)], "192.168.0.15")
                main.save_transfer_history([])

                self.assertEqual(main.load_transfer_history(), [])
                self.assertEqual(json.loads(history_file.read_text(encoding="utf-8")), [])


if __name__ == "__main__":
    unittest.main()