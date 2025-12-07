"""
Helpers for importing Kaggle WikiBooks datasets into ShadowBox.

The main entry point is :func:`import_wikibooks`, which reads real
WikiBooks data from a Kaggle SQLite (or .zip containing that SQLite)
and imports a subset into a ShadowBox box via :class:`FileManager`.

This file also exposes a small CLI so you can run:

    uv run scripts/import_kaggle_datasets.py /path/to/wikibooks.sqlite --limit 50
"""

from __future__ import annotations

import argparse
import sqlite3
import zipfile
from pathlib import Path
from typing import List, Optional, Tuple

from shadowbox.core.file_manager import FileManager


def _ensure_user_and_box(
    fm: FileManager,
    username: str,
    box_name: str,
    description: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Ensure the given user and box exist, creating them if needed.

    Returns:
        (user_id, box_id)
    """
    # Ensure user
    user = fm.user_model.get_by_username(username)
    if user is None:
        user_dir = fm.create_user(username)
        user_id = user_dir.user_id
    else:
        user_id = user["user_id"]

    # Ensure box
    existing_boxes = fm.box_model.list_by_user(user_id)
    box = None
    for row in existing_boxes:
        if row["box_name"] == box_name:
            box = fm.get_box(row["box_id"])
            break

    if box is None:
        box = fm.create_box(
            user_id=user_id,
            box_name=box_name,
            description=description,
        )

    return user_id, box.box_id


def _resolve_sqlite_path(dataset_path: Path, tmp_dir: Path) -> Path:
    """
    Resolve a Kaggle WikiBooks dataset path to a concrete SQLite file.

    Supports:
    - Direct `.sqlite` path
    - `.zip` containing a `*.sqlite` member (e.g. wikibooks.sqlite)
    """
    if not dataset_path.is_file():
        raise FileNotFoundError(f"Dataset file not found: {dataset_path}")

    suffix = dataset_path.suffix.lower()
    if suffix == ".sqlite":
        return dataset_path

    if suffix == ".zip":
        tmp_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(dataset_path, "r") as zf:
            members = [m for m in zf.namelist() if m.lower().endswith(".sqlite")]
            if not members:
                raise ValueError(
                    f"No .sqlite file found inside zip archive: {dataset_path}"
                )

            member = members[0]
            dest = tmp_dir / Path(member).name
            if not dest.exists():
                zf.extract(member, tmp_dir)
                extracted = tmp_dir / member
                if extracted != dest:
                    extracted.rename(dest)
            return dest

    raise ValueError(
        f"Unsupported dataset extension for WikiBooks import: {dataset_path.suffix}"
    )


def _iter_wikibooks_rows(sqlite_path: Path, lang: str, limit: int):
    """
    Yield rows from the WikiBooks SQLite for a given language table.

    Each row is a sqlite3.Row with at least:
        title, url, abstract, body_text
    """
    if not lang.isalpha():
        raise ValueError(f"Invalid language table name: {lang!r}")

    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        # Validate table existence
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (lang,)
        )
        if cur.fetchone() is None:
            raise ValueError(
                f"Language table '{lang}' not found in {sqlite_path.name}"
            )

        cur.execute(
            f"SELECT title, url, abstract, body_text FROM {lang} LIMIT ?",
            (int(limit),),
        )
        for row in cur:
            yield row
    finally:
        conn.close()


def import_wikibooks(
    sqlite_path: Path | str,
    fm: FileManager,
    username: str = "datasets",
    box_name: str = "wikibooks-en",
    lang: str = "en",
    batch_size: int = 5,
    limit: Optional[int] = None,
) -> int:
    """
    Import a subset of a local WikiBooks Kaggle dataset into ShadowBox.

    Args:
        sqlite_path: Path to the local dataset file (zip or .sqlite).
        fm: An initialized FileManager instance.
        username: Username for the dataset owner.
        box_name: Name of the box that will contain the imported files.
        lang: Language code / table name in the dataset (e.g. 'en').
        batch_size: Default batch size if limit is not provided.
        limit: Maximum number of files to create; if None or <= 0,
            falls back to ``batch_size``.

    Returns:
        Number of files successfully imported.
    """
    dataset_path = Path(sqlite_path)

    if limit is None or limit <= 0:
        limit = batch_size

    # Place temporary artifacts within the FileManager's storage root
    tmp_dir = Path(fm.storage_root) / "_kaggle_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    sqlite_file = _resolve_sqlite_path(dataset_path, tmp_dir)

    user_id, box_id = _ensure_user_and_box(
        fm,
        username=username,
        box_name=box_name,
        description=f"Imported WikiBooks dataset ({lang}) from {dataset_path.name}",
    )

    paths: List[str] = []
    for idx, row in enumerate(_iter_wikibooks_rows(sqlite_file, lang, limit), start=1):
        title = row["title"] or f"Untitled {lang} #{idx}"
        url = row["url"] or ""
        abstract = row["abstract"] or ""
        body_text = row["body_text"] or ""

        lines: List[str] = [title]
        if url:
            lines.append("")
            lines.append(url)
        if abstract:
            lines.append("")
            lines.append(abstract)
        if body_text:
            lines.append("")
            lines.append(body_text)

        content = "\n".join(lines)
        fname = f"wikibook_{lang}_{idx}.txt"
        fpath = tmp_dir / fname
        fpath.write_text(content, encoding="utf-8")
        paths.append(str(fpath))

    if not paths:
        return 0

    result = fm.add_files_bulk(
        user_id=user_id,
        box_id=box_id,
        file_paths=paths,
        tags=["wikibooks", lang],
        encrypt=None,
    )
    return len(result["success"])


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import Kaggle WikiBooks dataset into a ShadowBox box."
    )
    parser.add_argument(
        "dataset",
        help="Path to wikibooks.sqlite or wikibooks.zip",
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default="shadowbox.db",
        help="Path to ShadowBox SQLite database (default: shadowbox.db)",
    )
    parser.add_argument(
        "--storage-root",
        default="storage",
        help="Storage root directory (default: storage)",
    )
    parser.add_argument(
        "--lang",
        default="en",
        help="Language table code to import (default: en)",
    )
    parser.add_argument(
        "--username",
        default="datasets",
        help="Username that will own the imported box (default: datasets)",
    )
    parser.add_argument(
        "--box-name",
        default=None,
        help="Box name to import into (default: wikibooks-<lang>)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Default batch size if limit is not provided (default: 100)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of entries to import (default: batch-size)",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> None:
    from shadowbox.database.connection import DatabaseConnection

    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    db = DatabaseConnection(str(args.db_path))
    db.initialize()

    fm = FileManager(str(args.storage_root), db_connection=db)

    box_name = args.box_name or f"wikibooks-{args.lang}"
    imported = import_wikibooks(
        sqlite_path=args.dataset,
        fm=fm,
        username=args.username,
        box_name=box_name,
        lang=args.lang,
        batch_size=args.batch_size,
        limit=args.limit,
    )

    print(
        f"Imported {imported} entries into box '{box_name}' "
        f"for user '{args.username}'."
    )


if __name__ == "__main__":  # pragma: no cover - CLI entry
    main()
