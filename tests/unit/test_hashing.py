"""Unit tests for hashing functionality."""

import hashlib

from shadowbox.core import hashing

# import io
# from pathlib import Path
#
# import pytest


def test_calculate_sha256_bytes_basic() -> None:
    """Hashing bytes should match hashlib output."""
    data = b"hello world"
    expected = hashlib.sha256(data).hexdigest()
    assert hashing.calculate_sha256_bytes(data) == expected


def test_calculate_sha256_bytes_empty() -> None:
    """Empty bytes should still produce a valid hash."""
    data = b""
    expected = hashlib.sha256(data).hexdigest()
    assert hashing.calculate_sha256_bytes(data) == expected
