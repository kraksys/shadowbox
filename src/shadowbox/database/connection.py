"""Database connection and initialization management - no decorators."""

import sqlite3
from pathlib import Path
from typing import Optional, Any, List, Dict
import threading
import json

from .schema import get_init_schema, SCHEMA_VERSION
from ..core.exceptions import StorageError

"""
    We implement a control system to use proper cursors (sessions that connect to db), so that we don't forget closing it (freeing resources) and leaving the db in a failure / incomplete state 
    Transactions are the operations we perform with our queries, so we need to ensure the ACID properties by properly defining them, sqlite handles the rest 
"""


class DatabaseConnection:
    """
    Manages SQLite database connections
    """

    __slots__ = ("db_path", "_local", "_lock", "_initialized")

    def __init__(self, db_path="./shadowbox.db"):
        """
        Initialize database connection

        Args:
            db_path: Path to SQLite db file
        """
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._initialized = False

    def initialize(self):
        """
        Initialize db schema

        Raises:
            StorageError: If init fails
        """
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
        """
        Get local db connection

        Returns:
            SQLite connection object
        """
        if not hasattr(self._local, "connection") or self._local.connection is None:
            self._local.connection = sqlite3.connect(
                str(self.db_path), check_same_thread=False, isolation_level=None
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA foreign_keys = ON")

        return self._local.connection

    def get_cursor_context(self):
        """
        Get context manager for db cursor

        Returns:
            Context manager that gives SQLite cursor
        """
        return CursorContext(self._get_connection())

    def get_transaction_context(self):
        """
        Get context manager for db transactions

        Returns:
            Context manager that gives SQLite cursor with transaction
        """
        return TransactionContext(self._get_connection())

    def execute(self, query, params=None):
        """
        Execute a single query

        Args:
            query: SQL query string
            params: Optional query parameters

        Returns:
            Cursor with results
        """
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
        """
        Execute query with multiple parameters

        Args:
            query: SQL query string
            params_list: List of parameter tuples
        """
        ctx = self.get_cursor_context()
        cursor = ctx.__enter__()
        try:
            cursor.executemany(query, params_list)
        finally:
            ctx.__exit__(None, None, None)

    def fetch_one(self, query, params=None):
        """
        Fetch single row

        Args:
            query: SQL query string
            params: Optional query parameters

        Returns:
            Dictionary of column to value or None
        """
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
        """
        Fetch all rows

        Args:
            query: SQL query string
            params: Optional query parameters

        Returns:
            List of dictionaries
        """
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
        """
        Get current schema version

        Returns:
            Schema version number
        """
        try:
            result = self.fetch_one("SELECT MAX(version) as version FROM schema_version")
            return result["version"] if result and result["version"] else 0
        except sqlite3.Error:
            return 0

    def close(self):
        """Close database connection."""
        if hasattr(self._local, "connection") and self._local.connection:
            self._local.connection.close()
            self._local.connection = None


class CursorContext:
    """
    Context manager for database cursor
    """

    __slots__ = ("connection", "cursor")

    def __init__(self, connection):
        """
        Initialize cursor context

        Args:
            connection: SQLite connection
        """
        self.connection = connection
        self.cursor = None

    def __enter__(self):
        """
        Enter context and create cursor
        """
        self.cursor = self.connection.cursor()
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context and close cursor
        """
        if self.cursor:
            self.cursor.close()


class TransactionContext:
    """
    Context manager for database transactions
    """

    __slots__ = ("connection", "cursor")

    def __init__(self, connection):
        """
        Initialize transaction context

        Args:
            connection: SQLite connection
        """
        self.connection = connection
        self.cursor = None

    def __enter__(self):
        """
        Enter context and begin transaction
        """
        self.cursor = self.connection.cursor()
        self.cursor.execute("BEGIN")
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        Exit context and commit or rollback transaction
        """
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            if self.cursor:
                self.cursor.close()
