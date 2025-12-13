"""Unit tests for the database indexing module (FTS)."""

import pytest
from unittest.mock import Mock, call
from shadowbox.database.indexing import init_fts, index_file, remove_from_index, reindex_all, tags_for


@pytest.fixture
def mock_db():
    return Mock()


def test_init_fts(mock_db):
    """Test init_fts creates tables and triggers."""
    init_fts(mock_db)
    # It executes multiple SQL statements (table + triggers)
    assert mock_db.execute.call_count >= 5
    calls = [str(c) for c in mock_db.execute.call_args_list]
    assert any("CREATE VIRTUAL TABLE" in c for c in calls)
    assert any("CREATE TRIGGER" in c for c in calls)


def test_tags_for(mock_db):
    """Test tags_for helper aggregates tags."""
    mock_db.fetch_all.return_value = [{"tag_name": "t1"}, {"tag_name": "t2"}]
    res = tags_for(mock_db, "f1")
    assert res == "t1 t2"

    # Check SQL
    sql = mock_db.fetch_all.call_args[0][0]
    assert "entity_type = 'file'" in sql


def test_index_file_not_found(mock_db):
    """Test index_file does nothing if file missing."""
    mock_db.fetch_one.return_value = None
    index_file(mock_db, "missing")
    # Should not execute insert/delete logic for FTS
    mock_db.execute.assert_not_called()


def test_index_file_success(mock_db):
    """Test index_file updates FTS index for a file."""
    mock_db.fetch_one.return_value = {
        "file_id": "f1",
        "filename": "name",
        "description": "desc",
        "custom_metadata": "meta"
    }
    # Mock tags fetch (indirectly tested via tags_for logic inside index_file)
    mock_db.fetch_all.return_value = [{"tag_name": "t1"}]

    index_file(mock_db, "f1")

    # Check delete then insert calls
    assert mock_db.execute.call_count == 2
    calls = mock_db.execute.call_args_list

    # First call: DELETE FROM files_fts
    assert "DELETE" in calls[0][0][0]

    # Second call: INSERT INTO files_fts
    insert_call = calls[1][0]
    assert "INSERT" in insert_call[0]
    # Check params passed to insert: id, name, desc, tags, metadata
    params = insert_call[1]
    assert params[0] == "f1"
    assert params[1] == "name"
    assert params[3] == "t1"  # tags string


def test_remove_from_index(mock_db):
    """Test remove_from_index executes delete."""
    remove_from_index(mock_db, "f1")
    mock_db.execute.assert_called_with("DELETE FROM files_fts WHERE file_id = ?", ("f1",))


def test_reindex_all(mock_db):
    """Test reindex_all clears index and rebuilds for all files."""
    # Mock finding 2 files
    mock_db.fetch_all.side_effect = [
        [
            {"file_id": "f1", "filename": "n1", "description": "", "custom_metadata": ""},
            {"file_id": "f2", "filename": "n2", "description": "", "custom_metadata": ""}
        ],
        [{"tag_name": "t1"}],  # Tags for f1
        []  # Tags for f2
    ]

    count = reindex_all(mock_db)

    assert count == 2
    # 1 global delete + 2 inserts
    assert mock_db.execute.call_count == 3
    assert "DELETE FROM files_fts" in mock_db.execute.call_args_list[0][0][0]