"""Unit tests for the network adapter module."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from shadowbox.network import adapter
from shadowbox.core.models import FileType

# --- Fixtures ---

@pytest.fixture
def mock_env(tmp_path):
    """Create a mock environment dict."""
    db = MagicMock()
    storage = MagicMock()
    storage.user_root.return_value = tmp_path / "u1"
    storage.box_root.return_value = tmp_path / "u1" / "boxes" / "b1"
    storage.blob_root.return_value = tmp_path / "u1" / "boxes" / "b1" / "blobs"
    
    return {
        "db": db,
        "storage": storage,
        "username": "tester",
        "user_id": "u1",
        "box_id": "b1"
    }

# --- Tests ---

def test_init_env_defaults():
    """Test environment initialization."""
    with patch("shadowbox.network.adapter.DatabaseConnection"), \
         patch("shadowbox.network.adapter.Storage"), \
         patch("shadowbox.network.adapter.UserModel") as MockUserModel, \
         patch("shadowbox.network.adapter.BoxModel") as MockBoxModel:
        
        um = MockUserModel.return_value
        um.get_by_username.return_value = None
        
        bm = MockBoxModel.return_value
        bm.list_by_user.return_value = []
        
        env = adapter.init_env(username="newuser")
        
        assert env["username"] == "newuser"
        assert "db" in env
        assert "storage" in env
        um.create.assert_called()

def test_select_box_success(mock_env):
    """Test selecting a box owned by self."""
    with patch("shadowbox.network.adapter.UserModel") as MockUserModel, \
         patch("shadowbox.network.adapter.BoxModel") as MockBoxModel:
        
        um = MockUserModel.return_value
        um.get_by_username.return_value = {"user_id": "u1", "username": "tester"}
        
        bm = MockBoxModel.return_value
        bm.list_by_user.return_value = [
            {"box_id": "b_new", "box_name": "mybox", "user_id": "u1"}
        ]
        bm.get.return_value = {"box_id": "b_new", "user_id": "u1"}
        
        result = adapter.select_box(mock_env, "mybox")
        
        assert result["box_id"] == "b_new"
        assert mock_env["box_id"] == "b_new"

def test_select_box_not_found(mock_env):
    """Test selecting a non-existent box."""
    with patch("shadowbox.network.adapter.UserModel") as MockUserModel:
        um = MockUserModel.return_value
        um.get_by_username.return_value = {"user_id": "u1", "username": "tester"}
        
        with patch("shadowbox.network.adapter.BoxModel") as MockBoxModel:
            bm = MockBoxModel.return_value
            bm.list_by_user.return_value = []
            
            with pytest.raises(Exception, match="not found"):
                adapter.select_box(mock_env, "missing")

def test_list_boxes(mock_env):
    """Test listing available boxes."""
    with patch("shadowbox.network.adapter.BoxModel") as MockBoxModel:
        bm = MockBoxModel.return_value
        bm.list_by_user.return_value = [
            {"box_name": "A", "description": "desc A", "box_id": "b1"},
            {"box_name": "B", "description": None, "box_id": "b2"}
        ]
        
        output = adapter.list_boxes(mock_env)
        
        # Output format is: "- {name} (ID: {id})"
        assert "- A (ID: b1)" in output
        assert "- B (ID: b2)" in output
        assert "Available boxes:" in output

def test_format_list_active_box(mock_env):
    """Test listing files in the currently selected box."""
    with patch("shadowbox.network.adapter.check_permission", return_value=True), \
         patch("shadowbox.network.adapter.FileModel") as MockFileModel:
        
        fm = MockFileModel.return_value
        f1 = Mock(file_id="f1", filename="file1.txt", size=100, tags=[], status="active")
        f2 = Mock(file_id="f2", filename="file2.jpg", size=2000, tags=[], status="active")
        fm.list_by_box.return_value = [f1, f2]
        
        output = adapter.format_list(mock_env)
        
        assert "file1.txt" in output
        assert "file2.jpg" in output
        assert "100" in output

def test_format_list_no_box_selected(mock_env):
    """Test listing files when permission denied."""
    with patch("shadowbox.network.adapter.check_permission", return_value=False):
        with pytest.raises(Exception): 
            adapter.format_list(mock_env)

def test_open_for_get_success(mock_env):
    """Test opening a file stream for download."""
    # 1. Mock DB result
    row_data = {
        "file_id": "f1", 
        "filename": "test.txt", 
        "box_id": "b1",
        "created_at": "2023-01-01",
        "modified_at": "2023-01-01",
        "accessed_at": "2023-01-01",
        "size": 123,
        "file_type": FileType.DOCUMENT.value,
        "mime_type": "text/plain",
        "hash_sha256": "abc_hash",
        "user_id": "u1",
        "owner": "tester",
        "status": "active",
        "version": 1,
        "parent_version_id": None,
        "description": "",
        "custom_metadata": None,
        "original_path": "/tmp/orig"
    }
    
    mock_env["db"].fetch_one.return_value = row_data
    mock_env["db"].fetch_all.return_value = [] # tags
    
    # 2. Mock storage path resolution
    # Instead of relying on division magic which failed,
    # we'll mock the Path object returned by blob_root() and its join logic manually
    # or rely on the adapter just calling / operator.
    # The fail was: mock_env["storage"].blob_root.return_value.__truediv__.return_value = mock_blob_path
    
    mock_blob_path = MagicMock()
    mock_blob_path.exists.return_value = True
    
    # Configure the mock returned by blob_root() to return mock_blob_path when divided
    mock_root = MagicMock()
    mock_root.__truediv__.return_value = mock_blob_path
    mock_env["storage"].blob_root.return_value = mock_root
    
    with patch("builtins.open", new_callable=MagicMock) as mock_open:
        res = adapter.open_for_get(mock_env, "test.txt")
        assert res == mock_open.return_value

def test_open_for_get_not_found(mock_env):
    """Test file not found in DB."""
    mock_env["db"].fetch_one.return_value = None
    assert adapter.open_for_get(mock_env, "missing.txt") is None

def test_delete_filename_success(mock_env):
    """Test successful soft delete."""
    with patch("shadowbox.network.adapter.find_by_filename") as mock_find, \
         patch("shadowbox.network.adapter.check_permission", return_value=True), \
         patch("shadowbox.network.adapter.FileModel") as MockFileModel, \
         patch("shadowbox.network.adapter.UserModel") as MockUserModel:
        
        mock_find.return_value = Mock(file_id="f1", user_id="u1", size=100)
        
        fm = MockFileModel.return_value
        um = MockUserModel.return_value
        um.get.return_value = {"used_bytes": 500} 
        
        result = adapter.delete_filename(mock_env, "del.txt")
        
        assert result is True
        fm.delete.assert_called_with("f1", soft=True)

def test_share_box_success(mock_env):
    """Test sharing a box."""
    with patch("shadowbox.network.adapter.UserModel") as MockUserModel, \
         patch("shadowbox.network.adapter.BoxModel") as MockBoxModel, \
         patch("shadowbox.network.adapter.BoxShareModel") as MockShareModel:
        
        um = MockUserModel.return_value
        bm = MockBoxModel.return_value
        bm.list_by_user.return_value = [{"box_name": "mybox", "box_id": "b1"}]
        um.get_by_username.return_value = {"user_id": "u_target", "username": "friend"}
        
        sm = MockShareModel.return_value
        sm.list_by_box.return_value = []
        
        result = adapter.share_box(mock_env, "mybox", "friend", "read")
        
        assert "OK" in result
        sm.create.assert_called()

def test_share_box_target_missing(mock_env):
    """Test sharing with missing user."""
    with patch("shadowbox.network.adapter.UserModel") as MockUserModel, \
         patch("shadowbox.network.adapter.BoxModel") as MockBoxModel:
        
        bm = MockBoxModel.return_value
        bm.list_by_user.return_value = [{"box_name": "mybox", "box_id": "b1"}]
        um = MockUserModel.return_value
        um.get_by_username.return_value = None 
        
        result = adapter.share_box(mock_env, "mybox", "ghost", "read")
        assert "User 'ghost' not found" in result

def test_list_available_users(mock_env):
    """Test listing users."""
    with patch("shadowbox.network.adapter.UserModel") as MockUserModel:
        um = MockUserModel.return_value
        um.list_all.return_value = [
            {"username": "alice", "user_id": "u2"},
            {"username": "bob", "user_id": "u3"},
            {"username": "tester", "user_id": "u1"}
        ]
        
        output = adapter.list_available_users(mock_env)
        
        assert "alice" in output
        assert "bob" in output
        assert "tester" not in output