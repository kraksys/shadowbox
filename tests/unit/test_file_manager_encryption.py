from pathlib import Path

from src.shadowbox.core.file_manager import FileManager
from src.shadowbox.database.connection import DatabaseConnection


def test_file_manager_encrypt_store_and_decrypt(tmp_path: Path) -> None:
    """
    End-to-end encryption flow using FileManager, Storage and BoxEncryptionBackend.

    This exercises the high-level API that the rest of the application uses:

    - FileManager is created with encryption enabled and a master password
    - a user and an encrypted box are created
    - a file is added with ``encrypt=True`` so it goes through the encrypted path
    - the file is retrieved back via ``get_file(decrypt=True)`` and should match
      the original bytes on disk
    """
    # Setup: isolated database and encrypted FileManager.
    db_path = tmp_path / "test.db"
    db = DatabaseConnection(str(db_path))
    db.initialize()

    storage_root = tmp_path / "storage"
    fm = FileManager(
        str(storage_root),
        db,
        enable_encryption=True,
        master_password="s3curepassword",
    )

    # Create user and an encrypted box.
    user = fm.create_user("alice")
    box = fm.create_box(user.user_id, "secure", enable_encryption=True)

    # Create a sample file on disk.
    data = b"This is a secret file content" * 100
    src = tmp_path / "secret.txt"
    src.write_bytes(data)

    # Add file encrypted into the box.
    metadata = fm.add_file(
        user_id=user.user_id,
        box_id=box.box_id,
        source_path=str(src),
        encrypt=True,
    )

    # Custom metadata should record that the blob is encrypted.
    assert metadata.custom_metadata.get("encrypted", False) is True

    # Retrieve and decrypt to a new path.
    out = tmp_path / "restored.txt"
    fm.get_file(metadata.file_id, str(out), decrypt=True)

    assert out.read_bytes() == data
