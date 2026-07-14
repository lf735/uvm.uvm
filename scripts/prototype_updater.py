"""
scripts/prototype_updater.py
============================
Script 4 — UVM Phase Prototype Updater.

For each UVM class in a SystemVerilog file, inspects declared phase methods
(build_phase, run_phase, etc.) and checks their signatures against the UVM
standard.

Decision rules
--------------
- If a method has an ``extern`` declaration:
    - Declaration CORRECT + body WRONG   → fix the body (automatic)
    - Declaration WRONG                  → report PROTOTYPE_ERROR only
    - Declaration WRONG + ``--force-fix`` → fix both declaration and body
- If no ``extern`` (body only):
    - Body CORRECT   → PROTOTYPE_OK
    - Body WRONG     → report PROTOTYPE_ERROR only
    - Body WRONG + ``--force-fix`` → fix the body

Injection (``--inject-phases``):
- ``main``  → inject build_phase, connect_phase, run_phase stubs if absent
- ``all``   → inject all 21 UVM standard phase stubs if absent

Usage::

    python -m scripts.prototype_updater path/to/sv/ [options]

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
from core.uvm_taxonomy import UVMTaxonomy, UVMFamily, UVM_PHASE_PROTOTYPES, PhaseProto
from core.file_io import read_lines, write_lines, collect_sv_files
from core.reporter import Reporter, ActionType


# ---------------------------------------------------------------------------
# Signature comparison helpers
# ---------------------------------------------------------------------------

_RE_SINGLE_PARAM = re.compile(
    r"uvm_phase\s+\w+",   # matches "uvm_phase phase", "uvm_phase p", etc.
)


def _sig_matches(func: SVFunction, proto: PhaseProto) -> bool:
    """Return True if *func* already matches *proto* exactly."""
    if func.is_task != proto.is_task:
        return False
    if not proto.is_task and func.return_type.lower() != proto.return_type.lower():
        return False
    # Check that at least one port with type uvm_phase exists
    has_uvm_phase_port = any(
        "uvm_phase" in p.sv_type.lower() for p in func.port_list
    )
    if not has_uvm_phase_port:
        return False
    return True


# ---------------------------------------------------------------------------
# Line reconstruction
# ---------------------------------------------------------------------------

def _rebuild_decl_line(original: str, proto: PhaseProto, is_extern: bool) -> str:
    """
    Reconstruct a function/task declaration line to match *proto*.

    Preserves: leading whitespace, ``virtual``, ``override``.
    Replaces:  ``function``/``task`` keyword, return type, parameter list.
    """
    indent_m = re.match(r"(\s*)", original)
    indent = indent_m.group(1) if indent_m else ""

    # preserve virtual / override modifiers
    modifiers = ""
    for mod in ("virtual", "override"):
        if re.search(rf"\b{mod}\b", original):
            modifiers += f"{mod} "

    extern_part = "extern " if is_extern else ""

    if proto.is_task:
        return f"{indent}{extern_part}{modifiers}task {proto.name}({proto.param});\n"
    else:
        return f"{indent}{extern_part}{modifiers}function void {proto.name}({proto.param});\n"


# ---------------------------------------------------------------------------
# Phase stub generation
# ---------------------------------------------------------------------------

def _generate_phase_stub(proto: PhaseProto, indent: str) -> list[str]:
    """Generate a minimal stub for a UVM phase method."""
    i2 = indent + "  "
    if proto.is_task:
        return [
            f"{indent}task {proto.name}({proto.param});\n",
            f"{i2}// TODO: implement {proto.name}\n",
            f"{indent}endtask\n",
            "\n",
        ]
    else:
        return [
            f"{indent}function void {proto.name}({proto.param});\n",
            f"{i2}super.{proto.name}(phase);\n",
            f"{indent}endfunction\n",
            "\n",
        ]


# ---------------------------------------------------------------------------
# Find corresponding body function for an extern
# ---------------------------------------------------------------------------

def _find_body_func(cls: SVClass, name: str) -> SVFunction | None:
    """
    Among *cls* functions, find a non-extern occurrence of *name*
    (i.e. the body implementation, not the extern declaration).
    """
    body = None
    for f in cls.functions:
        if f.name == name and not f.is_extern:
            body = f
    return body


def _find_extern_func(cls: SVClass, name: str) -> SVFunction | None:
    """Find the extern declaration for *name* in *cls*."""
    for f in cls.functions:
        if f.name == name and f.is_extern:
            return f
    return None


# ---------------------------------------------------------------------------
# Per-class processor
# ---------------------------------------------------------------------------

def _process_class(
    lines: list[str],
    cls: SVClass,
    reporter: Reporter,
    path: Path,
    dry_run: bool,
    force_fix: bool,
    inject_phases: str | None,
) -> tuple[list[str], bool]:
    """
    Inspect and optionally fix phase prototypes for one class.

    Returns (possibly_modified_lines, was_modified).
    """
    modified = False

    # Collect all phase methods declared (extern + body)
    seen_phase_names: set[str] = {
        f.name for f in cls.functions if f.name in UVM_PHASE_PROTOTYPES
    }

    # -- Check existing phase methods --
    # Process in one pass: for each unique phase name found
    for phase_name in seen_phase_names:
        proto = UVM_PHASE_PROTOTYPES[phase_name]
        extern_func = _find_extern_func(cls, phase_name)
        body_func   = _find_body_func(cls, phase_name)

        if extern_func is not None:
            # --- Extern exists: it is the reference ---
            extern_correct = _sig_matches(extern_func, proto)

            if extern_correct:
                # Extern is good → check/fix body
                if body_func is not None and not _sig_matches(body_func, proto):
                    # Fix body automatically (no --force-fix needed)
                    new_line = _rebuild_decl_line(
                        lines[body_func.start_line - 1], proto, is_extern=False
                    )
                    if not dry_run:
                        lines[body_func.start_line - 1] = new_line
                    modified = True
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_FIXED,
                        line=body_func.start_line,
                        detail=f"Body of {phase_name} fixed to match extern declaration",
                    )
                else:
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_OK,
                        line=extern_func.start_line,
                        detail=f"{phase_name} signature OK",
                    )
            else:
                # Extern is wrong
                if force_fix:
                    # Fix extern
                    new_extern = _rebuild_decl_line(
                        lines[extern_func.start_line - 1], proto, is_extern=True
                    )
                    if not dry_run:
                        lines[extern_func.start_line - 1] = new_extern
                    modified = True
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_FIXED,
                        line=extern_func.start_line,
                        detail=f"Extern declaration of {phase_name} fixed (--force-fix)",
                    )
                    # Also fix body if present
                    if body_func is not None and not _sig_matches(body_func, proto):
                        new_body = _rebuild_decl_line(
                            lines[body_func.start_line - 1], proto, is_extern=False
                        )
                        if not dry_run:
                            lines[body_func.start_line - 1] = new_body
                        modified = True
                        reporter.add_action(
                            path, cls.name, ActionType.PROTOTYPE_FIXED,
                            line=body_func.start_line,
                            detail=f"Body of {phase_name} fixed (--force-fix)",
                        )
                else:
                    # Report error only
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_ERROR,
                        line=extern_func.start_line,
                        detail=f"extern declaration of {phase_name} has wrong signature "
                               f"(use --force-fix to correct)",
                    )
                    reporter.add_warning(
                        path, cls.name,
                        f"Phase '{phase_name}': extern declaration has wrong signature. "
                        f"Use --force-fix to correct automatically.",
                    )

        elif body_func is not None:
            # --- No extern, body only ---
            if _sig_matches(body_func, proto):
                reporter.add_action(
                    path, cls.name, ActionType.PROTOTYPE_OK,
                    line=body_func.start_line,
                    detail=f"{phase_name} signature OK",
                )
            else:
                if force_fix:
                    new_line = _rebuild_decl_line(
                        lines[body_func.start_line - 1], proto, is_extern=False
                    )
                    if not dry_run:
                        lines[body_func.start_line - 1] = new_line
                    modified = True
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_FIXED,
                        line=body_func.start_line,
                        detail=f"{phase_name} body signature fixed (--force-fix)",
                    )
                else:
                    reporter.add_action(
                        path, cls.name, ActionType.PROTOTYPE_ERROR,
                        line=body_func.start_line,
                        detail=f"{phase_name} has wrong signature "
                               f"(use --force-fix to correct)",
                    )
                    reporter.add_warning(
                        path, cls.name,
                        f"Phase '{phase_name}': body has wrong signature. "
                        f"Use --force-fix to correct automatically.",
                    )

    # -- Injection of missing phases --
    if inject_phases:
        # Determine which phases to inject
        candidates = [
            p for p in UVM_PHASE_PROTOTYPES.values()
            if (inject_phases == "all" or p.is_main)
            and p.name not in seen_phase_names
        ]

        if candidates:
            # Find insertion point: after last macro / class header
            insert_idx = cls.start_line  # 0-indexed: after class header line
            for i in range(cls.start_line - 1, min(cls.end_line, len(lines))):
                stripped = lines[i].strip()
                if stripped.startswith("`uvm_") or stripped.startswith("`UVM_"):
                    insert_idx = i + 1

            # Indentation from class header
            class_line = lines[cls.start_line - 1]
            indent = re.match(r"(\s*)", class_line).group(1) + "  "

            # Insert stubs in reverse order to keep line numbers stable
            for proto in reversed(candidates):
                stub = _generate_phase_stub(proto, indent)
                if not dry_run:
                    lines = lines[:insert_idx] + stub + lines[insert_idx:]
                modified = True
                reporter.add_action(
                    path, cls.name, ActionType.PROTOTYPE_INJECTED,
                    line=insert_idx + 1,
                    detail=f"Injected stub for {proto.name} (--inject-phases {inject_phases})",
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
    force_fix: bool = False,
    inject_phases: str | None = None,
) -> None:
    """Process a single .sv file for phase prototype issues."""
    reporter.start_file(path)
    lines = read_lines(path)
    classes = parse_file(path)

    modified = False

    # Process in reverse order so injections don't shift subsequent line indices
    for cls in reversed(classes):
        family = taxonomy.resolve(cls.parent)
        reporter.start_class(path, cls.name, family.name)

        if family != UVMFamily.COMPONENT:
            # Phase methods are only relevant for UVM components
            continue

        lines, was_modified = _process_class(
            lines, cls, reporter, path,
            dry_run=dry_run,
            force_fix=force_fix,
            inject_phases=inject_phases,
        )
        if was_modified:
            modified = True

    if modified:
        write_lines(path, lines, backup=backup, dry_run=dry_run)
        reporter.mark_file_modified(path)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "UVM Prototype Updater — checks and fixes UVM phase method signatures.\n\n"
            "By default, only reports errors for wrong declarations (extern).\n"
            "Use --force-fix to also correct erroneous declarations.\n"
            "Use --inject-phases to add missing phase stubs."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("path", nargs="+", help="SV file(s) or directory")
    p.add_argument("--recursive", "-r", action="store_true")
    p.add_argument("--no-backup", dest="no_backup", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--report", metavar="FILE")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument(
        "--force-fix", dest="force_fix", action="store_true",
        help="Force correction of erroneous extern declarations",
    )
    p.add_argument(
        "--inject-phases", dest="inject_phases",
        choices=["all", "main"], default=None,
        help=(
            "Inject missing phase stubs. "
            "'main' = build_phase, connect_phase, run_phase only. "
            "'all' = all 21 UVM standard phases."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    taxonomy = UVMTaxonomy()
    reporter = Reporter(
        mode="dry-run" if args.dry_run else "fix",
        scripts_run=["prototype_updater"],
    )

    files: list[Path] = []
    for p in args.path:
        files.extend(collect_sv_files(p, recursive=args.recursive))

    if not files:
        print("No .sv files found.", file=sys.stderr)
        return 1

    for f in files:
        process_file(
            f, taxonomy, reporter,
            backup=not args.no_backup,
            dry_run=args.dry_run,
            force_fix=args.force_fix,
            inject_phases=args.inject_phases,
        )

    reporter.print_summary(verbose=args.verbose)

    if args.report:
        reporter.write_json(args.report)
        print(f"Report written to {args.report}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
