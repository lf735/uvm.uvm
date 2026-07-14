"""
core/reporter.py
================
Report generation for the UVM transpiler suite.

Produces:
  - A structured in-memory report (dict)
  - JSON file output (--report out.json)
  - Coloured console summary (--verbose)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from colorama import Fore, Style, init as _colorama_init
    _colorama_init(autoreset=True)
    _HAS_COLORAMA = True
except ImportError:
    _HAS_COLORAMA = False


# ===========================================================================
# Action types (string constants for the report)
# ===========================================================================
class ActionType:
    FACTORY_ADDED   = "FACTORY_ADDED"
    FACTORY_FIXED   = "FACTORY_FIXED"
    FACTORY_OK      = "FACTORY_OK"
    FIELD_ADDED     = "FIELD_ADDED"
    FIELD_OK        = "FIELD_OK"
    CONSTRUCTOR_ADDED = "CONSTRUCTOR_ADDED"
    CONSTRUCTOR_FIXED = "CONSTRUCTOR_FIXED"
    CONSTRUCTOR_OK  = "CONSTRUCTOR_OK"
    SKIPPED         = "SKIPPED"


# ===========================================================================
# Report builder
# ===========================================================================

class Reporter:
    """
    Accumulates results from all transpiler scripts and renders them.

    Usage::

        rep = Reporter(mode="fix", scripts_run=["factory_checker"])
        rep.add_action("my_driver.sv", "my_driver", "FACTORY_ADDED",
                       macro="`uvm_component_utils(my_driver)", line=3)
        rep.add_warning("my_base.sv", "my_base", "Parent unresolved")
        rep.write_json("report.json")
        rep.print_summary(verbose=True)
    """

    def __init__(self, mode: str = "fix", scripts_run: list[str] | None = None) -> None:
        self._mode = mode
        self._scripts_run = scripts_run or []
        self._files: dict[str, dict[str, Any]] = {}    # path -> file_entry
        self._warnings: list[dict[str, str]] = []
        self._files_scanned: int = 0
        self._files_modified: int = 0
        self._classes_processed: int = 0
        self._action_counts: dict[str, int] = {
            "factory_macros_added": 0,
            "factory_macros_fixed": 0,
            "field_macros_added": 0,
            "constructors_added": 0,
            "constructors_fixed": 0,
        }

    # ------------------------------------------------------------------
    # Data ingestion
    # ------------------------------------------------------------------

    def start_file(self, path: "str | Path") -> None:
        """Register that we started processing a file."""
        key = str(path)
        if key not in self._files:
            self._files[key] = {"path": key, "classes": []}
        self._files_scanned += 1

    def mark_file_modified(self, path: "str | Path") -> None:
        """Mark a file as modified."""
        self._files_modified += 1

    def start_class(self, path: "str | Path", class_name: str, uvm_family: str) -> None:
        """Register a class being processed."""
        key = str(path)
        if key not in self._files:
            self._files[key] = {"path": key, "classes": []}
        self._files[key]["classes"].append({
            "name": class_name,
            "uvm_family": uvm_family,
            "actions": [],
        })
        self._classes_processed += 1

    def add_action(
        self,
        path: "str | Path",
        class_name: str,
        action_type: str,
        macro: str = "",
        line: int = 0,
        detail: str = "",
    ) -> None:
        """Record an action taken on a class."""
        key = str(path)
        entry: dict[str, Any] = {"type": action_type}
        if macro:
            entry["macro"] = macro
        if line:
            entry["line"] = line
        if detail:
            entry["detail"] = detail

        # find class entry
        for cls in self._files.get(key, {}).get("classes", []):
            if cls["name"] == class_name:
                cls["actions"].append(entry)
                break

        # update counts
        if action_type == ActionType.FACTORY_ADDED:
            self._action_counts["factory_macros_added"] += 1
        elif action_type == ActionType.FACTORY_FIXED:
            self._action_counts["factory_macros_fixed"] += 1
        elif action_type == ActionType.FIELD_ADDED:
            self._action_counts["field_macros_added"] += 1
        elif action_type == ActionType.CONSTRUCTOR_ADDED:
            self._action_counts["constructors_added"] += 1
        elif action_type == ActionType.CONSTRUCTOR_FIXED:
            self._action_counts["constructors_fixed"] += 1

    def add_warning(self, path: "str | Path", class_name: str, message: str) -> None:
        """Record a warning."""
        self._warnings.append({
            "file": str(path),
            "class": class_name,
            "message": message,
        })

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Build and return the full report as a dict."""
        return {
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": self._mode,
                "scripts_run": self._scripts_run,
            },
            "summary": {
                "files_scanned": self._files_scanned,
                "files_modified": self._files_modified,
                "classes_processed": self._classes_processed,
                "actions": self._action_counts,
                "warnings": len(self._warnings),
            },
            "files": list(self._files.values()),
            "warnings": self._warnings,
        }

    def write_json(self, output_path: "str | Path") -> None:
        """Write the report to a JSON file."""
        output_path = Path(output_path)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2),
            encoding="utf-8",
        )

    def print_summary(self, verbose: bool = False) -> None:
        """Print a console summary, optionally with colour."""
        data = self.to_dict()
        summary = data["summary"]
        actions = summary["actions"]

        def _c(text: str, colour: str) -> str:
            if _HAS_COLORAMA:
                return f"{colour}{text}{Style.RESET_ALL}"
            return text

        print(_c("\n=== UVM Transpiler — Summary ===", Fore.CYAN if _HAS_COLORAMA else ""))
        print(f"  Files scanned   : {summary['files_scanned']}")
        print(f"  Files modified  : {_c(str(summary['files_modified']), Fore.GREEN if _HAS_COLORAMA else '')}")
        print(f"  Classes processed: {summary['classes_processed']}")
        print()
        print(f"  Factory macros added : {actions['factory_macros_added']}")
        print(f"  Factory macros fixed : {actions['factory_macros_fixed']}")
        print(f"  Field macros added   : {actions['field_macros_added']}")
        print(f"  Constructors added   : {actions['constructors_added']}")
        print(f"  Constructors fixed   : {actions['constructors_fixed']}")

        if data["warnings"]:
            print()
            warn_colour = Fore.YELLOW if _HAS_COLORAMA else ""
            print(_c(f"  Warnings ({len(data['warnings'])}):", warn_colour))
            for w in data["warnings"]:
                print(_c(f"    [{w['file']}] {w['class']}: {w['message']}", warn_colour))

        if verbose and data["files"]:
            print()
            print("  Per-file details:")
            for fentry in data["files"]:
                for cls in fentry["classes"]:
                    for act in cls["actions"]:
                        if act["type"] in (ActionType.FACTORY_OK, ActionType.FIELD_OK, ActionType.CONSTRUCTOR_OK):
                            continue
                        line_info = f" (line {act['line']})" if act.get("line") else ""
                        macro_info = f" {act['macro']}" if act.get("macro") else ""
                        print(f"    [{act['type']}]{macro_info}{line_info} in {cls['name']} ({fentry['path']})")
