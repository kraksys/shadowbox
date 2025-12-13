"""Unit tests for the network server module."""

import os
import pytest
import socket
import threading
from unittest.mock import Mock, patch, MagicMock
from shadowbox.network import server


# --- Fixtures ---

@pytest.fixture
def mock_socket():
    """Returns a mock socket that captures sent data and provides canned responses."""
    s = MagicMock(spec=socket.socket)
    s.recv.return_value = b""
    return s


@pytest.fixture
def mock_adapter():
    """Patches all adapter functions imported in server.py."""
    with patch("shadowbox.network.server.select_box") as sel_box, \
            patch("shadowbox.network.server.open_for_get") as open_get, \
            patch("shadowbox.network.server.finalize_put") as fin_put, \
            patch("shadowbox.network.server.delete_filename") as del_file, \
            patch("shadowbox.network.server.format_list") as fmt_list, \
            patch("shadowbox.network.server.list_boxes") as lst_boxes, \
            patch("shadowbox.network.server.share_box") as shr_box:
        yield {
            "select_box": sel_box,
            "open_for_get": open_get,
            "finalize_put": fin_put,
            "delete_filename": del_file,
            "format_list": fmt_list,
            "list_boxes": lst_boxes,
            "share_box": shr_box
        }


# --- Utility Tests ---

def test_give_code():
    """Test code generation format."""
    code = server.give_code()
    assert len(code) == 4
    assert code.islower()
    assert code.isalpha()


def test_delete_path_recursive(tmp_path):
    """Test delete_path recursively removes directories."""
    # Setup: dir/subdir/file
    d = tmp_path / "dir"
    d.mkdir()
    sub = d / "subdir"
    sub.mkdir()
    f = sub / "file.txt"
    f.write_text("content")

    assert d.exists()
    server.delete_path(str(d))
    assert not d.exists()


def test_get_file_lock():
    """Test file locking mechanism."""
    path = "/tmp/test"
    lock1 = server.get_file_lock(path)
    lock2 = server.get_file_lock(path)
    # Should return the same lock object for same path
    assert lock1 is lock2

    lock3 = server.get_file_lock("/tmp/other")
    assert lock1 is not lock3


# --- Protocol Handler Tests (handle_client) ---

def test_handle_client_list_test_mode(mock_socket, tmp_path):
    """Test LIST command in test mode (filesystem listing)."""
    # Setup dummy files
    (tmp_path / "file1.txt").touch()
    (tmp_path / "file2.txt").touch()

    # Mock client sending "LIST\n"
    mock_socket.recv.side_effect = [b"LIST\n", b""]

    context = {"mode": "test", "shared_dir": str(tmp_path)}

    server.handle_client(mock_socket, ("127.0.0.1", 1234), context)

    # Check sent data contains filenames
    sent = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"file1.txt" in sent
    assert b"file2.txt" in sent


def test_handle_client_list_core_mode(mock_socket, mock_adapter):
    """Test LIST command in core mode (database listing)."""
    mock_socket.recv.side_effect = [b"LIST\n", b""]
    mock_adapter["format_list"].return_value = "file1\nfile2"

    context = {"mode": "core", "env": {}}

    server.handle_client(mock_socket, ("127.0.0.1", 1234), context)

    mock_socket.sendall.assert_called_with(b"file1\nfile2")


def test_handle_client_box_command(mock_socket, mock_adapter):
    """Test BOX command to switch active box."""
    mock_socket.recv.side_effect = [b"BOX mybox\n", b""]
    mock_adapter["select_box"].return_value = {"box_id": "b1"}

    context = {"mode": "core", "env": {}}

    server.handle_client(mock_socket, ("127.0.0.1", 1234), context)

    mock_adapter["select_box"].assert_called_with({}, "mybox")
    # Verify success message
    sent = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"OK: Selected box 'mybox'" in sent


def test_handle_client_put_core_mode(mock_socket, mock_adapter, tmp_path):
    """Test PUT command uploading a file."""
    file_content = b"12345"
    file_size = len(file_content)

    # Mock sequence: 
    # 1. Command "PUT file.txt 5\n"
    # 2. Server sends READY
    # 3. Client sends 5 bytes
    mock_socket.recv.side_effect = [
        f"PUT test.txt {file_size}\n".encode(),
        file_content,
        b""
    ]

    # We need to mock the storage root environment
    mock_storage = Mock()
    mock_storage.user_root.return_value = tmp_path
    context = {"mode": "core", "env": {"storage": mock_storage, "user_id": "u1"}}

    server.handle_client(mock_socket, ("127.0.0.1", 1234), context)

    # Verify READY was sent
    calls = mock_socket.sendall.call_args_list
    assert calls[0][0][0] == b"READY\n"
    assert b"OK: Uploaded" in calls[1][0][0]

    # Verify finalize_put was called
    mock_adapter["finalize_put"].assert_called()
    args = mock_adapter["finalize_put"].call_args[0]
    # args[1] is the temp path, args[2] is the filename
    assert args[2] == "test.txt"


def test_handle_client_put_invalid_args(mock_socket):
    """Test PUT rejection on missing args."""
    mock_socket.recv.side_effect = [b"PUT file.txt\n", b""]  # missing size
    server.handle_client(mock_socket, ("127.0.0.1", 1234), {"mode": "test"})
    mock_socket.sendall.assert_called_with(b"ERROR: PUT requires filename and size\n")


def test_handle_client_delete(mock_socket, mock_adapter):
    """Test DELETE command."""
    mock_socket.recv.side_effect = [b"DELETE old.txt\n", b""]
    mock_adapter["delete_filename"].return_value = True

    context = {"mode": "core", "env": {}}
    server.handle_client(mock_socket, ("127.0.0.1", 1234), context)

    mock_adapter["delete_filename"].assert_called_with({}, "old.txt")
    sent = b"".join(call.args[0] for call in mock_socket.sendall.call_args_list)
    assert b"OK: Deleted" in sent


def test_handle_client_unknown_command(mock_socket):
    """Test fallback for unknown commands."""
    mock_socket.recv.side_effect = [b"JUNK cmd\n", b""]
    server.handle_client(mock_socket, ("127.0.0.1", 1234), {"mode": "test"})
    mock_socket.sendall.assert_called_with(b"ERROR - Unknown command\n")


# --- Server Lifecycle Tests ---

@patch("shadowbox.network.server.socket.socket")
def test_start_tcp_server_lifecycle(mock_socket_cls):
    """Test that server loop runs and stops on signal."""
    mock_socket = MagicMock()
    mock_socket_cls.return_value = mock_socket

    # Mock accept to raise an exception eventually to break loop, 
    # or we can rely on SERVER_SHOULD_STOP check.
    # Here we simulate one connection then stop.
    mock_conn = MagicMock()
    mock_socket.accept.return_value = (mock_conn, ("127.0.0.1", 5555))

    # We need to run start_tcp_server in a thread because it blocks
    context = {"mode": "test", "shared_dir": "/tmp"}

    t = threading.Thread(target=server.start_tcp_server, args=(context, 9999))
    t.start()

    # Let it "run" briefly then signal stop
    import time
    time.sleep(0.1)
    server.stop_server()
    t.join(timeout=1.0)

    assert not t.is_alive()
    mock_socket.bind.assert_called_with(("", 9999))
    mock_socket.listen.assert_called_with(5)
    # verify stop_server closed the socket
    mock_socket.close.assert_called()