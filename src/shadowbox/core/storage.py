from pathlib import Path
import shutil
from .hashing import calculate_sha256


class Storage:
    # content addressed storage under user root
    def __init__(self, root_path=None):
        self.root = Path(root_path).expanduser() if root_path else Path.home() / ".shdwbox"
        self.root.mkdir(parents=True, exist_ok=True)

    def user_root(self, user_id):

        return self.root / user_id

    def ensure_user(self, user_id):
        # ensure user dirs exist
        u = self.user_root(user_id)
        (u / "blobs").mkdir(parents=True, exist_ok=True)
        return u

    def blob_path(self, user_id, hash_hex):
        # path to blob by hash
        return self.user_root(user_id) / "blobs" / hash_hex

    def put(self, user_id, source_path):
        # store file by content hash
        self.ensure_user(user_id)
        src = Path(source_path).expanduser()
        hash_hex = calculate_sha256(src)
        destination = self.blob_path(user_id, hash_hex)
        if not destination.exists():
            shutil.copy2(src, destination)
        size = src.stat().st_size
        return {"hash": hash_hex, "size": size, "path": str(destination)}

    def has(self, user_id, hash_hex):
        # check blob existence
        return self.blob_path(user_id, hash_hex).exists()

    def verify(self, user_id, hash_hex):
        # verify blob content
        path = self.blob_path(user_id, hash_hex)
        if not path.exists():
            return False
        return calculate_sha256(path) == hash_hex

    def read(self, user_id, hash_hex, destination_path):
        # copy blob to destination
        src = self.blob_path(user_id, hash_hex)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, destination)
        return str(destination)
