"""Unit tests for database connection and ORM-style model helpers."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import shadowbox.database.connection as connection_module
from shadowbox.core.exceptions import StorageError
from shadowbox.core.models import Box, BoxShare, FileMetadata, FileStatus, FileType
from shadowbox.database.connection import DatabaseConnection, TransactionContext
from shadowbox.database.models import (
    BaseModel,
    BoxModel,
    BoxShareModel,
    FileModel,
    FileVersionModel,
    UserModel,
    row_to_metadata,
)

# --- Fixtures ---


@pytest.fixture
def db_conn(tmp_path):
    """Create an initialized DatabaseConnection backed by a temporary SQLite file."""
    db_path = tmp_path / "db.sqlite"
    conn = DatabaseConnection(str(db_path))
    conn.initialize()
    try:
        yield conn
    finally:
        conn.close()


# --- DatabaseConnection tests ---


def test_initialize_creates_schema_once(db_conn):
    """initialize() should be idempotent and set a positive schema version."""
    # First call happened in fixture; calling again should be a no-op.
    db_conn.initialize()
    version = db_conn.get_version()
    assert isinstance(version, int)
    assert version >= 1


def test_execute_and_fetch_helpers(db_conn):
    """execute, fetch_one and fetch_all should work together for basic CRUD."""
    db_conn.execute(
        "INSERT INTO users (user_id, username) VALUES (?, ?)", ("u1", "alice")
    )

    row = db_conn.fetch_one("SELECT * FROM users WHERE user_id = ?", ("u1",))
    assert row is not None
    assert row["username"] == "alice"

    rows = db_conn.fetch_all("SELECT * FROM users", None)
    assert any(r["user_id"] == "u1" for r in rows)


def test_execute_many_inserts_multiple_rows(db_conn):
    """execute_many should insert multiple rows in a single call."""
    query = """
        INSERT INTO tags (entity_type, entity_id, tag_name)
        VALUES ('file', ?, ?)
    """
    params_list = [
        ("f1", "tag1"),
        ("f2", "tag2"),
    ]
    db_conn.execute_many(query, params_list)

    tags = db_conn.fetch_all("SELECT * FROM tags", None)
    assert {t["tag_name"] for t in tags} == {"tag1", "tag2"}


def test_get_version_returns_zero_on_error(db_conn, monkeypatch):
    """get_version should swallow sqlite errors and return 0."""

    def bad_fetch(self, *args, **kwargs):  # noqa: ARG001
        raise sqlite3.Error("boom")

    monkeypatch.setattr(DatabaseConnection, "fetch_one", bad_fetch)
    assert db_conn.get_version() == 0


def test_backup_creates_working_copy(tmp_path, db_conn):
    """backup() should produce a copy of the database with the same contents."""
    backup_path = tmp_path / "backup.sqlite"

    db_conn.execute(
        "INSERT INTO users (user_id, username) VALUES (?, ?)", ("u1", "bob")
    )
    db_conn.backup(str(backup_path))

    assert backup_path.exists()

    conn = sqlite3.connect(str(backup_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT username FROM users WHERE user_id = 'u1'").fetchone()
    conn.close()

    assert row is not None
    assert row["username"] == "bob"


def test_transaction_context_commit_and_rollback(db_conn):
    """TransactionContext should commit on success and rollback on error."""
    conn = db_conn._get_connection()

    # Commit case
    with TransactionContext(conn) as cur:
        cur.execute("INSERT INTO users (user_id, username) VALUES ('u1', 'alice')")
    row = db_conn.fetch_one("SELECT * FROM users WHERE user_id = 'u1'")
    assert row is not None

    # Rollback case
    with pytest.raises(RuntimeError):
        with TransactionContext(conn) as cur:
            cur.execute("INSERT INTO users (user_id, username) VALUES ('u2', 'bob')")
            raise RuntimeError("force rollback")
    row = db_conn.fetch_one("SELECT * FROM users WHERE user_id = 'u2'")
    assert row is None


def test_initialize_raises_storage_error_on_failure(tmp_path, monkeypatch):
    """initialize should wrap sqlite errors in StorageError."""
    bad_conn = DatabaseConnection(str(tmp_path / "bad.sqlite"))

    def bad_schema():
        raise sqlite3.Error("boom")

    monkeypatch.setattr(connection_module, "get_init_schema", bad_schema)

    try:
        with pytest.raises(StorageError):
            bad_conn.initialize()
    finally:
        bad_conn.close()


# --- BaseModel helpers ---


def test_base_model_json_helpers(db_conn):
    """_serialize_json and _deserialize_json should handle dict and None."""
    base = BaseModel(db_conn)
    data = {"a": 1}
    s = base._serialize_json(data)
    assert isinstance(s, str)
    assert base._deserialize_json(s) == data
    assert base._serialize_json(None) is None
    assert base._deserialize_json(None) is None


# --- UserModel tests ---


def test_user_model_crud(db_conn):
    """UserModel should support create, get, update_quota and delete."""
    um = UserModel(db_conn)

    created = um.create("u1", "alice", quota_bytes=100)
    assert created["username"] == "alice"
    assert created["quota_bytes"] == 100

    assert um.get("u1")["username"] == "alice"
    assert um.get_by_username("alice")["user_id"] == "u1"

    um.update_quota("u1", used_bytes=50)
    assert um.get("u1")["used_bytes"] == 50

    um.delete("u1")
    assert um.get("u1") is None


# --- BoxModel and BoxShareModel tests ---


def _create_user_and_box(db_conn):
    """Helper to create a basic user and box row."""
    um = UserModel(db_conn)
    um.create("u1", "owner")

    bm = BoxModel(db_conn)
    box = Box(
        box_id="b1",
        user_id="u1",
        box_name="docs",
        description="desc",
        is_shared=False,
        share_token="token-1",
        settings={"foo": "bar"},
    )
    bm.create(box)
    return um, bm, box


def test_box_model_crud_and_tags(db_conn):
    """BoxModel should perform basic CRUD and tag management."""
    _um, bm, box = _create_user_and_box(db_conn)

    row = bm.get(box.box_id)
    assert row["box_name"] == "docs"

    # list_by_user
    boxes = bm.list_by_user("u1")
    assert len(boxes) == 1

    # update and set_shared
    box.description = "updated"
    box.is_shared = True
    box.settings = {"foo": "baz"}
    bm.update(box)
    updated = bm.get(box.box_id)
    assert updated["description"] == "updated"
    assert updated["is_shared"] == 1  # SQLite boolean

    bm.add_tags(box.box_id, ["t1", "t2"])
    assert set(bm.get_tags(box.box_id)) == {"t1", "t2"}

    bm.update_tags(box.box_id, ["t3"])
    assert bm.get_tags(box.box_id) == ["t3"]

    bm.set_shared(box.box_id, False)
    assert bm.get(box.box_id)["is_shared"] == 0

    bm.delete(box.box_id)
    assert bm.get(box.box_id) is None


def test_box_share_model_access_levels(db_conn):
    """BoxShareModel.has_access should respect read/write/admin levels."""
    _um, bm, box = _create_user_and_box(db_conn)

    # Second user to share with
    UserModel(db_conn).create("guest", "guest")

    sm = BoxShareModel(db_conn)
    share = BoxShare(
        share_id="s1",
        box_id=box.box_id,
        shared_by_user_id="u1",
        shared_with_user_id="guest",
        permission_level="write",
        expires_at=None,
        access_token="tok123",
    )
    sm.create(share)

    assert sm.get("s1")["box_id"] == box.box_id
    assert sm.get_by_access_token("tok123")["share_id"] == "s1"
    assert len(sm.list_by_box(box.box_id)) == 1
    assert len(sm.list_by_user("guest")) == 1

    # read/write levels
    assert sm.has_access(box.box_id, "guest", "read") is True
    assert sm.has_access(box.box_id, "guest", "write") is True
    assert sm.has_access(box.box_id, "guest", "admin") is False

    # Admin share for separate user
    UserModel(db_conn).create("admin", "admin")
    admin_share = BoxShare(
        share_id="s2",
        box_id=box.box_id,
        shared_by_user_id="u1",
        shared_with_user_id="admin",
        permission_level="admin",
        expires_at=None,
        access_token="tok-admin",
    )
    sm.create(admin_share)
    assert sm.has_access(box.box_id, "admin", "admin") is True

    sm.delete_by_box_and_user(box.box_id, "guest")
    assert sm.get("s1") is None
    sm.delete("s2")
    assert sm.get("s2") is None


# --- FileModel and FileVersionModel tests ---


def _create_file_metadata(file_id="f1"):
    """Helper to build a FileMetadata instance with minimal required fields."""
    now = datetime.utcnow()
    return FileMetadata(
        file_id=file_id,
        box_id="b1",
        filename="file.txt",
        original_path="/tmp/file.txt",
        size=10,
        file_type=FileType.DOCUMENT,
        mime_type="text/plain",
        hash_sha256="hash-1",
        created_at=now,
        modified_at=now,
        accessed_at=now,
        user_id="u1",
        owner="u1",
        status=FileStatus.ACTIVE,
        version=1,
        parent_version_id=None,
        tags=["t1", "t2"],
        description="desc",
        custom_metadata={"x": 1},
    )


def _ensure_user_and_box_for_files(db_conn):
    """Ensure a user and box exist for file foreign keys."""
    um = UserModel(db_conn)
    if um.get("u1") is None:
        um.create("u1", "alice")
    bm = BoxModel(db_conn)
    if bm.get("b1") is None:
        box = Box(
            box_id="b1",
            user_id="u1",
            box_name="docs",
            description="",
            is_shared=False,
            share_token="token-f",
            settings={},
        )
        bm.create(box)


def test_file_model_create_and_get(db_conn):
    """FileModel.create and get should round-trip metadata and tags."""
    _ensure_user_and_box_for_files(db_conn)
    fm = FileModel(db_conn)

    meta = _create_file_metadata()
    file_id = fm.create(meta)
    assert file_id == meta.file_id

    loaded = fm.get(file_id)
    assert loaded is not None
    assert loaded.filename == "file.txt"
    assert loaded.tags == ["t1", "t2"]


def test_file_model_create_many_and_listing(db_conn):
    """create_many and list_by_user/box should return expected results."""
    _ensure_user_and_box_for_files(db_conn)
    fm = FileModel(db_conn)

    meta1 = _create_file_metadata("f1")
    meta2 = _create_file_metadata("f2")
    meta2.filename = "other.txt"
    meta2.hash_sha256 = "hash-2"
    meta2.tags = ["tag-x"]

    fm.create_many([meta1, meta2])

    by_user = fm.list_by_user("u1")
    assert len(by_user) == 2

    by_box = fm.list_by_box("b1")
    assert len(by_box) == 2

    subset = fm.list_by_user("u1", limit=1, offset=0)
    assert len(subset) == 1

    by_user_box = fm.list_by_user_and_box("u1", "b1")
    assert len(by_user_box) == 2


def test_file_model_update_and_delete(db_conn):
    """FileModel.update should change fields and tags; delete soft/hard paths."""
    _ensure_user_and_box_for_files(db_conn)
    fm = FileModel(db_conn)

    meta = _create_file_metadata("fx")
    fm.create(meta)

    # Update filename, size, description, tags
    meta.filename = "updated.txt"
    meta.size = 20
    meta.description = "updated"
    meta.tags = ["new"]
    meta.version = 2
    meta.modified_at = datetime.utcnow()
    fm.update(meta)

    loaded = fm.get("fx")
    assert loaded.filename == "updated.txt"
    assert loaded.size == 20
    assert loaded.tags == ["new"]
    assert loaded.version == 2

    # Soft delete
    fm.delete("fx", soft=True)
    active = fm.list_by_user("u1")
    assert all(f.file_id != "fx" for f in active)
    deleted_included = fm.list_by_user("u1", include_deleted=True)
    assert any(f.file_id == "fx" for f in deleted_included)

    # Hard delete
    fm.delete("fx", soft=False)
    assert fm.get("fx") is None


def test_file_model_find_by_hash_and_row_to_metadata(db_conn):
    """find_by_hash and row_to_metadata should behave as expected, including bad JSON."""
    _ensure_user_and_box_for_files(db_conn)
    fm = FileModel(db_conn)

    meta = _create_file_metadata("fh")
    fm.create(meta)

    found = fm.find_by_hash("hash-1")
    assert len(found) == 1
    assert found[0].file_id == "fh"

    # Force invalid JSON in custom_metadata to hit the error branch
    db_conn.execute(
        "UPDATE files SET custom_metadata = 'not-json' WHERE file_id = ?",
        ("fh",),
    )
    row = db_conn.fetch_one("SELECT * FROM files WHERE file_id = ?", ("fh",))
    meta2 = row_to_metadata(row, ["tag-from-row"])
    assert meta2.custom_metadata == {}
    assert meta2.tags == ["tag-from-row"]


def test_file_version_model_create_and_list(db_conn):
    """FileVersionModel should create and list historical versions."""
    _ensure_user_and_box_for_files(db_conn)
    fm = FileModel(db_conn)
    meta = _create_file_metadata("fv")
    fm.create(meta)

    # Take a snapshot
    row = db_conn.fetch_one("SELECT * FROM files WHERE file_id = 'fv'")
    fvm = FileVersionModel(db_conn)
    version_id = fvm.create_from_file_row(row, "initial snapshot")

    assert isinstance(version_id, str)

    versions = fvm.list_by_file("fv")
    assert len(versions) == 1
    assert versions[0]["change_description"] == "initial snapshot"
