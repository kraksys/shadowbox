"""
Entry point to run the ShadowBox TUI app.
"""

import sys
from pathlib import Path

# Ensure the src/ directory is on sys.path so `import shadowbox` works
ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shadowbox.frontend.cli.app import ShadowBoxApp


def main() -> None:
    """Run the ShadowBox Textual CLI application."""
    ShadowBoxApp().run()


if __name__ == "__main__":
    main()
