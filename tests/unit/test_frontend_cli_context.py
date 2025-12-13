"""Unit tests for the CLI AppContext builder."""

import pytest
from unittest.mock import Mock, patch
from pathlib import Path
from shadowbox.frontend.cli.context import build_context, _user_from_row


@pytest.fixture
def mock_deps():
    """Mock external dependencies: DB, FileManager, FTS init."""
    with patch("shadowbox.frontend.cli.context.DatabaseConnection") as db, \
            patch("shadowbox.frontend.cli.context.FileManager") as fm, \
            patch("shadowbox.frontend.cli.context.init_fts") as fts:
        # Configure FileManager mock instance
        fm_instance = fm.return_value
        fm_instance.storage_root = "/tmp/root"
        yield db, fm, fts


def test_build_context_first_run(mock_deps, tmp_path):
    """Test context building when DB is missing (First Run)."""
    mock_db_cls, mock_fm_cls, mock_fts = mock_deps

    # Simulate missing DB
    db_path = tmp_path / "missing.db"

    fm_instance = mock_fm_cls.return_value
    # User not found -> create new
    fm_instance.user_model.get_by_username.return_value = None
    fm_instance.create_user.return_value = Mock(user_id="u1", username="tester")

    ctx = build_context(db_path=db_path, username="tester")

    assert ctx.first_run is True
    # In first run, active_box is None (user must create one)
    assert ctx.active_box is None
    # Check FTS was initialized
    mock_fts.assert_called_once()
    # Check User was created
    fm_instance.create_user.assert_called_with("tester")


def test_build_context_existing_db(mock_deps, tmp_path):
    """Test context building with existing DB and User."""
    mock_db_cls, mock_fm_cls, _ = mock_deps

    # Simulate existing DB
    db_path = tmp_path / "exists.db"
    db_path.touch()

    fm_instance = mock_fm_cls.return_value
    # Existing user
    fm_instance.user_model.get_by_username.return_value = {
        "user_id": "u1", "username": "tester", "quota_bytes": 100, "used_bytes": 10
    }
    # Existing boxes
    default_box = Mock(box_name="default", box_id="b1")
    fm_instance.list_user_boxes.return_value = [default_box]

    ctx = build_context(db_path=db_path, username="tester")

    assert ctx.first_run is False
    assert ctx.user.user_id == "u1"
    # Should automatically select default box
    assert ctx.active_box == default_box


def test_user_from_row():
    """Test helper to rehydrate UserDirectory from DB row."""
    fm = Mock()
    fm.storage_root = "/storage"
    row = {
        "user_id": "u123",
        "username": "bob",
        "quota_bytes": 1000,
        "used_bytes": 500
    }

    user = _user_from_row(fm, row)

    assert user.user_id == "u123"
    assert user.username == "bob"
    assert user.quota_bytes == 1000
    assert user.used_bytes == 500
    assert user.root_path == "/storage/u123"