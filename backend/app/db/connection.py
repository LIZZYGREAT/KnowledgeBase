"""SQLite connection setup for disposable Runtime state."""

from pathlib import Path
import sqlite3
from typing import Union


_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect_database(path: Union[str, Path]) -> sqlite3.Connection:
    """Open a Runtime database and ensure the current schema is present."""
    database_path = str(path)
    if database_path != ":memory:":
        Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    initialize_database(connection)
    return connection


def initialize_database(connection: sqlite3.Connection) -> None:
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    connection.executescript(schema)
