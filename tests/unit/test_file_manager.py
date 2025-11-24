"""Unit tests covering ``FileManager`` behaviour."""

import sys
from pathlib import Path

import pytest

from shadowbox.core.exceptions import (
    BoxExistsError,
    UserExistsError,
)
from shadowbox.core.file_manager import FileManager
from shadowbox.database.connection import DatabaseConnection

sys.path.append(str(Path(__file__).resolve().parents[2] / "src"))


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


def test_create_user_duplicate_raises(file_manager: FileManager) -> None:
    """Raise an error when attempting to create a duplicate user."""
    file_manager.create_user("alice")

    with pytest.raises(UserExistsError):
        file_manager.create_user("alice")


def test_create_box_duplicate_name_raises(file_manager: FileManager) -> None:
    """Creating a box with a duplicate name for the same user raises an error."""
    user = file_manager.create_user("alex")
    file_manager.create_box(user_id=user.user_id, box_name="projects")

    with pytest.raises(BoxExistsError):
        file_manager.create_box(user_id=user.user_id, box_name="projects")


def test_add_file_happy_path_updates_quota_and_metadata(
    file_manager: FileManager, tmp_path: Path
) -> None:
    """Add a file and confirm metadata and quota update correctly."""
    user = file_manager.create_user("bob")
    box = file_manager.create_box(
        user_id=user.user_id,
        box_name="some-test-box",
    )
    source_file = tmp_path / "example.txt"
    content = b"sample data"
    source_file.write_bytes(content)

    metadata = file_manager.add_file(
        user_id=user.user_id,
        source_path=str(source_file),
        box_id=box.box_id,
        tags=["docs"],
    )

    stored = file_manager.file_model.get(metadata.file_id)
    assert stored is not None
    assert stored.hash_sha256 == metadata.hash_sha256
    assert stored.tags == ["docs"]

    user_record = file_manager.user_model.get(user.user_id)
    assert user_record["used_bytes"] == len(content)
