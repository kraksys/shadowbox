"""Unit tests covering ``FileManager`` behaviour."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

import pytest

from shadowbox.core.exceptions import (
    AccessDeniedError,
    BoxExistsError,
    BoxNotFoundError,
    FileNotFoundError,
    QuotaExceededError,
    UserExistsError,
    UserNotFoundError,
)
from shadowbox.core.file_manager import FileManager
from shadowbox.core.models import Box, BoxShare
from shadowbox.core.storage import Storage
from shadowbox.database.connection import DatabaseConnection


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


def test_add_file_requires_existing_box(file_manager: FileManager, tmp_path: Path) -> None:
    """Attempting to add a file to a missing box raises an error."""
    user = file_manager.create_user("eve")
    source_file = tmp_path / "missing_box.txt"
    source_file.write_bytes(b"data")

    with pytest.raises(BoxNotFoundError):
        file_manager.add_file(
            user_id=user.user_id,
            box_id="nonexistent-box",
            source_path=str(source_file),
        )


def test_add_file_respects_quota(file_manager: FileManager, tmp_path: Path) -> None:
    """Adding a file that exceeds the user's quota raises an error."""
    user = file_manager.create_user("quincy")
    file_manager.db.execute("UPDATE users SET quota_bytes = ? WHERE user_id = ?", (5, user.user_id))
    box = file_manager.create_box(user_id=user.user_id, box_name="tiny")
    source_file = tmp_path / "oversized.bin"
    source_file.write_bytes(b"0123456789")

    with pytest.raises(QuotaExceededError):
        file_manager.add_file(
            user_id=user.user_id,
            box_id=box.box_id,
            source_path=str(source_file),
        )


def test_delete_file_updates_used_bytes(file_manager: FileManager, tmp_path: Path) -> None:
    """Deleting a file frees the quota used by that file."""
    user = file_manager.create_user("cora")
    box = file_manager.create_box(user_id=user.user_id, box_name="docs")
    source_file = tmp_path / "note.txt"
    content = b"memo"
    source_file.write_bytes(content)

    metadata = file_manager.add_file(
        user_id=user.user_id,
        box_id=box.box_id,
        source_path=str(source_file),
    )

    assert file_manager.user_model.get(user.user_id)["used_bytes"] == len(content)

    file_manager.delete_file(metadata.file_id)

    assert file_manager.user_model.get(user.user_id)["used_bytes"] == 0


def test_shared_box_write_access_allows_add_file(file_manager: FileManager, tmp_path: Path) -> None:
    """A user with write access to a shared box can add files."""
    owner = file_manager.create_user("owner")
    collaborator = file_manager.create_user("collab")
    box = file_manager.create_box(user_id=owner.user_id, box_name="shared")
    file_manager.share_box(
        box_id=box.box_id,
        shared_by_user_id=owner.user_id,
        shared_with_user_id=collaborator.user_id,
        permission_level="write",
    )

    source_file = tmp_path / "shared.txt"
    content = b"shared content"
    source_file.write_bytes(content)

    metadata = file_manager.add_file(
        user_id=collaborator.user_id,
        box_id=box.box_id,
        source_path=str(source_file),
        tags=["shared"],
    )

    stored = file_manager.file_model.get(metadata.file_id)
    assert stored is not None
    assert stored.tags == ["shared"]
    assert stored.user_id == collaborator.user_id
    assert file_manager.user_model.get(collaborator.user_id)["used_bytes"] == len(content)


def test_list_box_files_enforces_access_control(file_manager: FileManager, tmp_path: Path) -> None:
    """Listing box files is forbidden for users without read access."""
    owner = file_manager.create_user("dana")
    outsider = file_manager.create_user("outsider")
    box = file_manager.create_box(user_id=owner.user_id, box_name="private")

    source_file = tmp_path / "secret.txt"
    source_file.write_bytes(b"top secret")
    file_manager.add_file(
        user_id=owner.user_id,
        box_id=box.box_id,
        source_path=str(source_file),
    )

    with pytest.raises(AccessDeniedError):
        file_manager.list_box_files(box.box_id, user_id=outsider.user_id)


