"""OS keystore integration using keyring for optional, convenient master-key storage.

This module provides a tiny wrapper around `keyring` to store and retrieve
binary keys (base64-encoded) under a service/account pair. Use this only for
opt-in convenience storage; do not assume keyring provides hardware-backed
security on all platforms.
"""
import base64
from typing import Optional

try:
    import keyring
except Exception:
    keyring = None


def _require_keyring():
    if keyring is None:
        raise RuntimeError("keyring package is not available; install keyring to use keystore features")


def save_key(service: str, account: str, key_bytes: bytes) -> None:
    """Persist binary key_bytes in the OS keystore under (service, account).

    The key is base64-encoded before storage to keep it string-friendly.
    """
    _require_keyring()
    secret = base64.b64encode(key_bytes).decode("ascii")
    keyring.set_password(service, account, secret)


def assess_keyring_backend() -> tuple[bool, str]:
    """Return (is_secure, message) describing the current keyring backend.

    Heuristics are used because the `keyring` package exposes different backends
    across platforms. If `keyring` is not available this returns (False, reason).
    """
    if keyring is None:
        return False, "keyring package is not installed"

    try:
        backend = keyring.get_keyring()
    except Exception as e:
        return False, f"failed to get keyring backend: {e}"

    name = backend.__class__.__name__
    priority = getattr(backend, "priority", None)

    insecure_indicators = ("Plaintext", "Uncrypted", "Simple", "File")
    if any(tok in name for tok in insecure_indicators):
        return False, f"insecure backend detected: {name}"

    if priority is not None and priority <= 0:
        return False, f"no suitable secure keyring backend available (priority={priority}, backend={name})"

    # treat known platform backends as acceptable
    if "Win" in name or "Keychain" in name or "SecretService" in name or "KWallet" in name:
        return True, f"backend looks acceptable: {name} (priority={priority})"

    return True, f"unknown backend '{name}', treat with caution (priority={priority})"


def load_key(service: str, account: str) -> Optional[bytes]:
    """Load a persisted key from the OS keystore; returns raw bytes or None."""
    _require_keyring()
    secret = keyring.get_password(service, account)
    if secret is None:
        return None
    try:
        return base64.b64decode(secret)
    except Exception:
        return None


def delete_key(service: str, account: str) -> None:
    """Remove the key from the OS keystore."""
    _require_keyring()
    try:
        keyring.delete_password(service, account)
    except Exception:
        # ignore backend-specific errors
        pass
