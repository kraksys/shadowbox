"""Unit tests covering ``FileManager`` behaviour."""

import sys
from pathlib import Path

import pytest

from shadowbox.core.file_manager import FileManager
from shadowbox.database.connection import DatabaseConnection

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))

# from shadowbox.core.exceptions import (  # noqa: E402
#     FileNotFoundError,
#     QuotaExceededError,
#     UserExistsError,
#     UserNotFoundError,
# )


@pytest.fixture()
def file_manager(tmp_path: Path) -> FileManager:
    """Create a temporary ``FileManager`` backed by an isolated database."""
    storage_root = tmp_path / "storage"
    db_path = tmp_path / "db.sqlite"
    db_conn = DatabaseConnection(str(db_path))
    db_conn.initialize()
    return FileManager(str(storage_root), db_conn)