def test_setup_encryption_calls_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify master key setup is invoked when encryption is enabled."""
    called: Dict[str, str] = {}

    def fake_setup(self: Storage, password: str) -> None:
        called["password"] = password

    monkeypatch.setattr(Storage, "setup_master_key", fake_setup)

    storage_root = tmp_path / "storage"
    db_path = tmp_path / "db.sqlite"
    db_conn = DatabaseConnection(str(db_path))
    db_conn.initialize()

    manager = FileManager(
        str(storage_root),
        db_conn,
        enable_encryption=True,
        master_password="secret",
    )

    assert manager.encryption_enabled is True
    assert called["password"] == "secret"


def test_create_box_duplicate_and_encrypted_settings(
    file_manager: FileManager,
) -> None:
    """Create an encrypted box and confirm duplicates are rejected."""
    user = file_manager.create_user("alice")
    secure_box = file_manager.create_box(
        user.user_id, "vault", enable_encryption=True, description="private"
    )

    assert secure_box.settings["encryption_enabled"] is True

    with pytest.raises(BoxExistsError):
        file_manager.create_box(user.user_id, "vault")


def test_update_box_rejects_encryption_change(
    file_manager: FileManager,
) -> None:
    """Reject attempts to toggle encryption via update payload."""
    user = file_manager.create_user("bob")
    box = file_manager.create_box(user.user_id, "docs")

    mutated = Box(**{**box.to_dict(), "settings": {"encryption_enabled": True}})

    with pytest.raises(ValueError):
        file_manager.update_box(mutated)


def test_list_shared_boxes_skips_irrelevant(file_manager: FileManager) -> None:
    """Return only boxes shared with the requested user."""
    owner = file_manager.create_user("una")
    viewer = file_manager.create_user("victor")
    other = file_manager.create_user("wanda")
    box = file_manager.create_box(owner.user_id, "articles")

    file_manager.share_box(box.box_id, owner.user_id, viewer.user_id)
    file_manager.share_box(box.box_id, owner.user_id, other.user_id)

    boxes_for_viewer = file_manager.list_shared_boxes(viewer.user_id)
    assert {b.box_id for b in boxes_for_viewer} == {box.box_id}


def test_update_box_error_paths(file_manager: FileManager, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover malformed settings and storage failures during update."""
    with pytest.raises(BoxNotFoundError):
        file_manager.update_box(Box(box_id="missing", user_id="nope", box_name="ghost"))

    user = file_manager.create_user("riley")
    box = file_manager.create_box(user.user_id, "projects")
    file_manager.db.execute(
        "UPDATE boxes SET settings = ? WHERE box_id = ?",
        ("not-json", box.box_id),
    )

    def blow_up(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(file_manager.storage, "set_box_encryption_enabled", blow_up)

    updated = Box(**{**box.to_dict(), "settings": "not-json"})
    assert file_manager.update_box(updated) is True


def test_delete_and_add_file_validations(file_manager: FileManager, tmp_path: Path) -> None:
    """Validate access checks across add/delete/share operations."""
    with pytest.raises(BoxNotFoundError):
        file_manager.delete_box("missing")

    owner = file_manager.create_user("sam")
    box = file_manager.create_box(owner.user_id, "restricted")
    outsider = file_manager.create_user("tara")
    src = tmp_path / "blocked.txt"
    src.write_text("no access")

    with pytest.raises(AccessDeniedError):
        file_manager.add_file(outsider.user_id, box.box_id, str(src))

    with pytest.raises(FileNotFoundError):
        file_manager.get_file("missing", "dest")

    with pytest.raises(BoxNotFoundError):
        file_manager.list_box_files("missing")

    with pytest.raises(BoxNotFoundError):
        file_manager.share_box("missing", owner.user_id, outsider.user_id)

    with pytest.raises(AccessDeniedError):
        file_manager.share_box(box.box_id, outsider.user_id, owner.user_id)

    first_share = file_manager.share_box(box.box_id, owner.user_id, outsider.user_id)
    second_share = file_manager.share_box(box.box_id, owner.user_id, outsider.user_id)
    assert first_share.share_id != second_share.share_id

    with pytest.raises(BoxNotFoundError):
        file_manager.unshare_box("missing", owner.user_id, outsider.user_id)

    with pytest.raises(AccessDeniedError):
        file_manager.unshare_box(box.box_id, outsider.user_id, owner.user_id)

    assert file_manager.unshare_box(box.box_id, owner.user_id, outsider.user_id) is True


def test_create_and_list_box_validations(file_manager: FileManager) -> None:
    """Validate error handling when creating and listing boxes."""
    with pytest.raises(UserNotFoundError):
        file_manager.create_box("missing", "docs")

    user = file_manager.create_user("quinn")
    with pytest.raises(UserNotFoundError):
        file_manager.list_user_boxes("missing")

    box = file_manager.create_box(user.user_id, "docs")
    result = file_manager.list_user_boxes(user.user_id)
    assert {b.box_id for b in result} == {box.box_id}


def test_get_box_info_and_enable_encryption_guard(
    file_manager: FileManager,
) -> None:
    """Fetch box info and block enabling encryption without password."""
    assert file_manager.get_box_info("missing", "missing") == {}

    user = file_manager.create_user("pat")
    box = file_manager.create_box(user.user_id, "info")
    info = file_manager.get_box_info(user.user_id, box.box_id)
    assert info["box_name"] == "info"
    assert info["owner"] is True

    with pytest.raises(ValueError):
        file_manager.enable_box_encryption(user.user_id, box.box_id, "pwd")


def test_delete_file_updates_quota_and_missing_errors(
    file_manager: FileManager, tmp_path: Path
) -> None:
    """Deleting files updates quotas and handles missing identifiers."""
    with pytest.raises(FileNotFoundError):
        file_manager.delete_file("missing")

    user = file_manager.create_user("oliver")
    box = file_manager.create_box(user.user_id, "mix")
    src = tmp_path / "sample.txt"
    src.write_text("abc")
    metadata = file_manager.add_file(user.user_id, box.box_id, str(src))

    file_manager.delete_file(metadata.file_id)
    assert file_manager.user_model.get(user.user_id)["used_bytes"] == 0


def test_list_shared_boxes_filters_expired(file_manager: FileManager) -> None:
    """Filter out expired shares when listing accessible boxes."""
    owner = file_manager.create_user("maya")
    guest = file_manager.create_user("nick")
    other_guest = file_manager.create_user("olga")
    box = file_manager.create_box(owner.user_id, "designs")

    file_manager.share_box(box.box_id, owner.user_id, guest.user_id, permission_level="read")
    expired_share = BoxShare(
        box_id=box.box_id,
        shared_by_user_id=owner.user_id,
        shared_with_user_id=other_guest.user_id,
        permission_level="read",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    file_manager.box_share_model.create(expired_share)

    shared_boxes = file_manager.list_shared_boxes(guest.user_id)
    assert {b.box_id for b in shared_boxes} == {box.box_id}
    assert file_manager.list_shared_boxes(other_guest.user_id) == []


def test_sharing_and_unsharing_flow(file_manager: FileManager) -> None:
    """Validate sharing lifecycle including invalid permissions."""
    owner = file_manager.create_user("kim")
    guest = file_manager.create_user("lee")
    box = file_manager.create_box(owner.user_id, "reports")

    with pytest.raises(ValueError):
        file_manager.share_box(
            box.box_id,
            owner.user_id,
            guest.user_id,
            permission_level="invalid",
        )

    share = file_manager.share_box(box.box_id, owner.user_id, guest.user_id)
    assert share.permission_level == "read"
    assert file_manager.box_model.get(box.box_id)["is_shared"]

    assert file_manager.unshare_box(box.box_id, owner.user_id, guest.user_id) is True
    assert bool(file_manager.box_model.get(box.box_id)["is_shared"]) is False


def test_listing_functions_enforce_access_controls(
    file_manager: FileManager, tmp_path: Path
) -> None:
    """Confirm listing APIs enforce share permissions and missing users."""
    owner = file_manager.create_user("ivy")
    guest = file_manager.create_user("jack")
    box = file_manager.create_box(owner.user_id, "shared")

    src = tmp_path / "entry.txt"
    src.write_text("entry")
    file_manager.add_file(owner.user_id, box.box_id, str(src))

    with pytest.raises(AccessDeniedError):
        file_manager.list_box_files(box.box_id, user_id=guest.user_id)

    file_manager.share_box(
        box.box_id,
        owner.user_id,
        guest.user_id,
        permission_level="read",
    )
    assert file_manager.list_box_files(box.box_id, user_id=guest.user_id)

    with pytest.raises(UserNotFoundError):
        file_manager.list_user_files("missing-user")


def test_get_file_routes_to_correct_storage_path(
    file_manager: FileManager, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Route file retrieval through encrypted or plain storage helpers."""
    user = file_manager.create_user("henry")
    box = file_manager.create_box(user.user_id, "docs")
    src = tmp_path / "info.txt"
    src.write_text("contents")
    metadata = file_manager.add_file(user.user_id, box.box_id, str(src))

    monkeypatch.setattr(file_manager.storage, "get", lambda *a, **k: "plain")
    assert file_manager.get_file(metadata.file_id, "dest", decrypt=False) == "plain"

    encrypted = metadata.to_dict()
    encrypted["custom_metadata"] = json.dumps({"encrypted": True})
    file_manager.db.execute(
        "UPDATE files SET custom_metadata = ? WHERE file_id = ?",
        (encrypted["custom_metadata"], metadata.file_id),
    )

    monkeypatch.setattr(file_manager.storage, "get_encrypted", lambda *a, **k: "secure")
    file_manager.encryption_enabled = True
    assert file_manager.get_file(metadata.file_id, "dest", decrypt=True) == "secure"


def test_delete_box_removes_files_and_shares(file_manager: FileManager, tmp_path: Path) -> None:
    """Deleting a box cascades through files and shares."""
    owner = file_manager.create_user("zoe")
    guest = file_manager.create_user("yuri")
    box = file_manager.create_box(owner.user_id, "temp")

    source_file = tmp_path / "t.txt"
    source_file.write_text("bye")
    file_manager.add_file(owner.user_id, box.box_id, str(source_file))
    file_manager.share_box(box.box_id, owner.user_id, guest.user_id)

    assert file_manager.delete_box(box.box_id) is True
    assert file_manager.box_model.get(box.box_id) is None
    assert file_manager.box_share_model.list_by_box(box.box_id) == []
    assert file_manager.file_model.list_by_box(box.box_id) == []
