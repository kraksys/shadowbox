"""Minimal Textual app scaffold for ShadowBox.

Start here with `python -m shadowbox.frontend.cli.app`
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Iterable, Optional

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
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
    Tree,
)

from shadowbox.core.models import BoxShare, FileMetadata
from shadowbox.database.models import BoxModel, BoxShareModel
from shadowbox.database.models import row_to_metadata
from shadowbox.database.search import fuzzy_search_fts, search_by_tag, tags_map
from shadowbox.frontend.cli.clipboard import copy_to_clipboard
from shadowbox.frontend.cli.context import AppContext, build_context
from shadowbox.network.adapter import init_env, select_box
from shadowbox.network.client import (
    cmd_delete,
    cmd_put,
    connect_and_request,
    get_server_address,
)
from shadowbox.network.server import (
    advertise_service,
    give_code,
    start_tcp_server,
    stop_server,
)


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

    def on_button_pressed(
        self, event: Button.Pressed
    ) -> None:  # pragma: no cover - UI only
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        path = self.path_input.value.strip()
        tags = [t.strip() for t in self.tags_input.value.split(",") if t.strip()]
        self.dismiss(
            AddFileResult(path=path, tags=tags, encrypt=self.encrypt_box.value)
        )

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            # trigger primary action
            path = self.path_input.value.strip()
            tags = [t.strip() for t in self.tags_input.value.split(",") if t.strip()]
            self.dismiss(
                AddFileResult(path=path, tags=tags, encrypt=self.encrypt_box.value)
            )


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


class InitialSetupResult:
    """Initial setup result - first box name and optional master key."""

    def __init__(self, box_name: str, master_key: str | None):
        self.box_name = box_name
        self.master_key = master_key


class InitialSetupModal(ModalScreen[Optional[InitialSetupResult]]):
    """First-run setup modal to configure initial box and master key."""

    def compose(self) -> ComposeResult:  # pragma: no cover - UI only
        with Vertical(classes="dialog"):
            yield Static("Initial Setup", classes="title")
            yield Label("Name for your first box")
            self.box_input = Input(
                placeholder="wikibooks-en or default", value="default"
            )
            yield self.box_input
            yield Label("Master key (optional - blank disables encryption)")
            self.master_input = Input(placeholder="••••••")
            yield self.master_input
            with Horizontal():
                yield Button("Skip", id="skip")
                yield Button("Save (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.box_input)

    def _submit(self) -> None:
        box_name = (self.box_input.value or "").strip() or "default"
        master = (self.master_input.value or "").strip()
        if not master:
            master = None
        self.dismiss(InitialSetupResult(box_name=box_name, master_key=master))

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "skip":
            self.dismiss(None)
        else:
            self._submit()

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()


class SetMasterPasswordModal(ModalScreen[Optional[str]]):
    """Modal to set the master password for encryption after initial setup."""

    def compose(self) -> ComposeResult:  # pragma: no cover - UI only
        with Vertical(classes="dialog"):
            yield Static("Set Master Password", classes="title")
            yield Label("This enables encryption for new boxes and files.")
            yield Label("Password")
            self.password_input = Input(placeholder="••••••", password=True)
            yield self.password_input
            yield Label("Confirm Password")
            self.confirm_input = Input(placeholder="••••••", password=True)
            yield self.confirm_input
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Set Password", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.password_input)

    def _submit(self) -> None:
        password = (self.password_input.value or "").strip()
        confirm = (self.confirm_input.value or "").strip()
        if not password:
            self.app.notify("Password cannot be empty", severity="error")
            return
        if password != confirm:
            self.app.notify("Passwords do not match", severity="error")
            return
        self.dismiss(password)

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._submit()

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()


class LiveSearchResult:
    """Result from live search - selected box and file."""

    def __init__(self, box_id: str, file_id: str):
        self.box_id = box_id
        self.file_id = file_id


class LiveSearchScreen(ModalScreen[Optional[LiveSearchResult]]):
    """Telescope-style live search with hierarchical results."""

    CSS = """
    LiveSearchScreen {
        align: center middle;
        background: rgba(0,0,0,0.6);
    }
    LiveSearchScreen > Vertical {
        width: 80%;
        height: 80%;
        padding: 1;
        border: heavy $surface;
        background: $boost;
    }
    LiveSearchScreen #search-input {
        margin-bottom: 1;
    }
    LiveSearchScreen #results-tree {
        height: 1fr;
    }
    LiveSearchScreen #status-line {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, ctx: "AppContext"):
        super().__init__()
        self.ctx = ctx
        self._debounce_timer = None
        # Cache: box_id -> box_name
        self._box_names: dict[str, str] = {}
        self._load_box_names()

    def _load_box_names(self) -> None:
        """Pre-load box names for display."""
        try:
            user_boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
            for box in user_boxes:
                self._box_names[box.box_id] = box.box_name
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Search Files", classes="title")
            yield Input(placeholder="Type to search...", id="search-input")
            yield Tree("Results", id="results-tree")
            yield Static("", id="status-line")

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        tree = self.query_one("#results-tree", Tree)
        tree.show_root = False

    @on(Input.Changed, "#search-input")
    def on_search_changed(self, event: Input.Changed) -> None:
        """Debounced live search as user types."""
        if self._debounce_timer:
            self._debounce_timer.stop()
        self._debounce_timer = self.set_timer(0.15, self._do_search)

    def _search_accessible_files(self, term: str, limit: int = 100):
        """Search files in all accessible boxes (owned + shared).
        
        Unlike fuzzy_search_fts which only searches user's own files,
        this includes files from boxes shared with the user.
        """
        # Build prefix-match tokens for FTS
        tokens = [t for t in term.strip().split() if t]
        if not tokens:
            return []
        fts_query = " ".join(t + "*" for t in tokens)
        
        user_id = self.ctx.user.user_id
        
        # Query that searches files the user can access:
        # - Files in boxes owned by the user, OR
        # - Files in boxes shared with the user (non-expired)
        sql = """
            SELECT DISTINCT f.*, bm25(files_fts) AS rank
            FROM files_fts
            JOIN files f ON f.file_id = files_fts.file_id
            JOIN boxes b ON f.box_id = b.box_id
            LEFT JOIN box_shares bs 
                ON bs.box_id = b.box_id 
                AND bs.shared_with_user_id = ?
            WHERE files_fts MATCH ?
              AND f.status != 'deleted'
              AND (
                  b.user_id = ? 
                  OR (
                      bs.share_id IS NOT NULL 
                      AND (bs.expires_at IS NULL OR bs.expires_at > CURRENT_TIMESTAMP)
                  )
              )
            ORDER BY rank
            LIMIT ?
        """
        
        rows = self.ctx.db.fetch_all(sql, (user_id, fts_query, user_id, limit))
        
        # Convert rows to FileMetadata with tags
        file_ids = [r["file_id"] for r in rows]
        tm = tags_map(self.ctx.db, file_ids)
        return [row_to_metadata(r, tm.get(r["file_id"], [])) for r in rows]

    def _do_search(self) -> None:
        """Execute search and update tree."""
        query = self.query_one("#search-input", Input).value.strip()
        tree = self.query_one("#results-tree", Tree)
        status = self.query_one("#status-line", Static)

        tree.clear()

        if not query:
            status.update("Type to search...")
            return

        try:
            # Search files in all accessible boxes (owned + shared)
            hits = self._search_accessible_files(query, limit=100)
        except Exception as exc:
            status.update(f"Search error: {exc}")
            return

        if not hits:
            status.update("No results")
            return

        # Group by box_id
        by_box: dict[str, list] = {}
        for f in hits:
            if f.box_id not in by_box:
                by_box[f.box_id] = []
            by_box[f.box_id].append(f)

        # Build tree
        file_count = 0
        for box_id, files in by_box.items():
            box_name = self._box_names.get(box_id, box_id[:8])
            box_node = tree.root.add(f"[bold]{box_name}[/bold]", expand=True)
            box_node.data = {"type": "box", "box_id": box_id}

            for f in files:
                size_str = _human_size(f.size)
                file_node = box_node.add_leaf(f"{f.filename}  [dim]{size_str}[/dim]")
                file_node.data = {
                    "type": "file",
                    "box_id": box_id,
                    "file_id": f.file_id,
                }
                file_count += 1

        status.update(f"{file_count} file(s) in {len(by_box)} box(es)")

    @on(Tree.NodeSelected, "#results-tree")
    def on_tree_selected(self, event: Tree.NodeSelected) -> None:
        """Handle selection - if file, dismiss with result."""
        node_data = event.node.data
        if not node_data:
            return

        if node_data.get("type") == "file":
            self.dismiss(
                LiveSearchResult(
                    box_id=node_data["box_id"],
                    file_id=node_data["file_id"],
                )
            )

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)


