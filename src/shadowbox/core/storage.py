"""
Storage module with box encryption support

Structure Map for reference:
==============================
 - <storage_root>/
      - keys/
          - master.key
          - box_keys/
              - {box_id}.key
      - {user_id}/
          - boxes/
              - {box_id}/
                  - metadata.json (may be encrypted)
                  - settings.json
                  - blobs/
                      - {sha256} (plain)
                      - {sha256}.enc (encrypted)
==============================
For reference:
> Files are stored as blobs => Files are not actual files / filetypes, but validated as bytes and their hash signature
> This allows any type of file storage and idempotent retrieval, without the hassle of supporting specific file types or adjustments to those.
> The module defines all file operations for boxes and their files

Both encrypted and non-encrypted ops are permitted.

If we add encryption we also have the following:
> Per-box encryption with separate keys
> Encrypted metadata
> Physical isolation
> Clean deletion --> remove box = remove all encrypted data

Encryption can be plugged in, as soon as it gets developed by Security (under security/)

"""

from pathlib import Path
import shutil
import json
from typing import Optional, Dict, Any
from .hashing import calculate_sha256, calculate_sha256_bytes
from datetime import datetime
from ..security.encryption import BoxEncryptionBackend


class Storage:
    """Storage with optional per-box encryption support"""

    def __init__(self, root_path: Optional[str] = None):
        self.root = (
            Path(root_path).expanduser() if root_path else Path.home() / ".shdwbox"
        )
        self.root.mkdir(parents=True, exist_ok=True)
        self.encrypt: Optional[BoxEncryptionBackend] = None

    def setup_master_key(self, password: str) -> None:
        if self.encrypt is None:
            self.encrypt = BoxEncryptionBackend(self.root)
        self.encrypt.setup_master_key(password)

    def user_root(self, user_id: str) -> Path:
        return self.root / user_id

    def box_root(self, user_id: str, box_id: str) -> Path:
        return self.user_root(user_id) / "boxes" / box_id

    def blob_root(self, user_id: str, box_id: str) -> Path:
        return self.box_root(user_id, box_id) / "blobs"

    def metadata_path(self, user_id: str, box_id: str) -> Path:
        return self.box_root(user_id, box_id) / "metadata.json"

    def index_path(self, user_id: str, box_id: str) -> Path:
        return self.box_root(user_id, box_id) / "index.db"

    def box_settings_path(self, user_id: str, box_id: str) -> Path:
        return self.box_root(user_id, box_id) / "settings.json"

    def ensure_user(self, user_id: str) -> Path:
        u = self.user_root(user_id)
        u.mkdir(parents=True, exist_ok=True)
        return u

    def ensure_box(self, user_id: str, box_id: str) -> Path:
        self.ensure_user(user_id)
        box_path = self.box_root(user_id, box_id)
        blob_path = self.blob_root(user_id, box_id)
        box_path.mkdir(parents=True, exist_ok=True)
        blob_path.mkdir(parents=True, exist_ok=True)
        return box_path

    def load_metadata(self, user_id: str, box_id: str) -> Dict[str, Any]:
        p = self.metadata_path(user_id, box_id)
        if not p.exists():
            return {
                "box_id": box_id,
                "created_at": datetime.utcnow().isoformat(),
                "files": {},
            }
        with open(p, "rb") as f:
            raw = f.read()
        if self.encrypt and self.is_box_encryption_enabled(user_id, box_id):
            try:
                return self.encrypt.decrypt_json(raw, box_id)
            except Exception:
                return {"box_id": box_id, "created_at": None, "files": {}}
        try:
            return json.loads(raw.decode())
        except Exception:
            return {"box_id": box_id, "created_at": None, "files": {}}

    def save_metadata(
        self, user_id: str, box_id: str, metadata: Dict[str, Any]
    ) -> None:
        p = self.metadata_path(user_id, box_id)
        if self.encrypt and self.is_box_encryption_enabled(user_id, box_id):
            blob = self.encrypt.encrypt_json(metadata, box_id)
            with open(p, "wb") as f:
                f.write(blob)
        else:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False)

    def load_box_settings(self, user_id: str, box_id: str) -> Dict[str, Any]:
        p = self.box_settings_path(user_id, box_id)
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def save_box_settings(
        self, user_id: str, box_id: str, settings: Dict[str, Any]
    ) -> None:
        p = self.box_settings_path(user_id, box_id)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False)

    def set_box_encryption_enabled(
        self, user_id: str, box_id: str, enabled: bool
    ) -> None:
        settings = self.load_box_settings(user_id, box_id)
        settings["encryption_enabled"] = bool(enabled)
        self.save_box_settings(user_id, box_id, settings)

    def is_box_encryption_enabled(self, user_id: str, box_id: str) -> bool:
        settings = self.load_box_settings(user_id, box_id)
        if isinstance(settings.get("encryption_enabled"), bool):
            return settings["encryption_enabled"]
        if self.encrypt is None:
            return False
        box_key_path = self.root / "keys" / "box_keys" / f"{box_id}.key"
        return box_key_path.exists()

    def put_encrypted(
        self, user_id: str, box_id: str, source_path: str
    ) -> Dict[str, Any]:
        if not self.encrypt:
            raise RuntimeError("Encryption backend not configured")
        self.ensure_box(user_id, box_id)
        src = Path(source_path).expanduser()
        with open(src, "rb") as f:
            original_data = f.read()
        file_hash = calculate_sha256(src)
        blob = self.encrypt.encrypt_bytes(original_data, box_id)
        destination = self.blob_root(user_id, box_id) / f"{file_hash}.enc"
        with open(destination, "wb") as f:
            f.write(blob)
        self.set_box_encryption_enabled(user_id, box_id, True)
        self.update_box_metadata(
            user_id,
            box_id,
            file_hash,
            {
                "original_name": src.name,
                "size": len(original_data),
                "encrypted": True,
                "encrypted_size": len(blob),
                "added_at": datetime.utcnow().isoformat(),
            },
        )
        return {
            "hash": file_hash,
            "size": len(original_data),
            "encrypted_path": str(destination),
        }

    def get_encrypted(
        self, user_id: str, box_id: str, file_hash: str, destination_path: str
    ) -> str:
        if not self.encrypt:
            raise RuntimeError("Encryption backend not configured")
        encrypted_path = self.blob_root(user_id, box_id) / f"{file_hash}.enc"
        if not encrypted_path.exists():
            raise FileNotFoundError(
                f"Encrypted file {file_hash} not found in box {box_id}"
            )
        with open(encrypted_path, "rb") as f:
            blob = f.read()
        data = self.encrypt.decrypt_bytes(blob, box_id)
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with open(destination, "wb") as f:
            f.write(data)
        return str(destination)

    def update_box_metadata(
        self, user_id: str, box_id: str, file_hash: str, file_info: dict
    ) -> None:
        metadata = self.load_metadata(user_id, box_id)
        if not metadata.get("created_at"):
            metadata["created_at"] = datetime.utcnow().isoformat()
        metadata.setdefault("files", {})
        metadata["files"][file_hash] = file_info
        metadata["updated_at"] = datetime.utcnow().isoformat()
        self.save_metadata(user_id, box_id, metadata)

    def has_encrypted(self, user_id: str, box_id: str, file_hash: str) -> bool:
        encrypted_filename = f"{file_hash}.enc"
        encrypted_path = self.blob_root(user_id, box_id) / encrypted_filename
        return encrypted_path.exists()

    def verify_encrypted(self, user_id: str, box_id: str, file_hash: str) -> bool:
        try:
            encrypted_filename = f"{file_hash}.enc"
            encrypted_path = self.blob_root(user_id, box_id) / encrypted_filename

            if not encrypted_path.exists():
                return False

            with open(encrypted_path, "rb") as f:
                blob = f.read()

            if not self.encrypt:
                return False

            decrypted_data = self.encrypt.decrypt_bytes(blob, box_id)
            return calculate_sha256_bytes(decrypted_data) == file_hash

        except Exception:
            return False

    def delete_encrypted(self, user_id: str, box_id: str, file_hash: str) -> bool:
        encrypted_filename = f"{file_hash}.enc"
        encrypted_path = self.blob_root(user_id, box_id) / encrypted_filename

        if encrypted_path.exists():
            encrypted_path.unlink()

            try:
                metadata = self.load_metadata(user_id, box_id)
                if file_hash in metadata.get("files", {}):
                    del metadata["files"][file_hash]
                    metadata["updated_at"] = datetime.utcnow().isoformat()
                    self.save_metadata(user_id, box_id, metadata)
            except Exception:
                pass

            return True
        return False

    def list_encrypted_files(self, user_id: str, box_id: str) -> dict[str, dict]:
        metadata = self.load_metadata(user_id, box_id)
        files = metadata.get("files", {})
        return {h: info for h, info in files.items() if info.get("encrypted", False)}

    def get_box_info(self, user_id: str, box_id: str) -> dict[str, Any]:
        metadata = self.load_metadata(user_id, box_id)
        files = metadata.get("files", {})
        total_size = sum(file_info.get("size", 0) for file_info in files.values())
        return {
            "box_id": box_id,
            "created_at": metadata.get("created_at"),
            "updated_at": metadata.get("updated_at"),
            "file_count": len(files),
            "total_size": total_size,
        }

    # Unencrypted operations for per-box storage
    def put(self, user_id: str, box_id: str, source_path: str) -> dict[str, Any]:
        self.ensure_box(user_id, box_id)
        src = Path(source_path).expanduser()
        hash_hex = calculate_sha256(src)
        destination = self.blob_root(user_id, box_id) / hash_hex
        if not destination.exists():
            shutil.copy2(src, destination)
        size = src.stat().st_size
        self.update_box_metadata(
            user_id,
            box_id,
            hash_hex,
            {
                "original_name": src.name,
                "size": size,
                "encrypted": False,
                "added_at": datetime.utcnow().isoformat(),
            },
        )
        return {"hash": hash_hex, "size": size, "path": str(destination)}

    def get(
        self, user_id: str, box_id: str, hash_hex: str, destination_path: str
    ) -> str:
        src = self.blob_root(user_id, box_id) / hash_hex
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, destination)
        return str(destination)

    def has(self, user_id: str, box_id: str, hash_hex: str) -> bool:
        return (self.blob_root(user_id, box_id) / hash_hex).exists()

    def verify(self, user_id: str, box_id: str, hash_hex: str) -> bool:
        path = self.blob_root(user_id, box_id) / hash_hex
        if not path.exists():
            return False
        return calculate_sha256(path) == hash_hex
