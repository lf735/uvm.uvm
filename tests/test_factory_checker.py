"""
tests/test_factory_checker.py
==============================
Unit tests for scripts/factory_checker.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.sv_parser import parse_text
from core.uvm_taxonomy import UVMTaxonomy, UVMFamily
from core.reporter import Reporter
from scripts.factory_checker import decide, FactoryDecision, apply_factory_fix


TAXONOMY = UVMTaxonomy()


# ---------------------------------------------------------------------------
# Test: decision engine
# ---------------------------------------------------------------------------

class TestDecision:

    def test_component_no_macro_absent(self):
        src = """\
class my_driver extends uvm_driver;
  int timeout;
endclass
"""
        classes = parse_text(src)
        assert len(classes) == 1
        cls = classes[0]
        decision, expected = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.ABSENT
        assert expected == "uvm_component_utils"

    def test_object_wrong_macro_type(self):
        src = """\
class my_item extends uvm_sequence_item;
  `uvm_component_utils(my_item)
endclass
"""
        classes = parse_text(src)
        assert len(classes) == 1
        cls = classes[0]
        decision, expected = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.WRONG_TYPE
        assert expected == "uvm_object_utils"

    def test_component_correct_macro_ok(self):
        src = """\
class my_monitor extends uvm_monitor;
  `uvm_component_utils(my_monitor)
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, _ = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.OK

    def test_wrong_class_name_in_macro(self):
        src = """\
class my_driver extends uvm_driver;
  `uvm_component_utils(old_driver_name)
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, _ = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.WRONG_NAME

    def test_parameterized_component(self):
        src = """\
class my_drv #(parameter int W=8) extends uvm_driver;
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, expected = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.ABSENT
        assert expected == "uvm_component_param_utils"

    def test_unknown_parent_returns_absent_with_none(self):
        src = """\
class my_cls extends some_unknown_base;
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, expected = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.ABSENT
        assert expected is None  # unknown → no expected macro

    def test_begin_end_block_wrong_prefix(self):
        src = """\
class my_item extends uvm_sequence_item;
  `uvm_component_utils_begin(my_item)
  `uvm_component_utils_end
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, expected = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.BEGIN_END
        assert expected == "uvm_object_utils"

    def test_begin_end_block_correct(self):
        src = """\
class my_item extends uvm_sequence_item;
  `uvm_object_utils_begin(my_item)
  `uvm_object_utils_end
endclass
"""
        classes = parse_text(src)
        cls = classes[0]
        decision, _ = decide(cls, TAXONOMY)
        assert decision == FactoryDecision.OK


# ---------------------------------------------------------------------------
# Test: line modification
# ---------------------------------------------------------------------------

class TestApplyFix:

    def test_inject_absent_macro(self):
        src = "class my_driver extends uvm_driver;\n  int x;\nendclass\n"
        lines = src.splitlines(keepends=True)
        classes = parse_text(src)
        cls = classes[0]
        lines, actions = apply_factory_fix(lines, cls, FactoryDecision.ABSENT, "uvm_component_utils")
        assert any("`uvm_component_utils(my_driver)" in a["macro"] for a in actions)
        full = "".join(lines)
        assert "`uvm_component_utils(my_driver)" in full

    def test_fix_wrong_type(self):
        src = "class my_item extends uvm_sequence_item;\n  `uvm_component_utils(my_item)\nendclass\n"
        lines = src.splitlines(keepends=True)
        classes = parse_text(src)
        cls = classes[0]
        lines, actions = apply_factory_fix(lines, cls, FactoryDecision.WRONG_TYPE, "uvm_object_utils")
        full = "".join(lines)
        assert "`uvm_object_utils(my_item)" in full
        assert "`uvm_component_utils" not in full

    def test_dry_run_does_not_modify(self):
        src = "class my_driver extends uvm_driver;\n  int x;\nendclass\n"
        lines_orig = src.splitlines(keepends=True)
        lines = list(lines_orig)
        classes = parse_text(src)
        cls = classes[0]
        lines_out, actions = apply_factory_fix(lines, cls, FactoryDecision.ABSENT,
                                               "uvm_component_utils", dry_run=True)
        # Dry run returns original lines unchanged
        assert "".join(lines_out) == "".join(lines_orig)
        # But actions are still reported
        assert len(actions) == 1


# ---------------------------------------------------------------------------
# Test: integration via file
# ---------------------------------------------------------------------------

class TestFileIntegration:
    """Integration tests using fixture files."""

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_component_no_macro_fixture(self, fixtures_dir, tmp_path):
        import shutil
        src = fixtures_dir / "component_no_macro.sv"
        dst = tmp_path / "component_no_macro.sv"
        shutil.copy(src, dst)

        from scripts.factory_checker import process_file
        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)

        content = dst.read_text()
        assert "`uvm_component_utils(my_driver)" in content

    def test_object_wrong_macro_fixture(self, fixtures_dir, tmp_path):
        import shutil
        src = fixtures_dir / "object_wrong_macro.sv"
        dst = tmp_path / "object_wrong_macro.sv"
        shutil.copy(src, dst)

        from scripts.factory_checker import process_file
        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)

        content = dst.read_text()
        assert "`uvm_object_utils(my_seq_item)" in content
        # The comment line contains the text but the actual macro invocation must be gone
        assert "`uvm_component_utils(" not in content
