"""
Base data models for Metadata and core file operations
"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any
import uuid


class FileType(Enum):
    # File types for classification, useful for sorting, ordering and (possibly) llm ops
    DOCUMENT = "document"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    ARCHIVE = "archive"
    CODE = "code"
    OTHER = "other"


class FileStatus(Enum):
    # What status a file has in the system, useful for versioning and other ops
    ACTIVE = "active"
    DELETED = "deleted"
    ARCHIVED = "archived"
    CORRUPTED = "corrupted"

class FileMetadata: 
    __slots__ = (
        'file_id', 
        'filename',
        'original_path',
        'size',
        'filetype',
        'mimetype',
        'hash_sha256',
        'created_at',
        'modified_at',
        'accessed_at',
        'user_id',
        'owner',
        'status',
        'version',
        'parent_version_id',
        'tags',
        'description',
        'custom_metadata'
    )

    def __init__(self, file_id=None, filename="",original_path="",size=0,filetype=None,mimetype=None,hash_sha256=None,created_at=None,modified_at=None,accessed_at=None,user_id="",owner="",status=None,version=1,parent_version_id=None,tags=None,description=None,custom_metadata=None):
        """ 
            Initialize file metadata
        """
        self.file_id = file_id if file_id is not None else str(uuid.uuid4())
        self.filename = filename 
        self.original_path = original_path 
        self.size = size 
        self.filetype = filetype if filetype is not None else FileType.OTHER 
        self.mimetype = mimetype 
        self.hash_sha256 
        self.created_at = created_at if created_at is not None else datetime.utcnow()
        self.modified_at = modified_at if modified_at is not None else datetime.utcnow() 
        self.accessed_at = accesssed_at if accessed_at is not None else datetime.utcnow()
        self.user_id = user_id
        self.owner = owner 
        self.status = status if status is not None else FileStatus.ACTIVE 
        self.version = version 
        self.parent_version_id = parent_version_id
        self.tags = tags if tags is not None else []
        self.description = description 
        self.custom_metadata = custom_metadata if custom_metadata is not None else {}

    def to_dict(self):
          """
             Convert metadata to dict
          """
          return {
              'file_id': self.file_id,
              'filename': self.filename,
              'original_path': self.original_path,
              'size': self.size,
              'file_type': self.file_type.value,
              'mime_type': self.mime_type,
              'hash_sha256': self.hash_sha256,
              'created_at': self.created_at.isoformat(),
              'modified_at': self.modified_at.isoformat(),
              'accessed_at': self.accessed_at.isoformat(),
              'user_id': self.user_id,
              'owner': self.owner,
              'status': self.status.value,
              'version': self.version,
              'parent_version_id': self.parent_version_id,
              'tags': self.tags,
              'description': self.description,
              'custom_metadata': self.custom_metadata,
          }

    def __repr__(self):
        """
            String representation 
        """
        return f"FileMetadata(file_id={self.file_id!r}, filename={self.filename!r})"

    def __eq__(self, other):
        """
            Equality comparison 
        """
        if not isinstance(other, FileMetadata):
            return NotImplemented
        return self.file_id == other.file_id

    def __hash__(self):
        """
            Hash for use in dicts
        """
        return hash(self.file_id)

    
    def create_metadata_from_dict(data):
        """
            Create file metadata from dict 
        """
        file_type_val = data.get('file_type', 'other')
        file_type = FileType(file_type_val) if isinstance(file_type_val, str) else file_type_val 
        
        status_val = data.get('status', 'active') 
        status = FileStatus(status_val) if isinstance(status_val, str) else status_val 

        created_at = None 
        if 'created_at' in data: 
            created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']

        modified_at = None 
        if 'modified_at' in data: 
            modified_at = datetime.fromisoformat(data['modified_at']) if isinstance(data['modified_at'], str) else data['modified_at'] 

        accessed_at = None 
        if 'accessed_at' in data: 
            accessed_at = datetime.fromisoformat(data['accessed_at']) if isinstance(data['accessed_at'], str) else data['accessed_at']

        return FileMetadata(
          file_id=data.get('file_id'),
          filename=data.get('filename', ''),
          original_path=data.get('original_path', ''),
          size=data.get('size', 0),
          file_type=file_type,
          mime_type=data.get('mime_type'),
          hash_sha256=data.get('hash_sha256'),
          created_at=created_at,
          modified_at=modified_at,
          accessed_at=accessed_at,
          user_id=data.get('user_id', ''),
          owner=data.get('owner', ''),
          status=status,
          version=data.get('version', 1),
          parent_version_id=data.get('parent_version_id'),
          tags=data.get('tags', []),
          description=data.get('description'),
          custom_metadata=data.get('custom_metadata', {}),
      )

class UserDirectory:
    """
        Represents a user's directory structure
    """

      __slots__ = ('user_id', 'username', 'root_path', 'created_at', 'quota_bytes', 'used_bytes')

      def __init__(self,user_id,username,root_path,created_at=None,quota_bytes=10 * 1024 * 1024 * 1024,used_bytes=0):
          """
              Initialize UserDirectory
          """
          self.user_id = user_id
          self.username = username
          self.root_path = root_path
          self.created_at = created_at if created_at is not None else datetime.utcnow()
          self.quota_bytes = quota_bytes
          self.used_bytes = used_bytes

      def get_quota_remaining(self):
          """
              Calculate remaining quota bytes 
          """
          return max(0, self.quota_bytes - self.used_bytes)

      def get_quota_percentage(self):
          """
              Calculate quota usage percentage
          """
          if self.quota_bytes == 0:
              return 100.0
          return (self.used_bytes / self.quota_bytes) * 100

      def to_dict(self):
          """
              Convert to dictionary
          """
          return {
              'user_id': self.user_id,
              'username': self.username,
              'root_path': str(self.root_path),
              'created_at': self.created_at.isoformat(),
              'quota_bytes': self.quota_bytes,
              'used_bytes': self.used_bytes,
          }

      def __repr__(self):
          """String representation."""
          return f"UserDirectory(user_id={self.user_id!r}, 
  username={self.username!r})"


class Snapshot:
    """
        Represents an immutable file snapshot
    """

    __slots__ = ('snapshot_id', 'file_id', 'user_id', 'version','hash_sha256', 'size', 'created_at', 'description','metadata')

    def __init__(self,snapshot_id,file_id,user_id,version,hash_sha256,size,created_at=None,description=None,metadata=None):
        """
            Initialize Snapshot
        """
        self.snapshot_id = snapshot_id
        self.file_id = file_id
        self.user_id = user_id
        self.version = version
        self.hash_sha256 = hash_sha256
        self.size = size
        self.created_at = created_at if created_at is not None else datetime.utcnow()
        self.description = description
        self.metadata = metadata

    def to_dict(self):
        """
            Convert snapshot to dict
        """
        return {
            'snapshot_id': self.snapshot_id,
            'file_id': self.file_id,
            'user_id': self.user_id,
            'version': self.version,
            'hash_sha256': self.hash_sha256,
            'size': self.size,
            'created_at': self.created_at.isoformat(),
            'description': self.description,
            'metadata': self.metadata,
        }


def create_snapshot_from_dict(data):
    """
        Create snapshot from dictionary
    """
    created_at = None
    if 'created_at' in data:
        created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']

    return Snapshot(
        snapshot_id=data['snapshot_id'],
        file_id=data['file_id'],
        user_id=data['user_id'],
        version=data['version'],
        hash_sha256=data['hash_sha256'],
        size=data['size'],
        created_at=created_at,
        description=data.get('description'),
        metadata=data.get('metadata'),
    )


class FileVersion:
    """
        Represents a specific version of a file
    """

    __slots__ = ('version_id', 'file_id', 'version_number', 'hash_sha256','size', 'created_at', 'created_by', 'change_description','parent_version_id', 'snapshot_id')

    def __init__(
        self,
        version_id,
        file_id,
        version_number,
        hash_sha256,
        size,
        created_at,
        created_by,
        change_description=None,
        parent_version_id=None,
        snapshot_id=None
    ):
        """
            Initialize FileVersion
        """
        self.version_id = version_id
        self.file_id = file_id
        self.version_number = version_number
        self.hash_sha256 = hash_sha256
        self.size = size
        self.created_at = created_at
        self.created_by = created_by
        self.change_description = change_description
        self.parent_version_id = parent_version_id
        self.snapshot_id = snapshot_id

    def to_dict(self):
        """
            Convert to dict
        """
        return {
            'version_id': self.version_id,
            'file_id': self.file_id,
            'version_number': self.version_number,
            'hash_sha256': self.hash_sha256,
            'size': self.size,
            'created_at': self.created_at.isoformat(),
            'created_by': self.created_by,
            'change_description': self.change_description,
            'parent_version_id': self.parent_version_id,
            'snapshot_id': self.snapshot_id,
        }


def create_version_from_dict(data):
    """
        Create FileVersion from dictionary
    """
    created_at = datetime.fromisoformat(data['created_at']) if isinstance(data['created_at'], str) else data['created_at']

    return FileVersion(
        version_id=data['version_id'],
        file_id=data['file_id'],
        version_number=data['version_number'],
        hash_sha256=data['hash_sha256'],
        size=data['size'],
        created_at=created_at,
        created_by=data['created_by'],
        change_description=data.get('change_description'),
        parent_version_id=data.get('parent_version_id'),
        snapshot_id=data.get('snapshot_id'),
    )


class DuplicateGroup:
    """
        Represents a group of duplicate files
    """

    __slots__ = ('hash_sha256', 'file_count', 'total_size','potential_savings', 'file_ids', 'file_paths')

    def __init__(self, hash_sha256, file_count, total_size, potential_savings, file_ids, file_paths):
        """
            Initialize DuplicateGroup
        """
        self.hash_sha256 = hash_sha256
        self.file_count = file_count
        self.total_size = total_size
        self.potential_savings = potential_savings
        self.file_ids = file_ids
        self.file_paths = file_paths

    def to_dict(self):
        """
            Convert to dictionary
        """
        return {
            'hash': self.hash_sha256,
            'file_count': self.file_count,
            'total_size': self.total_size,
            'potential_savings': self.potential_savings,
            'file_ids': self.file_ids,
            'file_paths': [str(p) for p in self.file_paths],
        }


class SearchResult:
    """
        Represents a search result with relevance score
    """

    __slots__ = ('file_metadata', 'relevance_score', 'matched_fields', 'snippet')

    def __init__(self, file_metadata, relevance_score, matched_fields, snippet=None):
        """
            Initialize SearchResult
        """
        self.file_metadata = file_metadata
        self.relevance_score = relevance_score
        self.matched_fields = matched_fields
        self.snippet = snippet

    def to_dict(self):
        """
            Convert to dictionary
        """
        return {
            'file_metadata': self.file_metadata.to_dict(),
            'relevance_score': self.relevance_score,
            'matched_fields': self.matched_fields,
            'snippet': self.snippet,
        }
