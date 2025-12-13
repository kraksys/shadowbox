"""Unit tests for the Storage core module."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from shadowbox.core.storage import Storage


@pytest.fixture
def storage(tmp_path):
    """Return a Storage instance rooted in tmp_path."""
    return Storage(str(tmp_path))


@pytest.fixture
def storage_with_key(storage):
    """Return a Storage instance with encryption setup."""
    storage.setup_master_key("testpass")
    return storage


# --- Priority 1: verify_encrypted (Lines 223-240) ---

def test_verify_encrypted_success(storage_with_key, tmp_path):
    """Test verify_encrypted returns True when hash matches."""
    user_id = "u1"
    box_id = "b1"

    # create a dummy file
    src = tmp_path / "test.txt"
    src.write_bytes(b"content")

    # Put it (this sets up keys and metadata)
    info = storage_with_key.put_encrypted(user_id, box_id, str(src))
    file_hash = info['hash']

    # Verify
    assert storage_with_key.verify_encrypted(user_id, box_id, file_hash) is True


def test_verify_encrypted_failure_corruption(storage_with_key, tmp_path):
    """Test verify_encrypted returns False when content is tampered."""
    user_id = "u1"
    box_id = "b1"
    src = tmp_path / "test.txt"
    src.write_bytes(b"content")

    info = storage_with_key.put_encrypted(user_id, box_id, str(src))
    file_hash = info['hash']

    # Tamper with the .enc file on disk
    enc_path = Path(info['encrypted_path'])
    data = enc_path.read_bytes()
    # Flip the last byte (integrity check should fail inside crypto or hash mismatch)
    with open(enc_path, 'wb') as f:
        f.write(data[:-1] + b'\x00')

    # Should return False (either due to crypto error or hash mismatch)
    assert storage_with_key.verify_encrypted(user_id, box_id, file_hash) is False


def test_verify_encrypted_missing_file(storage_with_key):
    """Test verify_encrypted returns False if file missing."""
    assert storage_with_key.verify_encrypted("u1", "b1", "nonexistent_hash") is False


def test_verify_encrypted_no_backend(storage, tmp_path):
    """Test verify_encrypted returns False if encryption backend not set up."""
    # We manually create a fake .enc file to pass the .exists() check
    user_id = "u1"
    box_id = "b1"
    h = "abc123hash"

    blob_dir = storage.blob_root(user_id, box_id)
    blob_dir.mkdir(parents=True, exist_ok=True)
    (blob_dir / f"{h}.enc").write_bytes(b"garbage")

    # storage.encrypt is None here
    assert storage.verify_encrypted(user_id, box_id, h) is False


# --- Priority 2: delete_encrypted (Lines 243-259) ---

def test_delete_encrypted_success(storage_with_key, tmp_path):
    """Test deleting an encrypted file removes it from disk and metadata."""
    user_id = "u1"
    box_id = "b1"
    src = tmp_path / "test.txt"
    src.write_bytes(b"content")

    info = storage_with_key.put_encrypted(user_id, box_id, str(src))
    file_hash = info['hash']

    # Ensure it exists
    assert (Path(info['encrypted_path'])).exists()
    meta_before = storage_with_key.load_metadata(user_id, box_id)
    assert file_hash in meta_before['files']

    # Delete
    result = storage_with_key.delete_encrypted(user_id, box_id, file_hash)

    assert result is True
    assert not (Path(info['encrypted_path'])).exists()

    meta_after = storage_with_key.load_metadata(user_id, box_id)
    assert file_hash not in meta_after['files']


def test_delete_encrypted_missing(storage_with_key):
    """Test delete_encrypted returns False for non-existent file."""
    assert storage_with_key.delete_encrypted("u1", "b1", "missing_hash") is False


# --- Priority 3: Metadata Error Handling (Lines 100-107, 128-129) ---

def test_load_metadata_corrupted_json(storage):
    """Test load_metadata returns default dict on corrupted file."""
    user_id = "u1"
    box_id = "b1"
    meta_path = storage.metadata_path(user_id, box_id)
    storage.ensure_box(user_id, box_id)

    # Write garbage
    with open(meta_path, 'w') as f:
        f.write("{ invalid json")

    meta = storage.load_metadata(user_id, box_id)
    # Should return default structure
    assert meta["box_id"] == box_id
    assert meta["files"] == {}


def test_load_box_settings_corrupted(storage):
    """Test load_box_settings returns empty dict on error."""
    user_id = "u1"
    box_id = "b1"
    p = storage.box_settings_path(user_id, box_id)
    storage.ensure_box(user_id, box_id)

    with open(p, 'w') as f:
        f.write("not json")

    assert storage.load_box_settings(user_id, box_id) == {}


# --- Priority 4: Encryption Edge Cases & Idempotency ---

def test_put_encrypted_no_backend_raises(storage):
    """Test put_encrypted raises RuntimeError if setup_master_key not called."""
    with pytest.raises(RuntimeError, match="Encryption backend not configured"):
        storage.put_encrypted("u1", "b1", "somepath")


def test_get_encrypted_errors(storage_with_key):
    """Test get_encrypted error states."""
    # 1. Missing file
    with pytest.raises(FileNotFoundError):
        storage_with_key.get_encrypted("u1", "b1", "missing_hash", "dest")

    # 2. Backend not configured (need a fresh storage instance)
    fresh_storage = Storage()
    with pytest.raises(RuntimeError):
        fresh_storage.get_encrypted("u1", "b1", "h", "d")


def test_put_plain_idempotency(storage, tmp_path):
    """Test that put() doesn't overwrite if file exists (Lines 284-286)."""
    user_id = "u1"
    box_id = "b1"
    src = tmp_path / "file.txt"
    src.write_bytes(b"data")

    # First put
    res1 = storage.put(user_id, box_id, str(src))
    dest_path = Path(res1['path'])
    mtime_1 = dest_path.stat().st_mtime

    # Wait a tiny bit to ensure mtime would change if written
    import time
    time.sleep(0.01)

    # Second put
    storage.put(user_id, box_id, str(src))
    mtime_2 = dest_path.stat().st_mtime

    assert mtime_1 == mtime_2


# --- Priority 5: Plain Verification & Listing ---

def test_verify_plain(storage, tmp_path):
    """Test verify() for plain files."""
    user_id = "u1"
    box_id = "b1"
    src = tmp_path / "file.txt"
    src.write_bytes(b"data")

    info = storage.put(user_id, box_id, str(src))
    h = info['hash']

    # 1. Success
    assert storage.verify(user_id, box_id, h) is True

    # 2. Missing
    assert storage.verify(user_id, box_id, "badhash") is False

    # 3. Content mismatch
    dest = Path(info['path'])
    dest.write_bytes(b"corruption")
    assert storage.verify(user_id, box_id, h) is False


def test_list_encrypted_files(storage):
    """Test list_encrypted_files filters correctly."""
    user_id = "u1"
    box_id = "b1"

    # Manually seed metadata with mixed content
    meta = {
        "files": {
            "h1": {"encrypted": True},
            "h2": {"encrypted": False},
            "h3": {"encrypted": True}
        }
    }
    storage.ensure_box(user_id, box_id)
    storage.save_metadata(user_id, box_id, meta)

    result = storage.list_encrypted_files(user_id, box_id)
    assert "h1" in result
    assert "h3" in result
    assert "h2" not in result
    assert len(result) == 2