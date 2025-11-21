"""Minimal Textual app scaffold for ShadowBox.

Start here with `python -m shadowbox.frontend.cli.app`
and extend widgets/flows without touching the backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import logging

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)
from textual.screen import ModalScreen

from shadowbox.core.models import FileMetadata
from shadowbox.frontend.cli.context import AppContext, build_context
from shadowbox.frontend.cli.logging_config import configure_logging
from shadowbox.database.search import search_fts


def _human_size(num: int) -> str:
    # Simple human-readable bytes formatter.
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024
    return f"{num:.1f} PB"


# === Modal definitions ===


class AddFileResult:
    def __init__(self, path: str, tags: list[str], encrypt: bool):
        self.path = path
        self.tags = tags
        self.encrypt = encrypt


class AddFileModal(ModalScreen[Optional[AddFileResult]]):
    def __init__(self, encrypt_ready: bool = False):
        super().__init__()
        self.encrypt_ready = encrypt_ready

    def compose(self) -> ComposeResult:  # pragma: no cover - UI only
        yield Static("Add File", classes="title")
        yield Label("Path (Enter to add, Esc to cancel)")
        self.path_input = Input(placeholder="/path/to/file")
        yield self.path_input
        yield Label("Tags (comma-separated)")
        self.tags_input = Input(placeholder="tag1, tag2")
        yield self.tags_input
        encrypt_label = (
            "Encrypt file"
            if self.encrypt_ready
            else "Encryption unavailable (master key not set)"
        )
        self.encrypt_box = Checkbox(encrypt_label, disabled=not self.encrypt_ready)
        yield self.encrypt_box
        with Horizontal():
            yield Button("Cancel (Esc)", id="cancel")
            yield Button("Add (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.path_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover - UI only
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        path = self.path_input.value.strip()
        tags = [t.strip() for t in self.tags_input.value.split(",") if t.strip()]
        self.dismiss(AddFileResult(path=path, tags=tags, encrypt=self.encrypt_box.value))

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            # trigger primary action
            path = self.path_input.value.strip()
            tags = [t.strip() for t in self.tags_input.value.split(",") if t.strip()]
            self.dismiss(AddFileResult(path=path, tags=tags, encrypt=self.encrypt_box.value))


class DownloadResult:
    def __init__(self, dest: str):
        self.dest = dest


class DownloadModal(ModalScreen[Optional[DownloadResult]]):
    def compose(self) -> ComposeResult:  # pragma: no cover
        yield Static("Download File", classes="title")
        yield Label("Save to path (Enter to save, Esc to cancel)")
        self.dest_input = Input(placeholder="/tmp/output")
        yield self.dest_input
        with Horizontal():
            yield Button("Cancel (Esc)", id="cancel")
            yield Button("Save (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.dest_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        dest = self.dest_input.value.strip()
        self.dismiss(DownloadResult(dest=dest))

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            dest = self.dest_input.value.strip()
            self.dismiss(DownloadResult(dest=dest))


class SearchResult:
    def __init__(self, query: str, scope_all: bool):
        self.query = query
        self.scope_all = scope_all


class SearchModal(ModalScreen[Optional[SearchResult]]):
    def compose(self) -> ComposeResult:  # pragma: no cover
        yield Static("Search", classes="title")
        self.q_input = Input(placeholder="query text")
        yield self.q_input
        self.scope_box = Checkbox("Search all boxes (unchecked = current box)")
        yield self.scope_box
        with Horizontal():
            yield Button("Cancel (Esc)", id="cancel")
            yield Button("Search (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.q_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        q = self.q_input.value.strip()
        self.dismiss(SearchResult(query=q, scope_all=self.scope_box.value))

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            q = self.q_input.value.strip()
            self.dismiss(SearchResult(query=q, scope_all=self.scope_box.value))


class ShadowBoxApp(App):
    """Textual scaffold showing boxes and files; ready to extend."""

    CSS = """
    #sidebar { width: 28%; min-width: 22; border: heavy $surface; }
    #main { border: heavy $surface; }
    .title { padding: 1 1; text-style: bold; }
    #status { padding: 0 1 1 1; height: 3; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "add_file", "Add"),
        ("enter", "download", "Download"),
        ("d", "delete_file", "Delete"),
        ("/", "search", "Search"),
    ]

    def __init__(self, ctx: AppContext | None = None):
        configure_logging()
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ctx = ctx or build_context()
        super().__init__()

        self.boxes: ListView | None = None
        self.table: DataTable | None = None
        self.status: Static | None = None
        self.row_keys: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("Boxes", classes="title")
                self.boxes = ListView(id="boxes")
                yield self.boxes
            with Vertical(id="main"):
                yield Static("Files", classes="title")
                self.table = DataTable(id="files")
                yield self.table
                self.status = Static("", id="status")
                yield self.status
        yield Footer()

    def on_mount(self) -> None:
        # Configure table columns once.
        assert self.table is not None
        self.table.add_columns("Name", "Size", "Tags", "Status", "Modified")
        self.refresh_boxes()
        self.refresh_files()

    def refresh_boxes(self) -> None:
        assert self.boxes is not None
        self.boxes.clear()
        try:
            user_boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
        except Exception as exc:  # pragma: no cover - UI only
            self.logger.error("Failed to load boxes: %s", exc)
            self._set_status(f"Error loading boxes: {exc}")
            return

        for box in user_boxes:
            item = ListItem(Static(box.box_name))
            item.data = box
            self.boxes.append(item)

        # Keep selection aligned with active box.
        for idx, item in enumerate(self.boxes.children):
            if getattr(item, "data", None) and item.data.box_id == self.ctx.active_box.box_id:
                self.boxes.index = idx
                break

    def refresh_files(self) -> None:
        assert self.table is not None
        # Clear existing rows but keep column definitions intact.
        self.table.clear(columns=False)
        self.row_keys = []

        try:
            files: Iterable[FileMetadata] = self.ctx.fm.list_box_files(
                self.ctx.active_box.box_id
            )
        except Exception as exc:  # pragma: no cover - UI-only
            self.logger.error("Failed to load files: %s", exc)
            self._set_status(f"Error loading files: {exc}")
            return

        for f in files:
            tags = ", ".join(f.tags) if f.tags else "--"
            status = f.status.value if hasattr(f.status, "value") else str(f.status)
            modified = (
                f.modified_at.isoformat(timespec="seconds")
                if isinstance(f.modified_at, datetime)
                else str(f.modified_at)
            )
            self.table.add_row(
                f.filename, _human_size(f.size), tags, status, modified, key=f.file_id
            )
            self.row_keys.append(f.file_id)

        self._update_status()

    def action_refresh(self) -> None:
        self.refresh_boxes()
        self.refresh_files()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        box = getattr(event.item, "data", None)
        if box:
            self.ctx.active_box = box
            self.refresh_files()

    def _set_status(self, message: str) -> None:
        if self.status:
            self.status.update(message)

    def _update_status(self) -> None:
        # pull fresh user quota for accuracy
        row = self.ctx.fm.user_model.get(self.ctx.user.user_id)
        if row:
            self.ctx.user.used_bytes = row.get("used_bytes", self.ctx.user.used_bytes)
            self.ctx.user.quota_bytes = row.get("quota_bytes", self.ctx.user.quota_bytes)
        used = _human_size(self.ctx.user.used_bytes)
        total = _human_size(self.ctx.user.quota_bytes)
        self._set_status(
            f"User: {self.ctx.user.username} • Box: {self.ctx.active_box.box_name} • Files: {self.table.row_count} • Quota: {used}/{total}"
        )

    # === Actions ===

    def action_add_file(self) -> None:
        self.push_screen(
            AddFileModal(encrypt_ready=self.ctx.fm.encryption_enabled),
            self._handle_add_file,
        )

    def _handle_add_file(self, result: Optional["AddFileResult"]) -> None:
        if not result:
            return
        try:
            self.ctx.fm.add_file(
                user_id=self.ctx.user.user_id,
                box_id=self.ctx.active_box.box_id,
                source_path=result.path,
                tags=result.tags,
                encrypt=result.encrypt,
            )
            self.refresh_files()
            self.logger.info("Added file %s", result.path)
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Add failed: {exc}")

    def _selected_file_id(self) -> Optional[str]:
        if not self.table or self.table.cursor_row is None:
            return None
        idx = self.table.cursor_row
        if 0 <= idx < len(self.row_keys):
            return self.row_keys[idx]
        return None

    def action_download(self) -> None:
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        self.push_screen(DownloadModal(), lambda res: self._handle_download(res, file_id))

    def _handle_download(self, result: Optional["DownloadResult"], file_id: str) -> None:
        if not result:
            return
        try:
            self.ctx.fm.get_file(file_id=file_id, destination_path=result.dest)
            self._set_status(f"Saved to {result.dest}")
            self.logger.info("Downloaded %s", result.dest)
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Download failed: {exc}")

    def action_delete_file(self) -> None:
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        try:
            self.ctx.fm.delete_file(file_id, soft=True)
            self.refresh_files()
            self.logger.info("Deleted file %s", file_id)
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Delete failed: {exc}")

    def action_search(self) -> None:
        self.push_screen(SearchModal(), self._handle_search)

    def _handle_search(self, result: Optional["SearchResult"]):
        if not result:
            return
        try:
            hits = search_fts(
                self.ctx.db,
                result.query,
                user_id=self.ctx.user.user_id if result.scope_all is False else None,
                limit=200,
            )
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Search failed: {exc}")
            return

        self.table.clear(columns=False)
        self.row_keys = []
        for f in hits:
            tags = ", ".join(f.tags) if f.tags else "--"
            status = f.status.value if hasattr(f.status, "value") else str(f.status)
            modified = (
                f.modified_at.isoformat(timespec="seconds")
                if isinstance(f.modified_at, datetime)
                else str(f.modified_at)
            )
            self.table.add_row(
                f"{f.filename} ({f.box_id[:6]})",
                _human_size(f.size),
                tags,
                status,
                modified,
                key=f.file_id,
            )
            self.row_keys.append(f.file_id)

        self._set_status(f"Search: {len(hits)} result(s)")


if __name__ == "__main__":  # pragma: no cover
    ShadowBoxApp().run()
