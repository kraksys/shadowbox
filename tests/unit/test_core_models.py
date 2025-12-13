"""
Unit tests for core data models.
"""

import json
import uuid
from datetime import datetime, timedelta
import pytest

from shadowbox.core.models import (
    FileType,
    FileStatus,
    BoxStatus,
    FileMetadata,
    UserDirectory,
    Box,
    BoxShare,
    FileVersion,
    create_version_from_dict,
    DuplicateGroup,
    SearchResult,
)


# ==============================================================================
# FileMetadata Tests
# ==============================================================================

class TestFileMetadata:
    def test_repr(self):
        """Cover __repr__."""
        fm = FileMetadata(file_id="123", filename="test.txt")
        assert repr(fm) == "FileMetadata(file_id='123', filename='test.txt')"

    def test_equality_and_hash(self):
        """Cover __eq__ and __hash__."""
        fm1 = FileMetadata(file_id="abc", filename="A")
        fm2 = FileMetadata(file_id="abc", filename="B")  # ID matches
        fm3 = FileMetadata(file_id="def", filename="A")  # Different ID

        assert fm1 == fm2
        assert fm1 != fm3
        assert fm1 != "not-a-metadata-object"
        assert hash(fm1) == hash(fm2)

    def test_to_dict(self):
        """Cover to_dict."""
        now = datetime.utcnow()
        fm = FileMetadata(
            file_id="1",
            box_id="b1",
            filename="f.txt",
            size=100,
            file_type=FileType.DOCUMENT,
            created_at=now
        )
        data = fm.to_dict()
        assert data["file_id"] == "1"
        assert data["file_type"] == "document"
        assert data["created_at"] == now.isoformat()

    def test_create_from_dict_full(self):
        """Cover create_metadata_from_dict with all fields valid."""
        now_str = datetime.utcnow().isoformat()
        data = {
            "file_id": "123",
            "box_id": "box1",
            "filename": "test.png",
            "original_path": "/tmp/test.png",
            "size": 500,
            "file_type": "image",  # String input for Enum
            "mime_type": "image/png",
            "hash_sha256": "hash123",
            "created_at": now_str,
            "modified_at": now_str,
            "accessed_at": now_str,
            "user_id": "u1",
            "owner": "alice",
            "status": "active",
            "version": 2,
            "tags": ["tag1"],
            "custom_metadata": {"key": "val"}
        }

        fm = FileMetadata.create_metadata_from_dict(data)

        assert fm.file_id == "123"
        assert fm.file_type == FileType.IMAGE
        assert isinstance(fm.created_at, datetime)
        assert fm.tags == ["tag1"]

    def test_create_from_dict_sparse(self):
        """Cover create_metadata_from_dict with missing optional fields."""
        data = {"file_id": "sparse"}
        fm = FileMetadata.create_metadata_from_dict(data)

        assert fm.file_id == "sparse"
        assert fm.filename == ""
        assert fm.file_type == FileType.OTHER  # Default
        assert fm.status == FileStatus.ACTIVE  # Default

    def test_create_from_dict_datetime_objects(self):
        """Cover create_metadata_from_dict where dates are already datetime objects."""
        now = datetime.utcnow()
        data = {
            "file_id": "dt_test",
            "created_at": now,  # Not a string
            "modified_at": now,
            "accessed_at": now
        }
        fm = FileMetadata.create_metadata_from_dict(data)
        assert fm.created_at == now


# ==============================================================================
# UserDirectory Tests
# ==============================================================================

class TestUserDirectory:
    def test_quota_calculations(self):
        """Cover get_quota_remaining and get_quota_percentage."""
        # Case 1: 50% used
        u = UserDirectory("u1", "alice", "/root", quota_bytes=100, used_bytes=50)
        assert u.get_quota_remaining() == 50
        assert u.get_quota_percentage() == 50.0

        # Case 2: 0 quota (unlimited/edge case)
        u_zero = UserDirectory("u2", "bob", "/root", quota_bytes=0, used_bytes=50)
        assert u_zero.get_quota_percentage() == 100.0

        # Case 3: Over quota
        u_over = UserDirectory("u3", "eve", "/root", quota_bytes=10, used_bytes=20)
        assert u_over.get_quota_remaining() == 0

    def test_serialization(self):
        """Cover to_dict and __repr__."""
        u = UserDirectory("u1", "alice", "/path")
        d = u.to_dict()
        assert d["username"] == "alice"
        assert d["used_bytes"] == 0
        assert repr(u) == "UserDirectory(user_id='u1', username='alice')"


# ==============================================================================
# Box Tests
# ==============================================================================

