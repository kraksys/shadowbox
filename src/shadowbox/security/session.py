"""In-memory session manager for holding unlocked master keys with auto-lock.

This is a lightweight prototype session manager. It stores a single in-memory
master key and an expiry timestamp. Calling get_master_key() will return the
key if the session is unlocked and not expired; otherwise it raises a
RuntimeError. Use unlock_with_key() or unlock_with_password() to populate
the session. Call lock() to explicitly clear the key.
"""
from __future__ import annotations

import time
from typing import Optional

from .kdf import derive_master_key, generate_salt
# import assess_keyring_backend at the top of the file
from .keystore import save_key, load_key, delete_key, assess_keyring_backend


class SessionManager:
    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._expires_at: Optional[float] = None
        self._kdf_salt: Optional[bytes] = None
        self._kdf_params = None

    def unlock_with_key(self, master_key: bytes, ttl_seconds: int = 300) -> None:
        """Unlock the session with an already-derived master key.

        Args:
            master_key: raw master key bytes (32 bytes recommended)
            ttl_seconds: time-to-live in seconds for the unlocked session
        """
        self._master_key = master_key
        self._expires_at = time.time() + float(ttl_seconds)

    def unlock_with_password(
        self,
        password: bytes | str,
        salt: Optional[bytes] = None,
        time_cost: int = 3,
        memory_cost: int = 65536,
        parallelism: int = 1,
        ttl_seconds: int = 300,
    ) -> None:
        """Derive a master key from a password and unlock the session.

        If no salt is provided, a random salt is generated but not persisted by
        this manager — caller is responsible for storing salt for future
        derivations.
        """
        if isinstance(password, str):
            password = password.encode("utf-8")
        if salt is None:
            salt = generate_salt()
        key = derive_master_key(
            password,
            salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )
        self._kdf_salt = salt
        self._kdf_params = {"time": time_cost, "memory": memory_cost, "parallelism": parallelism}
        self.unlock_with_key(key, ttl_seconds=ttl_seconds)

    def get_master_key(self) -> bytes:
        """Return the unlocked master key or raise if locked/expired."""
        if self._master_key is None:
            raise RuntimeError("Session is locked")
        if self._expires_at is not None and time.time() > self._expires_at:
            # auto-lock on expiry
            self.lock()
            raise RuntimeError("Session expired and was locked")
        return self._master_key

    def extend(self, extra_seconds: int) -> None:
        """Extend session TTL by extra_seconds if unlocked."""
        if self._master_key is None:
            raise RuntimeError("Session is locked")
        self._expires_at = (self._expires_at or time.time()) + float(extra_seconds)

    def lock(self) -> None:
        """Clear the master key from memory (best-effort) and lock the session."""
        try:
            if self._master_key is not None:
                # best-effort attempt to overwrite
                overwrite = bytearray(len(self._master_key))
                for i in range(len(overwrite)):
                    overwrite[i] = 0
        finally:
            self._master_key = None
            self._expires_at = None
            self._kdf_salt = None
            self._kdf_params = None

    def persist_to_keyring(self, service: str, account: str) -> None:
        """
        Persist the current in-memory master key to the OS keystore under (service, account).
        Raises RuntimeError if no key is unlocked.
        """
        if self._master_key is None:
            raise RuntimeError("No master key to persist")
        # Check keyring backend security heuristics before persisting. avoids storing keys in plaintext

        secure, msg = assess_keyring_backend()
        if not secure:
            raise RuntimeError(
                f"refusing to persist master key to OS keystore: {msg}; "
                "pass force=True to override if you understand the risk"
            )
        save_key(service, account, self._master_key)

    def persist_to_keyring_force(self, service: str, account: str) -> None:
        """Persist the current in-memory master key to the OS keystore without backend checks.

        Use with caution; this will write to whatever keyring backend is available.
        """
        if self._master_key is None:
            raise RuntimeError("No master key to persist")
        save_key(service, account, self._master_key)

    def load_from_keyring(self, service: str, account: str, ttl_seconds: int = 300) -> None:
        """Load a master key from the OS keystore into the session and unlock it.

        Raises RuntimeError if no key is found.
        """
        key = load_key(service, account)
        if key is None:
            raise RuntimeError("No key found in OS keystore for given service/account")
        self.unlock_with_key(key, ttl_seconds=ttl_seconds)

    def delete_from_keyring(self, service: str, account: str) -> None:
        """Remove the persisted master key from the OS keystore."""
        delete_key(service, account)


# module-level default session manager
_default_session = SessionManager()


def get_session() -> SessionManager:
    return _default_session


def unlock_with_key(master_key: bytes, ttl_seconds: int = 300) -> None:
    get_session().unlock_with_key(master_key, ttl_seconds=ttl_seconds)


def unlock_with_password(*args, **kwargs) -> None:
    get_session().unlock_with_password(*args, **kwargs)


def get_master_key() -> bytes:
    return get_session().get_master_key()


def lock() -> None:
    get_session().lock()
