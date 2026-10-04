"""Test helpers for opening Runtime SQLite connections on the pytest thread."""

from contextlib import contextmanager

from backend.app.db.connection import connect_database


@contextmanager
def open_test_runtime(api_client):
    """Open the API client's database in the calling test thread."""
    connection = connect_database(api_client.app.state.database_path)
    try:
        yield connection
    finally:
        connection.close()
