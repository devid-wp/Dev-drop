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

                self.assertFalse(history_file.exists())
                self.assertTrue(history_file.with_suffix(".sqlite3").exists())
                self.assertEqual(main.load_transfer_history(), history)

    def test_clear_history_removes_saved_transfers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            history_file = Path(temporary_directory) / "transfer_history.json"
            with patch.object(main, "HISTORY_PATH", history_file):
                main.record_transfers([("photo.jpg", 12 * 1024 * 1024)], "192.168.0.15")
                main.save_transfer_history([])

                self.assertEqual(main.load_transfer_history(), [])
                self.assertFalse(history_file.exists())

    def test_initialize_session_stats_uses_incremental_totals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            session_dir = Path(temporary_directory)
            (session_dir / "one.bin").write_bytes(b"x" * 3456)
            (session_dir / "two.bin").write_bytes(b"y" * 3456)

            main.SESSION_DIR = session_dir
            main.invalidate_session_stats()
            main.initialize_session_stats(session_dir)

            with patch.object(Path, "iterdir", side_effect=AssertionError("iterdir should not be called after initialization")):
                stats = main.session_stats()

            self.assertEqual(stats, {"received_files": 2, "received_size": 6912})


if __name__ == "__main__":
    unittest.main()