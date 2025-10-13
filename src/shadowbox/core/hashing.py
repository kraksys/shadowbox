""" Utility for file hashing operations. """

import hashlib
from pathlib import Path


CHUNK_SIZE = 65536  # 64KB

def calculate_sha256(file_path: Path) -> str:
    
    # Calculates the SHA-256 hash of a file.

    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(CHUNK_SIZE)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()
