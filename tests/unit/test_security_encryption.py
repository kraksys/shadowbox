"""
Unit tests for the BoxEncryptionBackend.
"""

import pytest
import json
import os
from pathlib import Path
from shadowbox.security.encryption import BoxEncryptionBackend


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def backend(tmp_path):
    """Returns a fresh, uninitialized backend."""
    return BoxEncryptionBackend(tmp_path)


@pytest.fixture
def initialized_backend(tmp_path):
    """Returns a backend initialized with a master password."""
    be = BoxEncryptionBackend(tmp_path)
    be.setup_master_key("correct-password")
    return be


# ==============================================================================
# Tests: Master Key Lifecycle (Lines 89-118)
# ==============================================================================

def test_setup_master_key_fresh(tmp_path):
    """Happy path: Setup master key for the first time."""
    be = BoxEncryptionBackend(tmp_path)
    be.setup_master_key("pass")
    assert be.initialized
    assert (tmp_path / "keys" / "master.json").exists()


def test_setup_master_key_reload_success(tmp_path):
    """
    Cover lines 89-118 (success path).
    Reload an existing backend with the correct password.
    """
    # 1. Initialize first
    be1 = BoxEncryptionBackend(tmp_path)
    be1.setup_master_key("my_secret_pass")

    # 2. Reload
    be2 = BoxEncryptionBackend(tmp_path)
    be2.setup_master_key("my_secret_pass")
    assert be2.initialized

    # Verify they derived the same key (by encrypting with one and decrypting with other)
    # Note: We can't access ._master_key directly easily, but we can verify interoperability
    ct = be1.encrypt_bytes(b"data", "box1")
    pt = be2.decrypt_bytes(ct, "box1")
    assert pt == b"data"


def test_setup_master_key_reload_wrong_password(tmp_path):
    """
    Cover lines 89-118 (error path).
    Reload an existing backend with the WRONG password.
    """
    be1 = BoxEncryptionBackend(tmp_path)
    be1.setup_master_key("correct_pass")

    be2 = BoxEncryptionBackend(tmp_path)
    # Should fail HMAC check
    with pytest.raises(ValueError, match="Invalid master password"):
        be2.setup_master_key("wrong_pass")


# ==============================================================================
# Tests: Uninitialized Access (Line 154)
# ==============================================================================

def test_require_master_key_raises(backend):
    """Cover line 154: Accessing keys before setup raises RuntimeError."""
    with pytest.raises(RuntimeError, match="Master key not initialized"):
        backend.get_box_key("box1")

    with pytest.raises(RuntimeError, match="Master key not initialized"):
        backend.encrypt_bytes(b"data", "box1")


# ==============================================================================
# Tests: Box Key Management & Persistence
# ==============================================================================

def test_get_box_key_persistence(tmp_path):
    """
    Cover 'if path.exists()' branch in get_box_key.
    Ensure box keys are persisted and reloaded correctly.
    """
    be1 = BoxEncryptionBackend(tmp_path)
    be1.setup_master_key("pass")

    # Generate key for box A
    key1 = be1.get_box_key("box_A")
    assert (tmp_path / "keys" / "box_keys" / "box_A.key").exists()

    # Reload backend
    be2 = BoxEncryptionBackend(tmp_path)
    be2.setup_master_key("pass")

    # Retrieve same key
    key2 = be2.get_box_key("box_A")
    assert key1 == key2


# ==============================================================================
# Tests: Encryption/Decryption Edges (Line 213)
# ==============================================================================

def test_decrypt_bytes_too_short(initialized_backend):
    """Cover line 213: Decrypting blob shorter than nonce raises ValueError."""
    with pytest.raises(ValueError, match="Ciphertext too short"):
        initialized_backend.decrypt_bytes(b"short", "box1")


def test_encrypt_decrypt_bytes_roundtrip(initialized_backend):
    """Verify basic byte encryption functionality."""
    msg = b"hello world"
    ct = initialized_backend.encrypt_bytes(msg, "box1")
    # Ciphertext should be nonce (12) + ciphertext (len(msg) + tag(16))
    assert len(ct) == 12 + len(msg) + 16

    pt = initialized_backend.decrypt_bytes(ct, "box1")
    assert pt == msg


# ==============================================================================
# Tests: JSON Helpers (Lines 238-239)
# ==============================================================================

def test_encrypt_decrypt_json_roundtrip(initialized_backend):
    """
    Cover lines 238-239 (encrypt_json) and decrypt_json.
    """
    data = {
        "string": "value",
        "int": 42,
        "list": [1, 2, 3],
        "unicode": "🔒"
    }

    # Encrypt
    blob = initialized_backend.encrypt_json(data, "box_json")
    assert isinstance(blob, bytes)

    # Decrypt
    out = initialized_backend.decrypt_json(blob, "box_json")
    assert out == data