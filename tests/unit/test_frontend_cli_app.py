"""Unit tests for the ShadowBox Textual App (Frontend)."""

import pytest
from unittest.mock import Mock, MagicMock
from datetime import datetime

# Import the app and context
from shadowbox.frontend.cli.app import ShadowBoxApp, _human_size, InitialSetupModal, NewBoxModal
from shadowbox.frontend.cli.context import AppContext
from shadowbox.core.models import FileMetadata, FileStatus, Box, FileType
from textual.widgets import Static


# --- Fixtures ---

@pytest.fixture
def mock_fm():
    """Create a mock FileManager with configured user_model."""
    fm = MagicMock()
    # Default behavior: encryption enabled/disabled
    fm.encryption_enabled = False

    # IMPORTANT: Mock the user_model.get() call used in _update_status
    # This prevents the "MagicMock < int" TypeError
    fm.user_model.get.return_value = {
        "user_id": "user123",
        "username": "tester",
        "quota_bytes": 1000,
        "used_bytes": 100
    }
    return fm


@pytest.fixture
def mock_user():
    """Create a mock UserDirectory."""
    user = Mock()
    user.user_id = "user123"
    user.username = "tester"
    user.quota_bytes = 1000
    user.used_bytes = 100
    return user


@pytest.fixture
def mock_box():
    """Create a mock Box."""
    box = Mock(spec=Box)
    box.box_id = "box1"
    box.box_name = "documents"
    box.user_id = "user123"
    box.settings = {}
    return box


@pytest.fixture
def mock_context(mock_fm, mock_user, mock_box):
    """Create a mock AppContext."""
    return AppContext(
        db=MagicMock(),
        fm=mock_fm,
        user=mock_user,
        active_box=mock_box,
        first_run=False
    )


# --- Test 1: Utility Functions ---

def test_human_size_formatting():
    """Test the human readable size formatter."""
    # Logic: return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
    assert _human_size(100) == "100 B"
    assert _human_size(1024) == "1.0 KB"
    assert _human_size(1024 * 1024 * 2.5) == "2.5 MB"
    assert _human_size(1024 * 1024 * 1024) == "1.0 GB"


# --- Test 2: App Startup & Data Loading ---

@pytest.mark.asyncio
async def test_app_startup_refresh(mock_context):
    """
    Test that the app starts up and populates the lists.
    This covers refresh_boxes() and refresh_files().
    """
    # Setup Data
    box_a = Mock(box_id="b1", box_name="Box A", settings={})
    box_b = Mock(box_id="b2", box_name="Box B", settings={})
    mock_context.fm.list_user_boxes.return_value = [box_a, box_b]
    mock_context.fm.list_shared_boxes.return_value = []

    file_meta = FileMetadata(
        file_id="f1",
        box_id="b1",
        filename="test.txt",
        size=123,
        status=FileStatus.ACTIVE,
        modified_at=datetime(2023, 1, 1),
        file_type=FileType.DOCUMENT
    )
    mock_context.fm.list_box_files.return_value = [file_meta]

    # Run App Headless
    app = ShadowBoxApp(ctx=mock_context)
    async with app.run_test() as pilot:
        # Check if boxes list is populated
        boxes_list = app.query_one("#boxes")
        assert len(boxes_list.children) == 2

        # Verify the data attached to the list items (robust check)
        assert boxes_list.children[0].data.box_name == "Box A"
        assert boxes_list.children[1].data.box_name == "Box B"

        # Check if files table is populated
        table = app.query_one("#files")
        assert table.row_count == 1
        # The table row key should match the file_id
        assert app.row_keys[0] == "f1"


# --- Test 3: First Run Setup Logic ---

@pytest.mark.asyncio
async def test_first_run_triggers_modal(mock_context):
    """Test that the initial setup modal appears on first run."""
    mock_context.first_run = True
    app = ShadowBoxApp(ctx=mock_context)

    async with app.run_test() as pilot:
        # Wait a tick for the app to mount and push the screen
        await pilot.pause()

        # Assert a modal is pushed (the top of the screen stack)
        assert isinstance(app.screen, InitialSetupModal)

        # Simulate dismissing it (skipping setup) via the "Skip" button
        await pilot.click("#skip")

        # Verify app attempted to create a default box after skipping
        mock_context.fm.create_box.assert_called_with(
            user_id="user123",
            box_name="default",
            description="Default box"
        )


# --- Test 4: Modal Interactions (New Box) ---

@pytest.mark.asyncio
async def test_new_box_action(mock_context):
    """Test the New Box action and modal submission."""
    app = ShadowBoxApp(ctx=mock_context)

    async with app.run_test() as pilot:
        # Trigger the action via key binding 'n'
        await pilot.press("n")

        # Wait for modal to mount
        await pilot.pause()

        assert isinstance(app.screen, NewBoxModal)

        # Fill inputs
        app.screen.name_input.value = "MyNewBox"
        app.screen.desc_input.value = "A test box"

        # Click Create
        await pilot.click("#ok")

        # Verify FileManager call
        mock_context.fm.create_box.assert_called_with(
            user_id="user123",
            box_name="MyNewBox",
            description="A test box",
            enable_encryption=False
        )
