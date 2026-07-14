"""
uvm_transpile.py
================
Main orchestrator for the UVM SV Transpiler Suite.

Runs the four scripts in the correct pipeline order:
    factory_checker  →  field_macro_adder  →  constructor_checker  →  prototype_updater

Usage::

    # Run all scripts
    python uvm_transpile.py --all path/to/sv/

    # Run individual scripts
    python uvm_transpile.py --factory path/to/sv/
    python uvm_transpile.py --fields  path/to/sv/
    python uvm_transpile.py --constructor path/to/sv/
    python uvm_transpile.py --prototype path/to/sv/

    # Common options
    --recursive      Recurse into subdirectories
    --no-backup      Disable .sv.bak backups (not recommended)
    --report FILE    Write JSON report to FILE
    --verbose        Verbose console output
    --dry-run        Simulate without modifying files

    # Prototype-specific options
    --force-fix              Fix erroneous extern declarations
    --inject-phases {all,main}  Inject missing phase stubs

"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure project root is on path
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.uvm_taxonomy import UVMTaxonomy
from core.file_io import collect_sv_files
from core.reporter import Reporter

from scripts.factory_checker import process_file as factory_process
from scripts.field_macro_adder import process_file as fields_process
from scripts.constructor_checker import process_file as constructor_process
from scripts.prototype_updater import process_file as prototype_process


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uvm_transpile",
        description=(
            "UVM SV Transpiler Suite\n"
            "Automatically adds/fixes UVM factory macros, field macros, and constructors\n"
            "in SystemVerilog source files."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Script selection
    script_group = p.add_mutually_exclusive_group(required=True)
    script_group.add_argument(
        "--all", dest="run_all", action="store_true",
        help="Run all scripts in order: factory → fields → constructor → prototype",
    )
    script_group.add_argument(
        "--factory", dest="run_factory", action="store_true",
        help="Run factory_checker only",
    )
    script_group.add_argument(
        "--fields", dest="run_fields", action="store_true",
        help="Run field_macro_adder only",
    )
    script_group.add_argument(
        "--constructor", dest="run_constructor", action="store_true",
        help="Run constructor_checker only",
    )
    script_group.add_argument(
        "--prototype", dest="run_prototype", action="store_true",
        help="Run prototype_updater only",
    )

    # Paths
    p.add_argument(
        "path", nargs="+",
        help="SV file(s) or directory to process",
    )

    # Common options
    p.add_argument("--recursive", "-r", action="store_true",
                   help="Recurse into subdirectories")
    p.add_argument("--no-backup", dest="no_backup", action="store_true",
                   help="Disable automatic .sv.bak backups (not recommended)")
    p.add_argument("--report", metavar="FILE",
                   help="Write JSON report to FILE")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Verbose console output")
    p.add_argument("--dry-run", dest="dry_run", action="store_true",
                   help="Simulate without modifying any files")

    # Prototype-updater options
    p.add_argument(
        "--force-fix", dest="force_fix", action="store_true",
        help="(prototype_updater) Force correction of erroneous extern declarations",
    )
    p.add_argument(
        "--inject-phases", dest="inject_phases",
        choices=["all", "main"], default=None,
        help="(prototype_updater) Inject missing phase stubs: 'main' or 'all'",
    )

    return p


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run(args: argparse.Namespace) -> int:
    taxonomy = UVMTaxonomy()

    scripts_run: list[str] = []
    if args.run_all or args.run_factory:
        scripts_run.append("factory_checker")
    if args.run_all or args.run_fields:
        scripts_run.append("field_macro_adder")
    if args.run_all or args.run_constructor:
        scripts_run.append("constructor_checker")
    if args.run_all or getattr(args, "run_prototype", False):
        scripts_run.append("prototype_updater")

    reporter = Reporter(
        mode="dry-run" if args.dry_run else "fix",
        scripts_run=scripts_run,
    )

    # Collect files
    files: list[Path] = []
    for p in args.path:
        files.extend(collect_sv_files(p, recursive=args.recursive))

    if not files:
        print("No .sv files found.", file=sys.stderr)
        return 1

    backup = not args.no_backup

    print(f"Processing {len(files)} file(s)...")
    if args.dry_run:
        print("  [DRY RUN — no files will be modified]")

    # --- Pipeline ---
    if args.run_all or args.run_factory:
        print("\n[1/4] Running factory_checker...")
        for f in files:
            factory_process(f, taxonomy, reporter, backup=backup, dry_run=args.dry_run)

    if args.run_all or args.run_fields:
        print("\n[2/4] Running field_macro_adder...")
        # Re-parse files after factory_checker may have modified them
        for f in files:
            fields_process(f, taxonomy, reporter, backup=backup, dry_run=args.dry_run)

    if args.run_all or args.run_constructor:
        print("\n[3/4] Running constructor_checker...")
        for f in files:
            constructor_process(f, taxonomy, reporter, backup=backup, dry_run=args.dry_run)

    if args.run_all or getattr(args, "run_prototype", False):
        print("\n[4/4] Running prototype_updater...")
        force_fix    = getattr(args, "force_fix", False)
        inject_phases = getattr(args, "inject_phases", None)
        for f in files:
            prototype_process(
                f, taxonomy, reporter,
                backup=backup,
                dry_run=args.dry_run,
                force_fix=force_fix,
                inject_phases=inject_phases,
            )

    # --- Summary ---
    reporter.print_summary(verbose=args.verbose)

    if args.report:
        reporter.write_json(args.report)
        print(f"\nReport written to: {args.report}")

    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
