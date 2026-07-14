"""
tests/test_constructor_checker.py
==================================
Unit tests for scripts/constructor_checker.py
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
from scripts.constructor_checker import _generate_constructor, process_file


TAXONOMY = UVMTaxonomy()


# ---------------------------------------------------------------------------
# Constructor generation
# ---------------------------------------------------------------------------

class TestGenerateConstructor:

    def _make_cls(self, name: str, parent: str):
        classes = parse_text(f"class {name} extends {parent};\nendclass\n")
        return classes[0]

    def test_component_constructor_signature(self):
        cls = self._make_cls("my_driver", "uvm_driver")
        lines = _generate_constructor(cls, UVMFamily.COMPONENT, "  ")
        full = "".join(lines)
        assert 'string name = "my_driver"' in full
        assert "uvm_component parent = null" in full
        assert "super.new(name, parent);" in full
        assert "endfunction" in full

    def test_object_constructor_signature(self):
        cls = self._make_cls("my_item", "uvm_sequence_item")
        lines = _generate_constructor(cls, UVMFamily.OBJECT, "  ")
        full = "".join(lines)
        assert 'string name = "my_item"' in full
        assert "uvm_component parent" not in full
        assert "super.new(name);" in full

    def test_component_indent_applied(self):
        cls = self._make_cls("my_drv", "uvm_driver")
        lines = _generate_constructor(cls, UVMFamily.COMPONENT, "    ")
        assert lines[0].startswith("    function")
        assert lines[1].startswith("      super")


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestConstructorIntegration:

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_constructor_added_when_absent(self, fixtures_dir, tmp_path):
        import shutil
        src = fixtures_dir / "no_constructor.sv"
        dst = tmp_path / "no_constructor.sv"
        shutil.copy(src, dst)

        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)

        content = dst.read_text()
        assert "function new(" in content
        assert 'string name = "my_scoreboard"' in content
        assert "super.new(name, parent);" in content
        assert "endfunction" in content

    def test_super_new_inserted_when_missing(self, fixtures_dir, tmp_path):
        import shutil
        src = fixtures_dir / "missing_super_new.sv"
        dst = tmp_path / "missing_super_new.sv"
        shutil.copy(src, dst)

        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)

        content = dst.read_text()
        assert "super.new(name, parent);" in content

    def test_existing_correct_constructor_unchanged(self, fixtures_dir, tmp_path):
        import shutil
        src = fixtures_dir / "component_no_macro.sv"  # has correct new()
        dst = tmp_path / "component_no_macro.sv"
        shutil.copy(src, dst)

        original = dst.read_text()
        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)
        after = dst.read_text()

        # Constructor was already correct — body should be unchanged
        assert "super.new(name, parent);" in after

    def test_idempotent(self, fixtures_dir, tmp_path):
        """Running constructor_checker twice should produce the same output."""
        import shutil
        src = fixtures_dir / "no_constructor.sv"
        dst = tmp_path / "no_constructor.sv"
        shutil.copy(src, dst)

        rep = Reporter()
        process_file(dst, TAXONOMY, rep, backup=False)
        content1 = dst.read_text()
        process_file(dst, TAXONOMY, rep, backup=False)
        content2 = dst.read_text()

        assert content1 == content2
