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
       
        # CREATE or UPDATE Operation
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