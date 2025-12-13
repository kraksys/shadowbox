"""
Supplemental unit tests for shadowbox.security.crypto.
Targeting coverage for error paths.
"""

import struct
import pytest
from shadowbox.security.crypto import (
    encrypt_file_stream,
    decrypt_file_stream,
    MAGIC,
    VERSION,
    ALG_ID_AESGCM,
)
from shadowbox.security.kdf import generate_salt, derive_master_key

# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def master_key():
    """Generate a valid master key for testing."""
    salt = generate_salt()
    return derive_master_key(b"test_password", salt)

@pytest.fixture
def valid_encrypted_file(tmp_path, master_key):
    """Creates a valid encrypted file for tampering tests."""
    in_path = tmp_path / "plaintext.txt"
    in_path.write_bytes(b"Secret Content")
    out_path = tmp_path / "encrypted.sbx"
    encrypt_file_stream(str(in_path), str(out_path), master_key)
    return out_path

# ==============================================================================
# Tests: Decryption Error Paths
# ==============================================================================

def test_decrypt_invalid_magic(tmp_path, master_key):
    """Cover raise ValueError("Invalid file format (magic mismatch)")"""
    bad_file = tmp_path / "bad_magic.sbx"
    # Write wrong magic (BADX instead of SBX1)
    with open(bad_file, "wb") as f:
        f.write(b"BADX")
        f.write(b"\x00" * 10) # Padding
    
    with pytest.raises(ValueError, match="Invalid file format"):
        decrypt_file_stream(str(bad_file), str(tmp_path / "out.txt"), master_key)

def test_decrypt_unsupported_version(tmp_path, master_key):
    """Cover raise ValueError("Unsupported version")"""
    bad_file = tmp_path / "bad_ver.sbx"
    with open(bad_file, "wb") as f:
        f.write(MAGIC)
        # Write Version 99 (invalid)
        f.write(struct.pack("B", 99))
        f.write(struct.pack("B", ALG_ID_AESGCM))
    
    with pytest.raises(ValueError, match="Unsupported version"):
        decrypt_file_stream(str(bad_file), str(tmp_path / "out.txt"), master_key)

def test_decrypt_unsupported_algorithm(tmp_path, master_key):
    """Cover raise ValueError("Unsupported algorithm")"""
    bad_file = tmp_path / "bad_alg.sbx"
    with open(bad_file, "wb") as f:
        f.write(MAGIC)
        f.write(struct.pack("B", VERSION))
        # Write Algorithm 99 (invalid)
        f.write(struct.pack("B", 99))
    
    with pytest.raises(ValueError, match="Unsupported algorithm"):
        decrypt_file_stream(str(bad_file), str(tmp_path / "out.txt"), master_key)

def test_decrypt_hmac_mismatch(valid_encrypted_file, tmp_path, master_key):
    """
    Cover raise ValueError("header authentication failed (HMAC mismatch)")
    """
    # Read the valid file
    content = bytearray(valid_encrypted_file.read_bytes())
    
    # Flip a bit in the wrapped key (at offset 10 to be safe)
    content[10] ^= 0xFF
    
    tampered_file = tmp_path / "tampered_header.sbx"
    tampered_file.write_bytes(content)
    
    with pytest.raises(ValueError, match="header authentication failed"):
        decrypt_file_stream(str(tampered_file), str(tmp_path / "out.txt"), master_key)