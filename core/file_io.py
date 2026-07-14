"""
core/file_io.py
===============
File I/O utilities for the UVM transpiler suite.

Features:
  - Read SV files as list of lines
  - Write modified lines back in-place
  - Automatic backup to <file>.sv.bak before writing
  - Dry-run mode (simulate without writing)
"""
from __future__ import annotations

import shutil
from pathlib import Path


def read_lines(path: "str | Path") -> list[str]:
    """Read a file and return its lines (preserving line endings)."""
    path = Path(path)
    return path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)


def write_lines(
    path: "str | Path",
    lines: list[str],
    backup: bool = True,
    dry_run: bool = False,
) -> bool:
    """
    Write lines back to a file in-place.

    Parameters
    ----------
    path:    Target file path.
    lines:   New content as a list of strings (with or without newlines).
    backup:  If True (default), copy the original to ``<path>.bak`` first.
    dry_run: If True, do nothing and return True without writing.

    Returns
    -------
    True if the file was written (or dry_run is True), False on error.
    """
    path = Path(path)
    if dry_run:
        return True

    if backup and path.exists():
        bak = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, bak)

    # Ensure all lines end with a newline
    normalised: list[str] = []
    for i, line in enumerate(lines):
        if not line.endswith("\n") and i < len(lines) - 1:
            normalised.append(line + "\n")
        else:
            normalised.append(line)

    path.write_text("".join(normalised), encoding="utf-8")
    return True


def collect_sv_files(root: "str | Path", recursive: bool = False) -> list[Path]:
    """Return a sorted list of .sv files under root."""
    root = Path(root)
    if root.is_file():
        return [root] if root.suffix == ".sv" else []
    pattern = "**/*.sv" if recursive else "*.sv"
    return sorted(root.glob(pattern))
