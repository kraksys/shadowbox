"""
Versioning Service
Handles the logic of snapshotting files and managing version history.
"""

from ..database.models import FileModel, FileVersionModel


class VersionManager:
    def __init__(self, db_connection):
        """Initializes the version manager."""

        self.db = db_connection
        self.file_model = FileModel(self.db)
        self.version_model = FileVersionModel(self.db)

    def create_version_snapshot(
        self, file_id: str, change_description: str = ""
    ) -> bool:
        """Takes the current state of 'files' table for file_id and archives it into 'file_versions'."""
        # 1. Get current file data directly as a row
        row = self.db.fetch_one("SELECT * FROM files WHERE file_id = ?", (file_id,))

        if not row:
            return False

        # 2. Insert into versions table
        self.version_model.create_from_file_row(row, change_description)

        return True

    def list_versions(self, file_id):
        """Return all historical versions for a given file."""

        return self.version_model.list_by_file(file_id)

    def restore_version(self, file_id: str, version_id: str):
        """
        Restores a specific version to be the active file.
        It does a database-only restore.
        It looks up requested version in file_versions
        It snapshots current files into file_versions
        it updates files to use the hash and size from the chosen historical one, and increments the version counter
        """

        version_row = self.db.fetch_one(
            "SELECT * FROM file_versions WHERE version_id = ? AND file_id = ?",
            (version_id, file_id),
        )

        if not version_row:
            return False

        current_row = self.db.fetch_one(
            "SELECT * FROM files WHERE file_id = ?",
            (file_id,),
        )

        if not current_row:
            return False

        self.version_model.create_from_file_row(
            current_row,
            "Restore Previous Version",
        )

        current_version_number = current_row.get("version", 1)
        try:
            new_version_number = int(current_version_number) + 1
        except (TypeError, ValueError):
            new_version_number = 1

        self.db.execute(
            """
            UPDATE files 
            SET 
                hash_sha256 = ?,
                size = ?,
                version = ?,
                parent_version_id = ?,
                modified_at = CURRENT_TIMESTAMP
            WHERE file_id = ?
            """,
            (
                version_row["hash_sha256"],
                version_row["size"],
                new_version_number,
                version_row["version_id"],
                file_id,
            ),
        )
        return True
