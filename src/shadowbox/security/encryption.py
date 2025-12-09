"""
Placeholder encryption backend for ShadowBox storage.

Initially leaving this empty so that anyone working on security can implement this.
Some of those methods are called in core/file_manager.py so if you change the names make sure to also change them there.
FYI: the method names and this class is just an example of how encryption can work. It can be completely different and adopt a much simpler / stricter method.

One key idea to retain:
- Keys should be stored per box ( to retain isolation ) and adhere to the map shown in Structure Map
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

import json
import os
import hmac
import hashlib

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .kdf import generate_salt, derive_master_key
from .crypto import generate_cek, wrap_cek, unwrap_cek


class BoxEncryptionBackend:
    """
    Per-box encryption backend for ShadowBox storage.

    This class is intentionally low-level and focused only on:

    - deriving and persisting a *master key* from a user password
    - issuing a separate content-encryption key (CEK) per box
    - encrypting/decrypting raw bytes
    - encrypting/decrypting JSON metadata blobs

    It deliberately knows nothing about the database or `FileManager`.
    `Storage` is the integration point that wires this backend into the
    rest of the system.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.initialized: bool = False
        self._master_key: Optional[bytes] = None

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @property
    def _keys_root(self) -> Path:
        return self.root / "keys"

    @property
    def _master_meta_path(self) -> Path:
        # Stores KDF parameters and a MAC sentinel, not the raw key.
        return self._keys_root / "master.json"

    @property
    def _box_keys_root(self) -> Path:
        # Directory containing one wrapped CEK per box_id.
        return self._keys_root / "box_keys"

    # ------------------------------------------------------------------
    # Master key lifecycle
    # ------------------------------------------------------------------

    def setup_master_key(self, password: str) -> None:
        """
        Initialize or load the master key derived from ``password``.

        First-time initialization:
        - generate a random salt
        - derive a master key using Argon2id (:mod:`shadowbox.security.kdf`)
        - compute a MAC over a fixed label using the master key
        - persist salt, KDF parameters and MAC sentinel in ``keys/master.json``

        Subsequent calls:
        - reload salt and parameters
        - re-derive master key from the provided password
        - verify the MAC sentinel; raise ``ValueError`` if it does not match
        """
        self._keys_root.mkdir(parents=True, exist_ok=True)

        if self._master_meta_path.exists():
            with open(self._master_meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            salt = bytes.fromhex(meta["salt"])
            time_cost = int(meta.get("time", 3))
            memory_cost = int(meta.get("memory", 65536))
            parallelism = int(meta.get("parallelism", 1))

            # Derive master key from the supplied password and stored salt/params.
            master_key = derive_master_key(
                password=password.encode("utf-8"),
                salt=salt,
                time_cost=time_cost,
                memory_cost=memory_cost,
                parallelism=parallelism,
            )

            sentinel_hex = meta.get("sentinel")
            if sentinel_hex:
                expected = bytes.fromhex(sentinel_hex)
                mac = hmac.new(
                    master_key, b"shadowbox-master-key", hashlib.sha256
                ).digest()
                if not hmac.compare_digest(mac, expected):
                    # The password does not match the stored key material.
                    raise ValueError("Invalid master password for existing key material")

            self._master_key = master_key
            self.initialized = True
            return

        # No metadata yet: this is the first time a password is configured.
        salt = generate_salt()
        time_cost = 3
        memory_cost = 65536
        parallelism = 1

        master_key = derive_master_key(
            password=password.encode("utf-8"),
            salt=salt,
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
        )

        mac = hmac.new(master_key, b"shadowbox-master-key", hashlib.sha256).digest()

        meta = {
            "salt": salt.hex(),
            "time": time_cost,
            "memory": memory_cost,
            "parallelism": parallelism,
            "sentinel": mac.hex(),
        }

        self._keys_root.mkdir(parents=True, exist_ok=True)
        with open(self._master_meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f)

        self._master_key = master_key
        self.initialized = True

    def _require_master_key(self) -> bytes:
        """Return the unlocked master key or raise if not initialized."""
        if not self.initialized or self._master_key is None:
            raise RuntimeError("Master key not initialized; call setup_master_key() first")
        return self._master_key

    # ------------------------------------------------------------------
    # Box keys
    # ------------------------------------------------------------------

    def get_box_key(self, box_id: str) -> bytes:
        """
        Return a box-specific content-encryption key (CEK).

        Each box gets its own random CEK which is wrapped with the master
        key using AES key wrap (:func:`wrap_cek`) and stored under
        ``keys/box_keys/{box_id}.key``.
        """
        master_key = self._require_master_key()
        self._box_keys_root.mkdir(parents=True, exist_ok=True)
        path = self._box_keys_root / f"{box_id}.key"

        if path.exists():
            wrapped = path.read_bytes()
            return unwrap_cek(master_key, wrapped)

        # First-time CEK for this box.
        cek = generate_cek()
        wrapped = wrap_cek(master_key, cek)
        path.write_bytes(wrapped)
        return cek

    # ------------------------------------------------------------------
    # Byte-level encryption
    # ------------------------------------------------------------------

    def encrypt_bytes(self, data: bytes, box_id: str) -> bytes:
        """
        Encrypt raw bytes for the given box and return ciphertext bytes.

        Encryption details:
        - AES-256-GCM (via :class:`cryptography.hazmat.primitives.ciphers.aead.AESGCM`)
        - CEK from :meth:`get_box_key`
        - fresh 96-bit random nonce per call

        The returned blob is ``nonce || ciphertext``, which is treated as an
        opaque payload by the rest of the system.
        """
        key = self.get_box_key(box_id)
        aead = AESGCM(key)
        nonce = os.urandom(12)
        ct = aead.encrypt(nonce, data, None)
        return nonce + ct

    def decrypt_bytes(self, blob: bytes, box_id: str) -> bytes:
        """
        Decrypt ciphertext bytes for the given box and return plaintext.

        The input must be in the ``nonce || ciphertext`` format produced by
        :meth:`encrypt_bytes`.
        """
        if len(blob) < 12:
            raise ValueError("Ciphertext too short to contain nonce")

        key = self.get_box_key(box_id)
        nonce, ct = blob[:12], blob[12:]
        aead = AESGCM(key)
        return aead.decrypt(nonce, ct, None)

    # ------------------------------------------------------------------
    # JSON helpers
    # ------------------------------------------------------------------

    def encrypt_json(self, obj: Dict[str, Any], box_id: str) -> bytes:
        """
        Encrypt a JSON-serializable dict for the given box.

        The object is serialized with :func:`json.dumps` using UTF-8 encoding
        and then passed through :meth:`encrypt_bytes`.
        """
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return self.encrypt_bytes(raw, box_id)

    def decrypt_json(self, blob: bytes, box_id: str) -> Dict[str, Any]:
        """
        Decrypt a JSON blob previously produced by :meth:`encrypt_json`.
        """
        raw = self.decrypt_bytes(blob, box_id)
        return json.loads(raw.decode("utf-8"))
