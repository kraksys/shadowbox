"""
FileManager for ShadowBox with per-box storage and optional encryption.
"""

import uuid
from pathlib import Path
import json
from datetime import datetime
from typing import Optional, List
from ..database.connection import DatabaseConnection
from ..database.models import UserModel, FileModel, BoxModel, BoxShareModel
from .models import FileMetadata, FileStatus, UserDirectory, Box, BoxShare
from .storage import Storage
from .versioning import VersionManager
from .metadata import MetadataExtractor
from .exceptions import (
    UserNotFoundError,
    FileNotFoundError,
    QuotaExceededError,
    UserExistsError,
    BoxNotFoundError,
    BoxExistsError,
    AccessDeniedError,
)


class FileManager:
    """High-level file operations over storage and database."""

    def __init__(
        self,
        storage_root: str,
        db_connection: DatabaseConnection,
        enable_encryption: bool = False,
        master_password: Optional[str] = None,
    ):
        # Initialize manager, storage, and models; optionally enable encryption
        self.storage_root = Path(storage_root)
        self.db = db_connection
        self.user_model = UserModel(self.db)
        self.file_model = FileModel(self.db)
        self.box_model = BoxModel(self.db)
        self.box_share_model = BoxShareModel(self.db)
        self.metadata_extractor = MetadataExtractor()

        # Initialize storage (handles both encrypted and unencrypted ops)
        self.storage = Storage(storage_root)

        # Setup encryption if enabled
        self.encryption_enabled = enable_encryption
        if enable_encryption and master_password:
            self.setup_encryption(master_password)

        self.storage_root.mkdir(parents=True, exist_ok=True)

    def setup_encryption(self, master_password: str) -> None:
        """Configure storage encryption with a master password."""
        self.storage.setup_master_key(master_password)
        self.encryption_enabled = True

    def create_user(self, username: str) -> UserDirectory:
        """Create a new user and their isolated directory."""
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

    def create_box(
        self,
        user_id: str,
        box_name: str,
        description: Optional[str] = None,
        enable_encryption: bool = False,
    ) -> Box:
        """Create a new box; optionally mark it encrypted."""
        user = self.user_model.get(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        # Check if box name already exists for this user
        existing_boxes = self.box_model.list_by_user(user_id)
        for box in existing_boxes:
            if box["box_name"] == box_name:
                raise BoxExistsError(f"Box '{box_name}' already exists for user.")

        box = Box(
            user_id=user_id,
            box_name=box_name,
            description=description,
        )

        # Store encryption preference in box settings
        if enable_encryption:
            box.settings["encryption_enabled"] = True

        self.box_model.create(box)
        # Mirror DB settings to storage settings file and ensure box dirs
        try:
            self.storage.ensure_box(user_id, box.box_id)
            self.storage.set_box_encryption_enabled(
                user_id, box.box_id, box.settings.get("encryption_enabled", False)
            )
        except Exception:
            pass
        return box

    def list_user_boxes(self, user_id: str) -> List[Box]:
        """List all boxes for a user."""
        if not self.user_model.get(user_id):
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        box_data_list = self.box_model.list_by_user(user_id)
        return [Box(**box_data) for box_data in box_data_list]

    def get_box(self, box_id: str) -> Optional[Box]:
        """Get box by ID."""
        box_data = self.box_model.get(box_id)
        if not box_data:
            return None
        return Box(**box_data)

    def update_box(self, box: Box) -> bool:
        """Update box information."""
        current = self.get_box(box.box_id)
        if current is None:
            raise BoxNotFoundError(f"Box with ID '{box.box_id}' not found.")

        def _is_enabled(b: Box) -> bool:
            s = b.settings
            if isinstance(s, str):
                try:
                    s = json.loads(s)
                except Exception:
                    s = {}
            return bool(s.get("encryption_enabled", False))

        if _is_enabled(current) != _is_enabled(box):
            raise ValueError("Changing encryption state of a box is not supported")

        ok = self.box_model.update(box)
        try:
            self.storage.set_box_encryption_enabled(
                box.user_id, box.box_id, _is_enabled(box)
            )
        except Exception:
            pass
        return ok

    def delete_box(self, box_id: str) -> bool:
        """Delete a box and all its contents."""
        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box with ID '{box_id}' not found.")

        # Delete all files in the box
        files = self.list_box_files(box_id)
        for file_metadata in files:
            self.delete_file(file_metadata.file_id, soft=False)

        # Delete all shares
        shares = self.box_share_model.list_by_box(box_id)
        for share in shares:
            self.box_share_model.delete(share["share_id"])

        # Delete the box
        return self.box_model.delete(box_id)

    def add_file(
        self,
        user_id: str,
        box_id: str,
        source_path: str,
        tags: Optional[List[str]] = None,
        encrypt: Optional[bool] = None,
    ) -> FileMetadata:
        """Add a file to a box; optional encryption."""
        src = Path(source_path)

        if not src.exists():
            raise FileNotFoundError(f"Source file not found at: {source_path}")

        user = self.user_model.get(user_id)
        if not user:
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")

        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box with ID '{box_id}' not found.")

        # Check Access
        if box.user_id != user_id:
            if not self.box_share_model.has_access(box_id, user_id, "write"):
                raise AccessDeniedError(f"User '{user_id}' no write access to box '{box_id}'.")

        # Check quota
        size = src.stat().st_size
        if user["used_bytes"] + size > user["quota_bytes"]:
            raise QuotaExceededError("Adding this file would exceed the user's quota.")

        # NEW: Extract Metadata before storage
        extracted_meta = self.metadata_extractor.extract(str(src))
        detected_mime = extracted_meta.pop("mime_type", None) # Remove mime to store in dedicated col

        # Determine encryption setting
        if encrypt is None:
            encrypt = box.settings.get("encryption_enabled", self.encryption_enabled)

        # Store file
        if encrypt and self.encryption_enabled:
            info = self.storage.put_encrypted(user_id, box_id, str(src))
            is_encrypted = True
        else:
            info = self.storage.put(user_id, box_id, str(src))
            is_encrypted = False

        # Prepare Custom Metadata (Merge extraction + system flags)
        final_custom_metadata = extracted_meta
        if is_encrypted:
            final_custom_metadata["encrypted"] = True

        # Create metadata record
        metadata = FileMetadata(
            user_id=user_id,
            box_id=box_id,
            filename=src.name,
            original_path=str(source_path),
            size=info["size"],
            hash_sha256=info["hash"],
            mime_type=detected_mime, # Use detected mime type
            owner=user["username"],
            tags=tags if tags else [],
            custom_metadata=final_custom_metadata,
        )

        self.file_model.create(metadata)
        self.user_model.update_quota(user_id, user["used_bytes"] + size)
        return metadata

    def get_file(
        self, file_id: str, destination_path: str, decrypt: bool = True
    ) -> str:
        """Retrieve a file, optionally decrypting if encrypted."""
        metadata = self.get_file_metadata(file_id)
        if not metadata:
            raise FileNotFoundError(f"File with ID '{file_id}' not found.")

        # Determine if file is encrypted
        is_encrypted = metadata.custom_metadata.get("encrypted", False)

        if is_encrypted and decrypt and self.encryption_enabled:
            return self.storage.get_encrypted(
                metadata.user_id,
                metadata.box_id,
                metadata.hash_sha256,
                destination_path,
            )
        else:
            # Use regular storage (either unencrypted or encryption disabled)
            return self.storage.get(
                metadata.user_id,
                metadata.box_id,
                metadata.hash_sha256,
                destination_path,
            )

    def get_file_metadata(self, file_id: str) -> Optional[FileMetadata]:
        """Fetch a file's metadata from the database."""
        return self.file_model.get(file_id)

    def list_user_files(self, user_id: str) -> List[FileMetadata]:
        """List all active files for a user across boxes."""
        if not self.user_model.get(user_id):
            raise UserNotFoundError(f"User with ID '{user_id}' not found.")
        return self.file_model.list_by_user(user_id)

    def list_box_files(
        self, box_id: str, user_id: Optional[str] = None
    ) -> List[FileMetadata]:
        """List all files in a box."""
        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box with ID '{box_id}' not found.")

        # Check access if user_id provided
        if user_id and box.user_id != user_id:
            if not self.box_share_model.has_access(box_id, user_id, "read"):
                raise AccessDeniedError(
                    f"User '{user_id}' does not have read access to box '{box_id}'."
                )

        return self.file_model.list_by_box(box_id)

    def share_box(
        self,
        box_id: str,
        shared_by_user_id: str,
        shared_with_user_id: str,
        permission_level: str = "read",
        expires_at: Optional[datetime] = None,
    ) -> BoxShare:
        """Share a box with another user."""
        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box with ID '{box_id}' not found.")

        if box.user_id != shared_by_user_id:
            raise AccessDeniedError(
                f"User '{shared_by_user_id}' is not the owner of box '{box_id}'."
            )

        if permission_level not in ["read", "write", "admin"]:
            raise ValueError(f"Invalid permission level: {permission_level}")

        # Check if already shared
        existing_shares = self.box_share_model.list_by_box(box_id)
        for share in existing_shares:
            if share["shared_with_user_id"] == shared_with_user_id:
                # Update existing share by deleting and recreating
                self.box_share_model.delete(share["share_id"])

        # Create new share
        share = BoxShare(
            box_id=box_id,
            shared_by_user_id=shared_by_user_id,
            shared_with_user_id=shared_with_user_id,
            permission_level=permission_level,
            expires_at=expires_at,
        )

        self.box_share_model.create(share)

        # Update box sharing status
        self.box_model.set_shared(box_id, True)

        return share

    def unshare_box(
        self, box_id: str, shared_by_user_id: str, shared_with_user_id: str
    ) -> bool:
        """Remove a box share."""
        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box with ID '{box_id}' not found.")

        if box.user_id != shared_by_user_id:
            raise AccessDeniedError(
                f"User '{shared_by_user_id}' is not the owner of box '{box_id}'."
            )

        result = self.box_share_model.delete_by_box_and_user(
            box_id, shared_with_user_id
        )

        # Check if box is still shared
        remaining_shares = self.box_share_model.list_by_box(box_id)
        if not remaining_shares:
            self.box_model.set_shared(box_id, False)

        return result

    def list_shared_boxes(self, user_id: str) -> List[Box]:
        """
        List all boxes shared with a user.

        Args:
            user_id: User ID

        Returns:
            List of Box instances
        """
        shares = self.box_share_model.list_by_user(user_id)
        boxes = []
        for share in shares:
            if share["shared_with_user_id"] == user_id:
                box = self.get_box(share["box_id"])
                if box and not BoxShare(**share).is_expired():
                    boxes.append(box)
        return boxes

    def delete_file(self, file_id: str, soft: bool = True):
        """Delete a file record (soft by default) and update quota."""
        metadata = self.get_file_metadata(file_id)
        if not metadata:
            raise FileNotFoundError(f"File with ID '{file_id}' not found.")

        # Perform delete in the database
        self.file_model.delete(file_id, soft=soft)

        # Update user's quota
        user = self.user_model.get(metadata.user_id)
        if user:
            new_used_bytes = max(0, user["used_bytes"] - metadata.size)
            self.user_model.update_quota(metadata.user_id, new_used_bytes)

    def get_box_info(self, user_id: str, box_id: str) -> dict:
        """Get information about a box including encryption state."""
        box = self.get_box(box_id)
        if not box:
            return {}

        # Get basic box info from encrypted storage
        box_info = self.storage.get_box_info(user_id, box_id)

        # Add additional metadata
        box_info.update(
            {
                "box_name": box.box_name,
                "description": box.description,
                "is_shared": box.is_shared,
                "encryption_enabled": box.settings.get("encryption_enabled", False),
                "owner": box.user_id == user_id,
            }
        )

        return box_info

    def enable_box_encryption(self, user_id: str, box_id: str, password: str) -> bool:
        """Changing encryption state of a box is not supported."""
        raise ValueError("Changing encryption state of a box is not supported")
    
    def update_file(
        self,
        file_id: str,
        source_path: str,
        change_description: str = "File updated",
        encrypt: Optional[bool] = None
    ) -> FileMetadata:
        """Update an existing file with new content, versioning, and metadata extraction."""
        src = Path(source_path)
        if not src.exists():
            raise FileNotFoundError(f"Source file not found at: {source_path}")

        current_metadata = self.get_file_metadata(file_id)
        if not current_metadata:
            raise FileNotFoundError(f"File with ID '{file_id}' not found.")

        user_id = current_metadata.user_id
        box_id = current_metadata.box_id

        # Check Quota
        new_size = src.stat().st_size
        size_diff = new_size - current_metadata.size
        user = self.user_model.get(user_id)
        if user["used_bytes"] + size_diff > user["quota_bytes"]:
            raise QuotaExceededError("Updating exceeds quota.")

        # Create Snapshot
        version_mgr = VersionManager(self.db)
        version_mgr.create_version_snapshot(file_id, change_description)

        # Extract Metadata
        extracted_meta = self.metadata_extractor.extract(str(src))
        detected_mime = extracted_meta.pop("mime_type", None)

        # Storage
        is_encrypted_prev = current_metadata.custom_metadata.get("encrypted", False)
        should_encrypt = encrypt if encrypt is not None else is_encrypted_prev

        if should_encrypt and self.encryption_enabled:
            info = self.storage.put_encrypted(user_id, box_id, str(src))
            is_encrypted = True
        else:
            info = self.storage.put(user_id, box_id, str(src))
            is_encrypted = False

        # Merge Metadata
        final_custom_metadata = extracted_meta
        if is_encrypted:
            final_custom_metadata["encrypted"] = True

        # Update Record
        current_metadata.filename = src.name 
        current_metadata.size = info["size"]
        current_metadata.hash_sha256 = info["hash"]
        current_metadata.mime_type = detected_mime
        current_metadata.modified_at = datetime.utcnow()
        current_metadata.version += 1
        current_metadata.custom_metadata = final_custom_metadata

        self.file_model.update(current_metadata)
        self.user_model.update_quota(user_id, user["used_bytes"] + size_diff)

        return current_metadata
    
    def add_files_bulk(
        self,
        user_id: str,
        box_id: str,
        file_paths: List[str],
        tags: Optional[List[str]] = None,
        encrypt: Optional[bool] = None
    ) -> dict:
        """
        Add multiple files efficiently.
        Returns a dict: {'success': [FileMetadata], 'failed': [{'path': str, 'error': str}]}
        """
        results = {"success": [], "failed": []}
        
        # Validation and Setup 
        user = self.user_model.get(user_id)
        if not user:
            raise UserNotFoundError(f"User {user_id} not found.")
            
        box = self.get_box(box_id)
        if not box:
            raise BoxNotFoundError(f"Box {box_id} not found.")

        if box.user_id != user_id:
            if not self.box_share_model.has_access(box_id, user_id, "write"):
                raise AccessDeniedError(f"No write access to box {box_id}.")

        # Pre-calculate total size to check quota
        total_batch_size = 0
        valid_paths = []
        
        for p in file_paths:
            path_obj = Path(p)
            if not path_obj.exists():
                results["failed"].append({"path": p, "error": "File not found"})
                continue
            size = path_obj.stat().st_size
            total_batch_size += size
            valid_paths.append(path_obj)

        if user["used_bytes"] + total_batch_size > user["quota_bytes"]:
            raise QuotaExceededError("Batch upload exceeds user quota.")

        # Determine encryption
        if encrypt is None:
            encrypt = box.settings.get("encryption_enabled", self.encryption_enabled)

        # Process Files
        metadata_to_insert = []
        
        for src in valid_paths:
            try:
                # Extract Metadata
                extracted_meta = self.metadata_extractor.extract(str(src))
                detected_mime = extracted_meta.pop("mime_type", None)

                # Storage Put
                if encrypt and self.encryption_enabled:
                    info = self.storage.put_encrypted(user_id, box_id, str(src))
                    is_encrypted = True
                else:
                    info = self.storage.put(user_id, box_id, str(src))
                    is_encrypted = False

                final_custom_metadata = extracted_meta
                if is_encrypted:
                    final_custom_metadata["encrypted"] = True

                # Create Object
                meta = FileMetadata(
                    user_id=user_id,
                    box_id=box_id,
                    filename=src.name,
                    original_path=str(src),
                    size=info["size"],
                    hash_sha256=info["hash"],
                    mime_type=detected_mime,
                    owner=user["username"],
                    tags=tags if tags else [],
                    custom_metadata=final_custom_metadata,
                )
                metadata_to_insert.append(meta)
                results["success"].append(meta)

            except Exception as e:
                results["failed"].append({"path": str(src), "error": str(e)})

        # 4. Bulk DB Insert
        if metadata_to_insert:
            self.file_model.create_many(metadata_to_insert)
            
            # Update Quota ONCE
            new_usage = user["used_bytes"] + sum(m.size for m in metadata_to_insert)
            self.user_model.update_quota(user_id, new_usage)

        return results

    def delete_files_bulk(self, file_ids: List[str], soft: bool = True) -> int:
        """ Delete multiple files efficiently. Returns count of deleted files. """
        if not file_ids:
            return 0

        # Fetch files to calculate size and verify ownership
        placeholders = ",".join(["?"] * len(file_ids))
        query = f"SELECT * FROM files WHERE file_id IN ({placeholders})"
        rows = self.db.fetch_all(query, tuple(file_ids))
        
        if not rows:
            return 0

        total_freed_bytes = 0
        user_id = rows[0]["user_id"]

        # Perform Deletion
        if soft:
            update_sql = f"UPDATE files SET status = 'deleted' WHERE file_id IN ({placeholders})"
            self.db.execute(update_sql, tuple(file_ids))
        else:
            delete_sql = f"DELETE FROM files WHERE file_id IN ({placeholders})"
            self.db.execute(delete_sql, tuple(file_ids))

        # Calculate Freed Space
        for row in rows:
            if row["status"] != "deleted":
                total_freed_bytes += row["size"]

        # Update Quota
        if total_freed_bytes > 0:
            user = self.user_model.get(user_id)
            if user:
                new_used = max(0, user["used_bytes"] - total_freed_bytes)
                self.user_model.update_quota(user_id, new_used)

        return len(rows)
