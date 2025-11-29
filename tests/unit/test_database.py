"""Unit tests covering ``DatabaseConnection`` and database models."""

import tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Generator, TypedDict

import pytest

from shadowbox.core.models import Box, BoxShare, FileMetadata, FileStatus, FileType
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import (
    BoxModel,
    BoxShareModel,
    FileModel,
    UserModel,
    row_to_metadata,
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


def _make_metadata(user_id: str, box_id: str, **overrides: object) -> FileMetadata:
    """Build ``FileMetadata`` instances with overrides for test scenarios."""
    base = {
        "file_id": "file-1",
        "box_id": box_id,
        "filename": "report.txt",
        "original_path": "/tmp/report.txt",
        "size": 1024,
        "file_type": FileType.DOCUMENT,
        "mime_type": "text/plain",
        "hash_sha256": "hash1",
        "created_at": datetime.utcnow(),
        "modified_at": datetime.utcnow(),
        "accessed_at": datetime.utcnow(),
        "user_id": user_id,
        "owner": user_id,
        "status": FileStatus.ACTIVE,
        "version": 1,
        "parent_version_id": None,
        "tags": ["work", "urgent"],
        "description": "Quarterly report",
        "custom_metadata": {"category": "finance"},
    }
    base.update(overrides)
    return FileMetadata(**base)


def test_file_model_crud_and_tag_management(models: ModelBundle) -> None:
    """Cover file creation, updates, listing filters, and bulk insert guard."""
    files = models["files"]
    users = models["users"]
    boxes = models["boxes"]

    users.create("user-1", "alpha")
    box = Box(user_id="user-1", box_name="Docs", description="Primary box")
    boxes.create(box)

    metadata = _make_metadata("user-1", box.box_id)
    files.create(metadata)

    fetched = files.get(metadata.file_id)
    assert fetched.tags == ["work", "urgent"]
    assert fetched.custom_metadata == {"category": "finance"}

    metadata.filename = "report-final.txt"
    metadata.size = 2048
    metadata.tags = ["work", "final"]
    metadata.status = FileStatus.ARCHIVED
    files.update(metadata)

    updated = files.get(metadata.file_id)
    assert updated.filename == "report-final.txt"
    assert set(updated.tags) == {"work", "final"}
    assert updated.status is FileStatus.ARCHIVED

    metadata_deleted = _make_metadata(
        "user-1",
        box.box_id,
        file_id="file-2",
        filename="old.txt",
        status=FileStatus.DELETED,
        tags=["old"],
    )
    files.create(metadata_deleted)

    active_files = files.list_by_user("user-1")
    assert all(f.status is not FileStatus.DELETED for f in active_files)

    deleted_included = files.list_by_user("user-1", include_deleted=True)
    assert any(f.file_id == "file-2" for f in deleted_included)

    box_files = files.list_by_box(box.box_id, include_deleted=True)
    assert {f.file_id for f in box_files} >= {"file-1", "file-2"}


def test_row_to_metadata_handles_strings_and_invalid_json() -> None:
    """Parse metadata rows with string timestamps and invalid JSON payloads."""
    row = {
        "file_id": "file-1",
        "box_id": "box-1",
        "filename": "note.txt",
        "original_path": "/tmp/note.txt",
        "size": 10,
        "file_type": "other",
        "mime_type": "text/plain",
        "hash_sha256": "abc",
        "created_at": datetime.utcnow().isoformat(),
        "modified_at": datetime.utcnow().isoformat(),
        "accessed_at": datetime.utcnow().isoformat(),
        "user_id": "user-1",
        "owner": "user-1",
        "status": "active",
        "version": 1,
        "parent_version_id": None,
        "description": None,
        "custom_metadata": "not-json",
    }

    metadata = row_to_metadata(row, ["tag1"])
    assert metadata.custom_metadata == {}
    assert metadata.tags == ["tag1"]


def test_box_shares_access_rules(models: ModelBundle) -> None:
    """Verify share creation, access checks, token lookups, and deletion."""
    users = models["users"]
    boxes = models["boxes"]
    shares = models["shares"]

    users.create("owner", "owner")
    users.create("guest", "guest")
    box = Box(user_id="owner", box_name="Shared", description="shareable")
    boxes.create(box)

    share = BoxShare(
        share_id="share-1",
        box_id=box.box_id,
        shared_by_user_id="owner",
        shared_with_user_id="guest",
        permission_level="read",
        expires_at=None,
        access_token="token-123",
    )
    shares.create(share)

    assert shares.has_access(box.box_id, "guest") is True
    assert shares.has_access(box.box_id, "guest", permission_level="write") is False
    assert shares.get_by_access_token("token-123")["share_id"] == "share-1"
    assert shares.delete(share.share_id) is True
    assert shares.get(share.share_id) is None
