"""
scripts/constructor_checker.py
==============================
Script 3 — UVM Constructor Checker and Generator.

For each class:
  - If `new()` is ABSENT → generate and inject a complete constructor
    (correct signature + super.new call), placed after the factory macros
  - If `new()` is PRESENT:
      - Check the signature (parameter types, default values)
      - Check that super.new(...) is called
      - Fix signature / insert super.new if necessary (with warning)

Expected signatures:
  uvm_component: function new(string name = "ClassName", uvm_component parent = null);
  uvm_object:    function new(string name = "ClassName");

Usage::

    python -m scripts.constructor_checker path/to/sv/ [options]

"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.sv_parser import parse_file, SVClass, SVFunction
from core.uvm_taxonomy import UVMTaxonomy, UVMFamily
from core.file_io import read_lines, write_lines, collect_sv_files
from core.reporter import Reporter, ActionType


# ---------------------------------------------------------------------------
# Constructor generation
# ---------------------------------------------------------------------------

def _generate_constructor(cls: SVClass, family: UVMFamily, indent: str) -> list[str]:
    """
    Generate a complete constructor block for a class.

    Returns a list of lines (with newlines).
    """
    i2 = indent + "  "
    if family == UVMFamily.COMPONENT:
        return [
            f"{indent}function new(string name = \"{cls.name}\", uvm_component parent = null);\n",
            f"{i2}super.new(name, parent);\n",
            f"{indent}endfunction\n",
            "\n",
        ]
    else:  # OBJECT
        return [
            f"{indent}function new(string name = \"{cls.name}\");\n",
            f"{i2}super.new(name);\n",
            f"{indent}endfunction\n",
            "\n",
        ]


# ---------------------------------------------------------------------------
# Constructor analysis helpers
# ---------------------------------------------------------------------------

_RE_NEW_FUNC = re.compile(
    r"function\s+new\s*\(([^)]*)\)\s*;",
    re.DOTALL,
)
_RE_SUPER_NEW = re.compile(r"\bsuper\s*\.\s*new\s*\(")


def _find_insertion_point(lines: list[str], cls: SVClass) -> int:
    """
    Find the best insertion point for a new constructor.

    Preferred: just after the last factory/field macro line (or begin/end block).
    Fallback: just after the class header line.

    Returns 0-indexed line index (insert BEFORE this index).
    """
    start = cls.start_line - 1  # 0-indexed
    end = cls.end_line - 1      # 0-indexed

    # Find the last macro line in the class body
    last_macro_idx = start + 1  # default: after class header
    for i in range(start + 1, min(end, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith("`uvm_") or stripped.startswith("`UVM_"):
            last_macro_idx = i + 1

    return last_macro_idx  # insert after this line (0-indexed)


def _check_and_fix_constructor(
    lines: list[str],
    cls: SVClass,
    func: SVFunction,
    family: UVMFamily,
    reporter: Reporter,
    path: Path,
    dry_run: bool,
) -> tuple[list[str], bool]:
    """
    Verify and potentially fix an existing constructor.

    Returns (modified_lines, was_modified).
    """
    modified = False
    func_start = func.start_line - 1  # 0-indexed

    # --- Check signature ---
    func_line = lines[func_start]
    expected_name_default = f'"{cls.name}"'

    # Check if default name is correct
    if expected_name_default not in func_line:
        # Try to fix it
        new_func_line = re.sub(
            r'(string\s+name\s*=\s*)"[^"]*"',
            rf'\1"{cls.name}"',
            func_line,
        )
        if new_func_line != func_line:
            if not dry_run:
                lines[func_start] = new_func_line
            modified = True
            reporter.add_action(
                path, cls.name, ActionType.CONSTRUCTOR_FIXED,
                detail=f"Fixed default name to \"{cls.name}\"",
                line=func.start_line,
            )

    # --- Check super.new ---
    if not func.has_super_call:
        # Insert super.new as first statement in the function body
        body_start = func_start + 1
        # Determine indentation
        indent = re.match(r"(\s*)", func_line).group(1) + "  "
        if family == UVMFamily.COMPONENT:
            super_line = f"{indent}super.new(name, parent);\n"
        else:
            super_line = f"{indent}super.new(name);\n"

        if not dry_run:
            lines.insert(body_start, super_line)
        modified = True
        reporter.add_action(
            path, cls.name, ActionType.CONSTRUCTOR_FIXED,
            detail="Inserted missing super.new call",
            line=body_start + 1,
        )
        reporter.add_warning(
            path, cls.name,
            f"Constructor was missing super.new() call — inserted automatically."
        )

    return lines, modified


# ---------------------------------------------------------------------------
# Per-file processor
# ---------------------------------------------------------------------------

def process_file(
    path: Path,
    taxonomy: UVMTaxonomy,
    reporter: Reporter,
    backup: bool = True,
    dry_run: bool = False,
) -> None:
    """Process a single .sv file for constructor issues."""
    reporter.start_file(path)
    lines = read_lines(path)
    classes = parse_file(path)

    modified = False

    for cls in classes:
        family = taxonomy.resolve(cls.parent)
        reporter.start_class(path, cls.name, family.name)

        if family == UVMFamily.UNKNOWN:
            continue

        constructor = cls.constructor

        if constructor is None:
            # --- ABSENT: inject constructor ---
            insert_idx = _find_insertion_point(lines, cls)

            # Determine indentation from class header
            class_line = lines[cls.start_line - 1]
            indent = re.match(r"(\s*)", class_line).group(1) + "  "

            ctor_lines = _generate_constructor(cls, family, indent)

            if not dry_run:
                lines = lines[:insert_idx] + ctor_lines + lines[insert_idx:]

            reporter.add_action(
                path, cls.name, ActionType.CONSTRUCTOR_ADDED,
                line=insert_idx + 1,
                detail=f"Generated constructor for {family.name}",
            )
            modified = True

        else:
            # --- PRESENT: verify and fix ---
            lines, was_fixed = _check_and_fix_constructor(
                lines, cls, constructor, family, reporter, path, dry_run
            )
            if was_fixed:
                modified = True
            else:
                reporter.add_action(
                    path, cls.name, ActionType.CONSTRUCTOR_OK,
                    line=constructor.start_line,
                )

    if modified:
        write_lines(path, lines, backup=backup, dry_run=dry_run)
        reporter.mark_file_modified(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="UVM Constructor Checker — adds or fixes new() constructors"
    )
    p.add_argument("path", nargs="+", help="SV file(s) or directory")
    p.add_argument("--recursive", "-r", action="store_true")
    p.add_argument("--no-backup", dest="no_backup", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--report", metavar="FILE")
    p.add_argument("--verbose", "-v", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    taxonomy = UVMTaxonomy()
    reporter = Reporter(
        mode="dry-run" if args.dry_run else "fix",
        scripts_run=["constructor_checker"],
    )

    files: list[Path] = []
    for p in args.path:
        files.extend(collect_sv_files(p, recursive=args.recursive))

    if not files:
        print("No .sv files found.", file=sys.stderr)
        return 1

    for f in files:
        process_file(f, taxonomy, reporter,
                     backup=not args.no_backup,
                     dry_run=args.dry_run)

    reporter.print_summary(verbose=args.verbose)

    if args.report:
        reporter.write_json(args.report)
        print(f"Report written to {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
