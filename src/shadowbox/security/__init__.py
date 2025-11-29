"""Security helpers: KDF and streaming encryption primitives for Shadowbox.

This package provides a minimal, reviewable prototype for:
- Argon2id-based master key derivation
- Per-file CEK generation and wrapping
- Streaming AEAD (AES-GCM) encryption/decryption with chunking

This is intentionally small and suitable for unit testing and iteration.
"""

from .kdf import generate_salt, derive_master_key
from .crypto import (
    generate_cek,
    wrap_cek,
    unwrap_cek,
    encrypt_file_stream,
    decrypt_file_stream,
)
from .session import get_session, unlock_with_key, unlock_with_password, get_master_key, lock

__all__ = [
    "generate_salt",
    "derive_master_key",
    "generate_cek",
    "wrap_cek",
    "unwrap_cek",
    "encrypt_file_stream",
    "decrypt_file_stream",
    "get_session",
    "unlock_with_key",
    "unlock_with_password",
    "get_master_key",
    "lock",
    "save_key",
    "load_key",
    "delete_key",
]
"""Security package of ShadowBox."""
