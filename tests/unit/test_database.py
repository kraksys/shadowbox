"""Unit tests covering ``DatabaseConnection`` and database models."""

import tempfile

# from datetime import datetime
from pathlib import Path
from typing import Dict, Generator

import pytest

# from shadowbox.core.models import Box, BoxShare, FileMetadata, FileStatus, FileType
from shadowbox.database.connection import DatabaseConnection
from shadowbox.database.models import (  # row_to_metadata,
    BoxModel,
    BoxShareModel,
    FileModel,
    UserModel,
)
from shadowbox.database.schema import SCHEMA_VERSION, get_drop_schema


@pytest.fixture()
def temp_db() -> Generator[DatabaseConnection, None, None]:
    """Provide a temporary, initialized ``DatabaseConnection`` instance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "shadowbox.db"
        db = DatabaseConnection(db_path)
        db.initialize()
        try:
            yield db
        finally:
            db.close()


@pytest.fixture()
def models(temp_db: DatabaseConnection) -> Dict[str, object]:
    """Return initialized model helpers for database testing."""
    return {
        "db": temp_db,
        "users": UserModel(temp_db),
        "boxes": BoxModel(temp_db),
        "files": FileModel(temp_db),
        "shares": BoxShareModel(temp_db),
    }


def test_initialize_is_idempotent(temp_db: DatabaseConnection) -> None:
    """Ensure schema initialization can be invoked multiple times safely."""
    temp_db.initialize()
    assert temp_db.get_version() == SCHEMA_VERSION

    for statement in get_drop_schema():
        temp_db.execute(statement)

    assert temp_db.get_version() == 0
