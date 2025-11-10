"""Unit tests for hashing functionality."""

import hashlib
from pathlib import Path

import pytest

from shadowbox.core import hashing


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


def test_calculate_sha256_file(tmp_path: Path) -> None:
    """Hashing a file should match manual hashlib computation."""
    file_path = tmp_path / "sample.txt"
    content = b"shadowbox test data"
    file_path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()
    assert hashing.calculate_sha256(file_path) == expected


def test_calculate_sha256_file_empty(tmp_path: Path) -> None:
    """Empty file should produce the same hash as empty bytes."""
    file_path = tmp_path / "empty.bin"
    file_path.write_bytes(b"")

    expected = hashlib.sha256(b"").hexdigest()
    assert hashing.calculate_sha256(file_path) == expected


def test_calculate_sha256_large_file(tmp_path: Path) -> None:
    """Large file should be processed correctly in chunks."""
    file_path = tmp_path / "large.bin"
    data = b"itreallydoesntmatterwhatgoeshere123" * (10**5)  # ~600 KB
    file_path.write_bytes(data)

    expected = hashlib.sha256(data).hexdigest()
    assert hashing.calculate_sha256(file_path) == expected


def test_hash_consistency_bytes() -> None:
    """Hashing the same byte string twice should yield identical results."""
    data = b"consistenthopefully"
    h1 = hashing.calculate_sha256_bytes(data)
    h2 = hashing.calculate_sha256_bytes(data)
    assert h1 == h2


def test_hash_consistency_file(tmp_path: Path) -> None:
    """Hashing the same file twice should yield identical results."""
    file_path = tmp_path / "repeat.txt"
    data = b"repeatable data"
    file_path.write_bytes(data)

    h1 = hashing.calculate_sha256(file_path)
    h2 = hashing.calculate_sha256(file_path)
    assert h1 == h2


def test_file_not_found_raises(tmp_path: Path) -> None:
    """calculate_sha256 should raise FileNotFoundError for missing files."""
    missing = tmp_path / "no_such_file.txt"
    with pytest.raises(FileNotFoundError):
        hashing.calculate_sha256(missing)