class FileVersionsModal(ModalScreen):
    """
    Simple dialog that lists versions (historical) for a file and lets the user pick one to restore
    """

    def __init__(self, filename, versions):
        super().__init__()
        self.filename = filename
        self.versions = versions
        self.list_view = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("Versions for : %s" % self.filename, classes="title")
            self.list_view = ListView()
            for row in self.versions:
                number = row.get("version_number", row.get("version", "?"))
                size = row.get("size", 0)
                created_at = row.get("created_at", "")
                label = "v%s . %s bytes . %s" % (number, size, created_at)
                item = ListItem(Static(label))
                self.list_view.append(item)
            yield self.list_view
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Restore (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:
        if self.list_view is not None:
            self.set_focus(self.list_view)

    def selected_version_id(self):
        if not self.list_view:
            return None
        if self.list_view.index is None:
            return None
        idx = self.list_view.index

        if idx < 0 or idx >= len(self.versions):
            return None

        row = self.versions[idx]
        return row.get("version_id")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        version_id = self.selected_version_id()
        if not version_id:
            self.dismiss(None)
            return
        self.dismiss(version_id)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            version_id = self.selected_version_id()
            if not version_id:
                self.dismiss(None)
            else:
                self.dismiss(version_id)


class TagSearchModal(ModalScreen):
    """
    Dialog to ask for a tag name and return it
    """

    def __init__(self):
        super().__init__()
        self.tag_input = None

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Static("Filter by Tag", classes="title")
            self.tag_input = Input(placeholder="tag name")
            yield self.tag_input
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Filter (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:
        if self.tag_input is not None:
            self.set_focus(self.tag_input)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        value = ""
        if self.tag_input is not None:
            value = self.tag_input.value.strip()
        self.dismiss(value or None)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            value = ""
            if self.tag_input is not None:
                value = self.tag_input.value.strip()
            self.dismiss(value or None)


class NewBoxResult:
    def __init__(self, name: str, description: str | None, encrypt: bool):
        self.name = name
        self.description = description
        self.encrypt = encrypt


class NewBoxModal(ModalScreen[Optional[NewBoxResult]]):
    def __init__(self, encrypt_ready: bool = True):
        super().__init__()
        # When False, the checkbox is disabled to reflect that the backend
        # encryption key has not been configured (FileManager.encryption_enabled).
        self.encrypt_ready = encrypt_ready

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("New Box", classes="title")
            self.name_input = Input(placeholder="box name")
            yield self.name_input
            self.desc_input = Input(placeholder="description (optional)")
            yield self.desc_input
            label = (
                "Encrypt box"
                if self.encrypt_ready
                else "Encryption unavailable (master key not set)"
            )
            self.encrypt_box = Checkbox(label, disabled=not self.encrypt_ready)
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


class AlertModal(ModalScreen[None]):
    """Simple alert modal with a title, message, and OK button."""

    def __init__(self, title: str, message: str):
        super().__init__()
        self.alert_title = title
        self.alert_message = message

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(self.alert_title, classes="title")
            yield Static("")
            yield Static(self.alert_message)
            yield Static("")
            with Horizontal():
                yield Button("OK", id="ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        self.dismiss(None)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key in ("escape", "enter"):
            self.dismiss(None)


class ReplaceShareConfirmModal(ModalScreen[Optional[bool]]):
    """Confirmation modal for replacing an existing share."""

    def __init__(self, current_box_name: str, new_box_name: str):
        super().__init__()
        self.current_box_name = current_box_name
        self.new_box_name = new_box_name

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Only one box can be shared at a time", classes="title")
            yield Static("")
            yield Static(f"Currently sharing: {self.current_box_name}")
            yield Static(f"New share: {self.new_box_name}")
            yield Static("")
            yield Static("Stop current share and start new one?")
            with Horizontal():
                yield Button("Cancel", id="cancel")
                yield Button("Replace", id="ok", variant="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        self.dismiss(event.button.id == "ok")

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


class ErrorModal(ModalScreen[None]):
    """Modal for displaying error messages prominently."""

    def __init__(self, title: str, message: str):
        super().__init__()
        self.error_title = title
        self.error_message = message

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(self.error_title, classes="title")
            yield Static(self.error_message)
            yield Static("")
            yield Button("OK", id="ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        self.dismiss(None)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key in ("escape", "enter"):
            self.dismiss(None)


class ShareBoxResult:
    """Result from the share modal - contains share type and write users."""

    def __init__(self, is_public: bool, write_usernames: list[str]):
        self.is_public = is_public
        self.write_usernames = write_usernames  # List of usernames with write access


class ShareBoxModal(ModalScreen[Optional[ShareBoxResult]]):
    """Modal to initiate sharing a box over LAN via mDNS."""

    def __init__(self, box_name: str):
        super().__init__()
        self.box_name = box_name

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static(f"Share Box: {self.box_name}", classes="title")
            yield Label("Share type:")
            self.public_checkbox = Checkbox(
                "Public (visible to everyone on LAN, read access)"
            )
            yield self.public_checkbox
            yield Label("Users with WRITE permission (comma-separated):")
            self.write_users_input = Input(placeholder="alice, bob, charlie")
            yield self.write_users_input
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Share (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.public_checkbox)

    def _submit(self) -> None:
        # Parse comma-separated usernames
        raw = self.write_users_input.value.strip()
        write_usernames = [u.strip() for u in raw.split(",") if u.strip()]
        self.dismiss(
            ShareBoxResult(
                is_public=self.public_checkbox.value, write_usernames=write_usernames
            )
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._submit()

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()


class ShareCodeModal(ModalScreen[None]):
    """Modal displaying the generated share code with copy functionality."""

    def __init__(
        self,
        code: str,
        box_name: str,
        write_usernames: list[str],
        owner: str,
        is_public: bool = False,
    ):
        super().__init__()
        self.code = code
        self.box_name = box_name
        self.write_usernames = write_usernames
        self.owner = owner
        self.is_public = is_public

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Box Shared!", classes="title")
            yield Static(f"Box: {self.box_name}")
            yield Static(f"Owner: {self.owner}")
            if self.is_public:
                yield Static("Access: Public (everyone can read)")
            if self.write_usernames:
                yield Static(f"Write access: {', '.join(self.write_usernames)}")
            else:
                yield Static("Write access: None (read-only)")
            yield Static("")
            if self.code:
                yield Static(f"Share Code: {self.code}", classes="title")
            else:
                yield Static("Public share (no code needed)", classes="title")
            yield Static("")
            with Horizontal():
                if self.code:
                    yield Button("Copy Code", id="copy")
                yield Button("Done", id="done", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "copy":
            try:
                copy_to_clipboard(self.code)
                self.notify("Code copied to clipboard!")
            except Exception:
                self.notify("Could not copy to clipboard", severity="error")
        else:
            self.dismiss(None)

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "enter":
            if self.code:
                try:
                    copy_to_clipboard(self.code)
                    self.notify("Code copied to clipboard!")
                except Exception:
                    self.notify("Could not copy to clipboard", severity="error")
            self.dismiss(None)
        elif event.key == "escape":
            self.dismiss(None)


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


class ConnectResult:
    """Result from connect modal - the 4-letter code entered."""

    def __init__(self, code: str):
        self.code = code


class ConnectModal(ModalScreen[Optional[ConnectResult]]):
    """Modal to enter a 4-letter share code to connect to a remote box."""

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Connect to Shared Box", classes="title")
            yield Label("Enter the 4-letter share code:")
            self.code_input = Input(placeholder="XXXX", max_length=4)
            yield self.code_input
            yield Static("")
            self.status_label = Static("")
            yield self.status_label
            with Horizontal():
                yield Button("Cancel (Esc)", id="cancel")
                yield Button("Connect (Enter)", id="ok", variant="primary")

    def on_mount(self) -> None:  # pragma: no cover
        self.set_focus(self.code_input)

    def _submit(self) -> None:
        code = self.code_input.value.strip().lower()
        if len(code) != 4:
            self.status_label.update("Code must be 4 characters")
            return
        self.dismiss(ConnectResult(code=code))

    def on_button_pressed(self, event: Button.Pressed) -> None:  # pragma: no cover
        if event.button.id == "cancel":
            self.dismiss(None)
        else:
            self._submit()

    def on_key(self, event) -> None:  # pragma: no cover
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "enter":
            self._submit()


class ConnectSuccessModal(ModalScreen[None]):
    """Modal showing successful connection to a remote box."""

    def __init__(self, code: str, ip: str, port: int, files_preview: str):
        super().__init__()
        self.code = code
        self.ip = ip
        self.port = port
        self.files_preview = files_preview

    def compose(self) -> ComposeResult:  # pragma: no cover
        with Vertical(classes="dialog"):
            yield Static("Connected!", classes="title")
            yield Static(f"Code: {self.code}")
            yield Static(f"Address: {self.ip}:{self.port}")
            yield Static("")
            yield Static("Files:")
            yield Static(self.files_preview or "(empty)")
            yield Static("")
            with Horizontal():
                yield Button("Close", id="close", variant="primary")

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
        ("g", "download", "Download"),
        ("d", "delete_file", "Delete"),
        ("/", "search", "Search"),
        ("n", "new_box", "New Box"),
        ("x", "delete_box", "Delete Box"),
        ("b", "box_info", "Box Info"),
        ("s", "share_box", "Share"),
        ("c", "connect", "Connect"),
        ("e", "edit_file", "Edit File"),
        ("v", "show_versions", "File Versions"),
        ("k", "backup_database", "Backup DB"),
        ("t", "filter_by_tag", "Filter by Tag"),
        ("m", "set_master_password", "Master Password"),
    ]

    def __init__(self, ctx: AppContext | None = None):
        self.ctx = ctx or build_context()
        super().__init__()

        self.boxes: ListView | None = None
        self.shared_boxes: ListView | None = None
        self.public_boxes: ListView | None = None
        self.table: DataTable | None = None
        self.status: Static | None = None
        self.row_keys: list[str] = []
        # Track active shares: box_id -> (zeroconf, info, code, is_public, stop_event, granted_user_ids)
        # granted_user_ids is a set of user_ids that were granted access during this session
        self.active_shares: dict[str, tuple] = {}
        # Track boxes currently being set up for sharing (loading state)
        self.pending_shares: set[str] = set()
        # Discovered public boxes on LAN: code -> {name, ip, port}
        self.discovered_public: dict[str, dict] = {}
        # Connected remote boxes: code -> {code, ip, port, name}
        self.connected_boxes: dict[str, dict] = {}
        # Currently active remote box (if any): {type, code, ip, port, name}
        self.active_remote_box: dict | None = None
        # Whether we're currently viewing a remote box's files
        self.viewing_remote: bool = False
        # Permission level for the currently active box ("read", "write", "admin", or "owner")
        self.active_box_permission: str = "owner"

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
                yield Static("Public Boxes (LAN)", classes="title")
                self.public_boxes = ListView(id="public")
                yield self.public_boxes
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
        # Discover public boxes immediately, then every 10 seconds
        self._discover_public_boxes()
        self.set_interval(10.0, self._discover_public_boxes)
        # Check connected box liveness every 30 seconds
        self.set_interval(30.0, self._check_connected_box_liveness)
        # extend share TTL every 3 seconds (shares expire after 10s without)
        self.set_interval(3.0, self._extend_share_expiration)

        # First-run setup: prompt for initial box and optional master key.
        if getattr(self.ctx, "first_run", False):
            self.push_screen(
                InitialSetupModal(),
                self._handle_initial_setup,
            )

    def _handle_initial_setup(self, result: Optional["InitialSetupResult"]) -> None:
        """
        Handle the first-run setup flow:

        - Optionally configure encryption via a master key
        - Create the initial box (encrypted or plain)
        - Activate it and refresh the UI
        """
        # Ensure we don't re-run the first-run flow in this session.
        self.ctx.first_run = False

        box = None

        # If the user skipped the dialog, create a default unencrypted box.
        if not result:
            try:
                box = self.ctx.fm.create_box(
                    user_id=self.ctx.user.user_id,
                    box_name="default",
                    description="Default box",
                )
            except Exception as exc:
                self._set_status(f"Initial setup skipped: {exc}")
                return
        else:
            # Configure encryption if a master key was provided.
            if result.master_key:
                try:
                    self.ctx.fm.setup_encryption(result.master_key)
                except Exception as exc:
                    # Surface encryption failures prominently but allow plain usage.
                    self.push_screen(
                        ErrorModal(
                            "Encryption Setup Failed",
                            f"Could not configure master key: {exc}",
                        )
                    )
                    self._set_status(
                        "Encryption setup failed; continuing without encryption"
                    )

            box_name = result.box_name or "default"
            try:
                box = self.ctx.fm.create_box(
                    user_id=self.ctx.user.user_id,
                    box_name=box_name,
                    description=f"Initial box '{box_name}'",
                    enable_encryption=bool(
                        result.master_key and self.ctx.fm.encryption_enabled
                    ),
                )
            except Exception as exc:
                self.push_screen(
                    ErrorModal(
                        "Initial Box Error",
                        f"Could not create box '{box_name}': {exc}",
                    )
                )
                self._set_status("Initial setup failed")
                return

        if not box:
            self._set_status("Initial setup did not create a box")
            return

        # Finalize: set active box and refresh UI.
        self.ctx.active_box = box
        self.refresh_boxes()
        self.refresh_files()
        self._set_status(f"Ready - active box: {box.box_name}")

    def refresh_boxes(self) -> None:
        assert self.boxes is not None
        self.boxes.clear()
        if self.shared_boxes:
            self.shared_boxes.clear()
        try:
            user_boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
        except Exception as exc:  # pragma: no cover - UI only
            self._set_status(f"Error loading boxes: {exc}")
            return

        for box in user_boxes:
            # Show indicator based on share status
            if box.box_id in self.pending_shares:
                indicator = r"\[...] "  # Loading/pending
            elif box.box_id in self.active_shares:
                _, _, code, is_public, _, _ = self.active_shares[box.box_id]
                indicator = r"\[P] " if is_public else f"\\[S:{code}] "
            else:
                indicator = ""
            item = ListItem(Static(f"{indicator}{box.box_name}"))
            item.data = box
            self.boxes.append(item)
        self.boxes.refresh()

        # Shared boxes: only show session-based remote connections (via code)
        if self.shared_boxes is not None:
            for code, info in self.connected_boxes.items():
                display = f"{info['name']} @ {info['ip']}"
                item = ListItem(Static(display))
                item.data = {"type": "remote", **info}
                self.shared_boxes.append(item)
            self.shared_boxes.refresh()

        # Keep selection aligned with active box.
        if self.ctx.active_box:
            for idx, item in enumerate(self.boxes.children):
                if (
                    getattr(item, "data", None)
                    and item.data.box_id == self.ctx.active_box.box_id
                ):
                    self.boxes.index = idx
                    break

    def refresh_files(self) -> None:
        assert self.table is not None
        # Clear existing rows but keep column definitions intact.
        self.table.clear(columns=False)
        self.row_keys = []
        self.viewing_remote = False

        if not self.ctx.active_box:
            self._set_status("No active box")
            return

        # Update permission level for active box
        self.active_box_permission = self._get_box_permission(self.ctx.active_box)

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
        # Trigger fresh discovery and liveness checks for all box sections
        self._discover_public_boxes()
        self._check_connected_box_liveness()
        self.refresh_boxes()
        self.refresh_files()

    def _clear_other_list_selections(self, active_list: ListView) -> None:
        """Clear selection highlight in all ListViews except the active one."""
        all_lists = [self.boxes, self.shared_boxes, self.public_boxes]
        for lv in all_lists:
            if lv is not None and lv is not active_list:
                lv.index = None

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        data = getattr(event.item, "data", None)
        if not data:
            return
        # Clear selection in other lists for mutual exclusivity
        self._clear_other_list_selections(event.list_view)
        # Remote/public box - show its files via network
        if isinstance(data, dict) and data.get("type") in ("remote", "public"):
            self.active_remote_box = data
            # Code-based connections (remote) assume write access, public boxes are read-only
            # Server will enforce actual permissions - show alert on failure
            default_perm = "write" if data.get("type") == "remote" else "read"
            self.active_box_permission = data.get("permission", default_perm)
            self._show_remote_box_files(data, show_modal=False)
            return
        # Local box - clear remote selection
        self.active_remote_box = None
        self.ctx.active_box = data
        self.active_box_permission = self._get_box_permission(data)
        self.refresh_files()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        data = getattr(event.item, "data", None)
        if not data:
            return
        # Clear selection in other lists for mutual exclusivity
        self._clear_other_list_selections(event.list_view)
        # Remote/public boxes - track selection but don't fetch on highlight
        if isinstance(data, dict) and data.get("type") in ("remote", "public"):
            self.active_remote_box = data
            # Code-based connections (remote) assume write access, public boxes are read-only
            default_perm = "write" if data.get("type") == "remote" else "read"
            self.active_box_permission = data.get("permission", default_perm)
            return
        # Local box - clear remote selection
        self.active_remote_box = None
        if data != self.ctx.active_box:
            self.ctx.active_box = data
            self.active_box_permission = self._get_box_permission(data)
            self.refresh_files()

    def _show_remote_box_files(
        self, remote_info: dict, show_modal: bool = False
    ) -> None:
        """Fetch and display files from a remote connected box (non-blocking).

        Args:
            remote_info: Dict with code, ip, port, name
            show_modal: If True, show ConnectSuccessModal after fetching (first connect or box info)
        """
        ip = remote_info["ip"]
        port = remote_info["port"]
        code = remote_info["code"]
        self._set_status(f"Fetching files from {code}...")
        self.run_worker(
            lambda: self._fetch_remote_files_worker(ip, port, code, show_modal),
            name="fetch_remote_files_worker",
            exclusive=True,
            thread=True,
        )

    def _fetch_remote_files_worker(
        self, ip: str, port: int, code: str, show_modal: bool = False
    ) -> dict:
        """Worker that fetches remote files (runs in thread)."""
        try:
            res = connect_and_request(ip, port, "LIST", timeout=5)
            files_text = (
                res.get("text", "").strip() if isinstance(res, dict) else str(res)
            )
            return {
                "success": True,
                "code": code,
                "ip": ip,
                "port": port,
                "files_text": files_text,
                "files_preview": files_text[:500] if files_text else "(empty)",
                "show_modal": show_modal,
            }
        except Exception as exc:
            return {"success": False, "code": code, "error": str(exc)}

    def _parse_remote_files(self, files_text: str) -> list[dict]:
        """Parse remote file list from backend format.

        New format: file_id: {Filename: name, Size: 123, Tags: ['tag1'], Status: active}
        Returns list of dicts with keys: file_id, filename, size, tags, status
        """
        import re

        files: list[dict] = []
        if not files_text:
            return files

        # New format uses ",\n" as separator, old format uses just "\n"
        # Try to detect format: if we see "{" it's likely new format
        if "{" in files_text:
            entries = files_text.split(",\n")
        else:
            entries = files_text.split("\n")

        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue

            # Try to parse new format: "file_id: {Filename: ..., Size: ..., Tags: ..., Status: ...}"
            match = re.match(r"^([^:]+):\s*\{(.+)\}$", entry)
            if match:
                file_id = match.group(1).strip()
                props_str = match.group(2)

                # Extract properties from the curly braces content
                filename = ""
                size = 0
                tags: list[str] = []
                status = "active"
                modified_at = ""

                # Parse Filename
                fn_match = re.search(r"Filename:\s*([^,]+?)(?:,|$)", props_str)
                if fn_match:
                    filename = fn_match.group(1).strip()

                # Parse Size
                size_match = re.search(r"Size:\s*(\d+)", props_str)
                if size_match:
                    size = int(size_match.group(1))

                # Parse Tags - format is Tags: ['tag1', 'tag2'] or Tags: []
                tags_match = re.search(r"Tags:\s*\[([^\]]*)\]", props_str)
                if tags_match:
                    tags_content = tags_match.group(1).strip()
                    if tags_content:
                        # Extract quoted strings
                        tags = re.findall(r"'([^']*)'", tags_content)

                # Parse Status
                status_match = re.search(r"Status:\s*(\w+)", props_str)
                if status_match:
                    status = status_match.group(1).strip()

                # Parse Modified - format is Modified: 2024-01-15T10:30:00 or datetime object str
                modified_match = re.search(r"Modified:\s*([^,}]+)", props_str)
                if modified_match:
                    modified_at = modified_match.group(1).strip()

                files.append(
                    {
                        "file_id": file_id,
                        "filename": filename,
                        "size": size,
                        "tags": tags,
                        "status": status,
                        "modified_at": modified_at,
                    }
                )
            else:
                # Fallback: try old format "filename: size"
                if ": " in entry:
                    parts = entry.rsplit(": ", 1)
                    if len(parts) == 2:
                        filename = parts[0]
                        try:
                            size = int(parts[1])
                            files.append(
                                {
                                    "file_id": filename,
                                    "filename": filename,
                                    "size": size,
                                    "tags": [],
                                    "status": "remote",
                                    "modified_at": "",
                                }
                            )
                        except ValueError:
                            files.append(
                                {
                                    "file_id": entry,
                                    "filename": entry,
                                    "size": 0,
                                    "tags": [],
                                    "status": "remote",
                                    "modified_at": "",
                                }
                            )
                else:
                    files.append(
                        {
                            "file_id": entry,
                            "filename": entry,
                            "size": 0,
                            "tags": [],
                            "status": "remote",
                            "modified_at": "",
                        }
                    )
        return files

    def _populate_remote_files(self, files: list[dict]) -> None:
        """Populate the table with remote file entries."""
        if self.table is None:
            return
        self.table.clear(columns=False)
        self.row_keys = []
        self.viewing_remote = True

        for f in files:
            tags_str = ", ".join(f["tags"]) if f["tags"] else "--"
            # Format modified_at - truncate datetime to just date+time if it's an ISO string
            modified_str = f.get("modified_at", "")
            if modified_str:
                # Try to format nicely - truncate microseconds if present
                if "." in modified_str:
                    modified_str = modified_str.split(".")[0]
                # Replace T with space for readability
                modified_str = modified_str.replace("T", " ")
            else:
                modified_str = "--"
            self.table.add_row(
                f["filename"],
                _human_size(f["size"]),
                tags_str,
                f["status"],
                modified_str,
                key=f["file_id"],
            )
            self.row_keys.append(f["file_id"])

        self._set_status(f"Remote box: {len(files)} file(s)")

    def _set_status(self, message: str) -> None:
        if self.status:
            self.status.update(message)

    def _get_box_permission(self, box) -> str:
        """Get the current user's permission level for a box."""
        if box.user_id == self.ctx.user.user_id:
            return "owner"
        # Check share permission from database
        shares = self.ctx.fm.box_share_model.list_by_box(box.box_id)
        for share in shares:
            if share["shared_with_user_id"] == self.ctx.user.user_id:
                return share["permission_level"]
        return "read"  # Default fallback

    def _has_write_permission(self) -> bool:
        """Check if current user has write permission on active box.

        Uses the stored permission level for both local and remote boxes.
        For remote boxes, permission defaults to 'read' unless the host
        grants higher access.
        """
        return self.active_box_permission in ("owner", "admin", "write")

    def _update_status(self) -> None:
        # pull fresh user quota for accuracy
        row = self.ctx.fm.user_model.get(self.ctx.user.user_id)
        if row:
            self.ctx.user.used_bytes = row.get("used_bytes", self.ctx.user.used_bytes)
            self.ctx.user.quota_bytes = row.get(
                "quota_bytes", self.ctx.user.quota_bytes
            )
        used = _human_size(self.ctx.user.used_bytes)
        total = _human_size(self.ctx.user.quota_bytes)
        box_name = self.ctx.active_box.box_name if self.ctx.active_box else "(none)"
        perm_display = self.active_box_permission.upper()
        self._set_status(
            f"User: {self.ctx.user.username} • Box: {box_name} [{perm_display}] • Files: {self.table.row_count} • Quota: {used}/{total}"
        )

    # === Actions ===

    def action_add_file(self) -> None:
        if not self.ctx.active_box:
            self._set_status("Create a box first")
            return
        if not self._has_write_permission():
            self._set_status(
                f"No write permission (current: {self.active_box_permission})"
            )
            return
        self._set_status("Adding file...")
        self.push_screen(
            AddFileModal(encrypt_ready=self.ctx.fm.encryption_enabled),
            self._handle_add_file,
        )

    def _handle_add_file(self, result: Optional["AddFileResult"]) -> None:
        if not result:
            return
        # Remote box: upload via network
        if self.active_remote_box is not None:
            ip = self.active_remote_box["ip"]
            port = self.active_remote_box["port"]
            self._set_status("Uploading to remote...")
            self.run_worker(
                lambda: self._remote_upload_worker(ip, port, result.path),
                name="remote_upload_worker",
                exclusive=True,
                thread=True,
            )
            return
        # Local box: use file manager
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
        if self.viewing_remote:
            # For remote files, file_id is actually the filename
            if not self.table or self.table.cursor_row is None:
                self._set_status("Select a file first")
                return
            filename = self.table.get_row_at(self.table.cursor_row)[0]
            self.push_screen(
                DownloadModal(),
                lambda res: self._handle_remote_download(res, filename),
            )
        else:
            self.push_screen(
                DownloadModal(),
                lambda res: self._handle_download(res, file_id),
            )

    def _handle_download(
        self, result: Optional["DownloadResult"], file_id: str
    ) -> None:
        if not result:
            return
        try:
            self.ctx.fm.get_file(file_id=file_id, destination_path=result.dest)
            self._set_status(f"Saved to {result.dest}")
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Download failed: {exc}")

    def _handle_remote_download(
        self, result: Optional["DownloadResult"], filename: str
    ) -> None:
        if not result or not self.active_remote_box:
            return
        ip = self.active_remote_box["ip"]
        port = self.active_remote_box["port"]
        self._set_status(f"Downloading {filename} from remote...")
        self.run_worker(
            lambda: self._remote_download_worker(ip, port, filename, result.dest),
            name="remote_download_worker",
            exclusive=True,
            thread=True,
        )

    def _remote_download_worker(
        self, ip: str, port: int, filename: str, dest_path: str
    ) -> dict:
        """Worker that downloads a file from a remote box."""
        try:
            # Stream bytes to dest path using network client's file mode
            res = connect_and_request(
                ip,
                port,
                f"GET {filename}",
                recv_file=True,
                out_path=dest_path,
                timeout=30,
            )
            if isinstance(res, dict) and res.get("status") == "ok":
                return {"success": True, "dest": dest_path, "filename": filename}
            else:
                error = (
                    res.get("error", "Unknown error")
                    if isinstance(res, dict)
                    else str(res)
                )
                return {"success": False, "error": error}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _remote_upload_worker(self, ip: str, port: int, local_path: str) -> dict:
        """Worker that uploads a file to a remote box."""
        try:
            res = cmd_put(ip, port, local_path, timeout=60)
            if isinstance(res, dict) and res.get("status") == "ok":
                return {"success": True, "path": local_path}
            else:
                error = (
                    res.get("error", res.get("reply", "Unknown error"))
                    if isinstance(res, dict)
                    else str(res)
                )
                return {"success": False, "error": error}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def _remote_delete_worker(self, ip: str, port: int, filename: str) -> dict:
        """Worker that deletes a file from a remote box."""
        try:
            res = cmd_delete(ip, port, filename, timeout=30)
            if isinstance(res, dict) and res.get("status") == "ok":
                text = res.get("text", "")
                if "ERROR" in text.upper():
                    return {"success": False, "error": text}
                return {"success": True, "filename": filename}
            else:
                error = (
                    res.get("error", "Unknown error")
                    if isinstance(res, dict)
                    else str(res)
                )
                return {"success": False, "error": error}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def action_delete_file(self) -> None:
        if not self._has_write_permission():
            self._set_status(
                f"No write permission (current: {self.active_box_permission})"
            )
            return
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        filename = self.table.get_row_at(self.table.cursor_row)[0] if self.table else ""
        prompt = f"Delete file '{filename}'?"
        self.push_screen(
            DeleteConfirmModal(prompt),
            lambda ok: self._handle_delete_file(ok, file_id, filename),
        )

    def _handle_delete_file(
        self, confirmed: bool, file_id: str, filename: str = ""
    ) -> None:
        if not confirmed:
            return
        # Remote box: delete via network
        if self.active_remote_box is not None:
            ip = self.active_remote_box["ip"]
            port = self.active_remote_box["port"]
            self._set_status("Deleting from remote...")
            self.run_worker(
                lambda: self._remote_delete_worker(ip, port, filename),
                name="remote_delete_worker",
                exclusive=True,
                thread=True,
            )
            return
        # Local box: use file manager
        try:
            self._set_status("Deleting...")
            self.ctx.fm.delete_file(file_id, soft=True)
            self.refresh_files()
            self._set_status("Deleted file")
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status(f"Delete failed: {exc}")

    def action_search(self) -> None:
        self.push_screen(LiveSearchScreen(self.ctx), self._handle_live_search)

    def _handle_live_search(self, result: Optional["LiveSearchResult"]) -> None:
        if not result:
            return
        # Switch to the selected box (only user's own boxes are searchable)
        try:
            all_boxes = self.ctx.fm.list_user_boxes(self.ctx.user.user_id)
            target_box = next((b for b in all_boxes if b.box_id == result.box_id), None)
            if target_box:
                self.ctx.active_box = target_box
                self.refresh_boxes()
                self.refresh_files()
                # Find and select the file in the table
                for idx, fid in enumerate(self.row_keys):
                    if fid == result.file_id:
                        self.table.move_cursor(row=idx)
                        break
                self._set_status(f"Jumped to {target_box.box_name}")
        except Exception as exc:
            self._set_status(f"Jump failed: {exc}")

    def action_filter_by_tag(self):
        """
        Ask the user for a tag name and filter files by that tag.
        """
        self.push_screen(TagSearchModal(), self._handle_filter_by_tag)

    def _search_accessible_by_tag(self, tag: str, box_id: str | None = None, limit: int = 200):
        """Search files by tag in all accessible boxes (owned + shared).
        
        Unlike search_by_tag which only searches user's own files,
        this includes files from boxes shared with the user.
        """
        tag = (tag or "").strip()
        if not tag:
            return []
        
        user_id = self.ctx.user.user_id
        
        sql = """
            SELECT DISTINCT f.*
            FROM files f
            JOIN tags t ON t.entity_type = 'file' AND t.entity_id = f.file_id
            JOIN boxes b ON f.box_id = b.box_id
            LEFT JOIN box_shares bs 
                ON bs.box_id = b.box_id 
                AND bs.shared_with_user_id = ?
            WHERE t.tag_name = ?
              AND f.status != 'deleted'
              AND (
                  b.user_id = ? 
                  OR (
                      bs.share_id IS NOT NULL 
                      AND (bs.expires_at IS NULL OR bs.expires_at > CURRENT_TIMESTAMP)
                  )
              )
        """
        params: list = [user_id, tag, user_id]
        
        if box_id:
            sql += " AND f.box_id = ?"
            params.append(box_id)
        
        sql += " ORDER BY f.created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = self.ctx.db.fetch_all(sql, tuple(params))
        
        # Convert rows to FileMetadata with tags
        file_ids = [r["file_id"] for r in rows]
        tm = tags_map(self.ctx.db, file_ids)
        return [row_to_metadata(r, tm.get(r["file_id"], [])) for r in rows]

    def _handle_filter_by_tag(self, tag):
        """
        Apply the tag filter and update the files table.
        """
        if not tag:
            return
        if not self.table:
            return

        try:
            box_id = None
            if self.ctx.active_box:
                box_id = self.ctx.active_box.box_id

            # Search files by tag in all accessible boxes (owned + shared)
            hits = self._search_accessible_by_tag(tag, box_id=box_id, limit=200)
        except Exception as exc:  # pragma: no cover - UI-only
            self._set_status("Tag search failed: %s" % exc)
            return

        self.table.clear(columns=False)
        self.row_keys = []

        for f in hits:
            tags_text = ", ".join(f.tags) if getattr(f, "tags", None) else "--"
            status = f.status.value if hasattr(f.status, "value") else str(f.status)
            if hasattr(f, "modified_at"):
                try:
                    modified = f.modified_at.isoformat(timespec="seconds")
                except Exception:
                    modified = str(f.modified_at)
            else:
                modified = ""

            self.table.add_row(
                f.filename,
                _human_size(getattr(f, "size", 0)),
                tags_text,
                status,
                modified,
                key=f.file_id,
            )
            self.row_keys.append(f.file_id)

        self._set_status("Tag '%s': %d result(s)" % (tag, len(hits)))

    # Box CRUD
    def action_new_box(self) -> None:
        # Only allow the "encrypt" toggle when the backend encryption key
        # has been configured via FileManager (master password set).
        self.push_screen(
            NewBoxModal(encrypt_ready=self.ctx.fm.encryption_enabled),
            self._handle_new_box,
        )

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
            self.refresh_files()
            self._set_status(f"Created box {box.box_name}")
        except Exception as exc:
            self._set_status(f"Create box failed: {exc}")

    def action_set_master_password(self) -> None:
        """Open modal to set master password for encryption."""
        if self.ctx.fm.encryption_enabled:
            self.push_screen(
                AlertModal(
                    "Already Configured",
                    "Master password is already set. Encryption is enabled.",
                )
            )
            return
        self.push_screen(SetMasterPasswordModal(), self._handle_set_master_password)

    def _handle_set_master_password(self, password: str | None) -> None:
        if not password:
            return
        try:
            self.ctx.fm.setup_encryption(password)
            self.notify("Encryption enabled successfully!", severity="information")
            self._set_status("Master password set - encryption now available")
        except Exception as exc:
            self.push_screen(
                AlertModal(
                    "Encryption Setup Failed",
                    f"Could not configure master password: {exc}",
                )
            )

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
            self.ctx.active_box = None
            if boxes:
                self.ctx.active_box = boxes[0]
            self.refresh_boxes()
            self.refresh_files()
            msg = "Box deleted"
            if not self.ctx.active_box:
                msg += " (no boxes left)"
            self._set_status(msg)
        except Exception as exc:
            self._set_status(f"Delete failed: {exc}")

    def action_box_info(self) -> None:
        # Handle remote box info - show modal with connection details
        if self.active_remote_box:
            self._show_remote_box_files(self.active_remote_box, show_modal=True)
            return
        # Local box info
        if not self.ctx.active_box:
            return
        info = self.ctx.fm.get_box_info(
            self.ctx.user.user_id, self.ctx.active_box.box_id
        )
        self.push_screen(BoxInfoModal(self.ctx.active_box, info))

    # Sharing via mDNS
    def action_share_box(self) -> None:
        if not self.ctx.active_box:
            return
        if self.ctx.active_box.user_id != self.ctx.user.user_id:
            self._set_status("Only owners can share boxes")
            return
        # Toggle off if this box is already shared
        if self.ctx.active_box.box_id in self.active_shares:
            self._stop_sharing(self.ctx.active_box.box_id)
            return
        if self.ctx.active_box.box_id in self.pending_shares:
            self.notify("Share already in progress", severity="warning")
            return
        # Check if another box is already shared (backend limitation: single TCP server)
        if self.active_shares:
            # Get the name of the currently shared box
            current_box_id = next(iter(self.active_shares.keys()))
            current_box_name = None
            for box in self.ctx.fm.list_user_boxes(self.ctx.user.user_id):
                if box.box_id == current_box_id:
                    current_box_name = box.box_name
                    break
            current_box_name = current_box_name or "Unknown"
            self.push_screen(
                ReplaceShareConfirmModal(current_box_name, self.ctx.active_box.box_name),
                self._handle_replace_share_confirm,
            )
            return
        self._show_share_modal()

    def _handle_replace_share_confirm(self, confirmed: bool) -> None:
        if not confirmed:
            return
        # Stop existing share and proceed with new one
        for existing_box_id in list(self.active_shares.keys()):
            self._stop_sharing(existing_box_id)
        self._show_share_modal()

    def _show_share_modal(self) -> None:
        """Show the share configuration modal."""
        self.push_screen(
            ShareBoxModal(self.ctx.active_box.box_name), self._handle_share_box
        )

    def _handle_share_box(self, result: Optional["ShareBoxResult"]) -> None:
        if not result:
            return
        # Mark as pending and refresh UI immediately
        box_id = self.ctx.active_box.box_id
        box_name = self.ctx.active_box.box_name
        username = self.ctx.user.username
        self.pending_shares.add(box_id)
        self.refresh_boxes()

        # Run the blocking mDNS work in a background thread
        self.run_worker(
            lambda: self._do_share_worker(box_id, box_name, result, username),
            name="share_worker",
            exclusive=True,
            thread=True,
        )

    def _do_share_worker(
        self, box_id: str, box_name: str, result: "ShareBoxResult", username: str
    ) -> dict:
        """Worker that does the actual server startup and mDNS registration (runs in thread)."""
        try:
            # Generate 4-letter code for private, empty for public (uses base service type)
            if result.is_public:
                code = (
                    ""  # Empty = base _shadowbox._tcp.local. (one public box per user)
                )
            else:
                code = give_code()

            # Build service type with code embedded
            service_type = f"_shadowbox{code}._tcp.local."

            # Create server environment using the TUI's database
            db_path = str(self.ctx.fm.db.db_path)
            storage_root = (
                str(self.ctx.fm.storage.root)
                if hasattr(self.ctx.fm.storage, "root")
                else None
            )
            # reuse FileManager Storage so encryption keys are available inside the sharing server env
            env = init_env(
                db_path=db_path,
                storage_root=storage_root,
                username=username,
                storage=self.ctx.fm.storage,
            )
            select_box(env, box_name)

            # Create share records for each write user BEFORE starting server
            # short TTL (10s), will extend while share is active
            # If host crashes, shares auto-expire without manual cleanup
            share_errors = []
            granted_user_ids: set[str] = set()
            bsm = BoxShareModel(env["db"])
            bm = BoxModel(env["db"])
            
            for write_user in result.write_usernames:
                try:
                    # Create user if doesn't exist by calling init_env with their username
                    user_env = init_env(
                        db_path=db_path, storage_root=storage_root, username=write_user
                    )
                    
                    # Delete any existing share first (to update expiration)
                    bsm.delete_by_box_and_user(env["box_id"], user_env["user_id"])
                    
                    # Create share with 10-second TTL
                    share = BoxShare(
                        box_id=env["box_id"],
                        shared_by_user_id=env["user_id"],
                        shared_with_user_id=user_env["user_id"],
                        permission_level="write",
                        expires_at=datetime.utcnow() + timedelta(seconds=10),
                    )
                    bsm.create(share)
                    bm.set_shared(env["box_id"], True)
                    
                    # Track for extension
                    granted_user_ids.add(user_env["user_id"])
                except Exception as e:
                    share_errors.append(f"{write_user}: {e}")

            context = {"mode": "core", "env": env}

            # Advertise the service
            server_name = (
                f"FileServer-{username}" if result.is_public else f"FileServer-{code}"
            )
            zeroconf, info = advertise_service(server_name, 9999, service_type)

            # Create stop event for this server
            server_stop_event = threading.Event()

            # Start TCP server in a daemon thread
            def run_server():
                start_tcp_server(context, 9999)

            server_thread = threading.Thread(target=run_server, daemon=True)
            server_thread.start()

            return {
                "success": True,
                "box_id": box_id,
                "box_name": box_name,
                "code": code,
                "is_public": result.is_public,
                "write_usernames": result.write_usernames,
                "granted_user_ids": granted_user_ids,
                "share_errors": share_errors,
                "username": username,
                "zeroconf": zeroconf,
                "info": info,
                "stop_event": server_stop_event,
            }
        except Exception as exc:
            return {
                "success": False,
                "box_id": box_id,
                "error": str(exc),
            }

    def _stop_sharing(self, box_id: str) -> None:
        """Stop sharing a box and cleanup mDNS registration and TCP server.
        
        Note: Database share records use TTL and will auto-expire in ~10 seconds.
        No manual cleanup needed - just stop sharing by removing from active_shares.
        """
        if box_id not in self.active_shares:
            return
        zeroconf, info, code, is_public, stop_event, _ = self.active_shares[box_id]
        
        try:
            # Stop the TCP server
            stop_server()
            # Unregister mDNS service
            zeroconf.unregister_service(info)
            zeroconf.close()
        except Exception:
            pass
        
        del self.active_shares[box_id]
        self.refresh_boxes()
        if is_public:
            self.notify("Stopped public sharing")
        else:
            self.notify(f"Stopped sharing (code: {code})")

    # Connect to remote box via 4-letter code
    def action_connect(self) -> None:
        self.push_screen(ConnectModal(), self._handle_connect)

    def _handle_connect(self, result: Optional["ConnectResult"]) -> None:
        if not result:
            return
        code = result.code
        self._set_status(f"Searching for {code}...")
        # Run the blocking discovery in a background thread
        self.run_worker(
            lambda: self._do_connect_worker(code),
            name="connect_worker",
            exclusive=True,
            thread=True,
        )

    def _do_connect_worker(self, code: str) -> dict:
        """Worker that does the actual mDNS lookup and TCP connection (runs in thread)."""
        try:
            # Use backend API for service discovery
            result = get_server_address(code, timeout=5.0)

            if not result:
                return {"success": False, "code": code, "error": "not_found"}

            ip, port = result

            # Try to connect and list files
            res = connect_and_request(ip, port, "LIST")
            files_text = (
                res.get("text", "").strip() if isinstance(res, dict) else str(res)
            )

            return {
                "success": True,
                "code": code,
                "ip": ip,
                "port": port,
                "files_preview": files_text[:500] if files_text else "(empty)",
            }
        except Exception as exc:
            return {"success": False, "code": code, "error": str(exc)}

    # Edit file metadata (tags + description)
    def action_edit_file(self) -> None:
        if not self._has_write_permission():
            self._set_status(
                f"No write permission (current: {self.active_box_permission})"
            )
            return
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

    def action_show_versions(self):
        """Show a list of historical versions for the selected file. User can pick one version to restore as the active file"""
        file_id = self._selected_file_id()
        if not file_id:
            self._set_status("Select a file first")
            return
        try:
            versions = self.ctx.fm.list_file_versions(file_id)
        except Exception as exc:
            self._set_status("Load versions failed: %s" % exc)
            return
        if not versions:
            self._set_status("No versions for this file")
            return

        meta = self.ctx.fm.get_file_metadata(file_id)
        filename = meta.filename if meta else file_id

        self.push_screen(
            FileVersionsModal(filename, versions),
            lambda version_id: self._handle_restore_version(file_id, version_id),
        )

    def _handle_restore_version(self, file_id, version_id):
        """Apply the chosen (historical) version if exists, and refresh the table"""
        if not version_id:
            return
        try:
            ok = self.ctx.fm.restore_file_version(file_id, version_id)
            if not ok:
                self._set_status("Restore failed")
                return
            self.refresh_files()
            self._set_status("Restored Version")
        except Exception as exc:
            self._set_status("Restore failed: %s" % exc)

    def action_backup_database(self):
        """Create a simple copy backup of the SQLite DB File"""
        import datetime
        import os

        try:
            now = datetime.datetime.utcnow()
            name = "backup-%s.sqlite" % now.strftime("%Y%m%d-%H%M%S")
            dest_path = os.path.join(os.getcwd(), name)

            self.ctx.db.backup(dest_path)
            self._set_status("Backup saved to %s" % dest_path)
        except Exception as exc:
            self._set_status("Backup Failed: %s" % exc)

    def _cleanup_shares(self) -> None:
        """Cleanup all active mDNS shares and TCP servers on exit.
        
        Note: Database share records use TTL and will auto-expire.
        No manual cleanup needed - if we crash, shares expire in ~10 seconds.
        """
        for box_id in list(self.active_shares.keys()):
            zeroconf, info, _, _, _, _ = self.active_shares[box_id]
            try:
                stop_server()
                zeroconf.unregister_service(info)
                zeroconf.close()
            except Exception:
                pass
        self.active_shares.clear()

    def _extend_share_expiration(self) -> None:
        """extend TTL of all active session shares.
        
        Runs every 3 seconds to keep shares alive while host is running.
        If host crashes, shares auto-expire after ~10 seconds.
        """
        if not self.active_shares:
            return
        
        new_expiry = datetime.utcnow() + timedelta(seconds=10)
        
        for box_id, (_, _, _, _, _, granted_user_ids) in self.active_shares.items():
            for user_id in granted_user_ids:
                try:
                    self.ctx.db.execute(
                        "UPDATE box_shares SET expires_at = ? WHERE box_id = ? AND shared_with_user_id = ?",
                        (new_expiry.isoformat(), box_id, user_id),
                    )
                except Exception:
                    # Best effort - if DB is busy, next extension will catch it
                    pass

    def _discover_public_boxes(self) -> None:
        """Background discovery for public boxes on LAN (non-blocking)."""
        # Use run_worker to avoid blocking the UI
        self.run_worker(
            self._discover_public_boxes_worker,
            name="_discover_public_boxes_worker",
            exclusive=True,
            thread=True,
        )

    def _discover_public_boxes_worker(self) -> dict[str, dict]:
        """Worker that does the actual discovery (runs in thread)."""
        import socket
        import time

        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf

        discovered: dict[str, dict] = {}
        base_service_type = "_shadowbox._tcp.local."

        try:
            zc = Zeroconf()

            class Listener(ServiceListener):
                def add_service(
                    self, zeroconf: Zeroconf, type_: str, name: str
                ) -> None:
                    # All services on base _shadowbox._tcp.local. are public
                    info = zeroconf.get_service_info(type_, name, timeout=1000)
                    if info and info.addresses:
                        ip = None
                        for packed in info.addresses:
                            if len(packed) == 4:
                                ip = socket.inet_ntoa(packed)
                                break
                        if ip:
                            # Extract username from "FileServer-{username}._shadowbox._tcp.local."
                            owner = name.split(".")[0].replace("FileServer-", "")
                            discovered[name] = {
                                "name": owner,
                                "ip": ip,
                                "port": info.port,
                            }

                def remove_service(self, _zc: Zeroconf, _type: str, _name: str) -> None:
                    pass

                def update_service(self, _zc: Zeroconf, _type: str, _name: str) -> None:
                    pass

            listener = Listener()
            browser = ServiceBrowser(zc, base_service_type, listener)
            time.sleep(1.5)  # OK to block here - we're in a worker thread
            browser.cancel()
            zc.close()
        except Exception:
            pass
        return discovered

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion to update UI."""
        if not event.worker.is_finished:
            return

        worker_name = event.worker.name
        result = event.worker.result

        # Handle public box discovery completion
        if worker_name == "_discover_public_boxes_worker":
            new_discovered = result if result is not None else {}
            # Check if active public box is no longer available
            if (
                self.active_remote_box
                and self.active_remote_box.get("type") == "public"
            ):
                active_code = self.active_remote_box.get("code")
                if active_code and active_code not in new_discovered:
                    self.active_remote_box = None
                    self.viewing_remote = False
                    self.refresh_files()
                    self.notify("Public box is no longer available", severity="warning")
            
            # Cross-reference: remove connected boxes whose IP now has a different/public share
            # This handles the case where sharer stopped and reshared with a new code
            discovered_ips = {info["ip"] for info in new_discovered.values()}
            stale_connected = []
            for code, info in self.connected_boxes.items():
                if info["ip"] in discovered_ips:
                    # Same IP is now advertising a (possibly different) public share
                    # The old code-based connection is stale
                    stale_connected.append(code)
            if stale_connected:
                for code in stale_connected:
                    del self.connected_boxes[code]
                # Check if active remote box was removed
                if (
                    self.active_remote_box
                    and self.active_remote_box.get("type") == "remote"
                    and self.active_remote_box.get("code") in stale_connected
                ):
                    self.active_remote_box = None
                    self.viewing_remote = False
                    self.refresh_files()
                self.refresh_boxes()
                self.notify(
                    f"Removed {len(stale_connected)} stale connection(s) (reshared)",
                    severity="warning",
                )
            
            self.discovered_public = new_discovered
            self._refresh_public_boxes()

        # Handle liveness check completion
        elif worker_name == "_check_liveness_worker" and result:
            stale_codes = result
            if stale_codes:
                # Check if active remote box is being removed
                active_removed = (
                    self.active_remote_box
                    and self.active_remote_box.get("code") in stale_codes
                )
                for code in stale_codes:
                    if code in self.connected_boxes:
                        del self.connected_boxes[code]
                self.refresh_boxes()
                # Clear file view if active box was removed
                if active_removed:
                    self.active_remote_box = None
                    self.viewing_remote = False
                    self.refresh_files()
                self.notify(
                    f"Removed {len(stale_codes)} unreachable box(es)",
                    severity="warning",
                )

        # Handle share worker completion
        elif worker_name == "share_worker" and result:
            if result.get("success"):
                box_id = result["box_id"]
                self.pending_shares.discard(box_id)
                self.active_shares[box_id] = (
                    result["zeroconf"],
                    result["info"],
                    result["code"],
                    result["is_public"],
                    result["stop_event"],
                    result.get("granted_user_ids", set()),
                )
                self.refresh_boxes()

                # Show any share errors
                if result.get("share_errors"):
                    for err in result["share_errors"]:
                        self.notify(err, title="Share Warning", severity="warning")

                if result["is_public"]:
                    self.notify("Box is now public on LAN", title="Shared")

                # Show the share code modal (for both public and private)
                self.push_screen(
                    ShareCodeModal(
                        code=result["code"],
                        box_name=result["box_name"],
                        write_usernames=result.get("write_usernames", []),
                        owner=result["username"],
                        is_public=result["is_public"],
                    )
                )
            else:
                self.pending_shares.discard(result.get("box_id", ""))
                self.refresh_boxes()
                self.notify(
                    f"Share failed: {result.get('error')}",
                    title="Error",
                    severity="error",
                )

        # Handle connect worker completion
        elif worker_name == "connect_worker" and result:
            if result.get("success"):
                code = result["code"]
                # Store the connection
                self.connected_boxes[code] = {
                    "code": code,
                    "ip": result["ip"],
                    "port": result["port"],
                    "name": f"Remote ({code})",
                }
                self._set_status(f"Connected to {code}")
                self.refresh_boxes()
                self.push_screen(
                    ConnectSuccessModal(
                        code=code,
                        ip=result["ip"],
                        port=result["port"],
                        files_preview=result["files_preview"],
                    )
                )
            else:
                error = result.get("error", "unknown")
                if error == "not_found":
                    self.notify(
                        f"No share found with code: {result['code']}",
                        title="Not Found",
                        severity="warning",
                    )
                elif error == "no_ip":
                    self.notify(
                        "Could not resolve address", title="Error", severity="error"
                    )
                else:
                    self.notify(
                        f"Connection failed: {error}", title="Error", severity="error"
                    )
                self._set_status("Connection failed")

        # Handle fetch remote files worker completion
        elif worker_name == "fetch_remote_files_worker" and result:
            if result.get("success"):
                # Parse and display files in the table
                files_text = result.get("files_text", "")
                parsed_files = self._parse_remote_files(files_text)
                self._populate_remote_files(parsed_files)
                # Only show modal on first connect or when box info is requested
                if result.get("show_modal"):
                    self.push_screen(
                        ConnectSuccessModal(
                            code=result["code"],
                            ip=result["ip"],
                            port=result["port"],
                            files_preview=result["files_preview"],
                        )
                    )
            else:
                self._set_status(f"Failed to fetch files: {result.get('error')}")

        # Handle remote download worker completion
        elif worker_name == "remote_download_worker" and result:
            if result.get("success"):
                self._set_status(f"Saved {result['filename']} to {result['dest']}")
            else:
                self._set_status(f"Download failed: {result.get('error')}")

        # Handle remote upload worker completion
        elif worker_name == "remote_upload_worker" and result:
            if result.get("success"):
                self._set_status(f"Uploaded {result['path']}")
                # Refresh the remote file list
                if self.active_remote_box:
                    self._show_remote_box_files(
                        self.active_remote_box, show_modal=False
                    )
            else:
                self._set_status(f"Upload failed: {result.get('error')}")

        # Handle remote delete worker completion
        elif worker_name == "remote_delete_worker" and result:
            if result.get("success"):
                self._set_status(f"Deleted {result['filename']}")
                # Refresh the remote file list
                if self.active_remote_box:
                    self._show_remote_box_files(
                        self.active_remote_box, show_modal=False
                    )
            else:
                self._set_status(f"Delete failed: {result.get('error')}")

    def _refresh_public_boxes(self) -> None:
        """Update the public boxes list in the sidebar."""
        if self.public_boxes is None:
            return
        self.public_boxes.clear()
        for code, info in self.discovered_public.items():
            display = f"{info['name']} @ {info['ip']}"
            item = ListItem(Static(display))
            item.data = {"type": "public", "code": code, **info}
            self.public_boxes.append(item)
        self.public_boxes.refresh()

    def _check_connected_box_liveness(self) -> None:
        """Check if connected remote boxes are still reachable (non-blocking)."""
        if not self.connected_boxes:
            return
        self.run_worker(
            self._check_liveness_worker,
            name="_check_liveness_worker",
            exclusive=True,
            thread=True,
        )

    def _check_liveness_worker(self) -> list[str]:
        """Worker that checks liveness of connected boxes (runs in thread)."""
        stale_codes: list[str] = []
        for code, info in list(self.connected_boxes.items()):
            try:
                # Quick TCP connect check with short timeout
                connect_and_request(info["ip"], info["port"], "PING", timeout=2)
            except Exception:
                stale_codes.append(code)
        return stale_codes

    def action_quit(self) -> None:
        """Override quit to cleanup shares first."""
        self._cleanup_shares()
        self.exit()


if __name__ == "__main__":  # pragma: no cover
    ShadowBoxApp().run()
