"""Minimal Textual app scaffold for ShadowBox.

Start here with `python -m shadowbox.frontend.cli.app`
and extend widgets/flows without touching the backend.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

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
from shadowbox.database.search import search_fts
from shadowbox.network.client import ServiceFinder, connect_and_request


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
        with Vertical(classes="dialog"):
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
        with Vertical(classes="dialog"):
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
        with Vertical(classes="dialog"):
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


class NewBoxResult:
    def __init__(self, name: str, description: str | None, encrypt: bool):
        self.name = name
        self.description = description
        self.encrypt = encrypt


class NewBoxModal(ModalScreen[Optional[NewBoxResult]]):
    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("New Box", classes="title")
            self.name_input = Input(placeholder="box name")
            yield self.name_input
            self.desc_input = Input(placeholder="description (optional)")
            yield self.desc_input
            self.encrypt_box = Checkbox("Encrypt box (if backend ready)")
            yield self.encrypt_box
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Create (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.name_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(
            NewBoxResult(
                name=self.name_input.value.strip(),
                description=self.desc_input.value.strip() or None,
                encrypt=self.encrypt_box.value,
            )
        )

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self.dismiss(
                NewBoxResult(
                    name=self.name_input.value.strip(),
                    description=self.desc_input.value.strip() or None,
                    encrypt=self.encrypt_box.value,
                )
            )


class DeleteConfirmModal(ModalScreen[Optional[bool]]):
    def __init__(self, prompt: str):
        super().__init__()
        self.prompt = prompt

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(self.prompt)
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Delete (Enter)", id="ok", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(False)
        else:
            self.dismiss(True)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(False)
        elif event.key == "enter":
            self.dismiss(True)


class BoxInfoModal(ModalScreen[None]):
    def __init__(self, box, info):
        super().__init__()
        self.box = box
        self.info = info or {}

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(f"Box: {self.box.box_name}", classes="title")
            lines = [
                f"Owner: {self.box.user_id}",
                f"Shared: {self.box.is_shared}",
                f"Encryption: {self.box.settings.get('encryption_enabled', False)}",
                f"Files: {self.info.get('file_count')}",
                f"Total size: {self.info.get('total_size', 0)} bytes",
                f"Created: {self.info.get('created_at')}",
                f"Updated: {self.info.get('updated_at')}",
            ]
            for line in lines:
                yield Static(line)
            yield Button("Close (Esc)", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        self.dismiss(None)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key in ("escape", "enter"):
            self.dismiss(None)


class ShareBoxResult:
    def __init__(self, user_id: str, permission: str, expires_at=None):
        self.user_id = user_id
        self.permission = permission
        self.expires_at = expires_at


class ShareBoxModal(ModalScreen[Optional[ShareBoxResult]]):
    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Share Box", classes="title")
            self.user_input = Input(placeholder="target user id")
            yield self.user_input
            self.perm_input = Input(placeholder="permission (read/write/admin)", value="read")
            yield self.perm_input
            self.expiry_input = Input(placeholder="expiry ISO (optional)")
            yield self.expiry_input
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Share (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.user_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        expiry_txt = self.expiry_input.value.strip()
        expires_at = None
        if expiry_txt:
            try:
                expires_at = datetime.fromisoformat(expiry_txt)
            except Exception:
                expires_at = None
        self.dismiss(
            ShareBoxResult(
                user_id=self.user_input.value.strip(),
                permission=self.perm_input.value.strip() or "read",
                expires_at=expires_at,
            )
        )

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            expiry_txt = self.expiry_input.value.strip()
            expires_at = None
            if expiry_txt:
                try:
                    expires_at = datetime.fromisoformat(expiry_txt)
                except Exception:
                    expires_at = None
            self.dismiss(
                ShareBoxResult(
                    user_id=self.user_input.value.strip(),
                    permission=self.perm_input.value.strip() or "read",
                    expires_at=expires_at,
                )
            )


class UnshareModal(ModalScreen[Optional[str]]):
    def __init__(self, box_id: str, share_model):
        super().__init__()
        self.box_id = box_id
        self.share_model = share_model

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Unshare Box", classes="title")
            users = [
                share["shared_with_user_id"]
                for share in self.share_model.list_by_box(self.box_id)
            ]
            users_str = ", ".join(users) if users else "No shares"
            yield Static(f"Shared with: {users_str}")
            self.user_input = Input(placeholder="user id to remove")
            yield self.user_input
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Remove (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.user_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(self.user_input.value.strip())

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self.dismiss(self.user_input.value.strip())


class EditFileResult:
    def __init__(self, tags: str, description: str):
        self.tags = tags
        self.description = description


class EditFileModal(ModalScreen[Optional[EditFileResult]]):
    def __init__(self, filename: str, tags: str, description: str):
        super().__init__()
        self.filename = filename
        self.initial_tags = tags
        self.initial_desc = description

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(f"Edit: {self.filename}", classes="title")
            yield Label("Tags (comma-separated)")
            self.tags_input = Input(value=self.initial_tags)
            yield self.tags_input
            yield Label("Description")
            self.desc_input = Input(value=self.initial_desc)
            yield self.desc_input
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Save (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.tags_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self.dismiss(EditFileResult(self.tags_input.value, self.desc_input.value))

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self.dismiss(EditFileResult(self.tags_input.value, self.desc_input.value))


class PeerListModal(ModalScreen[None]):
    def __init__(self):
        super().__init__()
        self.output = Static("Discovering peers...", classes="title")
        self.info = None

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Peers (LAN discovery)", classes="title")
            yield self.output
            with Horizontal():
                yield Button("Close (Esc/Enter)", id="close")

    def on_mount(self) -> None:  # pragma: no cover
        # kick off discovery without blocking UI
        self.set_interval(0.1, self._discover_and_list, pause=False, repeat=False)

    def _discover_and_list(self) -> None:
        try:
            finder = ServiceFinder()
            info = finder.wait_for_service()
            finder.close()
            if not info:
                self.output.update("No peers found.")
                return
            self.info = info
            res = connect_and_request(info["ip"], info["port"], "LIST")
            text = res.get("text", "").strip() if isinstance(res, dict) else str(res)
            self.output.update(
                f"Found: {info['name']} @ {info['ip']}:{info['port']}\n\nFiles:\n{text or '(empty)'}"
            )
        except Exception as exc:
            self.output.update(f"Discovery/List failed: {exc}")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        self.dismiss(None)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key in ("escape", "enter"):
            self.dismiss(None)


class ShadowBoxApp(App):
    """Textual scaffold showing boxes and files; ready to extend."""

    TITLE = "ShadowBox"

    CSS = """
    #sidebar { width: 30%; min-width: 24; border: heavy $surface; }
    #main { border: heavy $surface; }
    .title { padding: 1 1; text-style: bold; }
    #status { padding: 0 1 1 1; height: 3; color: $text-muted; }
    .section-label { padding: 0 1; color: $text-muted; }
    ModalScreen { align: center middle; background: rgba(0,0,0,0.45); }
    .dialog { width: 75%; height: 75%; padding: 1; border: heavy $surface; background: $boost; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("a", "add_file", "Add"),
        ("enter", "download", "Download"),
        ("d", "delete_file", "Delete"),
        ("/", "search", "Search"),
        ("n", "new_box", "New Box"),
        ("x", "delete_box", "Delete Box"),
        ("b", "box_info", "Box Info"),
        ("s", "share_box", "Share Box"),
        ("u", "unshare_box", "Unshare Box"),
        ("p", "peer_list", "Peers"),
        ("e", "edit_file", "Edit File"),
    ]

    def __init__(self, ctx: AppContext | None = None):
        self.ctx = ctx or build_context()
        super().__init__()

        self.boxes: ListView | None = None
        self.shared_boxes: ListView | None = None
        self.table: DataTable | None = None
        self.status: Static | None = None
        self.row_keys: list[str] = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static("My Boxes", classes="title")
                self.boxes = ListView(id="boxes")
                yield self.boxes
                yield Static("Shared with Me", classes="title")
                self.shared_boxes = ListView(id="shared")
                yield self.shared_boxes
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
        if self.shared_boxes:
            self.shared_boxes.clear()
        try:
            user_boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
            shared_boxes = self.ctx.fm.list_shared_boxes(self.ctx.user.user_id)
        except Exception as exc:  # pragma: no cover - UI only
            self._set_status(f"Error loading boxes: {exc}")
            return

        for box in user_boxes:
            item = ListItem(Static(box.box_name))
            item.data = box
            self.boxes.append(item)

        if self.shared_boxes is not None:
            for box in shared_boxes:
                item = ListItem(Static(f"{box.box_name} (shared)"))
                item.data = box
                self.shared_boxes.append(item)

        # Keep selection aligned with active box.
        for idx, item in enumerate(self.boxes.children):
            if getattr(item, "data", None) and item.data.box_id == self.ctx.active_box.box_id:
                self.boxes.index = idx
                break
        if self.shared_boxes and self.ctx.active_box:
            if self.ctx.active_box.user_id != self.ctx.user.user_id:
                for idx, item in enumerate(self.shared_boxes.children):
                    if getattr(item, "data", None) and item.data.box_id == self.ctx.active_box.box_id:
                        self.shared_boxes.index = idx
                        break

    def refresh_files(self) -> None:
        assert self.table is not None
        # Clear existing rows but keep column definitions intact.
        self.table.clear(columns=False)
        self.row_keys = []

        if not self.ctx.active_box:
            self._set_status("No active box")
            return

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

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        box = getattr(event.item, "data", None)
        if box and box != self.ctx.active_box:
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
        self._set_status("Adding file...")
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
            self._set_status("Added file")
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
        self._set_status("Downloading...")
        self.push_screen(DownloadModal(), lambda res: self._handle_download(res, file_id))

    def _handle_download(self, result: Optional["DownloadResult"], file_id: str) -> None:
        if not result:
            return
        try:
            self.ctx.fm.get_file(file_id=file_id, destination_path=result.dest)
            self._set_status(f"Saved to {result.dest}")
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Download failed: {exc}")

    def action_delete_file(self) -> None:
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        filename = self.table.get_row_at(self.table.cursor_row)[0] if self.table else ""
        prompt = f"Delete file '{filename}'?"
        self.push_screen(DeleteConfirmModal(prompt), lambda ok: self._handle_delete_file(ok, file_id))

    def _handle_delete_file(self, confirmed: bool, file_id: str) -> None:
        if not confirmed:
            return
        try:
            self._set_status("Deleting...")
            self.ctx.fm.delete_file(file_id, soft=True)
            self.refresh_files()
            self._set_status("Deleted file")
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

    # Box CRUD
    def action_new_box(self) -> None:
        self.push_screen(NewBoxModal(), self._handle_new_box)

    def _handle_new_box(self, result: Optional["NewBoxResult"]):
        if not result:
            return
        try:
            box = self.ctx.fm.create_box(
                user_id=self.ctx.user.user_id,
                box_name=result.name,
                description=result.description or None,
                enable_encryption=result.encrypt,
            )
            self.refresh_boxes()
            self.ctx.active_box = box
            self._persist_last_box(box.box_id)
            self.refresh_files()
            self._set_status(f"Created box {box.box_name}")
        except Exception as exc:
            self._set_status(f"Create box failed: {exc}")

    def action_delete_box(self) -> None:
        if not self.ctx.active_box:
            return
        if self.ctx.active_box.user_id != self.ctx.user.user_id:
            self._set_status("Cannot delete: not owner")
            return
        prompt = f"Delete box '{self.ctx.active_box.box_name}'?"
        self.push_screen(DeleteConfirmModal(prompt), self._handle_delete_box)

    def _handle_delete_box(self, confirmed: bool):
        if not confirmed:
            return
        try:
            self.ctx.fm.delete_box(self.ctx.active_box.box_id)
            boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
            shared_boxes = self.ctx.fm.list_shared_boxes(self.ctx.user.user_id)
            self.ctx.active_box = None
            if boxes:
                self.ctx.active_box = boxes[0]
            elif shared_boxes:
                self.ctx.active_box = shared_boxes[0]
            self.refresh_boxes()
            self.refresh_files()
            msg = "Box deleted"
            if not self.ctx.active_box:
                msg += " (no boxes left)"
            self._set_status(msg)
        except Exception as exc:
            self._set_status(f"Delete failed: {exc}")

    def action_box_info(self) -> None:
        if not self.ctx.active_box:
            return
        info = self.ctx.fm.get_box_info(self.ctx.user.user_id, self.ctx.active_box.box_id)
        self.push_screen(BoxInfoModal(self.ctx.active_box, info))

    # Sharing
    def action_share_box(self) -> None:
        if not self.ctx.active_box:
            return
        if self.ctx.active_box.user_id != self.ctx.user.user_id:
            self._set_status("Only owners can share boxes")
            return
        self.push_screen(ShareBoxModal(), self._handle_share_box)

    def _handle_share_box(self, result: Optional["ShareBoxResult"]) -> None:
        if not result:
            return
        try:
            self.ctx.fm.share_box(
                box_id=self.ctx.active_box.box_id,
                shared_by_user_id=self.ctx.user.user_id,
                shared_with_user_id=result.user_id,
                permission_level=result.permission,
                expires_at=result.expires_at,
            )
            self._set_status("Box shared")
        except Exception as exc:
            self._set_status(f"Share failed: {exc}")

    def action_unshare_box(self) -> None:
        if not self.ctx.active_box:
            return
        if self.ctx.active_box.user_id != self.ctx.user.user_id:
            self._set_status("Only owners can unshare boxes")
            return
        self.push_screen(UnshareModal(self.ctx.active_box.box_id, self.ctx.fm.box_share_model), self._handle_unshare)

    def _handle_unshare(self, result: Optional[str]) -> None:
        if not result:
            return
        try:
            self.ctx.fm.unshare_box(self.ctx.active_box.box_id, self.ctx.user.user_id, result)
            self._set_status("Unshared")
        except Exception as exc:
            self._set_status(f"Unshare failed: {exc}")

    # Network (read-only peer list)
    def action_peer_list(self) -> None:
        self.push_screen(PeerListModal())

    # Edit file metadata (tags + description)
    def action_edit_file(self) -> None:
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        meta = self.ctx.fm.get_file_metadata(file_id)
        if not meta:
            self._set_status("File not found")
            return
        self.push_screen(
            EditFileModal(
                filename=meta.filename,
                tags=", ".join(meta.tags),
                description=meta.description or "",
            ),
            lambda res: self._handle_edit_file(res, meta),
        )

    def _handle_edit_file(self, result, meta):
        if not result:
            return
        try:
            meta.tags = [t.strip() for t in result.tags.split(",") if t.strip()]
            meta.description = result.description.strip() or None
            self.ctx.fm.file_model.update(meta)
            self.refresh_files()
            self._set_status("Updated file metadata")
        except Exception as exc:  # pragma: no cover
            self._set_status(f"Update failed: {exc}")

    def _persist_last_box(self, box_id: str) -> None:
        from shadowbox.frontend.cli.config_store import load_config, save_config

        cfg = load_config()
        cfg["last_box_id"] = box_id
        save_config(cfg)


if __name__ == "__main__":  # pragma: no cover
    ShadowBoxApp().run()
