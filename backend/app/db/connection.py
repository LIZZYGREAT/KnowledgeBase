"""SQLite connection setup for disposable Runtime state."""

from pathlib import Path
import sqlite3
from typing import Union

from backend.app.db.migrations import migrate_database


_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
DEFAULT_BUSY_TIMEOUT_MS = 10_000


def connect_database(
    path: Union[str, Path], busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS
) -> sqlite3.Connection:
    """Open a Runtime database and ensure the current schema is present."""
    if (
        isinstance(busy_timeout_ms, bool)
        or not isinstance(busy_timeout_ms, int)
        or busy_timeout_ms < 0
        or busy_timeout_ms > 2_147_483_647
    ):
        raise ValueError("busy_timeout_ms must be an integer from 0 to 2147483647")

    database_path = str(path)
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path, timeout=busy_timeout_ms / 1000)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = {}".format(busy_timeout_ms))
    connection.execute("PRAGMA foreign_keys = ON")
    if database_path != ":memory:":
        connection.execute("PRAGMA journal_mode = WAL")
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    migrate_database(connection)
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)
