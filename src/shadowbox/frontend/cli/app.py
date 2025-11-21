"""Minimal Textual app scaffold for ShadowBox.

Start here with `python -m shadowbox.frontend.cli.app`
and extend widgets/flows without touching the backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Header, ListItem, ListView, Static

from shadowbox.core.models import FileMetadata
from shadowbox.frontend.cli.context import AppContext, build_context


def _human_size(num: int) -> str:
    # Simple human-readable bytes formatter.
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num < 1024:
            return f"{num:.1f} {unit}" if unit != "B" else f"{num} B"
        num /= 1024
    return f"{num:.1f} PB"


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
    ]

    def __init__(self, ctx: AppContext | None = None):
        self.ctx = ctx or build_context()
        super().__init__()

        self.boxes: ListView | None = None
        self.table: DataTable | None = None
        self.status: Static | None = None

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
        for box in self.ctx.fm.list_user_boxes(self.ctx.user.user_id):
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

        try:
            files: Iterable[FileMetadata] = self.ctx.fm.list_box_files(
                self.ctx.active_box.box_id
            )
        except Exception as exc:  # pragma: no cover - UI-only
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
            self.table.add_row(f.filename, _human_size(f.size), tags, status, modified)

        self._set_status(
            f"User: {self.ctx.user.username} • Box: {self.ctx.active_box.box_name} • Files: {self.table.row_count}"
        )

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


if __name__ == "__main__":  # pragma: no cover
    ShadowBoxApp().run()
