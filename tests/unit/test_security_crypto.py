import os
import tempfile
import struct

from shadowbox.security.kdf import generate_salt, derive_master_key
from shadowbox.security.crypto import encrypt_file_stream, decrypt_file_stream


def test_encrypt_decrypt_roundtrip(tmp_path):
    # create random input file
    data = os.urandom(250_000)
    in_file = tmp_path / "input.bin"
    enc_file = tmp_path / "input.bin.sbx"
    dec_file = tmp_path / "input.dec"
    in_file.write_bytes(data)

    salt = generate_salt()
    master = derive_master_key(b"correct horse battery staple", salt)

    encrypt_file_stream(str(in_file), str(enc_file), master)
    decrypt_file_stream(str(enc_file), str(dec_file), master)

    out = dec_file.read_bytes()
    assert out == data


def test_decrypt_fails_on_tamper(tmp_path):
    data = b"hello world" * 100
    in_file = tmp_path / "tinput.bin"
    enc_file = tmp_path / "tinput.bin.sbx"
    dec_file = tmp_path / "tinput.dec"
    in_file.write_bytes(data)

    salt = generate_salt()
    master = derive_master_key(b"password123", salt)
    encrypt_file_stream(str(in_file), str(enc_file), master)

    # tamper: flip a byte somewhere in ciphertext region
    with open(enc_file, "r+b") as f:
        # skip header: read magic + ver + alg + wrapped_len
        f.seek(0)
        hdr = f.read(8)
        # now flip a byte after header
        f.seek(len(hdr) + 10)
        b = f.read(1)
        if not b:
            # nothing to flip, just append bad byte
            f.write(b"\x00")
        else:
            f.seek(-1, os.SEEK_CUR)
            f.write(bytes([b[0] ^ 0x01]))

    try:
        decrypt_file_stream(str(enc_file), str(dec_file), master)
        assert False, "decrypt should have failed on tampered ciphertext"
    except Exception:
        pass


def test_decrypt_fails_on_truncated(tmp_path):
    data = os.urandom(10_000)
    in_file = tmp_path / "trinput.bin"
    enc_file = tmp_path / "trinput.bin.sbx"
    dec_file = tmp_path / "trinput.dec"
    in_file.write_bytes(data)

    salt = generate_salt()
    master = derive_master_key(b"hunter2", salt)
    encrypt_file_stream(str(in_file), str(enc_file), master)

    # truncate the encrypted file (remove last 10 bytes)
    with open(enc_file, "r+b") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.truncate(max(0, size - 10))

    try:
        decrypt_file_stream(str(enc_file), str(dec_file), master)
        assert False, "decrypt should have failed on truncated ciphertext"
    except Exception:
        pass


def test_corrupted_wrapped_cek(tmp_path):
    data = b"small data"
    in_file = tmp_path / "cek_input.bin"
    enc_file = tmp_path / "cek_input.bin.sbx"
    dec_file = tmp_path / "cek_input.dec"
    in_file.write_bytes(data)

    salt = generate_salt()
    master = derive_master_key(b"letmein", salt)
    encrypt_file_stream(str(in_file), str(enc_file), master)

    # corrupt wrapped cek in header
    with open(enc_file, "r+b") as f:
        # read magic + ver + alg
        f.seek(0)
        f.read(2)
        # read version+alg consumed; go to wrapped_len
        f.seek(4)
        # read wrapped_len
        wl = f.read(2)
        if len(wl) < 2:
            raise RuntimeError("header too small in test")
        (wrapped_len,) = struct.unpack(">H", wl)
        # flip a byte in wrapped region
        f.seek(6)
        if wrapped_len > 0:
            b = f.read(1)
            f.seek(-1, os.SEEK_CUR)
            f.write(bytes([b[0] ^ 0xFF]))

    try:
        decrypt_file_stream(str(enc_file), str(dec_file), master)
        assert False, "decrypt should have failed with corrupted wrapped CEK"
    except Exception:
        pass
