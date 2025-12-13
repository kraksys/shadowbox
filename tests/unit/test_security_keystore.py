"""
Unit tests for the keystore module.
"""

import base64
import pytest
from unittest.mock import MagicMock, patch
from shadowbox.security import keystore


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def mock_keyring_lib():
    """Patches the keyring module within shadowbox.security.keystore."""
    with patch("shadowbox.security.keystore.keyring", autospec=True) as mock_lib:
        yield mock_lib


@pytest.fixture
def no_keyring_lib():
    """Simulates keyring not being installed."""
    with patch("shadowbox.security.keystore.keyring", None):
        yield


# ==============================================================================
# Tests: Dependency Availability (_require_keyring)
# ==============================================================================

def test_require_keyring_raises_if_missing(no_keyring_lib):
    """
    Cover lines 13-14: _require_keyring logic when keyring is None.
    Should raise RuntimeError.
    """
    with pytest.raises(RuntimeError, match="keyring package is not available"):
        keystore.save_key("service", "user", b"key")

    with pytest.raises(RuntimeError, match="keyring package is not available"):
        keystore.load_key("service", "user")

    with pytest.raises(RuntimeError, match="keyring package is not available"):
        keystore.delete_key("service", "user")


def test_assess_backend_returns_false_if_missing(no_keyring_lib):
    """
    Cover 'if keyring is None' branch in assess_keyring_backend.
    """
    is_secure, msg = keystore.assess_keyring_backend()
    assert is_secure is False
    assert "not installed" in msg


# ==============================================================================
# Tests: Save Key (save_key)
# ==============================================================================

def test_save_key_encodes_and_stores(mock_keyring_lib):
    """
    Cover lines 18-29: save_key happy path.
    Verifies bytes are base64 encoded before storage.
    """
    service = "shadowbox_test"
    account = "alice"
    key_bytes = b"\x01\x02\x03\x04"

    keystore.save_key(service, account, key_bytes)

    # Check what was passed to set_password
    args = mock_keyring_lib.set_password.call_args
    assert args is not None
    called_service, called_account, called_secret = args[0]

    assert called_service == service
    assert called_account == account
    # Secret must be base64 string, not bytes
    assert called_secret == base64.b64encode(key_bytes).decode("ascii")


# ==============================================================================
# Tests: Load Key (load_key)
# ==============================================================================

def test_load_key_returns_bytes(mock_keyring_lib):
    """
    Cover lines 65-72: load_key happy path.
    Verifies base64 decoding.
    """
    original_key = b"secret_bytes"
    b64_secret = base64.b64encode(original_key).decode("ascii")

    mock_keyring_lib.get_password.return_value = b64_secret

    result = keystore.load_key("svc", "usr")
    assert result == original_key


def test_load_key_returns_none_if_missing(mock_keyring_lib):
    """
    Cover 'if secret is None' branch in load_key.
    """
    mock_keyring_lib.get_password.return_value = None

    result = keystore.load_key("svc", "usr")
    assert result is None


def test_load_key_returns_none_on_corrupt_data(mock_keyring_lib):
    """
    Cover exception handler in load_key (invalid base64).
    """
    mock_keyring_lib.get_password.return_value = "NotValidBase64!!!"

    result = keystore.load_key("svc", "usr")
    assert result is None


# ==============================================================================
# Tests: Delete Key (delete_key)
# ==============================================================================

def test_delete_key_calls_backend(mock_keyring_lib):
    """
    Cover lines 77-82: delete_key happy path.
    """
    keystore.delete_key("svc", "usr")
    mock_keyring_lib.delete_password.assert_called_once_with("svc", "usr")


def test_delete_key_swallows_exceptions(mock_keyring_lib):
    """
    Cover exception handler in delete_key.
    Backend might raise if item doesn't exist; we should suppress it.
    """
    mock_keyring_lib.delete_password.side_effect = Exception("Not found")

    # Should not raise
    keystore.delete_key("svc", "usr")


# ==============================================================================
# Tests: Backend Assessment (assess_keyring_backend)
# ==============================================================================

def test_assess_backend_handles_exception(mock_keyring_lib):
    """Cover exception block when getting keyring."""
    mock_keyring_lib.get_keyring.side_effect = Exception("DBus error")

    is_secure, msg = keystore.assess_keyring_backend()
    assert is_secure is False
    assert "failed to get keyring backend" in msg


def test_assess_backend_insecure_names(mock_keyring_lib):
    """Cover logic checking for 'Plaintext', 'File', etc."""
    # Mock a class structure for the backend
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "SimplePlaintextKeyring"
    mock_keyring_lib.get_keyring.return_value = mock_backend

    is_secure, msg = keystore.assess_keyring_backend()
    assert is_secure is False
    assert "insecure backend detected" in msg


def test_assess_backend_low_priority(mock_keyring_lib):
    """Cover priority check."""
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "SomeGenericBackend"
    mock_backend.priority = 0
    mock_keyring_lib.get_keyring.return_value = mock_backend

    is_secure, msg = keystore.assess_keyring_backend()
    assert is_secure is False
    assert "no suitable secure keyring backend" in msg


def test_assess_backend_secure_names(mock_keyring_lib):
    """Cover whitelist of secure backend names."""
    secure_names = ["KeychainKeyring", "WindowsWinVaultKeyring", "SecretServiceKeyring", "KWallet"]

    for name in secure_names:
        mock_backend = MagicMock()
        mock_backend.__class__.__name__ = name
        mock_backend.priority = 1
        mock_keyring_lib.get_keyring.return_value = mock_backend

        is_secure, msg = keystore.assess_keyring_backend()
        assert is_secure is True
        assert "looks acceptable" in msg


def test_assess_backend_unknown_but_high_priority(mock_keyring_lib):
    """Cover fallthrough for unknown but valid-looking backends."""
    mock_backend = MagicMock()
    mock_backend.__class__.__name__ = "SuperSecureHardwareKeyring"
    mock_backend.priority = 5
    mock_keyring_lib.get_keyring.return_value = mock_backend

    is_secure, msg = keystore.assess_keyring_backend()
    assert is_secure is True
    assert "unknown backend" in msg
    assert "treat with caution" in msg