"""Unit tests for the Key Derivation Function (KDF) module."""

import pytest
from shadowbox.security.kdf import generate_salt, derive_master_key, kdf_params_to_dict


def test_generate_salt_defaults():
    """Ensure salt generation returns bytes of the default length (16)."""
    salt = generate_salt()
    assert isinstance(salt, bytes)
    assert len(salt) == 16


def test_generate_salt_custom_length():
    """Ensure salt generation respects the length parameter."""
    salt = generate_salt(length=32)
    assert len(salt) == 32
    assert isinstance(salt, bytes)


def test_derive_master_key_with_string_password():
    """
    Cover Line 25: Ensure string passwords are automatically encoded.
    This covers the True branch of 'if isinstance(password, str)'.
    """
    salt = generate_salt()
    password_str = "secure_string_password"

    key = derive_master_key(password_str, salt)

    assert isinstance(key, bytes)
    assert len(key) == 32  # Default key length


def test_derive_master_key_with_bytes_password():
    """
    Cover the False branch of 'if isinstance(password, str)'.
    """
    salt = generate_salt()
    password_bytes = b"secure_bytes_password"

    key = derive_master_key(password_bytes, salt)

    assert isinstance(key, bytes)
    assert len(key) == 32


def test_derive_master_key_consistency():
    """Ensure passing the same password as string or bytes yields the same key."""
    salt = generate_salt()
    key_from_str = derive_master_key("password123", salt)
    key_from_bytes = derive_master_key(b"password123", salt)

    assert key_from_str == key_from_bytes


def test_derive_master_key_custom_params():
    """Ensure custom parameters (cost, length) are respected."""
    salt = generate_salt()
    # Use very low costs for speed in unit tests
    key = derive_master_key(
        b"pass",
        salt,
        time_cost=1,
        memory_cost=8,
        parallelism=1,
        key_len=64
    )

    assert len(key) == 64


def test_kdf_params_to_dict():
    """
    Cover Line 39: Validate the helper function serialization.
    """
    salt = b'\xaa' * 16
    result = kdf_params_to_dict(
        salt=salt,
        time_cost=2,
        memory_cost=1024,
        parallelism=4
    )

    expected = {
        "algo": "argon2id",
        "salt": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",  # hex representation
        "time": 2,
        "memory": 1024,
        "parallelism": 4
    }

    assert result == expected