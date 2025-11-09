"""SQLite schema definitions for ShadowBox."""

# SQL schema definitions
SCHEMA_VERSION = 1

CREATE_TABLES = [
    # Users table
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        quota_bytes INTEGER DEFAULT 10737418240,
        used_bytes INTEGER DEFAULT 0,
        settings TEXT
    )
    """,
    # Boxes table - this is the main logic behind "shadowBox", how we use isolated containers for data storage and sharing
    """
    CREATE TABLE IF NOT EXISTS boxes (
        box_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        box_name TEXT NOT NULL,
        description TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_shared BOOLEAN DEFAULT FALSE, 
        share_token TEXT UNIQUE,
        settings TEXT, 
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        UNIQUE(user_id, box_name)
    )
    """,
    # Box Shares table - this is used to share boxes, and their permissions
    """
    CREATE TABLE IF NOT EXISTS box_shares (
        share_id TEXT PRIMARY KEY,
        box_id TEXT NOT NULL,
        shared_by_user_id TEXT NOT NULL,
        shared_with_user_id TEXT NOT NULL,
        permission_level TEXT DEFAULT 'read', -- 'read', 'write', 'admin'
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP,
        access_token TEXT UNIQUE,
        FOREIGN KEY (box_id) REFERENCES boxes(box_id) ON DELETE CASCADE,
        FOREIGN KEY (shared_by_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (shared_with_user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        UNIQUE(box_id, shared_with_user_id)
    )
    """,
    # Files table
    """
    CREATE TABLE IF NOT EXISTS files (
        file_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        box_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        original_path TEXT,
        size INTEGER NOT NULL,
        file_type TEXT NOT NULL,
        mime_type TEXT,
        hash_sha256 TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        modified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        accessed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        owner TEXT NOT NULL,
        status TEXT DEFAULT 'active',
        version INTEGER DEFAULT 1,
        parent_version_id TEXT,
        description TEXT,
        custom_metadata TEXT,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (box_id) REFERENCES boxes(box_id) ON DELETE CASCADE 
    )
    """,
    # File versions table
    """
    CREATE TABLE IF NOT EXISTS file_versions (
        version_id TEXT PRIMARY KEY,
        file_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        box_id TEXT NOT NULL,
        version_number INTEGER NOT NULL,
        hash_sha256 TEXT NOT NULL,
        size INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_by TEXT NOT NULL,
        change_description TEXT,
        parent_version_id TEXT,
        FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
        FOREIGN KEY (box_id) REFERENCES boxes(box_id) ON DELETE CASCADE,
        UNIQUE(file_id, version_number)
    )
    """,
    # Tags table
    """
    CREATE TABLE IF NOT EXISTS tags (
        tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
        tag_name TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # File-tag association table
    """
    CREATE TABLE IF NOT EXISTS file_tags (
        file_id TEXT NOT NULL,
        tag_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (file_id, tag_id),
        FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE,
        FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
    )
    """,
    # Deduplication table,
    # if multiple users upload same file (same hash) with different filenames, it gets tracked to avoid duplication occurrences
    """
    CREATE TABLE IF NOT EXISTS deduplication (
        hash_sha256 TEXT PRIMARY KEY,
        reference_count INTEGER DEFAULT 1,
        size INTEGER NOT NULL,
        storage_path TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    # Schema version table
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
]

# Index definitions for optimization
CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_files_user_id ON files(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash_sha256)",
    "CREATE INDEX IF NOT EXISTS idx_files_status ON files(status)",
    "CREATE INDEX IF NOT EXISTS idx_files_created_at ON files(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_files_modified_at ON files(modified_at)",
    "CREATE INDEX IF NOT EXISTS idx_files_filename ON files(filename)",
    "CREATE INDEX IF NOT EXISTS idx_file_versions_file_id ON file_versions(file_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_versions_user_id ON file_versions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_tags_file_id ON file_tags(file_id)",
    "CREATE INDEX IF NOT EXISTS idx_file_tags_tag_id ON file_tags(tag_id)",
    "CREATE INDEX IF NOT EXISTS idx_boxes_user_id ON boxes(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_boxes_share_token ON boxes(share_token)",
    "CREATE INDEX IF NOT EXISTS idx_box_shares_box_id ON box_shares(box_id)",
    "CREATE INDEX IF NOT EXISTS idx_box_shares_shared_with ON box_shares(shared_with_user_id)",
    "CREATE INDEX IF NOT EXISTS idx_box_shares_access_token ON box_shares(access_token)",
    "CREATE INDEX IF NOT EXISTS idx_files_box ON files(box_id)",
]

# Triggers for automatic timestamp updates
CREATE_TRIGGERS = [
    """
    CREATE TRIGGER IF NOT EXISTS update_users_timestamp
    AFTER UPDATE ON users
    FOR EACH ROW
    BEGIN
        UPDATE users SET updated_at = CURRENT_TIMESTAMP
        WHERE user_id = NEW.user_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS update_files_timestamp
    AFTER UPDATE ON files
    FOR EACH ROW
    BEGIN
        UPDATE files SET modified_at = CURRENT_TIMESTAMP
        WHERE file_id = NEW.file_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS update_boxes_timestamp
    AFTER UPDATE ON boxes 
    FOR EACH ROW 
    BEGIN 
        UPDATE boxes SET updated_at = CURRENT_TIMESTAMP
        WHERE box_id = NEW.box_id;
    END
    """,
]


def get_init_schema():
    """
    Get complete schema initialization SQL

    Returns:
        List of SQL statements to execute
    """
    statements = []
    statements.extend(CREATE_TABLES)
    statements.extend(CREATE_INDEXES)
    statements.extend(CREATE_TRIGGERS)
    statements.append(
        f"INSERT OR IGNORE INTO schema_version (version) VALUES ({SCHEMA_VERSION})"
    )
    return statements


def get_drop_schema():
    """
    Get SQL statements to drop all tables for testing

    Returns:
        List of DROP TABLE statements
    """
    return [
        "DROP TABLE IF EXISTS file_tags",
        "DROP TABLE IF EXISTS tags",
        "DROP TABLE IF EXISTS box_shares",
        "DROP TABLE IF EXISTS file_versions",
        "DROP TABLE IF EXISTS files",
        "DROP TABLE IF EXISTS deduplication",
        "DROP TABLE IF EXISTS users",
        "DROP TABLE IF EXISTS boxes",
        "DROP TABLE IF EXISTS schema_version",
    ]
