"""Unit tests for the database search module."""

import pytest
from unittest.mock import Mock, patch
from shadowbox.database.search import tags_map, rows_to_metadata, search_fts, fuzzy_search_fts, search_by_tag


@pytest.fixture
def mock_db():
    return Mock()


def test_tags_map_empty(mock_db):
    """Test tags_map returns empty dict for empty file_ids list."""
    assert tags_map(mock_db, []) == {}


def test_tags_map_items(mock_db):
    """Test tags_map correctly groups tags by file_id."""
    mock_db.fetch_all.return_value = [
        {"entity_id": "f1", "tag_name": "t1"},
        {"entity_id": "f1", "tag_name": "t2"},
        {"entity_id": "f2", "tag_name": "t3"},
    ]
    res = tags_map(mock_db, ["f1", "f2"])
    assert res["f1"] == ["t1", "t2"]
    assert res["f2"] == ["t3"]
    # Verify SQL query structure
    sql = mock_db.fetch_all.call_args[0][0]
    assert "WHERE entity_type = 'file'" in sql
    assert "entity_id IN (?,?)" in sql


def test_search_fts_empty(mock_db):
    """Test search_fts returns empty list for empty query."""
    assert search_fts(mock_db, "   ") == []
    assert search_fts(mock_db, None) == []


@patch("shadowbox.database.search.rows_to_metadata")
def test_search_fts_valid(mock_r2m, mock_db):
    """Test search_fts executes correct SQL and returns metadata."""
    mock_db.fetch_all.return_value = [{"file_id": "f1"}]
    mock_r2m.return_value = ["meta1"]

    res = search_fts(mock_db, "query", user_id="u1", limit=10, offset=5)

    assert res == ["meta1"]
    mock_db.fetch_all.assert_called_once()
    sql = mock_db.fetch_all.call_args[0][0]
    params = mock_db.fetch_all.call_args[0][1]

    assert "MATCH ?" in sql
    assert "user_id = ?" in sql
    assert "LIMIT ? OFFSET ?" in sql
    assert params == ("query", "u1", 10, 5)


@patch("shadowbox.database.search.search_fts")
def test_fuzzy_search_fts(mock_search, mock_db):
    """Test fuzzy_search_fts expands terms with wildcards."""
    fuzzy_search_fts(mock_db, "foo bar", user_id="u1")
    mock_search.assert_called_with(mock_db, "foo* bar*", user_id="u1", limit=25, offset=0)


def test_fuzzy_search_fts_empty(mock_db):
    """Test fuzzy_search_fts returns empty list for empty input."""
    assert fuzzy_search_fts(mock_db, "") == []


def test_search_by_tag_empty(mock_db):
    """Test search_by_tag returns empty list for empty tag."""
    assert search_by_tag(mock_db, "") == []


@patch("shadowbox.database.search.rows_to_metadata")
def test_search_by_tag_valid(mock_r2m, mock_db):
    """Test search_by_tag executes correct SQL filters."""
    mock_db.fetch_all.return_value = []
    mock_r2m.return_value = []

    search_by_tag(mock_db, "tag1", user_id="u1", box_id="b1")

    args = mock_db.fetch_all.call_args
    sql = args[0][0]
    params = args[0][1]

    assert "tag_name = ?" in sql
    assert "user_id = ?" in sql
    assert "box_id = ?" in sql
    assert params[0] == "tag1"
    assert "u1" in params
    assert "b1" in params