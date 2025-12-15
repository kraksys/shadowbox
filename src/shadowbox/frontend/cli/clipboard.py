"""Clipboard utilities for the CLI frontend.

Uses pyperclip for cross-platform clipboard access.
"""

from __future__ import annotations

import pyperclip


def copy_to_clipboard(text: str) -> None:
    """Copy text to the system clipboard.

    Args:
        text: The text to copy.

    Raises:
        pyperclip.PyperclipException: If clipboard access fails.
    """
    pyperclip.copy(text)
