"""Lightweight logging setup for the TUI."""

import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    # Configure root logger once; keep output simple for terminals.
    logging.basicConfig(
        level=level,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )

