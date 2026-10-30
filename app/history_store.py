"""SQLite transfer metadata; one connection/transaction per operation.

The legacy JSON is read once and never modified. Payloads remain JSON objects
inside SQLite so migration preserves extra metadata fields without conversion.
No file contents are stored here.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class HistoryStoreError(RuntimeError):
    """History is unavailable; callers must not silently replace it with []."""


def _encode(records: object) -> list[tuple[str]]:
    if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
        raise ValueError("History must be a list of objects")
    for row in records:
        for field in ("filename", "timestamp", "sender_ip"):
            if field in row and not isinstance(row[field], str):
                raise ValueError(f"Invalid history field: {field}")
        if "size" in row and (type(row["size"]) is not int or row["size"] < 0):
            raise ValueError("Invalid history size")
    return [(json.dumps(row, ensure_ascii=False, allow_nan=False),) for row in records]


class HistoryStore:
    def __init__(self, database: Path, legacy_json: Path):
        self.database = database
        self.legacy_json = legacy_json

    @contextmanager
    def _transaction(self):
        connection = None
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database, timeout=10, isolation_level=None)
            # Serialize schema initialization, migration and writers across processes.
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ValueError("Unsupported history schema version")
            if version == 0:
                connection.execute("CREATE TABLE transfers (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
                connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                connection.execute("PRAGMA user_version = 1")
            migrated = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", ("legacy_imported",)
            ).fetchone()
            if migrated is None:
                try:
                    source = self.legacy_json.read_text(encoding="utf-8")
                except FileNotFoundError:
                    records = []
                else:
                    records = json.loads(source)
                connection.executemany("INSERT INTO transfers (payload) VALUES (?)", _encode(records))
                connection.execute("INSERT INTO metadata (key, value) VALUES (?, ?)",
                                   ("legacy_imported", "1"))
            yield connection
            connection.commit()
        except (sqlite3.Error, OSError, ValueError, TypeError) as error:
            if connection is not None:
                connection.rollback()
            raise HistoryStoreError("Transfer history is unavailable") from error
        finally:
            if connection is not None:
                connection.close()

    def read(self) -> list[dict[str, object]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM (SELECT id, payload FROM transfers ORDER BY id DESC LIMIT 20) ORDER BY id"
            ).fetchall()
            return [json.loads(row[0]) for row in rows]

    def append(self, records: list[dict[str, object]]) -> None:
        with self._transaction() as connection:
            connection.executemany("INSERT INTO transfers (payload) VALUES (?)", _encode(records))

    def replace(self, records: list[dict[str, object]]) -> None:
        """Explicit replacement, including manual clear; never reset migration marker."""
        with self._transaction() as connection:
            encoded = _encode(records)
            connection.execute("DELETE FROM transfers")
            connection.executemany("INSERT INTO transfers (payload) VALUES (?)", encoded)
