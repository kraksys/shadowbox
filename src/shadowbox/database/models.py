"""
    ORM query builders for all db ops 
"""

from typing import Optional, List, Dict, Any, Union
from datetime import datetime
import json

from .connection import DatabaseConnection
from ..core.models import FileMetadata, FileType, FileStatus, create_metadata_from_dict
from ..core.exceptions import StorageError


class BaseModel:
    """
        Base class for db models
    """

    __slots__ = ('db',)

    def __init__(self, db):
        """
            Initialize model

            Args:
                db: DatabaseConnection instance
        """
        self.db = db

    def _serialize_json(self, data):
        """
            Serialize data to JSON

            Args:
                data: Data to serialize

            Returns:
                JSON string or None
        """
        return json.dumps(data) if data else None

    def _deserialize_json(self, data):
        """
            Deserialize JSON to data.

            Args:
                data: JSON string

            Returns:
                Deserialized data or None
        """
        return json.loads(data) if data else None


class UserModel(BaseModel):
    """
        DB model for users
    """

    def create(self, user_id, username, quota_bytes=10737418240):
        """
            Create a new user

            Args:
                user_id: User identifier
                username: Custom username that can be selected 
                quota_bytes: Maximum allowable storage a user can have (10GB) 

            Returns:
                User dictionary
        """
        query = """
            INSERT INTO users (user_id, username, quota_bytes)
            VALUES (?, ?, ?)
        """

        self.db.execute(query, (user_id, username, quota_bytes))
        return self.get(user_id)

    def get(self, user_id):
        """
            Get user by ID

            Args:
                user_id: User identifier

            Returns:
                User dict or None
        """
        query = "SELECT * FROM users WHERE user_id = ?"
        return self.db.fetch_one(query, (user_id,))

    def get_by_username(self, username):
        """
            Get user by username

            Args:
                username: Username

            Returns:
                User dict or None
        """
        query = "SELECT * FROM users WHERE username = ?"
        return self.db.fetch_one(query, (username,))

    def update_quota(self, user_id, used_bytes):
        """
            Update user's quota

            Args:
                user_id: User identifier
                used_bytes: Number of bytes used

            Returns:
                True if successful
        """
        query = "UPDATE users SET used_bytes = ? WHERE user_id = ?"
        self.db.execute(query, (used_bytes, user_id))
        return True

    def delete(self, user_id):
        """
            Delete user

            Args:
                user_id: User identifier

            Returns:
                True if successful
        """
        query = "DELETE FROM users WHERE user_id = ?"
        self.db.execute(query, (user_id,))
        return True


