"""ORM-style helpers for database operations."""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json
from .connection import DatabaseConnection
from ..core.models import FileMetadata, FileType, FileStatus, Box, BoxShare
from ..core.exceptions import StorageError


class BaseModel:
    """Base class for DB models."""

    __slots__ = ("db",)

    def __init__(self, db):
        """Initialize with a DatabaseConnection."""
        self.db = db

    def _serialize_json(self, data):
        """Serialize Python data to JSON string."""
        return json.dumps(data) if data else None

    def _deserialize_json(self, data):
        """Deserialize JSON string to Python data."""
        return json.loads(data) if data else None


class UserModel(BaseModel):
    """DB model for users."""

    def create(self, user_id, username, quota_bytes=10737418240):
        """Create a user and return it."""
        query = """
            INSERT INTO users (user_id, username, quota_bytes)
            VALUES (?, ?, ?)
        """

        self.db.execute(query, (user_id, username, quota_bytes))
        return self.get(user_id)

    def get(self, user_id):
        """Get user by ID."""
        query = "SELECT * FROM users WHERE user_id = ?"
        return self.db.fetch_one(query, (user_id,))

    def get_by_username(self, username):
        """Get user by username."""
        query = "SELECT * FROM users WHERE username = ?"
        return self.db.fetch_one(query, (username,))

    def list_all(self):
        """List all users."""
        query = "SELECT * FROM users ORDER BY username"
        return self.db.fetch_all(query)

    def update_quota(self, user_id, used_bytes):
        """Update a user's used_bytes quota value."""
        query = "UPDATE users SET used_bytes = ? WHERE user_id = ?"
        self.db.execute(query, (used_bytes, user_id))
        return True

    def delete(self, user_id):
        """Delete user by ID."""
        query = "DELETE FROM users WHERE user_id = ?"
        self.db.execute(query, (user_id,))
        return True


class BoxModel(BaseModel):
    """DB model for boxes."""

    def create(self, box):
        """Create a box and return it."""
        query = """
            INSERT INTO boxes (box_id, user_id, box_name, description, is_shared, share_token, settings)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            box.box_id,
            box.user_id,
            box.box_name,
            box.description,
            box.is_shared,
            box.share_token,
            self._serialize_json(box.settings),
        )

        self.db.execute(query, params)
        return self.get(box.box_id)

    def get(self, box_id):
        """Get box by ID."""
        query = "SELECT * FROM boxes WHERE box_id = ?"
        return self.db.fetch_one(query, (box_id,))

    def get_by_share_token(self, share_token):
        """Get box by share token."""
        query = "SELECT * FROM boxes WHERE share_token = ?"
        return self.db.fetch_one(query, (share_token,))

    def list_by_user(self, user_id):
        """List all boxes for a user."""
        query = "SELECT * FROM boxes WHERE user_id = ? ORDER BY created_at DESC"
        return self.db.fetch_all(query, (user_id,))

    def update(self, box):
        """Update a box."""
        query = """
            UPDATE boxes SET
                box_name = ?,
                description = ?,
                is_shared = ?,
                settings = ?
            WHERE box_id = ?
        """

        params = (
            box.box_name,
            box.description,
            box.is_shared,
            self._serialize_json(box.settings),
            box.box_id,
        )

        self.db.execute(query, params)
        return True

    def delete(self, box_id):
        """Delete box by ID (cascades to files and shares)."""
        query = "DELETE FROM boxes WHERE box_id = ?"
        self.db.execute(query, (box_id,))
        return True

    def set_shared(self, box_id, is_shared=True):
        """Set box sharing status."""
        query = "UPDATE boxes SET is_shared = ? WHERE box_id = ?"
        self.db.execute(query, (is_shared, box_id))
        return True


class BoxShareModel(BaseModel):
    """DB model for box shares."""

    def create(self, share):
        """Create a box share and return it."""
        query = """
            INSERT INTO box_shares (share_id, box_id, shared_by_user_id, shared_with_user_id, 
                                  permission_level, expires_at, access_token)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            share.share_id,
            share.box_id,
            share.shared_by_user_id,
            share.shared_with_user_id,
            share.permission_level,
            share.expires_at,
            share.access_token,
        )

        self.db.execute(query, params)
        return self.get(share.share_id)

    def update(self, share):
        """
        Update box share

        Args:
            share: BoxShare instance with updated data

        Returns:
            True if successful
        """
        query = """
            UPDATE box_shares SET
                permission_level = ?,
                expires_at = ?
            WHERE share_id = ?
        """

        params = (
            share.permission_level,
            share.expires_at,
            share.share_id,
        )

        self.db.execute(query, params)
        return True

    def get(self, share_id):
        """Get share by ID."""
        query = "SELECT * FROM box_shares WHERE share_id = ?"
        return self.db.fetch_one(query, (share_id,))

    def get_by_access_token(self, access_token):
        """Get share by access token."""
        query = "SELECT * FROM box_shares WHERE access_token = ?"
        return self.db.fetch_one(query, (access_token,))

    def list_by_box(self, box_id):
        """List all shares for a box."""
        query = "SELECT * FROM box_shares WHERE box_id = ?"
        return self.db.fetch_all(query, (box_id,))

    def list_by_user(self, user_id):
        """List all shares for a user (shared by/with)."""
        query = """
            SELECT * FROM box_shares 
            WHERE shared_by_user_id = ? OR shared_with_user_id = ?
        """
        return self.db.fetch_all(query, (user_id, user_id))

    def has_access(self, box_id, user_id, permission_level="read"):
        """Return True if user has at least the given permission on box."""
        query = """
            SELECT COUNT(*) as count FROM box_shares
            WHERE box_id = ? AND shared_with_user_id = ?
            AND permission_level IN ('admin', 'write', 'read')
            AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)
        """
        
        if permission_level == "write":
            query = query.replace("IN ('admin', 'write', 'read')", "IN ('admin', 'write')")
        elif permission_level == "admin":
            query = query.replace("IN ('admin', 'write', 'read')", "= 'admin'")

        result = self.db.fetch_one(query, (box_id, user_id))
        return result['count'] > 0

    def delete(self, share_id):
        """Delete share by ID."""
        query = "DELETE FROM box_shares WHERE share_id = ?"
        self.db.execute(query, (share_id,))
        return True

    def delete_by_box_and_user(self, box_id, user_id):
        """Delete share by box and user."""
        query = "DELETE FROM box_shares WHERE box_id = ? AND shared_with_user_id = ?"
        self.db.execute(query, (box_id, user_id))
        return True


