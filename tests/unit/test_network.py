"""Unit tests covering network client/server interactions."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterable, Literal, Optional, Tuple

import pytest

from shadowbox.network import client

ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(ROOT / "src"))


class FakeSocket:
    """A lightweight socket stand-in used to script send/receive behavior."""

    def __init__(self, recv_chunks: Iterable[bytes]):
        """Initialize with predetermined chunks returned by :meth:`recv`."""
        self.recv_chunks: list[bytes] = list(recv_chunks)
        self.sent_data: bytes = b""
        self.timeout: Optional[float] = None
        self.closed = False

    def settimeout(self, timeout: Optional[float]) -> None:
        """Record the requested timeout value for assertions."""
        self.timeout = timeout

    def sendall(self, data: bytes) -> None:
        """Accumulate outbound data to mimic socket transmission."""
        self.sent_data += data

    def recv(self, bufsize: int) -> bytes:
        """Return scripted data chunks until exhausted, then terminate."""
        if self.recv_chunks:
            return self.recv_chunks.pop(0)
        return b""

    def close(self) -> None:
        """Mark the socket as closed."""
        self.closed = True

    def __enter__(self) -> "FakeSocket":
        """Support usage as a context manager in client code."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[object],
    ) -> Literal[False]:
        """Close the socket when exiting a context manager block."""
        self.close()
        return False


def test_connect_and_request_text_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate a text response from the server and verify returned payload."""
    expected_chunks = [b"OK: response line\n", b"from server", b""]

    def fake_create_connection(
        address: Tuple[str, int], timeout: Optional[float] = None
    ) -> FakeSocket:
        return FakeSocket(expected_chunks)

    monkeypatch.setattr("shadowbox.network.client.socket.create_connection", fake_create_connection)

    result = client.connect_and_request("127.0.0.1", 1234, "LIST")

    assert result["status"] == "ok"
    assert result["text"] == "OK: response line\nfrom server"


def test_connect_and_request_receives_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Stream file bytes into a destination path when requested."""
    expected_chunks = [b"file bytes", b" more", b""]
    fake_socket = FakeSocket(expected_chunks)

    def fake_create_connection(
        address: Tuple[str, int], timeout: Optional[float] = None
    ) -> FakeSocket:
        return fake_socket

    monkeypatch.setattr("shadowbox.network.client.socket.create_connection", fake_create_connection)

    out_path = tmp_path / "received.txt"
    result = client.connect_and_request(
        "127.0.0.1",
        5678,
        "GET sample",
        recv_file=True,
        out_path=out_path,
    )

    assert result == {"status": "ok", "saved_to": out_path}
    assert out_path.read_bytes() == b"file bytes more"
    assert fake_socket.sent_data == b"GET sample\n"


def test_connect_and_request_requires_out_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure file downloads without out_path raise a clear error.

    ``connect_and_request`` needs a destination path whenever ``recv_file`` is
    True so it knows where to stream the incoming bytes. This test swaps in a
    fake socket, calls the helper without ``out_path``, and asserts that the
    guardrail surfaces a ``ValueError`` before any network interaction
    proceeds.
    """
    fake_socket = FakeSocket([b""])

    def fake_create_connection(
        address: Tuple[str, int], timeout: Optional[float] = None
    ) -> FakeSocket:
        return fake_socket

    monkeypatch.setattr("shadowbox.network.client.socket.create_connection", fake_create_connection)

    with pytest.raises(ValueError):
        client.connect_and_request("10.0.0.1", 9000, "GET missing", recv_file=True)


def test_connect_and_request_missing_file_returns_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Return an error mapping when the server reports a missing file."""
    expected_chunks = [b"ERROR: File not found: missing\n", b""]
    fake_socket = FakeSocket(expected_chunks)

    def fake_create_connection(
        address: Tuple[str, int], timeout: Optional[float] = None
    ) -> FakeSocket:
        return fake_socket

    monkeypatch.setattr("shadowbox.network.client.socket.create_connection", fake_create_connection)

    out_path = tmp_path / "missing.txt"
    result = client.connect_and_request(
        "10.0.0.2",
        8000,
        "GET missing",
        recv_file=True,
        out_path=out_path,
    )

    assert result == {"status": "error", "error": f"File not found: {out_path}"}
    assert out_path.read_bytes() == b""
