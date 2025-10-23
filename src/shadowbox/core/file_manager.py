import os
import shutil
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, List
from ..database.connection import DatabaseConnection
from ..database.models import UserModel, FileModel
from .models import FileMetadata, FileStatus, UserDirectory
from .storage import Storage
from .exceptions import (
    UserNotFoundError,
    FileNotFoundError,
    QuotaExceededError,
    UserExistsError,
)


class FileManager:
    """
    Manages user directories and file operations.
    """

    def __init__(self, storage_root: str, db_connection: DatabaseConnection):

        # Initializes the FileManager.

        self.storage_root = Path(storage_root)
        self.db = db_connection
        self.user_model = UserModel(self.db)
        self.file_model = FileModel(self.db)
        # Ensure the root storage directory exists
        self.storage = Storage(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def create_user(self, username: str) -> UserDirectory:

        # Creates a new user and their isolated directory.

        if self.user_model.get_by_username(username):
            raise UserExistsError(f"Username '{username}' is already taken.")

        user_id = str(uuid.uuid4())
        user_data = self.user_model.create(user_id=user_id, username=username)

        user_root_path = self.storage_root / user_id
        user_root_path.mkdir(exist_ok=True)

        return UserDirectory(
            user_id=user_data["user_id"],
            username=user_data["username"],
            root_path=str(user_root_path),
            quota_bytes=user_data["quota_bytes"],
        )

    def add_file(
        self, user_id: str, source_path: str, tags: Optional[List[str]] = None
    ) -> FileMetadata:

        # Adds a file to the user's storage.

        src = Path(source_path)

        if not src.exists():
            raise FileNotFoundError(f"Source file not found at: {source_path}")

        user = self.user_model.get(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        # Check quota
        size = src.stat().st_size
        if user["used_bytes"] + size > user["quota_bytes"]:
            raise QuotaExceededError("Adding this file would exceed the user's quota.")

        info = self.storage.put(user_id, src)
        file_hash = info["hash"]
        size = info["size"]

        # Create metadata record
        metadata = FileMetadata(
            user_id=user_id,
            filename=src.name,
            original_path=str(source_path),
            size=size,
            hash_sha256=file_hash,
            owner=user["username"],
            tags=tags if tags else [],
        )

        # Save metadata to the database
        self.file_model.create(metadata)
        # Update users quota usage
        self.user_model.update_quota(user_id, user["used_bytes"] + size)
        return metadata

    def get_file_metadata(self, file_id: str) -> Optional[FileMetadata]:

        # Retrieves a files metadata from the database.
        return self.file_model.get(file_id)

    def list_user_files(self, user_id: str) -> List[FileMetadata]:

        # Lists all active files for a given user.

        if not self.user_model.get(user_id):
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")
        return self.file_model.list_by_user(user_id)

    def delete_file(self, file_id: str):

        # Deletes a file (soft delete by default).

        metadata = self.get_file_metadata(file_id)
        if not metadata:
            raise FileNotFoundError(f"File with ID '{file_id}' not found.")
        # Perform soft delete in the database
        self.file_model.delete(file_id, soft=True)
        # Update user's quota
        user = self.user_model.get(metadata.user_id)
        if user:
            new_used_bytes = max(0, user["used_bytes"] - metadata.size)
            self.user_model.update_quota(metadata.user_id, new_used_bytes)
