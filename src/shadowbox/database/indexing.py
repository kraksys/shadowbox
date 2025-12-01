from typing import Optional, List, Tuple
from .connection import DatabaseConnection

# We are creating basic index for FTS and have some helpers for re-indexing
# Use FTS5 with manual sync
# What is FTS5 ? https://www.sqlite.org/fts5.html


# create a virtual table under fts5 (done instead of the btree default engine), faster for fulltext querying
# unindexed == not tokenized
FTS_TABLE_SQL = """
    CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    file_id UNINDEXED, 
    filename,
    description,
    tags,
    custom_metadata
);
"""

FILES_AFTER_INSERT = """
    CREATE TRIGGER IF NOT EXISTS files_afteri_fts
    AFTER INSERT ON files 
    BEGIN 
        INSERT INTO files_fts (file_id, filename, description, tags, custom_metadata) 
        VALUES (
            NEW.file_id, 
            NEW.filename, 
            COALESCE(NEW.description, ''),
            '',
            COALESCE(NEW.custom_metadata, '')
        );
    END; 
"""

FILES_AFTER_UPDATE = """
    CREATE TRIGGER IF NOT EXISTS files_afteru_fts
    AFTER UPDATE ON files 
    BEGIN 
        UPDATE files_fts 
        SET 
            filename = NEW.filename, 
            description = COALESCE(NEW.description, ''),
            custom_metadata = COALESCE(NEW.custom_metadata, '')
        WHERE file_id = OLD.file_id; 
    END; 
"""

FILES_AFTER_DELETE = """
    CREATE TRIGGER IF NOT EXISTS files_afterd_fts
    AFTER DELETE ON files 
    BEGIN 
        DELETE FROM files_fts WHERE file_id = OLD.file_id;
    END;
"""

# Triggers for polymorphic tags table (entity_type = 'file')
TAGS_AFTER_INSERT = """
    CREATE TRIGGER IF NOT EXISTS tags_afteri_fts
    AFTER INSERT ON tags
    WHEN NEW.entity_type = 'file'
    BEGIN
        UPDATE files_fts
        SET tags = (
            SELECT COALESCE(GROUP_CONCAT(tag_name, ' '), '')
            FROM tags
            WHERE entity_type = 'file' AND entity_id = NEW.entity_id
        )
        WHERE file_id = NEW.entity_id;
    END;
"""

TAGS_AFTER_DELETE = """
    CREATE TRIGGER IF NOT EXISTS tags_afterd_fts
    AFTER DELETE ON tags
    WHEN OLD.entity_type = 'file'
    BEGIN
        UPDATE files_fts
        SET tags = (
            SELECT COALESCE(GROUP_CONCAT(tag_name, ' '), '')
            FROM tags
            WHERE entity_type = 'file' AND entity_id = OLD.entity_id
        )
        WHERE file_id = OLD.entity_id;
    END;
"""


def init_fts(db):
    # Create FTS table & triggers
    db.execute(FTS_TABLE_SQL)
    db.execute(FILES_AFTER_INSERT)
    db.execute(FILES_AFTER_UPDATE)
    db.execute(FILES_AFTER_DELETE)
    db.execute(TAGS_AFTER_INSERT)
    db.execute(TAGS_AFTER_DELETE)


def tags_for(db, file_id):
    # build space joined tag string from polymorphic tags table
    rows = db.fetch_all(
        """
        SELECT tag_name
        FROM tags
        WHERE entity_type = 'file' AND entity_id = ?
        """,
        (file_id,),
    )
    return " ".join(r["tag_name"] for r in rows)


def index_file(db, file_id):
    # insert or refresh one row
    row = db.fetch_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
    if not row:
        return
    tags = tags_for(db, file_id)
    db.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))
    db.execute(
        """
            INSERT INTO files_fts (file_id, filename, description, tags, custom_metadata)
            VALUES (?, ?, COALESCE(?, ''), ?, COALESCE(?, ''))
        """,
        (row["file_id"], row["filename"], row["description"], tags, row["custom_metadata"]),
    )


def remove_from_index(db, file_id):
    # remove one row
    db.execute("DELETE FROM files_fts WHERE file_id = ?", (file_id,))


def reindex_all(db):
    # rebuild all rows
    db.execute("DELETE FROM files_fts")
    rows = db.fetch_all("SELECT file_id, filename, description, custom_metadata FROM files")
    for r in rows:
        tags = tags_for(db, r["file_id"])
        db.execute(
            """
            INSERT INTO files_fts (file_id, filename, description, tags, custom_metadata)
            VALUES (?, ?, COALESCE(?, ''), ?, COALESCE(?, ''))
            """,
            (r["file_id"], r["filename"], r["description"], tags, r["custom_metadata"]),
        )
    return len(rows)
