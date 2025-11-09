"""SQLite connection and initialization utilities."""

import sqlite3
from pathlib import Path
from typing import Optional, Any, List, Dict
import threading
import json

from .schema import get_init_schema, SCHEMA_VERSION
from ..core.exceptions import StorageError


class DatabaseConnection:
    """Manage SQLite connections and schema init."""

    __slots__ = ("db_path", "_local", "_lock", "_initialized")

    def __init__(self, db_path="./shadowbox.db"):
        """Initialize connection state."""
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        """Initialize schema if not already initialized."""
        if self._initialized:
            return

        with self._lock:
            if self._initialized:
                return

            try:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)

                conn = self._get_connection()

                conn.execute("PRAGMA foreign_keys = ON")

                for statement in get_init_schema():
                    conn.execute(statement)

                conn.commit()
                self._initialized = True

            except sqlite3.Error as e:
                raise StorageError(f"Failed to initialize database: {e}")

    def _get_connection(self):
        """Get or create a thread-local SQLite connection."""
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path), check_same_thread=False, isolation_level=None
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA foreign_keys = ON")

        return self._local.connection

    def get_cursor_context(self):
        """Return a context manager for a SQLite cursor."""
        return CursorContext(self._get_connection())

    def get_transaction_context(self):
        """Return a transaction context manager (BEGIN/COMMIT/ROLLBACK)."""
        return TransactionContext(self._get_connection())

    def execute(self, query, params=None):
        """Execute a single SQL statement and return the cursor."""
        ctx = self.get_cursor_context()
        cursor = ctx.__enter__()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            return cursor
        finally:
            ctx.__exit__(None, None, None)

    def execute_many(self, query, params_list):
        """Execute a statement against multiple parameter sets."""
        ctx = self.get_cursor_context()
        cursor = ctx.__enter__()
        try:
            cursor.executemany(query, params_list)
        finally:
            ctx.__exit__(None, None, None)

    def fetch_one(self, query, params=None):
        """Fetch a single row as a dict or None."""
        ctx = self.get_cursor_context()
        cursor = ctx.__enter__()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            ctx.__exit__(None, None, None)

    def fetch_all(self, query, params=None):
        """Fetch all rows as a list of dicts."""
        ctx = self.get_cursor_context()
        cursor = ctx.__enter__()
        try:
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)

            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            ctx.__exit__(None, None, None)

    def get_version(self):
        """Return current schema version number."""
        try:
            result = self.fetch_one("SELECT MAX(version) as version FROM schema_version")
            return result["version"] if result and result["version"] else 0
        except sqlite3.Error:
            return 0

    def close(self):
        """Close the thread-local connection if open."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


class CursorContext:
    """Context manager for SQLite cursor."""

    __slots__ = ("connection", "cursor")

    def __init__(self, connection):
        """Initialize with a SQLite connection."""
        self.connection = connection
        self.cursor = None

    def __enter__(self):
        """Create and return a cursor."""
        self.cursor = self.connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Close the cursor."""
        if self.cursor:
            self.cursor.close()


class TransactionContext:
    """Context manager for transactions (BEGIN/COMMIT/ROLLBACK)."""

    __slots__ = ("connection", "cursor")

    def __init__(self, connection):
        """Initialize with a SQLite connection."""
        self.connection = connection
        self.cursor = None

    def __enter__(self):
        """Begin a transaction and return a cursor."""
        self.cursor = self.connection.cursor()
        self.cursor.execute("BEGIN")
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit on success, rollback on error, then close cursor."""
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            if self.cursor:
                self.cursor.close()
