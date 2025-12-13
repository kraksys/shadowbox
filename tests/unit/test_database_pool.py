"""Unit tests for the database connection pool."""

import pytest
from unittest.mock import Mock, patch
from shadowbox.database.pool import ConnectionPool

@pytest.fixture
def mock_db_cls():
    with patch("shadowbox.database.pool.DatabaseConnection") as mock:
        # FIX: Return a NEW Mock instance every time the class is called.
        # This allows tracking calls on individual connection instances correctly.
        mock.side_effect = lambda *args: Mock()
        yield mock

def test_pool_initialization(mock_db_cls):
    """Test pool initializes with correct size and distinct connections."""
    pool = ConnectionPool(size=3)
    assert pool.queue.maxsize == 3
    assert len(pool.all) == 3
    assert mock_db_cls.call_count == 3
    
    # Check each db was initialized exactly once
    for db in pool.all:
        db.initialize.assert_called_once()

def test_acquire_release(mock_db_cls):
    """Test acquiring and releasing connections."""
    pool = ConnectionPool(size=1)
    
    # Acquire
    db = pool.acquire()
    assert db is not None
    assert pool.queue.empty()
    
    # Release
    pool.release(db)
    assert not pool.queue.empty()
    assert pool.queue.get() == db

def test_pool_close(mock_db_cls):
    """Test pool closing closes all connections."""
    pool = ConnectionPool(size=2)
    pool.close()
    
    # Queue should be emptied
    assert pool.queue.empty()
    # All connections closed
    for db in pool.all:
        db.close.assert_called_once()
    assert pool.all == []