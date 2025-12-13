"""
Unit tests for the Session Manager.
"""

import time
import pytest
from unittest.mock import MagicMock, patch
from shadowbox.security import session
from shadowbox.security.session import SessionManager


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def session_manager():
    """Returns a fresh, locked SessionManager instance."""
    return SessionManager()


@pytest.fixture
def mock_kdf():
    with patch("shadowbox.security.session.derive_master_key") as mock:
        mock.return_value = b"derived_key_32_bytes_long_xxxxxx"
        yield mock


@pytest.fixture
def mock_salt_gen():
    with patch("shadowbox.security.session.generate_salt") as mock:
        mock.return_value = b"salt_16_bytes_xx"
        yield mock


@pytest.fixture
def mock_keystore():
    with patch("shadowbox.security.session.save_key") as mock_save, \
            patch("shadowbox.security.session.load_key") as mock_load, \
            patch("shadowbox.security.session.delete_key") as mock_delete, \
            patch("shadowbox.security.session.assess_keyring_backend") as mock_assess:
        yield {
            "save": mock_save,
            "load": mock_load,
            "delete": mock_delete,
            "assess": mock_assess
        }


# ==============================================================================
# Tests: Locking & Unlocking
# ==============================================================================

def test_unlock_with_key(session_manager):
    """Cover unlock_with_key (lines 32-33)."""
    key = b"my_master_key"
    session_manager.unlock_with_key(key, ttl_seconds=60)
    assert session_manager.get_master_key() == key


def test_unlock_with_password_defaults(session_manager, mock_kdf, mock_salt_gen):
    """Cover unlock_with_password default path (lines 50-63)."""
    session_manager.unlock_with_password("password")

    mock_salt_gen.assert_called_once()
    mock_kdf.assert_called_once()
    assert session_manager.get_master_key() == b"derived_key_32_bytes_long_xxxxxx"


def test_unlock_with_password_custom_params(session_manager, mock_kdf):
    """Cover unlock_with_password with custom salt/params."""
    salt = b"custom_salt"
    session_manager.unlock_with_password(b"password", salt=salt, time_cost=1)

    mock_kdf.assert_called_with(
        b"password", salt, time_cost=1, memory_cost=65536, parallelism=1
    )
    assert session_manager.get_master_key() == b"derived_key_32_bytes_long_xxxxxx"


def test_lock_clears_data(session_manager):
    """Cover lock logic (lines 83-93)."""
    session_manager.unlock_with_key(b"secret")
    assert session_manager._master_key is not None

    session_manager.lock()

    assert session_manager._master_key is None
    assert session_manager._expires_at is None
    with pytest.raises(RuntimeError, match="Session is locked"):
        session_manager.get_master_key()


# ==============================================================================
# Tests: Expiration & Time
# ==============================================================================

def test_get_master_key_raises_if_locked(session_manager):
    """Cover 'if self._master_key is None' branch."""
    with pytest.raises(RuntimeError, match="Session is locked"):
        session_manager.get_master_key()


def test_auto_lock_on_expiry(session_manager):
    """Cover expiration logic (lines 67-73)."""
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        session_manager.unlock_with_key(b"key", ttl_seconds=300)

        # Move time forward past expiry
        mock_time.return_value = 1301.0

        with pytest.raises(RuntimeError, match="Session expired and was locked"):
            session_manager.get_master_key()

        # Verify it actually locked
        assert session_manager._master_key is None


def test_extend_session(session_manager):
    """Cover extend logic (lines 77-79)."""
    with patch("time.time") as mock_time:
        mock_time.return_value = 1000.0
        session_manager.unlock_with_key(b"key", ttl_seconds=300)
        original_expiry = session_manager._expires_at

        session_manager.extend(60)
        assert session_manager._expires_at == original_expiry + 60.0


def test_extend_raises_if_locked(session_manager):
    """Cover extend error path."""
    with pytest.raises(RuntimeError, match="Session is locked"):
        session_manager.extend(60)


# ==============================================================================
# Tests: Keystore Integration
# ==============================================================================

def test_persist_raises_if_locked(session_manager):
    """Cover persist_to_keyring locked check."""
    with pytest.raises(RuntimeError, match="No master key to persist"):
        session_manager.persist_to_keyring("svc", "usr")


def test_persist_raises_if_backend_insecure(session_manager, mock_keystore):
    """Cover secure backend check failure (lines 100-111)."""
    session_manager.unlock_with_key(b"key")
    mock_keystore["assess"].return_value = (False, "Insecure backend")

    with pytest.raises(RuntimeError, match="refusing to persist"):
        session_manager.persist_to_keyring("svc", "usr")

    mock_keystore["save"].assert_not_called()


def test_persist_saves_if_backend_secure(session_manager, mock_keystore):
    """Cover persist happy path."""
    session_manager.unlock_with_key(b"key")
    mock_keystore["assess"].return_value = (True, "Secure")

    session_manager.persist_to_keyring("svc", "usr")
    mock_keystore["save"].assert_called_with("svc", "usr", b"key")


def test_persist_force(session_manager, mock_keystore):
    """Cover persist_to_keyring_force (lines 118-120)."""
    with pytest.raises(RuntimeError, match="No master key"):
        session_manager.persist_to_keyring_force("svc", "usr")

    session_manager.unlock_with_key(b"key")
    session_manager.persist_to_keyring_force("svc", "usr")
    # Should save without calling assess
    mock_keystore["assess"].assert_not_called()
    mock_keystore["save"].assert_called_with("svc", "usr", b"key")


def test_load_from_keyring_success(session_manager, mock_keystore):
    """Cover load_from_keyring happy path (lines 127-130)."""
    mock_keystore["load"].return_value = b"loaded_key"

    session_manager.load_from_keyring("svc", "usr", ttl_seconds=60)
    assert session_manager.get_master_key() == b"loaded_key"


def test_load_from_keyring_missing(session_manager, mock_keystore):
    """Cover load failure."""
    mock_keystore["load"].return_value = None

    with pytest.raises(RuntimeError, match="No key found"):
        session_manager.load_from_keyring("svc", "usr")


def test_delete_from_keyring(session_manager, mock_keystore):
    """Cover delete_from_keyring."""
    session_manager.delete_from_keyring("svc", "usr")
    mock_keystore["delete"].assert_called_with("svc", "usr")


# ==============================================================================
# Tests: Global Module Helpers
# ==============================================================================

def test_global_helpers(mock_kdf, mock_salt_gen):
    """Cover module-level functions (lines 134-158)."""
    # Reset global session for test
    session._default_session = SessionManager()

    # unlock_with_key
    session.unlock_with_key(b"global_key")
    assert session.get_master_key() == b"global_key"

    # lock
    session.lock()
    with pytest.raises(RuntimeError):
        session.get_master_key()

    # unlock_with_password
    session.unlock_with_password("pass")
    assert session.get_master_key() == b"derived_key_32_bytes_long_xxxxxx"