"""
scripts/field_macro_adder.py
============================
Script 2 — UVM Field Macro Adder.

For each class that has a _utils_begin/end block:
  - Maps each member variable to the appropriate `uvm_field_*` macro
  - Checks if the field macro already exists
  - Inserts missing field macros inside the begin/end block

If no _utils_begin/end block exists but there are mappable members,
factory_checker.py should be run first. This script will emit a warning
and skip field injection in that case (it does not create bare _utils macros).

Type mapping (SV → `uvm_field_*`):
  int / bit / logic / reg / ... → uvm_field_int
  string                        → uvm_field_string
  real / shortreal              → uvm_field_real
  enum type                     → uvm_field_enum
  uvm_object derivative         → uvm_field_object
  dynamic array []              → uvm_field_array_*
  queue [$]                     → uvm_field_queue_*
  static array [N]              → uvm_field_sarray_*

Default flag: UVM_ALL_ON

Usage::

    python -m scripts.field_macro_adder path/to/sv/ [options]

"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.sv_parser import parse_file, SVClass, SVMember
from core.uvm_taxonomy import UVMTaxonomy, UVMFamily
from core.file_io import read_lines, write_lines, collect_sv_files
from core.reporter import Reporter, ActionType


# ---------------------------------------------------------------------------
# Type resolution
# ---------------------------------------------------------------------------

_INT_TYPES = frozenset({
    "int", "integer", "longint", "shortint", "byte",
    "bit", "logic", "reg", "wire", "unsigned",
})
_REAL_TYPES = frozenset({"real", "shortreal"})

DEFAULT_FLAG = "UVM_ALL_ON"


def _base_field_macro(member: SVMember, taxonomy: UVMTaxonomy) -> str | None:
    """
    Resolve a member to its base `uvm_field_*` macro name (without prefix),
    taking into account array dimensions.

    Returns None if the type cannot be mapped.
    """
    sv_type = member.sv_type.strip().lower()
    base_type = sv_type.split("::")[- 1].strip()  # strip package prefix

    # Determine the scalar macro suffix
    if base_type in _INT_TYPES:
        scalar = "int"
    elif base_type == "string":
        scalar = "string"
    elif base_type in _REAL_TYPES:
        scalar = "real"
    elif member.is_enum:
        scalar = "enum"
    elif taxonomy.resolve(member.sv_type) in (UVMFamily.COMPONENT, UVMFamily.OBJECT):
        scalar = "object"
    else:
        # unknown type — try to detect uvm_object types by name convention
        if re.search(r"uvm_\w+", member.sv_type, re.IGNORECASE):
            scalar = "object"
        else:
            return None  # unmappable

    # Array prefix
    if member.is_queue:
        return f"uvm_field_queue_{scalar}"
    elif member.is_dynamic_array:
        return f"uvm_field_array_{scalar}"
    elif member.is_array:
        return f"uvm_field_sarray_{scalar}"
    else:
        if scalar == "enum":
            return "uvm_field_enum"
        return f"uvm_field_{scalar}"


def _build_field_macro_line(member: SVMember, taxonomy: UVMTaxonomy, indent: str) -> str | None:
    """Build the complete `uvm_field_*` line for a member."""
    macro_base = _base_field_macro(member, taxonomy)
    if macro_base is None:
        return None

    if "enum" in macro_base and not member.is_array:
        # uvm_field_enum needs the type as first arg
        line = f"{indent}`{macro_base}({member.sv_type}, {member.name}, {DEFAULT_FLAG})\n"
    else:
        line = f"{indent}`{macro_base}({member.name}, {DEFAULT_FLAG})\n"
    return line


# ---------------------------------------------------------------------------
# Block detection helpers
# ---------------------------------------------------------------------------

_RE_UTILS_BEGIN = re.compile(r"`uvm_\w+_utils_begin\b")
_RE_UTILS_END   = re.compile(r"`uvm_\w+_utils_end\b")
_RE_FIELD_MACRO = re.compile(r"`uvm_field_\w+\s*\(\s*([^,)]+)")


def _find_begin_end_block(lines: list[str], cls: SVClass) -> tuple[int, int] | None:
    """
    Find the (begin_line_idx, end_line_idx) of the _utils_begin/end block
    within the class body (0-indexed into full file lines).

    Returns None if not found.
    """
    start = cls.start_line - 1  # 0-indexed
    end = cls.end_line           # 0-indexed (exclusive)
    begin_idx = None
    for i in range(start, min(end, len(lines))):
        if _RE_UTILS_BEGIN.search(lines[i]):
            begin_idx = i
        if begin_idx is not None and _RE_UTILS_END.search(lines[i]):
            return begin_idx, i
    return None


def _get_existing_field_names(lines: list[str], begin_idx: int, end_idx: int) -> set[str]:
    """Return the set of member names already covered by field macros in the block."""
    names: set[str] = set()
    for i in range(begin_idx + 1, end_idx):
        m = _RE_FIELD_MACRO.search(lines[i])
        if m:
            # For uvm_field_enum the first arg is the type — skip it
            raw = m.group(1).strip()
            # If it looks like a type (contains uppercase or uvm_), skip to next comma
            names.add(raw)
    return names


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
    """Process a single .sv file for uvm_field_* macros."""
    reporter.start_file(path)
    lines = read_lines(path)
    classes = parse_file(path)

    modified = False

    # Process classes in order (no line shifting expected since we only insert inside begin/end)
    # But to be safe, track cumulative offset
    offset = 0

    for cls in classes:
        family = taxonomy.resolve(cls.parent)
        reporter.start_class(path, cls.name, family.name)

        if family == UVMFamily.UNKNOWN:
            continue

        if not cls.members:
            continue

        # Adjust line numbers by current offset
        cls_adjusted = cls
        block = _find_begin_end_block(lines, cls_adjusted)

        if block is None:
            reporter.add_warning(
                path, cls.name,
                "No `uvm_*_utils_begin/end block found. Run factory_checker.py first."
            )
            continue

        begin_idx, end_idx = block

        # Determine indentation inside the block
        # Use the indentation of begin line + 2 spaces
        begin_line = lines[begin_idx]
        indent = re.match(r"(\s*)", begin_line).group(1) + "  "

        existing_names = _get_existing_field_names(lines, begin_idx, end_idx)

        insert_lines: list[str] = []
        for member in cls.members:
            # Skip if already covered
            if member.name in existing_names:
                reporter.add_action(path, cls.name, ActionType.FIELD_OK,
                                     detail=f"`uvm_field_* for {member.name} already present")
                continue

            # Visibility warning
            if member.visibility in ("local", "protected"):
                reporter.add_warning(
                    path, cls.name,
                    f"Member '{member.name}' is {member.visibility} — "
                    "field automation will expose it."
                )

            macro_line = _build_field_macro_line(member, taxonomy, indent)
            if macro_line is None:
                reporter.add_warning(
                    path, cls.name,
                    f"Cannot determine uvm_field_* macro for member '{member.name}' "
                    f"(type: {member.sv_type}). Skipped."
                )
                continue

            insert_lines.append(macro_line)
            reporter.add_action(
                path, cls.name, ActionType.FIELD_ADDED,
                macro=macro_line.strip(),
                line=end_idx + 1,
            )

        if insert_lines:
            # Insert all new field macros just before the _utils_end line
            if not dry_run:
                lines = lines[:end_idx] + insert_lines + lines[end_idx:]
            offset += len(insert_lines)
            modified = True

    if modified:
        write_lines(path, lines, backup=backup, dry_run=dry_run)
        reporter.mark_file_modified(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="UVM Field Macro Adder — injects `uvm_field_*` macros inside `_utils_begin/end blocks"
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
        scripts_run=["field_macro_adder"],
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
