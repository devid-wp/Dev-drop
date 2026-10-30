import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from app.history_store import HistoryStore, HistoryStoreError


def entry(index):
    return {"filename": f"file-{index}.txt", "size": index,
            "timestamp": "2026-10-30T12:00:00+00:00", "sender_ip": "192.0.2.1"}


class HistoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.database = self.root / "history.sqlite3"
        self.legacy = self.root / "history.json"
        self.store = HistoryStore(self.database, self.legacy)

    def stored_rows(self):
        with closing(sqlite3.connect(self.database)) as connection:
            return connection.execute("SELECT COUNT(*) FROM transfers").fetchone()[0]

    def test_empty_database_and_schema_version(self):
        self.assertEqual(self.store.read(), [])
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)

    def test_append_read_and_reopen(self):
        self.store.append([entry(1)])
        self.assertEqual(self.store.read(), [entry(1)])
        self.assertEqual(HistoryStore(self.database, self.legacy).read(), [entry(1)])

    def test_clear_survives_reopen_without_reimporting(self):
        self.legacy.write_text(json.dumps([entry(1)]))
        self.assertEqual(self.store.read(), [entry(1)])
        self.store.replace([])
        self.assertEqual(HistoryStore(self.database, self.legacy).read(), [])
        self.assertEqual(json.loads(self.legacy.read_text()), [entry(1)])

    def test_order_and_last_twenty_without_discarding_stored_data(self):
        records = [entry(i) for i in range(30)]
        self.store.append(records)
        self.assertEqual(self.store.read(), records[-20:])
        self.assertEqual(self.stored_rows(), 30)

    def test_concurrent_initialization_migration_and_append(self):
        self.legacy.write_text(json.dumps([entry(100)]))
        def append(index):
            HistoryStore(self.database, self.legacy).append([entry(index)])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(append, range(40)))
        self.assertEqual(self.stored_rows(), 41)
        with closing(sqlite3.connect(self.database)) as connection:
            records = [json.loads(row[0]) for row in connection.execute("SELECT payload FROM transfers")]
        self.assertCountEqual(records, [entry(100)] + [entry(i) for i in range(40)])

    def test_migration_preserves_all_records_extra_fields_and_source(self):
        records = [entry(i) for i in range(25)]
        records[-1]["extra"] = {"unicode": "Привет", "values": [1, None, True]}
        original = json.dumps(records, ensure_ascii=False).encode("utf-8")
        self.legacy.write_bytes(original)
        for _ in range(2):
            self.assertEqual(HistoryStore(self.database, self.legacy).read(), records[-20:])
        self.assertEqual(self.stored_rows(), len(records))
        self.assertEqual(self.legacy.read_bytes(), original)

    def test_corrupt_or_invalid_json_is_not_partially_imported(self):
        for source in ['{broken', '{}', '[1]', json.dumps([entry(1), {"size": "bad"}])]:
            with self.subTest(source=source):
                self.legacy.write_text(source)
                with self.assertRaises(HistoryStoreError):
                    self.store.read()
                self.assertEqual(self.legacy.read_text(), source)
        # Repairing the source permits a clean, single import after all failures.
        self.legacy.write_text(json.dumps([entry(1)]))
        self.assertEqual(self.store.read(), [entry(1)])
        self.assertEqual(self.stored_rows(), 1)

    def test_missing_json_never_creates_source(self):
        self.store.append([entry(1)])
        self.assertFalse(self.legacy.exists())
        self.assertEqual(self.store.read(), [entry(1)])

    def test_failed_replace_preserves_existing_history(self):
        self.store.append([entry(1)])
        with self.assertRaises(HistoryStoreError):
            self.store.replace([entry(2), {"size": -1}])
        self.assertEqual(self.store.read(), [entry(1)])

    def test_future_schema_is_rejected_without_modification(self):
        self.store.append([entry(1)])
        with closing(sqlite3.connect(self.database)) as connection:
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        with self.assertRaises(HistoryStoreError):
            self.store.read()
        self.assertEqual(self.stored_rows(), 1)


class HistoryAPITests(unittest.TestCase):
    def test_migration_read_clear_and_storage_error(self):
        from unittest.mock import patch
        from app import main
        from test_auth import request

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "history.json"
            source.write_text(json.dumps([entry(1)]))
            with patch.object(main, "HISTORY_PATH", source):
                status, body = request("/api/history", host="127.0.0.1")
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(body), {"transfers": [entry(1)]})
                self.assertEqual(request("/api/history", "DELETE", host="127.0.0.1")[0], 200)
                self.assertEqual(json.loads(request("/api/history", host="127.0.0.1")[1]), {"transfers": []})
                self.assertEqual(json.loads(source.read_text()), [entry(1)])
            bad_source = Path(directory) / "broken.json"
            bad_source.write_text("invalid")
            with patch.object(main, "HISTORY_PATH", bad_source):
                status, body = request("/api/history", host="127.0.0.1")
                self.assertEqual(status, 503)
                self.assertEqual(json.loads(body), {"detail": "Transfer history is unavailable"})
