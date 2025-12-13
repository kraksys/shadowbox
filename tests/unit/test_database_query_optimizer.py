"""Unit tests for the query optimizer module."""

import pytest
from unittest.mock import Mock, call, patch
from shadowbox.database.query_optimizer import apply_pragmas, analyze, like_fix, search

@pytest.fixture
def mock_db():
    return Mock()

def test_apply_pragmas(mock_db):
    """Test that performance pragmas are applied."""
    apply_pragmas(mock_db)
    calls = [str(c) for c in mock_db.execute.call_args_list]
    # Check for essential optimizations
    assert any("journal_mode=WAL" in c for c in calls)
    assert any("synchronous=NORMAL" in c for c in calls)
    assert any("foreign_keys=ON" in c for c in calls)

def test_analyze(mock_db):
    """Test analyze command execution."""
    analyze(mock_db)
    mock_db.execute.assert_has_calls([
        call("ANALYZE"),
        call("PRAGMA optimize")
    ])

def test_like_fix():
    """Test escaping of SQL LIKE wildcards."""
    assert like_fix("foo%bar") == "foo\\%bar"
    assert like_fix("foo_bar") == "foo\\_bar"
    assert like_fix("normal") == "normal"

def test_search_empty(mock_db):
    """Test search returns empty list on empty query."""
    assert search(mock_db, "") == []
    assert search(mock_db, "   ") == []

# FIX: Patch the target module where row_to_metadata is defined, not where it is used locally.
@patch("shadowbox.database.models.row_to_metadata")
def test_search_execution(mock_r2m, mock_db):
    """Test search executes correct SQL with parameters."""
    mock_db.fetch_all.return_value = [{"id": 1}]
    mock_r2m.return_value = "meta_obj"
    
    results = search(mock_db, "test", user_id="u1", limit=10, offset=5)
    
    assert results == ["meta_obj"]
    
    args = mock_db.fetch_all.call_args
    sql = args[0][0]
    params = args[0][1]
    
    assert "LIKE ? ESCAPE" in sql
    assert "user_id = ?" in sql
    assert "ORDER BY created_at DESC" in sql
    
    # Verify wildcards are added
    assert "%test%" in params
    assert "u1" in params
    assert 10 in params
    assert 5 in params