class TestBox:
    def test_repr(self):
        b = Box(box_id="b1", user_id="u1", box_name="stuff")
        assert repr(b) == "Box(box_id='b1', box_name='stuff', user_id='u1')"

    def test_init_date_normalization(self):
        """Cover date string parsing in __init__."""
        now_str = datetime.utcnow().isoformat()

        # Valid strings
        b1 = Box(created_at=now_str, updated_at=now_str)
        assert isinstance(b1.created_at, datetime)

        # Invalid strings (fallback to utcnow)
        b2 = Box(created_at="not-a-date", updated_at="bad-date")
        assert isinstance(b2.created_at, datetime)

    def test_init_settings_parsing(self):
        """Cover settings JSON parsing in __init__."""
        # Valid JSON string
        b1 = Box(settings='{"enc": true}')
        assert b1.settings == {"enc": True}

        # Invalid JSON string
        b2 = Box(settings='{bad-json}')
        assert b2.settings == {}

        # None
        b3 = Box(settings=None)
        assert b3.settings == {}

    def test_to_dict(self):
        b = Box(box_id="b1")
        d = b.to_dict()
        assert d["box_id"] == "b1"
        assert isinstance(d["settings"], dict)


# ==============================================================================
# BoxShare Tests
# ==============================================================================

class TestBoxShare:
    def test_date_parsing_and_defaults(self):
        """Cover date parsing in __init__."""
        now_str = datetime.utcnow().isoformat()

        # Valid dates
        s1 = BoxShare(created_at=now_str, expires_at=now_str)
        assert isinstance(s1.created_at, datetime)
        assert isinstance(s1.expires_at, datetime)

        # Invalid dates
        s2 = BoxShare(created_at="bad", expires_at="bad")
        assert isinstance(s2.created_at, datetime)
        assert s2.expires_at is None

    def test_is_expired(self):
        """Cover is_expired logic."""
        # No expiry
        s1 = BoxShare(expires_at=None)
        assert s1.is_expired() is False

        # Future expiry
        future = datetime.utcnow() + timedelta(days=1)
        s2 = BoxShare(expires_at=future)
        assert s2.is_expired() is False

        # Past expiry
        past = datetime.utcnow() - timedelta(days=1)
        s3 = BoxShare(expires_at=past)
        assert s3.is_expired() is True

    def test_to_dict(self):
        s = BoxShare(expires_at=None)
        d = s.to_dict()
        assert d["expires_at"] is None


# ==============================================================================
# FileVersion Tests
# ==============================================================================

class TestFileVersion:
    def test_to_dict(self):
        now = datetime.utcnow()
        fv = FileVersion(
            version_id="v1",
            file_id="f1",
            version_number=1,
            hash_sha256="h",
            size=10,
            created_at=now,
            created_by="u1",
            change_description="init",
            parent_version_id="p",
            snapshot_id="s"
        )
        d = fv.to_dict()
        assert d["version_id"] == "v1"
        assert d["created_at"] == now.isoformat()
        assert d["change_description"] == "init"

    def test_create_version_from_dict(self):
        """Cover create_version_from_dict."""
        now = datetime.utcnow()
        data = {
            "version_id": "v2",
            "file_id": "f1",
            "version_number": 2,
            "hash_sha256": "h2",
            "size": 20,
            "created_at": now.isoformat(),
            "created_by": "u1",
            "change_description": "update"
        }

        # Test with string date
        fv1 = create_version_from_dict(data)
        assert fv1.version_id == "v2"
        assert isinstance(fv1.created_at, datetime)

        # Test with datetime object
        data["created_at"] = now
        fv2 = create_version_from_dict(data)
        assert fv2.created_at == now


# ==============================================================================
# DuplicateGroup Tests
# ==============================================================================

class TestDuplicateGroup:
    def test_to_dict(self):
        """Cover to_dict for DuplicateGroup."""
        dg = DuplicateGroup(
            hash_sha256="abc",
            file_count=2,
            total_size=200,
            potential_savings=100,
            file_ids=["f1", "f2"],
            file_paths=["/a", "/b"]
        )
        d = dg.to_dict()
        assert d["hash"] == "abc"
        assert d["file_ids"] == ["f1", "f2"]
        assert d["file_paths"] == ["/a", "/b"]


# ==============================================================================
# SearchResult Tests
# ==============================================================================

class TestSearchResult:
    def test_to_dict(self):
        """Cover to_dict for SearchResult."""
        fm = FileMetadata(file_id="f1")
        sr = SearchResult(
            file_metadata=fm,
            relevance_score=0.9,
            matched_fields=["filename"],
            snippet="test"
        )
        d = sr.to_dict()
        assert d["relevance_score"] == 0.9
        assert d["file_metadata"]["file_id"] == "f1"