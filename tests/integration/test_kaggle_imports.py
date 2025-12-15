import os
from pathlib import Path

import pytest

from shadowbox.database.connection import DatabaseConnection
from shadowbox.core.file_manager import FileManager

from scripts.import_kaggle_datasets import import_wikibooks


@pytest.fixture
def temp_env(tmp_path):
    db_path = tmp_path / "shadowbox.db"
    storage_root = tmp_path / "storage"
    db = DatabaseConnection(str(db_path))
    db.initialize()
    fm = FileManager(str(storage_root), db_connection=db)
    return fm


@pytest.mark.integration
def test_wikibooks_import_optional(temp_env):
    dataset_var = os.getenv("SHADOWBOX_TEST_WIKIBOOKS_ZIP")
    if not dataset_var:
        pytest.skip(
            "SHADOWBOX_TEST_WIKIBOOKS_ZIP not set; skipping WikiBooks import test"
        )

    dataset_path = Path(dataset_var)
    if not dataset_path.is_file():
        pytest.skip(f"WikiBooks dataset path does not exist: {dataset_path}")

    fm = temp_env
    imported = import_wikibooks(
        sqlite_path=dataset_path,
        fm=fm,
        username="datasets",
        box_name="wikibooks-en",
        lang="en",
        batch_size=5,
        limit=10,
    )
    assert imported >= 0
