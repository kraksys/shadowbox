import os
from pathlib import Path

class FileManager:

    # Manages file operations within a specific isolated base directory. Ensures that all file operations are contained within this directory.

    def __init__(self, base_directory: str):
 
        # Resolve the path to get a full absolute path.
        self.base_path = Path(base_directory).resolve()
        
        # Create the directory and any parent directories if they dont exist.
        try:
            self.base_path.mkdir(parents=True, exist_ok=True)
            print(f"FileManager initialized. Managing directory: '{self.base_path}'")
        except OSError as e:
            print(f"Error creating directory {self.base_path}: {e}")
            raise
            
    def _get_safe_path(self, filename: str) -> Path:
        # Ensures the filename does not lead to path traversal outside the base directory.
        safe_path = (self.base_path / filename).resolve()
        if not str(safe_path).startswith(str(self.base_path)):
            raise ValueError("Attempted Path Traversal Detected!")
        return safe_path

        
    def write_file(self, filename: str, content: bytes):
        
        # Creates a new file or overwrites an existing one with the given content.
        try:
            file_path = self._get_safe_path(filename)
            with open(file_path, 'wb') as f: # wb for writing in binary mode
                f.write(content)
            print(f"Successfully wrote to '{filename}'")
            return True
        except (IOError, ValueError) as e:
            print(f"Error writing file '{filename}': {e}")
            return False
            
    def read_file(self, filename: str) -> bytes | None:
        
        # Reads the content of a file.
        try:
            file_path = self._get_safe_path(filename)
            if not file_path.exists():
                print(f"File '{filename}' not found.")
                return None
            
            with open(file_path, 'rb') as f: # rb for reading in binary mode
                return f.read()
        except (IOError, ValueError) as e:
            print(f"Error reading file '{filename}': {e}")

            return None
    
    def delete_file(self, filename: str) -> bool:
        
        # Deletes a file.
        try:
            file_path = self._get_safe_path(filename)
            if not file_path.exists():
                print(f"File '{filename}' not found for deletion.")
                return False
            
            file_path.unlink()
            print(f"Successfully deleted '{filename}'")
            return True
        except (IOError, ValueError) as e:
            print(f"Error deleting file '{filename}': {e}")
            return False

    def list_files(self) -> list[str]:

        # Lists all the files in the base directory.
        try:
            return [f.name for f in self.base_path.iterdir() if f.is_file()]
        except IOError as e:
            print(f"Error listing files: {e}")
            return []
    
