"""
Versioning Service
Handles the logic of snapshotting files and managing version history.
"""
from ..database.models import FileModel, FileVersionModel

class VersionManager:
    def __init__(self, db_connection):
        self.db = db_connection
        self.file_model = FileModel(self.db)
        self.version_model = FileVersionModel(self.db)

    def create_version_snapshot(self, file_id: str, change_description: str = "") -> bool:
        """ Takes the current state of 'files' table for file_id and archives it into 'file_versions'."""
        # 1. Get current file data directly as a row
        row = self.db.fetch_one("SELECT * FROM files WHERE file_id = ?", (file_id,))
        
        if not row:
            return False

        # 2. Insert into versions table
        self.version_model.create_from_file_row(row, change_description)
        
        return True

    def restore_version(self, file_id: str, version_id: str):
        """ Restores a specific version to be the active file. (This would involve swapping the current file hash with the versioned hash) """
        #Uncertain if this will be implemented yet. Not like we need it.
        pass
