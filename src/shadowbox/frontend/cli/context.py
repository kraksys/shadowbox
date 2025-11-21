"""Small helper to build a ShadowBox app context for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import getpass

from shadowbox.database.connection import DatabaseConnection
from shadowbox.core.file_manager import FileManager
from shadowbox.core.models import UserDirectory, Box


@dataclass
class AppContext:
    """Container for runtime objects the UI needs."""

    db: DatabaseConnection
    fm: FileManager
    user: UserDirectory
    active_box: Box


def _user_from_row(fm: FileManager, row: dict) -> UserDirectory:
    # Rehydrate an existing user row into a UserDirectory instance.
    return UserDirectory(
        user_id=row["user_id"],
        username=row["username"],
        root_path=str(Path(fm.storage_root) / row["user_id"]),
        quota_bytes=row.get("quota_bytes", 0),
        used_bytes=row.get("used_bytes", 0),
    )


def build_context(
    db_path: str | Path = "./shadowbox.db",
    storage_root: Optional[str | Path] = None,
    username: Optional[str] = None,
) -> AppContext:
    """Initialize DB + FileManager and ensure a user and default box exist."""

    db = DatabaseConnection(str(db_path))
    db.initialize()

    fm = FileManager(storage_root=str(storage_root or Path.home() / ".shdwbox"), db_connection=db)

    uname = username or getpass.getuser()
    existing = fm.user_model.get_by_username(uname)
    if existing:
        user = _user_from_row(fm, existing)
    else:
        user = fm.create_user(uname)

    # Ensure there is at least one box; prefer a box named "default".
    boxes = fm.list_user_boxes(user.user_id) or []
    default_box = None
    for box in boxes:
        if box.box_name == "default":
            default_box = box
            break
    if default_box is None:
        default_box = fm.create_box(user.user_id, "default", description="Default box")

    return AppContext(db=db, fm=fm, user=user, active_box=default_box)
