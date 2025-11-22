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


def test_create_user_creates_directory_and_records(file_manager: FileManager) -> None:
    """Ensure creating a user initializes storage and records metadata."""
    user_directory = file_manager.create_user("alice")

    assert Path(user_directory.root_path).exists()
    assert file_manager.user_model.get(user_directory.user_id)["username"] == "alice"
