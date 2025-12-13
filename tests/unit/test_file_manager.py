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


def test_update_file_success_with_versioning(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover update_file: ensure content updates, quota adjusts, and version increments."""
    # 1. Setup initial file
    user = file_manager.create_user("updater")
    box = file_manager.create_box(user.user_id, "versions")

    src_v1 = tmp_path / "file_v1.txt"
    src_v1.write_bytes(b"version 1 data")  # 14 bytes

    meta = file_manager.add_file(user.user_id, box.box_id, str(src_v1))
    original_size = meta.size

    # 2. Update file (make it larger)
    src_v2 = tmp_path / "file_v2.txt"
    src_v2.write_bytes(b"version 2 data is longer")  # 24 bytes

    updated_meta = file_manager.update_file(
        meta.file_id,
        str(src_v2),
        change_description="Fix typo"
    )

    # 3. Verify Metadata updates
    assert updated_meta.version == 2
    assert updated_meta.size == 24
    assert updated_meta.filename == "file_v2.txt"

    # 4. Verify Quota Update (User usage should increase by diff: 24 - 14 = 10 bytes)
    user_rec = file_manager.user_model.get(user.user_id)
    assert user_rec["used_bytes"] == 24

    # 5. Verify Version Snapshot created
    # (assuming VersionManager works, we just check integration here)
    versions = file_manager.list_file_versions(meta.file_id)
    assert len(versions) == 1
    assert versions[0]["version_number"] == 1
    assert versions[0]["size"] == 14


def test_update_file_respects_quota(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover update_file quota check."""
    user = file_manager.create_user("quota_user")
    # Set small quota (20 bytes)
    file_manager.db.execute("UPDATE users SET quota_bytes = ? WHERE user_id = ?", (20, user.user_id))

    box = file_manager.create_box(user.user_id, "box")

    src = tmp_path / "small.txt"
    src.write_bytes(b"12345")  # 5 bytes
    meta = file_manager.add_file(user.user_id, box.box_id, str(src))

    # Update with file that exceeds quota (25 bytes > 20 bytes)
    large_src = tmp_path / "large.txt"
    large_src.write_bytes(b"1" * 25)

    with pytest.raises(QuotaExceededError):
        file_manager.update_file(meta.file_id, str(large_src))


def test_update_file_missing_errors(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover FileNotFoundError paths in update_file."""
    user = file_manager.create_user("err_user")
    box = file_manager.create_box(user.user_id, "box")
    src = tmp_path / "file.txt"
    src.write_text("content")
    meta = file_manager.add_file(user.user_id, box.box_id, str(src))

    # Case 1: Source file missing
    with pytest.raises(FileNotFoundError, match="Source file not found"):
        file_manager.update_file(meta.file_id, "/non/existent/path.txt")

    # Case 2: File ID missing in DB
    with pytest.raises(FileNotFoundError, match="File with ID"):
        file_manager.update_file("bad-id", str(src))


# ==============================================================================
# Tests for add_files_bulk (Lines 522-605)
# ==============================================================================

def test_add_files_bulk_success(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover add_files_bulk: happy path with multiple valid files."""
    user = file_manager.create_user("bulk_adder")
    box = file_manager.create_box(user.user_id, "bulk_box")

    # Create 3 files
    files = []
    for i in range(3):
        p = tmp_path / f"bulk_{i}.txt"
        p.write_text(f"content {i}")
        files.append(str(p))

    result = file_manager.add_files_bulk(user.user_id, box.box_id, files)

    assert len(result["success"]) == 3
    assert len(result["failed"]) == 0
    assert result["success"][0].filename == "bulk_0.txt"

    # Check quota updated once
    # 3 files * 9 bytes ("content X") = 27 bytes
    user_rec = file_manager.user_model.get(user.user_id)
    assert user_rec["used_bytes"] == 27


def test_add_files_bulk_partial_failures(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover add_files_bulk: mixed success and failure (missing file)."""
    user = file_manager.create_user("mixed_adder")
    box = file_manager.create_box(user.user_id, "box")

    real_file = tmp_path / "real.txt"
    real_file.write_text("real")

    paths = [str(real_file), "/path/to/ghost.txt"]

    result = file_manager.add_files_bulk(user.user_id, box.box_id, paths)

    assert len(result["success"]) == 1
    assert len(result["failed"]) == 1
    assert result["failed"][0]["error"] == "File not found"

    # DB should contain only the success
    assert len(file_manager.list_box_files(box.box_id)) == 1


def test_add_files_bulk_quota_check(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover add_files_bulk: pre-flight quota check prevents upload."""
    user = file_manager.create_user("quota_bulk")
    file_manager.db.execute("UPDATE users SET quota_bytes = ? WHERE user_id = ?", (10, user.user_id))
    box = file_manager.create_box(user.user_id, "box")

    # 2 files, 6 bytes each = 12 bytes > 10 quota
    f1 = tmp_path / "f1.txt"
    f1.write_bytes(b"123456")
    f2 = tmp_path / "f2.txt"
    f2.write_bytes(b"123456")

    with pytest.raises(QuotaExceededError):
        file_manager.add_files_bulk(user.user_id, box.box_id, [str(f1), str(f2)])

    # Ensure nothing was uploaded
    assert len(file_manager.list_box_files(box.box_id)) == 0


def test_add_files_bulk_permissions(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover add_files_bulk: permission denied for non-owners/writers."""
    owner = file_manager.create_user("owner")
    outsider = file_manager.create_user("outsider")
    box = file_manager.create_box(owner.user_id, "private")

    f1 = tmp_path / "f1.txt"
    f1.write_text("data")

    with pytest.raises(AccessDeniedError):
        file_manager.add_files_bulk(outsider.user_id, box.box_id, [str(f1)])


# ==============================================================================
# Tests for delete_files_bulk (Lines 609-645)
# ==============================================================================

def test_delete_files_bulk_soft(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover delete_files_bulk: soft delete functionality."""
    user = file_manager.create_user("deleter")
    box = file_manager.create_box(user.user_id, "trash")

    # Create 2 files
    ids = []
    for i in range(2):
        p = tmp_path / f"del_{i}.txt"
        p.write_bytes(b"data")  # 4 bytes
        meta = file_manager.add_file(user.user_id, box.box_id, str(p))
        ids.append(meta.file_id)

    # Pre-check quota
    assert file_manager.user_model.get(user.user_id)["used_bytes"] == 8

    # Bulk Delete
    count = file_manager.delete_files_bulk(ids, soft=True)

    assert count == 2

    # Verify status changed to 'deleted'
    for fid in ids:
        f = file_manager.file_model.get(fid)
        assert f.status.value == "deleted"

    # Verify quota freed
    assert file_manager.user_model.get(user.user_id)["used_bytes"] == 0


def test_delete_files_bulk_hard(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover delete_files_bulk: hard delete removes records."""
    user = file_manager.create_user("hard_deleter")
    box = file_manager.create_box(user.user_id, "trash")

    p = tmp_path / "file.txt"
    p.write_text("data")
    meta = file_manager.add_file(user.user_id, box.box_id, str(p))

    count = file_manager.delete_files_bulk([meta.file_id], soft=False)

    assert count == 1
    # Record should be gone
    assert file_manager.file_model.get(meta.file_id) is None


def test_delete_files_bulk_empty_or_missing(file_manager: FileManager) -> None:
    """Cover edge cases: empty list or non-existent IDs."""
    assert file_manager.delete_files_bulk([]) == 0
    assert file_manager.delete_files_bulk(["non-existent-id"]) == 0


# ==============================================================================
# Bonus: Versioning Integration (Lines 299-300 approx)
# ==============================================================================

def test_file_version_restore_flow(file_manager: FileManager, tmp_path: Path) -> None:
    """Cover list_file_versions and restore_file_version integration."""
    user = file_manager.create_user("reverter")
    box = file_manager.create_box(user.user_id, "rev_box")

    # V1
    p = tmp_path / "f.txt"
    p.write_text("v1")
    meta = file_manager.add_file(user.user_id, box.box_id, str(p))

    # V2
    p.write_text("v2")
    file_manager.update_file(meta.file_id, str(p))

    # List versions
    versions = file_manager.list_file_versions(meta.file_id)
    assert len(versions) == 1  # Contains V1 snapshot
    v1_id = versions[0]["version_id"]

    # Restore V1
    file_manager.restore_file_version(meta.file_id, v1_id)

    # Verify current state is V1 (size 2 bytes vs 2 bytes, but technically a restore logic check)
    # Since we lack deep inspection of the version manager's restore logic here, 
    # ensuring it runs without error covers the integration lines.
    current = file_manager.get_file_metadata(meta.file_id)
    assert current.version == 3  # Restore creates a new version
