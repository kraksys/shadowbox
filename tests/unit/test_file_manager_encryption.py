import os
from pathlib import Path

from src.shadowbox.core.file_manager import FileManager
from src.shadowbox.database.connection import DatabaseConnection
from src.shadowbox.security.kdf import generate_salt, derive_master_key
from src.shadowbox.security.session import unlock_with_key, lock


def test_file_manager_encrypt_store_and_decrypt(tmp_path):
    # setup db and file manager
    db_path = tmp_path / "test.db"
    db = DatabaseConnection(str(db_path))
    db.initialize()

    storage_root = tmp_path / "storage"
    fm = FileManager(str(storage_root), db)

    # create user
    user = fm.create_user("alice")
    user_id = user.user_id

    # create sample file
    data = b"This is a secret file content" * 100
    src = tmp_path / "secret.txt"
    src.write_bytes(data)

    # derive master key and unlock session
    salt = generate_salt()
    master = derive_master_key(b"s3curepassword", salt)
    unlock_with_key(master, ttl_seconds=60)

    # add file encrypted (FileManager will use active session key)
    metadata = fm.add_file(user_id, str(src), master_key=None)

    # decrypt blob to output file and verify contents (read_decrypted will use session key)
    out = tmp_path / "restored.txt"
    fm.storage.read_decrypted(user_id, metadata.hash_sha256, str(out))

    assert out.read_bytes() == data

    # cleanup session
    lock()
