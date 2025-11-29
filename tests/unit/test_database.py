"""Unit tests covering ``DatabaseConnection`` and database models."""

import tempfile

# from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, TypedDict

import pytest

from shadowbox.core.models import Box  # BoxShare, FileMetadata, FileStatus, FileType
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import (  # row_to_metadata,
    BoxModel,
    BoxShareModel,
    FileModel,
    UserModel,
)
from shadowbox.database.schema import SCHEMA_VERSION, get_drop_schema


class ModelBundle(TypedDict):
    """Typed collection of model helpers used across tests."""

    db: DatabaseConnection
    users: UserModel
    boxes: BoxModel
    files: FileModel
    shares: BoxShareModel


@pytest.fixture()
def temp_db() -> Generator[DatabaseConnection, None, None]:
    """Provide a temporary, initialized ``DatabaseConnection`` instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "shadowbox.db"
        db = DatabaseConnection(db_path)
        db.initialize()
        try:
            yield db
        finally:
            db.close()


@pytest.fixture()
def models(temp_db: DatabaseConnection) -> Dict[str, object]:
    """Return initialized model helpers for database testing."""
    return {
        "db": temp_db,
        "users": UserModel(temp_db),
        "boxes": BoxModel(temp_db),
        "files": FileModel(temp_db),
        "shares": BoxShareModel(temp_db),
    }


def test_initialize_is_idempotent(temp_db: DatabaseConnection) -> None:
    """Ensure schema initialization can be invoked multiple times safely."""
    temp_db.initialize()
    assert temp_db.get_version() == SCHEMA_VERSION

    for statement in get_drop_schema():
        temp_db.execute(statement)

    assert temp_db.get_version() == 0


def test_transaction_context_commit_and_rollback(temp_db: DatabaseConnection) -> None:
    """Validate commit and rollback behaviour of transaction context manager."""
    with temp_db.get_transaction_context() as cursor:
        cursor.execute(
            "INSERT INTO users (user_id, username) VALUES (?, ?)",
            ("user-1", "alpha"),
        )

    assert (
        temp_db.fetch_one(
            "SELECT username FROM users WHERE user_id = ?",
            ("user-1",),
        )["username"]
        == "alpha"
    )

    with pytest.raises(ValueError):
        with temp_db.get_transaction_context() as cursor:
            cursor.execute(
                "INSERT INTO users (user_id, username) VALUES (?, ?)",
                ("user-2", "beta"),
            )
            raise ValueError("force rollback")

    assert (
        temp_db.fetch_one(
            "SELECT username FROM users WHERE user_id = ?",
            ("user-2",),
        )
        is None
    )


def test_user_and_box_models(models: ModelBundle) -> None:
    """Exercise CRUD flows for users and boxes including updates."""
    db = models["db"]
    users = models["users"]
    boxes = models["boxes"]

    created = users.create("user-1", "alpha")
    assert created["username"] == "alpha"
    assert users.get_by_username("alpha")["user_id"] == "user-1"

    users.update_quota("user-1", 512)
    quota_row = db.fetch_one(
        "SELECT used_bytes FROM users WHERE user_id = ?",
        ("user-1",),
    )
    assert quota_row["used_bytes"] == 512

    box = Box(
        user_id="user-1",
        box_name="Docs",
        description="Primary box",
        is_shared=False,
    )
    created_box = boxes.create(box)
    assert created_box["box_name"] == "Docs"

    all_boxes = boxes.list_by_user("user-1")
    assert len(all_boxes) == 1
    assert all_boxes[0]["box_id"] == box.box_id

    box.description = "Updated"
    box.is_shared = True
    boxes.update(box)
    refreshed = boxes.get(box.box_id)
    assert refreshed["description"] == "Updated"
    assert refreshed["is_shared"] == 1

    assert users.delete("user-1") is True
    assert users.get("user-1") is None