class FileModel(BaseModel):
    """
        DB model for files
    """

    def create(self, metadata):
        """
            Create file record

            Args:
                metadata: FileMetadata object

            Returns:
                File ID
        """
        query = """
            INSERT INTO files (
                file_id, user_id, filename, original_path, size,
                file_type, mime_type, hash_sha256, created_at,
                modified_at, accessed_at, owner, status, version,
                parent_version_id, description, custom_metadata) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        params = (
            metadata.file_id,
            metadata.user_id,
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
        """
            Get file by ID

            Args:
                file_id: File identifier

            Returns:
                FileMetadata or None
        """
        query = "SELECT * FROM files WHERE file_id = ?"
        row = self.db.fetch_one(query, (file_id,))

        if not row:
            return None

        tags = self._get_tags(file_id)

        return row_to_metadata(row, tags)

    def list_by_user(self, user_id, include_deleted=False, limit=None, offset=0):
        """
            List files for a user

            Args:
                user_id: User identifier
                include_deleted: Whether to include deleted files
                limit: Maximum number of results
                offset: Result offset for pagination

            Returns:
                List of FileMetadata objects
        """
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
            tags = self._get_tags(row['file_id'])
            result.append(row_to_metadata(row, tags))

        return result

    def update(self, metadata):
        """
            Update file record

            Args:
                metadata: FileMetadata object

            Returns:
                True if successful
        """
        query = 
        """
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
        """
            Delete file record

            Args:
                file_id: File identifier
                soft: If True soft delete (which keeps the record, allows undo), if False permanent delete (which deletes the record, disallows undo)

            Returns:
                True if successful
        """
        if soft:
            query = "UPDATE files SET status = 'deleted' WHERE file_id = ?"
        else:
            query = "DELETE FROM files WHERE file_id = ?"

        self.db.execute(query, (file_id,))
        return True

    def find_by_hash(self, hash_sha256):
        """
            Find files with matching hash

            Args:
                hash_sha256: SHA-256 hash to search for

            Returns:
                List of FileMetadata objects
        """
        query = "SELECT * FROM files WHERE hash_sha256 = ?"
        rows = self.db.fetch_all(query, (hash_sha256,))

        result = []
        for row in rows:
            tags = self._get_tags(row['file_id'])
            result.append(row_to_metadata(row, tags))

        return result

    def _add_tags(self, file_id, tags):
        """
            Add tags to a file

            Args:
                file_id: File identifier
                tags: List of tag names
        """
        for tag in tags:
            tag_id = self._get_or_create_tag(tag)

            query = "INSERT OR IGNORE INTO file_tags (file_id, tag_id) VALUES (?, ?)"
            self.db.execute(query, (file_id, tag_id))

    def _update_tags(self, file_id, tags):
        """
            Update file tags

            Args:
                file_id: File identifier
                tags: List of tag names
        """
        self.db.execute("DELETE FROM file_tags WHERE file_id = ?", (file_id,))

        if tags:
            self._add_tags(file_id, tags)

    def _get_tags(self, file_id):
        """
            Get tags for a file

            Args:
                file_id: File identifier

            Returns:
                List of tag names
        """
        query = 
        """
            SELECT t.tag_name
            FROM tags t
            JOIN file_tags ft ON t.tag_id = ft.tag_id
            WHERE ft.file_id = ?
        """

        rows = self.db.fetch_all(query, (file_id,))
        return [row['tag_name'] for row in rows]

    def _get_or_create_tag(self, tag_name):
        """
            Get or create a tag

            Args:
                tag_name: Tag name

            Returns:
                Tag ID
        """
        query = "SELECT tag_id FROM tags WHERE tag_name = ?"
        row = self.db.fetch_one(query, (tag_name,))

        if row:
            return row['tag_id']

        query = "INSERT INTO tags (tag_name) VALUES (?)"
        self.db.execute(query, (tag_name,))

        row = self.db.fetch_one("SELECT tag_id FROM tags WHERE tag_name = ?", (tag_name,))
        return row['tag_id']


def row_to_metadata(row, tags):
    """
        Convert db row to FileMetadata

        Args:
            row: db row dictionary
            tags: List of tag names

        Returns:
            FileMetadata object
    """
    created_at = row['created_at']
    if isinstance(created_at, str):
        created_at = datetime.fromisoformat(created_at)

    modified_at = row['modified_at']
    if isinstance(modified_at, str):
        modified_at = datetime.fromisoformat(modified_at)

    accessed_at = row['accessed_at']
    if isinstance(accessed_at, str):
        accessed_at = datetime.fromisoformat(accessed_at)

    custom_metadata = {}
    if row.get('custom_metadata'):
        try:
            custom_metadata = json.loads(row['custom_metadata'])
        except (json.JSONDecodeError, TypeError):
            custom_metadata = {}

    return FileMetadata(
        file_id=row['file_id'],
        filename=row['filename'],
        original_path=row['original_path'],
        size=row['size'],
        file_type=FileType(row['file_type']),
        mime_type=row['mime_type'],
        hash_sha256=row['hash_sha256'],
        created_at=created_at,
        modified_at=modified_at,
        accessed_at=accessed_at,
        user_id=row['user_id'],
        owner=row['owner'],
        status=FileStatus(row['status']),
        version=row['version'],
        parent_version_id=row['parent_version_id'],
        tags=tags,
        description=row['description'],
        custom_metadata=custom_metadata,
    )
