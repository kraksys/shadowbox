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


class BoxEncryptionBackend:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        # Placeholder to track initialization state
        self.initialized: bool = False

    def setup_master_key(self, password: str) -> None:
        """Example Implementation: Initialize or load master key(s). Any setup / storage protections of the keys is set up here."""
        pass

    def get_box_key(self, box_id: str) -> bytes:
        """Example Implementation: Return a box-specific key suitable for content encryption. Generates box keys, derives them and ensures persistence"""
        pass

    def encrypt_bytes(self, data: bytes, box_id: str) -> bytes:
        """Example Implementation : Encrypt raw bytes for the given box and return ciphertext bytes"""
        pass

    def decrypt_bytes(self, blob: bytes, box_id: str) -> bytes:
        """Example Implementation: Decrypt ciphertext bytes for the given box and return plaintext bytes"""
        pass

    def encrypt_json(self, obj: Dict[str, Any], box_id: str) -> bytes:
        """Example Implementation: Metadata encryption, where a JSON dict is encrypted and returns ciphertext bytes"""
        pass

    def decrypt_json(self, blob: bytes, box_id: str) -> Dict[str, Any]:
        """Example Implementation: Decrypt bytes and return a Python dict"""
        pass
