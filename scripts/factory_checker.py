"""
scripts/factory_checker.py
==========================
Script 1 — UVM Factory Macro checker and injector.

For each SystemVerilog class in the input files:
  - Resolves the UVM family (component / object)
  - Determines the expected factory macro
  - Applies one of the following decisions:
      ABSENT        → inject macro at (start_line + 1)
      OK            → nothing to do
      WRONG_NAME    → fix the class name inside the macro
      WRONG_TYPE    → replace the entire macro
      BEGIN_END     → fix only the prefix/name inside the begin/end block
  - Classes with unknown parent → warning, skip

Usage (standalone)::

    python -m scripts.factory_checker path/to/sv/ [options]

"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Allow running as a module from the project root
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.sv_parser import parse_file, SVClass, SVMacro
from core.uvm_taxonomy import UVMTaxonomy, UVMFamily
from core.file_io import read_lines, write_lines, collect_sv_files
from core.reporter import Reporter, ActionType


# ---------------------------------------------------------------------------
# Factory decision logic
# ---------------------------------------------------------------------------

_FACTORY_MACRO_RE = re.compile(r"`(uvm_(?:component|object)(?:_param)?_utils(?:_begin)?)\s*\(([^)]*)\)")


class FactoryDecision:
    ABSENT     = "ABSENT"
    OK         = "OK"
    WRONG_NAME = "WRONG_NAME"
    WRONG_TYPE = "WRONG_TYPE"
    BEGIN_END  = "BEGIN_END"   # has _begin/end block (may need correction)


def _find_factory_macro(cls: SVClass) -> SVMacro | None:
    """Return the first factory macro found in the class, or None."""
    tax = UVMTaxonomy()
    for m in cls.macros:
        if tax.is_factory_macro(m.name):
            return m
    return None


def _has_begin_end_block(cls: SVClass) -> bool:
    """Return True if the class has a _utils_begin macro."""
    return any(m.name.endswith("_begin") for m in cls.macros
               if UVMTaxonomy().is_factory_macro(m.name))


def decide(cls: SVClass, taxonomy: UVMTaxonomy) -> tuple[str, str | None]:
    """
    Compute the factory decision for a class.

    Returns (decision, expected_macro_name).
    decision is one of FactoryDecision.*
    """
    family = taxonomy.resolve(cls.parent)
    if family == UVMFamily.UNKNOWN:
        return FactoryDecision.ABSENT, None  # will trigger warning

    expected_name = taxonomy.expected_factory_macro(family, cls.is_parameterized)
    has_begin = _has_begin_end_block(cls)
    existing = _find_factory_macro(cls)

    if existing is None:
        return FactoryDecision.ABSENT, expected_name

    # classify existing
    ex_family, ex_param, ex_is_begin = taxonomy.classify_factory_macro(existing.name)

    if has_begin:
        # Never replace a begin/end block with a plain _utils
        # Just check if the prefix is correct
        if ex_family == family and ex_param == cls.is_parameterized:
            # Check class name
            if existing.args and existing.args[0].strip() == cls.name:
                return FactoryDecision.OK, expected_name
            else:
                return FactoryDecision.WRONG_NAME, expected_name
        else:
            return FactoryDecision.BEGIN_END, expected_name
    else:
        if ex_family == family and ex_param == cls.is_parameterized:
            if existing.args and existing.args[0].strip() == cls.name:
                return FactoryDecision.OK, expected_name
            else:
                return FactoryDecision.WRONG_NAME, expected_name
        else:
            return FactoryDecision.WRONG_TYPE, expected_name


# ---------------------------------------------------------------------------
# Line modification helpers
# ---------------------------------------------------------------------------

def _make_macro_line(macro_name: str, class_name: str, param_str: str, indent: str) -> str:
    """Build a factory macro line like '  `uvm_component_utils(my_cls)\n'."""
    if "param" in macro_name:
        # For parameterized: `uvm_component_param_utils(my_cls #(PARAMS))
        if param_str:
            # strip outer #(...) if present and use raw param list inside
            inner = param_str.strip().lstrip("#").strip().lstrip("(").rstrip(")")
            arg = f"{class_name} #({inner})"
        else:
            arg = class_name
    else:
        arg = class_name
    return f"{indent}`{macro_name}({arg})\n"


def apply_factory_fix(
    lines: list[str],
    cls: SVClass,
    decision: str,
    expected_macro_name: str,
    dry_run: bool = False,
) -> tuple[list[str], list[dict]]:
    """
    Apply factory macro modifications to the lines list.

    Returns (modified_lines, list_of_actions).
    """
    actions: list[dict] = []

    if decision == FactoryDecision.OK:
        return lines, actions

    # Determine indentation from the class header line
    class_line = lines[cls.start_line - 1]  # 0-indexed
    indent = re.match(r"(\s*)", class_line).group(1) + "  "

    if decision == FactoryDecision.ABSENT:
        # Insert after the class header line
        insert_idx = cls.start_line  # 0-indexed: insert after header
        new_line = _make_macro_line(expected_macro_name, cls.name, cls.param_str, indent)
        if not dry_run:
            lines = lines[:insert_idx] + [new_line] + lines[insert_idx:]
        actions.append({"type": ActionType.FACTORY_ADDED, "macro": new_line.strip(), "line": cls.start_line + 1})

    elif decision == FactoryDecision.WRONG_NAME:
        # Find the factory macro line and fix the class name
        existing = _find_factory_macro(cls)
        if existing:
            idx = existing.line - 1  # 0-indexed
            old = lines[idx]
            new = re.sub(
                r"(`uvm_\w+_utils(?:_begin)?)\s*\(\s*[\w#(),\s]+\s*\)",
                lambda m: f"{m.group(1)}({cls.name})" if "param" not in m.group(1)
                          else f"{m.group(1)}({cls.name} #({cls.param_str.strip().lstrip('#').strip().lstrip('(').rstrip(')')}))",
                old,
            )
            if not dry_run:
                lines[idx] = new
            actions.append({"type": ActionType.FACTORY_FIXED, "macro": new.strip(), "line": existing.line})

    elif decision == FactoryDecision.WRONG_TYPE:
        # Replace the whole macro line
        existing = _find_factory_macro(cls)
        if existing:
            idx = existing.line - 1
            new_line = _make_macro_line(expected_macro_name, cls.name, cls.param_str, indent)
            if not dry_run:
                lines[idx] = new_line
            actions.append({"type": ActionType.FACTORY_FIXED, "macro": new_line.strip(), "line": existing.line})

    elif decision == FactoryDecision.BEGIN_END:
        # Fix the begin macro prefix and name
        existing = _find_factory_macro(cls)
        if existing:
            idx = existing.line - 1
            old = lines[idx]
            new_begin_name = expected_macro_name + "_begin"
            new = re.sub(
                r"`uvm_\w+_utils_begin\s*\(\s*[\w#(),\s]+\s*\)",
                f"`{new_begin_name}({cls.name})",
                old,
            )
            if not dry_run:
                lines[idx] = new
            actions.append({"type": ActionType.FACTORY_FIXED, "macro": new.strip(), "line": existing.line})

    return lines, actions


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
    """Process a single .sv file for factory macro issues."""
    reporter.start_file(path)
    lines = read_lines(path)
    classes = parse_file(path)

    modified = False
    # Process in reverse order so line insertions don't shift subsequent indices
    for cls in reversed(classes):
        family = taxonomy.resolve(cls.parent)
        reporter.start_class(path, cls.name, family.name)

        if family == UVMFamily.UNKNOWN:
            if cls.parent is not None:
                reporter.add_warning(path, cls.name,
                    f"Parent class '{cls.parent}' unresolved. Class skipped.")
            continue

        decision, expected_macro = decide(cls, taxonomy)

        if decision == FactoryDecision.OK:
            reporter.add_action(path, cls.name, ActionType.FACTORY_OK,
                                 macro=expected_macro or "", line=cls.start_line)
            continue

        lines, actions = apply_factory_fix(lines, cls, decision, expected_macro or "", dry_run)
        for act in actions:
            reporter.add_action(path, cls.name, act["type"],
                                 macro=act.get("macro", ""), line=act.get("line", 0))
        if actions:
            modified = True

    if modified:
        write_lines(path, lines, backup=backup, dry_run=dry_run)
        reporter.mark_file_modified(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="UVM Factory Macro Checker — checks and fixes `uvm_*_utils macros"
    )
    p.add_argument("path", nargs="+", help="SV file(s) or directory to process")
    p.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories")
    p.add_argument("--no-backup", dest="no_backup", action="store_true", help="Disable .bak backup")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", help="Simulate without modifying files")
    p.add_argument("--report", metavar="FILE", help="Write JSON report to FILE")
    p.add_argument("--verbose", "-v", action="store_true", help="Verbose console output")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    taxonomy = UVMTaxonomy()
    reporter = Reporter(
        mode="dry-run" if args.dry_run else "fix",
        scripts_run=["factory_checker"],
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
