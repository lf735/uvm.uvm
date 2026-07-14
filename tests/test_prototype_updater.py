"""
tests/test_prototype_updater.py
================================
Unit tests for scripts/prototype_updater.py (Script 4).

Test strategy
-------------
Most tests use ``process_file`` in ``dry_run=True`` mode and inspect the
Reporter's action list rather than the file system.  A few tests write to a
temporary file to verify actual line modifications.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import sys
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.uvm_taxonomy import UVMTaxonomy
from core.reporter import Reporter, ActionType
from scripts.prototype_updater import process_file, _sig_matches, _rebuild_decl_line
from core.uvm_taxonomy import UVM_PHASE_PROTOTYPES
from core.sv_parser import SVFunction, SVPort


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reporter() -> Reporter:
    return Reporter(mode="dry-run", scripts_run=["prototype_updater"])


def _actions_of_type(reporter: Reporter, action_type: str) -> list[dict]:
    """Collect all actions of a given type from the reporter."""
    result = []
    for fentry in reporter.to_dict()["files"]:
        for cls in fentry["classes"]:
            for act in cls["actions"]:
                if act["type"] == action_type:
                    result.append(act)
    return result


FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------

class TestSigMatches:
    """Tests for the _sig_matches() helper."""

    def test_correct_task_matches(self):
        proto = UVM_PHASE_PROTOTYPES["run_phase"]
        func = SVFunction(
            name="run_phase",
            is_task=True,
            return_type="",
            port_list=[SVPort(direction="", sv_type="uvm_phase", name="phase")],
        )
        assert _sig_matches(func, proto) is True

    def test_function_for_task_does_not_match(self):
        proto = UVM_PHASE_PROTOTYPES["run_phase"]
        func = SVFunction(
            name="run_phase",
            is_task=False,      # WRONG: should be task
            return_type="void",
            port_list=[SVPort(direction="", sv_type="uvm_phase", name="phase")],
        )
        assert _sig_matches(func, proto) is False

    def test_wrong_return_type_does_not_match(self):
        proto = UVM_PHASE_PROTOTYPES["build_phase"]
        func = SVFunction(
            name="build_phase",
            is_task=False,
            return_type="int",  # WRONG: should be void
            port_list=[SVPort(direction="", sv_type="uvm_phase", name="phase")],
        )
        assert _sig_matches(func, proto) is False

    def test_correct_void_function_matches(self):
        proto = UVM_PHASE_PROTOTYPES["build_phase"]
        func = SVFunction(
            name="build_phase",
            is_task=False,
            return_type="void",
            port_list=[SVPort(direction="", sv_type="uvm_phase", name="phase")],
        )
        assert _sig_matches(func, proto) is True

    def test_missing_uvm_phase_param_does_not_match(self):
        proto = UVM_PHASE_PROTOTYPES["connect_phase"]
        func = SVFunction(
            name="connect_phase",
            is_task=False,
            return_type="void",
            port_list=[],   # no parameters at all
        )
        assert _sig_matches(func, proto) is False


class TestRebuildDeclLine:
    """Tests for the _rebuild_decl_line() helper."""

    def test_rebuild_task(self):
        proto = UVM_PHASE_PROTOTYPES["run_phase"]
        original = "  function void run_phase(uvm_phase phase);\n"
        result = _rebuild_decl_line(original, proto, is_extern=False)
        assert result == "  task run_phase(uvm_phase phase);\n"

    def test_rebuild_function_void(self):
        proto = UVM_PHASE_PROTOTYPES["build_phase"]
        original = "  function int build_phase(uvm_phase phase);\n"
        result = _rebuild_decl_line(original, proto, is_extern=False)
        assert result == "  function void build_phase(uvm_phase phase);\n"

    def test_rebuild_extern(self):
        proto = UVM_PHASE_PROTOTYPES["connect_phase"]
        original = "  extern function void connect_phase();\n"
        result = _rebuild_decl_line(original, proto, is_extern=True)
        assert result == "  extern function void connect_phase(uvm_phase phase);\n"

    def test_preserves_virtual_modifier(self):
        proto = UVM_PHASE_PROTOTYPES["build_phase"]
        original = "  virtual function int build_phase(uvm_phase phase);\n"
        result = _rebuild_decl_line(original, proto, is_extern=False)
        assert "virtual" in result
        assert "function void build_phase" in result


# ---------------------------------------------------------------------------
# Integration tests — process_file on the fixture
# ---------------------------------------------------------------------------

class TestProcessFileOnFixture:
    """Integration tests using tests/fixtures/wrong_phase_sig.sv."""

    FIXTURE = FIXTURE_DIR / "wrong_phase_sig.sv"

    def setup_method(self):
        self.taxonomy = UVMTaxonomy()

    def test_wrong_body_only_reports_error_by_default(self):
        """run_phase as function (body only) → PROTOTYPE_ERROR, no fix."""
        rep = _make_reporter()
        process_file(self.FIXTURE, self.taxonomy, rep, backup=False, dry_run=True)
        errors = _actions_of_type(rep, ActionType.PROTOTYPE_ERROR)
        # my_driver has run_phase (function) and build_phase (int) — both wrong
        error_details = [e.get("detail", "") for e in errors]
        assert any("run_phase" in d for d in error_details)
        assert any("build_phase" in d for d in error_details)

    def test_wrong_extern_reports_error_by_default(self):
        """my_monitor: extern connect_phase() is wrong → PROTOTYPE_ERROR."""
        rep = _make_reporter()
        process_file(self.FIXTURE, self.taxonomy, rep, backup=False, dry_run=True)
        errors = _actions_of_type(rep, ActionType.PROTOTYPE_ERROR)
        assert any("connect_phase" in e.get("detail", "") for e in errors)

    def test_correct_extern_wrong_body_auto_fixed(self):
        """my_scoreboard: extern correct, body wrong → PROTOTYPE_FIXED (auto)."""
        rep = _make_reporter()
        process_file(self.FIXTURE, self.taxonomy, rep, backup=False, dry_run=True)
        fixed = _actions_of_type(rep, ActionType.PROTOTYPE_FIXED)
        # build_phase body in my_scoreboard should be auto-fixed
        assert any("build_phase" in f.get("detail", "") for f in fixed)

    def test_all_correct_class_reports_ok(self):
        """my_agent: both build_phase and run_phase correct → PROTOTYPE_OK."""
        rep = _make_reporter()
        process_file(self.FIXTURE, self.taxonomy, rep, backup=False, dry_run=True)
        ok_actions = _actions_of_type(rep, ActionType.PROTOTYPE_OK)
        ok_details = [a.get("detail", "") for a in ok_actions]
        assert any("build_phase" in d for d in ok_details)
        assert any("run_phase" in d for d in ok_details)

    def test_force_fix_corrects_wrong_body(self, tmp_path):
        """--force-fix on body-only wrong signature → file is actually modified."""
        import shutil
        tmp_sv = tmp_path / "wrong_phase_sig.sv"
        shutil.copy(self.FIXTURE, tmp_sv)

        rep = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=False, force_fix=True)

        content = tmp_sv.read_text(encoding="utf-8")
        # run_phase must now be 'task' in my_driver
        # (we look for the pattern in class my_driver, before the next class)
        driver_block = content.split("class my_monitor")[0]
        assert "task run_phase(uvm_phase phase)" in driver_block

    def test_force_fix_corrects_wrong_extern(self, tmp_path):
        """--force-fix on wrong extern → extern line is corrected."""
        import shutil
        tmp_sv = tmp_path / "wrong_phase_sig.sv"
        shutil.copy(self.FIXTURE, tmp_sv)

        rep = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=False, force_fix=True)

        content = tmp_sv.read_text(encoding="utf-8")
        # extern connect_phase must now have uvm_phase parameter
        assert "extern function void connect_phase(uvm_phase phase)" in content

    def test_dry_run_no_file_modification(self, tmp_path):
        """dry_run=True → file must not be modified."""
        import shutil
        tmp_sv = tmp_path / "wrong_phase_sig.sv"
        shutil.copy(self.FIXTURE, tmp_sv)
        original = tmp_sv.read_text(encoding="utf-8")

        rep = _make_reporter()
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=True, force_fix=True)

        assert tmp_sv.read_text(encoding="utf-8") == original

    def test_inject_phases_main(self, tmp_path):
        """--inject-phases main on a class without build/connect/run → stubs injected."""
        sv_content = textwrap.dedent("""\
            class my_env extends uvm_env;
              `uvm_component_utils(my_env)
              function new(string name = "my_env", uvm_component parent = null);
                super.new(name, parent);
              endfunction
            endclass
        """)
        tmp_sv = tmp_path / "no_phases.sv"
        tmp_sv.write_text(sv_content, encoding="utf-8")

        rep = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=False, inject_phases="main")

        injected = _actions_of_type(rep, ActionType.PROTOTYPE_INJECTED)
        injected_names = {a.get("detail", "") for a in injected}
        assert any("build_phase" in n for n in injected_names)
        assert any("connect_phase" in n for n in injected_names)
        assert any("run_phase" in n for n in injected_names)

    def test_inject_phases_all(self, tmp_path):
        """--inject-phases all → at least 8+ phase stubs injected."""
        sv_content = textwrap.dedent("""\
            class my_test extends uvm_test;
              `uvm_component_utils(my_test)
              function new(string name = "my_test", uvm_component parent = null);
                super.new(name, parent);
              endfunction
            endclass
        """)
        tmp_sv = tmp_path / "no_phases_all.sv"
        tmp_sv.write_text(sv_content, encoding="utf-8")

        rep = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=False, inject_phases="all")

        injected = _actions_of_type(rep, ActionType.PROTOTYPE_INJECTED)
        assert len(injected) >= 8  # at least the main phases

    def test_user_method_ignored(self, tmp_path):
        """A non-UVM method (my_custom_func) must not be touched."""
        sv_content = textwrap.dedent("""\
            class my_driver extends uvm_driver;
              `uvm_component_utils(my_driver)
              function new(string name = "my_driver", uvm_component parent = null);
                super.new(name, parent);
              endfunction
              function void my_custom_func(int x);
              endfunction
            endclass
        """)
        tmp_sv = tmp_path / "user_method.sv"
        tmp_sv.write_text(sv_content, encoding="utf-8")
        original = tmp_sv.read_text(encoding="utf-8")

        rep = _make_reporter()
        process_file(tmp_sv, self.taxonomy, rep,
                     backup=False, dry_run=True, force_fix=True)

        # No prototype actions except possibly PROTOTYPE_OK
        all_actions = []
        for fentry in rep.to_dict()["files"]:
            for cls in fentry["classes"]:
                all_actions.extend(cls["actions"])
        proto_actions = [a for a in all_actions
                         if a["type"] not in (ActionType.PROTOTYPE_OK, ActionType.SKIPPED)]
        assert proto_actions == []

    def test_unknown_parent_class_ignored(self, tmp_path):
        """Classes with unknown parent → skipped entirely."""
        sv_content = textwrap.dedent("""\
            class my_thing extends some_unknown_base;
              function void build_phase(uvm_phase phase);
              endfunction
            endclass
        """)
        tmp_sv = tmp_path / "unknown_parent.sv"
        tmp_sv.write_text(sv_content, encoding="utf-8")

        rep = _make_reporter()
        process_file(tmp_sv, self.taxonomy, rep, backup=False, dry_run=True)

        errors = _actions_of_type(rep, ActionType.PROTOTYPE_ERROR)
        fixed  = _actions_of_type(rep, ActionType.PROTOTYPE_FIXED)
        assert errors == []
        assert fixed  == []

    def test_idempotence(self, tmp_path):
        """Running the script twice on a fixed file produces no additional changes."""
        import shutil
        tmp_sv = tmp_path / "idem.sv"
        shutil.copy(self.FIXTURE, tmp_sv)

        tax = UVMTaxonomy()

        # First pass — fix everything
        rep1 = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, tax, rep1,
                     backup=False, dry_run=False, force_fix=True)

        content_after_first = tmp_sv.read_text(encoding="utf-8")

        # Second pass — should make no more changes
        rep2 = Reporter(mode="fix", scripts_run=["prototype_updater"])
        process_file(tmp_sv, tax, rep2,
                     backup=False, dry_run=False, force_fix=True)

        content_after_second = tmp_sv.read_text(encoding="utf-8")
        fixed_second = _actions_of_type(rep2, ActionType.PROTOTYPE_FIXED)

        assert content_after_first == content_after_second
        assert fixed_second == [], "Second pass should make no additional fixes"