class FileModel(BaseModel):
    """DB model for files."""

    def create(self, metadata):
        """Create a file record and return its ID."""
        query = """
            INSERT INTO files (
                file_id, user_id, box_id, filename, original_path, size,
                file_type, mime_type, hash_sha256, created_at,
                modified_at, accessed_at, owner, status, version,
                parent_version_id, description, custom_metadata) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            metadata.file_id,
            metadata.user_id,
            metadata.box_id,
            metadata.filename,
            metadata.original_path,
            metadata.size,
            metadata.file_type.value,
            metadata.mime_type,
            metadata.hash_sha256,
            metadata.created_at,
            metadata.modified_at,
            metadata.accessed_at,
            metadata.owner,
            metadata.status.value,
            metadata.version,
            metadata.parent_version_id,
            metadata.description,
            self._serialize_json(metadata.custom_metadata),
        )

        self.db.execute(query, params)

        if metadata.tags:
            self._add_tags(metadata.file_id, metadata.tags)

        return metadata.file_id

    def get(self, file_id):
        """Get FileMetadata by ID or None."""
        query = "SELECT * FROM files WHERE file_id = ?"
        row = self.db.fetch_one(query, (file_id,))

        if not row:
            return None

        tags = self._get_tags(file_id)

        return row_to_metadata(row, tags)

    def list_by_user(self, user_id, include_deleted=False, limit=None, offset=0):
        """List files for a user with optional filters."""
        query = "SELECT * FROM files WHERE user_id = ?"
        params = [user_id]

        if not include_deleted:
            query += " AND status != 'deleted'"

        query += " ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = self.db.fetch_all(query, tuple(params))

        result = []
        for row in rows:
            tags = self._get_tags(row["file_id"])
            result.append(row_to_metadata(row, tags))

        return result

    def update(self, metadata):
        """Update a file record and its tags."""
        query = """
            UPDATE files SET
                filename = ?,
                size = ?,
                file_type = ?,
                mime_type = ?,
                hash_sha256 = ?,
                modified_at = ?,
                status = ?,
                version = ?,
                description = ?,
                custom_metadata = ?
            WHERE file_id = ?
        """

        params = (
            metadata.filename,
            metadata.size,
            metadata.file_type.value,
            metadata.mime_type,
            metadata.hash_sha256,
            metadata.modified_at,
            metadata.status.value,
            metadata.version,
            metadata.description,
            self._serialize_json(metadata.custom_metadata),
            metadata.file_id,
        )

        self.db.execute(query, params)

        self._update_tags(metadata.file_id, metadata.tags)

        return True

    def delete(self, file_id, soft=True):
        """Soft-delete or permanently delete a file record."""
        if soft:
            query = "UPDATE files SET status = 'deleted' WHERE file_id = ?"
        else:
            query = "DELETE FROM files WHERE file_id = ?"

        self.db.execute(query, (file_id,))
        return True

    def find_by_hash(self, hash_sha256):
        """Find files with the given SHA-256 hash."""
        query = "SELECT * FROM files WHERE hash_sha256 = ?"
        rows = self.db.fetch_all(query, (hash_sha256,))

        result = []
        for row in rows:
            tags = self._get_tags(row["file_id"])
            result.append(row_to_metadata(row, tags))

        return result

    def _add_tags(self, file_id, tags):
        """Add tags to a file."""
        for tag in tags:
            tag_id = self._get_or_create_tag(tag)

            query = "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)"
            self.db.execute(query, (file_id, tag_id))

    def _update_tags(self, file_id, tags):
        """Replace tags for a file."""
        self.db.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))

        if tags:
            self._add_tags(file_id, tags)

    def _get_tags(self, file_id):
        """Return tag names for a file."""
        query = """
            SELECT t.tag_name
            FROM tags t
            JOIN file_tags ft ON t.tag_id = ft.tag_id
            WHERE ft.file_id = ?
        """

        rows = self.db.fetch_all(query, (file_id,))
        return [row["tag_name"] for row in rows]

    def _get_or_create_tag(self, tag_name):
        """Return tag_id for name, creating the tag if missing."""
        query = "SELECT tag_id FROM tags WHERE tag_name = ?"
        row = self.db.fetch_one(query, (tag_name,))

        if row:
            return row["tag_id"]

        query = "INSERT INTO tags (tag_name) VALUES (?)"
        self.db.execute(query, (tag_name,))

        row = self.db.fetch_one(
            "SELECT tag_id FROM tags WHERE tag_name = ?", (tag_name,)
        )
        return row["tag_id"]

    def list_by_box(self, box_id, include_deleted=False, limit=None, offset=0):
        """List files in a box with optional filters."""
        query = "SELECT * FROM files WHERE box_id = ?"
        params = [box_id]

        if not include_deleted:
            query += " AND status != 'deleted'"

        query += " ORDER BY created_at DESC"

        if limit:
            query += f" LIMIT {limit} OFFSET {offset}"

        rows = self.db.fetch_all(query, tuple(params))

        result = []
        for row in rows:
            tags = self._get_tags(row['file_id'])
            result.append(row_to_metadata(row, tags))

        return result

    def list_by_user_and_box(self, user_id, box_id, include_deleted=False):
        """List files for a user in a specific box."""
        query = "SELECT * FROM files WHERE user_id = ? AND box_id = ?"
        params = [user_id, box_id]

        if not include_deleted:
            query += " AND status != 'deleted'"

        query += " ORDER BY created_at DESC"

        rows = self.db.fetch_all(query, tuple(params))

        result = []
        for row in rows:
            tags = self._get_tags(row['file_id'])
            result.append(row_to_metadata(row, tags))

        return result


def row_to_metadata(row, tags):
    """Convert a row dict + tag list to FileMetadata."""
    created_at = row["created_at"]
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    modified_at = row["modified_at"]
    if isinstance(modified_at, str):
        modified_at = datetime.fromisoformat(modified_at)

    accessed_at = row["accessed_at"]
    if isinstance(accessed_at, str):
        accessed_at = datetime.fromisoformat(accessed_at)

    custom_metadata = {}
    if row.get("custom_metadata"):
        try:
            custom_metadata = json.loads(row["custom_metadata"])
        except (json.JSONDecodeError, TypeError):
            custom_metadata = {}

    return FileMetadata(
        file_id=row["file_id"],
        box_id=row["box_id"],
        filename=row["filename"],
        original_path=row["original_path"],
        size=row["size"],
        file_type=FileType(row["file_type"]),
        mime_type=row["mime_type"],
        hash_sha256=row["hash_sha256"],
        created_at=created_at,
        modified_at=modified_at,
        accessed_at=accessed_at,
        user_id=row["user_id"],
        owner=row["owner"],
        status=FileStatus(row["status"]),
        version=row["version"],
        parent_version_id=row["parent_version_id"],
        tags=tags,
        description=row["description"],
        custom_metadata=custom_metadata,
    )
