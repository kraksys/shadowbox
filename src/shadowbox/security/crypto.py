"""Minimal streaming AEAD file encryption prototype with compact binary header.

Header layout (binary, all big-endian):
- 4 bytes: magic b'SBX1'
- 1 byte: version (1)
- 1 byte: alg_id (1 = AESGCM)
- 2 bytes: len_wrapped (unsigned short)
- N bytes: wrapped CEK
- 1 byte: len_nonce_seed (L)
- L bytes: nonce_seed

Body: sequence of records: 4-byte big-endian ciphertext length + ciphertext bytes

This is still a prototype but avoids JSON header parsing pitfalls and is easier to reason
about when seeking and corrupting bytes in tests.
"""
import os
import struct
import hashlib
from typing import BinaryIO
from pathlib import Path
import tempfile
import shutil
from shadowbox.core.hashing import calculate_sha256
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap
import hmac


MAGIC = b"SBX1"
# version 2: adds a 32-byte HMAC-SHA256 over the header
VERSION = 2
ALG_ID_AESGCM = 1


def generate_cek() -> bytes:
    return os.urandom(32)


def _derive_kek(master_key: bytes, info: bytes = b"shadowbox-kek") -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(master_key)


def _derive_header_mac_key(master_key: bytes, info: bytes = b"shadowbox-header-mac") -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=info)
    return hkdf.derive(master_key)


def wrap_cek(master_key: bytes, cek: bytes) -> bytes:
    kek = _derive_kek(master_key)
    return aes_key_wrap(kek, cek)


def unwrap_cek(master_key: bytes, wrapped: bytes) -> bytes:
    kek = _derive_kek(master_key)
    return aes_key_unwrap(kek, wrapped)


def _make_nonce(seed: bytes, chunk_index: int) -> bytes:
    # Produce a 12-byte nonce by hashing seed||chunk_index and taking first 12 bytes.
    h = hashlib.sha256()
    h.update(seed)
    h.update(chunk_index.to_bytes(8, "big"))
    return h.digest()[:12]


def encrypt_file_stream(in_path: str, out_path: str, master_key: bytes, chunk_size: int = 64 * 1024) -> None:
    cek = generate_cek()
    wrapped = wrap_cek(master_key, cek)
    nonce_seed = os.urandom(16)

    with open(in_path, "rb") as inf, open(out_path, "wb") as outf:
        # build binary header then append header MAC (HMAC-SHA256)
        header = bytearray()
        header += MAGIC
        header += struct.pack("B", VERSION)
        header += struct.pack("B", ALG_ID_AESGCM)
        header += struct.pack(">H", len(wrapped))
        header += wrapped
        header += struct.pack("B", len(nonce_seed))
        header += nonce_seed

        mac_key = _derive_header_mac_key(master_key)
        header_mac = hmac.new(mac_key, bytes(header), hashlib.sha256).digest()

        outf.write(bytes(header))
        outf.write(header_mac)

        aead = AESGCM(cek)
        chunk_index = 0
        while True:
            chunk = inf.read(chunk_size)
            if not chunk:
                break
            nonce = _make_nonce(nonce_seed, chunk_index)
            ad = f"chunk:{chunk_index}".encode("utf-8")
            ct = aead.encrypt(nonce, chunk, ad)
            outf.write(struct.pack(">I", len(ct)))
            outf.write(ct)
            chunk_index += 1


def decrypt_file_stream(in_path: str, out_path: str, master_key: bytes) -> None:
    with open(in_path, "rb") as inf, open(out_path, "wb") as outf:
        magic = inf.read(4)
        if magic != MAGIC:
            raise ValueError("Invalid file format (magic mismatch)")
        ver = ord(inf.read(1))
        if ver != VERSION:
            raise ValueError("Unsupported version")
        alg = ord(inf.read(1))
        if alg != ALG_ID_AESGCM:
            raise ValueError("Unsupported algorithm")
        (wrapped_len,) = struct.unpack(">H", inf.read(2))
        wrapped = inf.read(wrapped_len)
        (nonce_len,) = struct.unpack("B", inf.read(1))
        nonce_seed = inf.read(nonce_len)

        # If version 2, expect a 32-byte HMAC-SHA256 following the header and verify it
        if ver == VERSION:
            header = bytearray()
            header += MAGIC
            header += struct.pack("B", ver)
            header += struct.pack("B", alg)
            header += struct.pack(">H", wrapped_len)
            header += wrapped
            header += struct.pack("B", nonce_len)
            header += nonce_seed

            mac = inf.read(32)
            if len(mac) != 32:
                raise IOError("truncated header MAC")
            mac_key = _derive_header_mac_key(master_key)
            expected = hmac.new(mac_key, bytes(header), hashlib.sha256).digest()
            if not hmac.compare_digest(mac, expected):
                raise ValueError("header authentication failed (HMAC mismatch)")

        cek = unwrap_cek(master_key, wrapped)
        aead = AESGCM(cek)

        chunk_index = 0
        while True:
            len_bytes = inf.read(4)
            if not len_bytes or len(len_bytes) < 4:
                break
            (ct_len,) = struct.unpack(">I", len_bytes)
            ct = inf.read(ct_len)
            if len(ct) != ct_len:
                raise IOError("truncated ciphertext")
            nonce = _make_nonce(nonce_seed, chunk_index)
            ad = f"chunk:{chunk_index}".encode("utf-8")
            pt = aead.decrypt(nonce, ct, ad)
            outf.write(pt)
            chunk_index += 1

    def put_encrypted(self, user_id, source_path, master_key: bytes, chunk_size: int = 64 * 1024):
        """Encrypts source_path to a temporary file, stores the encrypted blob by its hash, and returns metadata.

        The returned hash is the SHA256 of the encrypted blob on disk.
        """
        self.ensure_user(user_id)
        src = Path(source_path).expanduser()

        # create temp file for encrypted output
        with tempfile.NamedTemporaryFile(delete=False) as tmpf:
            tmp_path = Path(tmpf.name)

        try:
            encrypt_file_stream(str(src), str(tmp_path), master_key, chunk_size=chunk_size)
            hash_hex = calculate_sha256(tmp_path)
            destination = self.blob_path(user_id, hash_hex)
            if not destination.exists():
                shutil.copy2(tmp_path, destination)
            size = tmp_path.stat().st_size
            return {"hash": hash_hex, "size": size, "path": str(destination)}
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
