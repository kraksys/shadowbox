"""Small helper to build a ShadowBox app context for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import getpass
import os

from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.indexing import init_fts
from shadowbox.core.file_manager import FileManager
from shadowbox.core.models import UserDirectory, Box


@dataclass
class AppContext:
    """Container for runtime objects the UI needs."""

    db: DatabaseConnection
    fm: FileManager
    user: UserDirectory
    active_box: Box | None
    first_run: bool = False


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
    """
    Initialize DB + FileManager and ensure a user exists.

    Encryption behaviour for the TUI:

    - By default, the Textual frontend starts with encryption disabled to
      mirror a simple, out-of-the-box setup.
    - If the environment variable ``SHADOWBOX_MASTER_PASSWORD`` is set,
      the FileManager is created with ``enable_encryption=True`` and the
      provided password. This makes the encryption toggle in the UI active
      and will cause boxes/files created with the "encrypt" options to be
      stored using the encryption backend in ``shadowbox.security.encryption``.

    First-run behaviour:

    - When the database file does not exist yet, this function returns an
      AppContext with ``first_run=True`` and does not create a default box.
      The UI can then prompt the user for their initial box name and optional
      master key.
    """

    db_path = Path(db_path)
    first_run = not db_path.exists()

    db = DatabaseConnection(str(db_path))
    db.initialize()

    # Ensure FTS tables/triggers exist for search flow; ignore if already present.
    try:
        init_fts(db)
    except Exception:
        # FTS setup is best-effort; failures should not prevent basic usage.
        pass

    # Optional encryption for the TUI: driven by environment variables so
    # developers can opt-in without additional prompts inside the UI.
    master_password = os.getenv("SHADOWBOX_MASTER_PASSWORD")
    if master_password:
        fm = FileManager(
            storage_root=str(storage_root or Path.home() / ".shdwbox"),
            db_connection=db,
            enable_encryption=True,
            master_password=master_password,
        )
    else:
        fm = FileManager(
            storage_root=str(storage_root or Path.home() / ".shdwbox"),
            db_connection=db,
        )

    uname = username or getpass.getuser()
    existing = fm.user_model.get_by_username(uname)
    if existing:
        user = _user_from_row(fm, existing)
    else:
        user = fm.create_user(uname)

    # For existing DBs, ensure there is at least one box and prefer "default".
    # For first-run (new DB file), we leave box creation to the UI so it can
    # prompt the user for an initial box name.
    active_box: Box | None = None
    if not first_run:
        boxes = fm.list_user_boxes(user.user_id) or []
        default_box = None
        for box in boxes:
            if box.box_name == "default":
                default_box = box
                break
        if default_box is None:
            if boxes:
                default_box = boxes[0]
            else:
                default_box = fm.create_box(
                    user.user_id, "default", description="Default box"
                )
        active_box = default_box

    return AppContext(db=db, fm=fm, user=user, active_box=active_box, first_run=first_run)
