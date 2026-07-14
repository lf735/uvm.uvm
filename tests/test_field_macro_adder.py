"""
tests/test_field_macro_adder.py
================================
Unit tests for scripts/field_macro_adder.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from core.sv_parser import parse_text, SVMember
from core.uvm_taxonomy import UVMTaxonomy
from scripts.field_macro_adder import _base_field_macro, _build_field_macro_line


TAXONOMY = UVMTaxonomy()


# ---------------------------------------------------------------------------
# Type mapping tests
# ---------------------------------------------------------------------------

class TestTypeMappings:

    def _make_member(self, name: str, sv_type: str, **kwargs) -> SVMember:
        return SVMember(name=name, sv_type=sv_type, **kwargs)

    def test_int_maps_to_field_int(self):
        m = self._make_member("addr", "int")
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_int"

    def test_logic_maps_to_field_int(self):
        m = self._make_member("data", "logic")
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_int"

    def test_string_maps_to_field_string(self):
        m = self._make_member("tag", "string")
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_string"

    def test_real_maps_to_field_real(self):
        m = self._make_member("voltage", "real")
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_real"

    def test_enum_maps_to_field_enum(self):
        m = self._make_member("kind", "my_enum_t", is_enum=True)
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_enum"

    def test_dynamic_array_int(self):
        m = self._make_member("data", "int", is_array=True, is_dynamic_array=True)
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_array_int"

    def test_queue_string(self):
        m = self._make_member("msgs", "string", is_array=True, is_queue=True)
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_queue_string"

    def test_static_array_int(self):
        m = self._make_member("regs", "int", is_array=True, is_dynamic_array=False, is_queue=False)
        assert _base_field_macro(m, TAXONOMY) == "uvm_field_sarray_int"

    def test_unknown_type_returns_none(self):
        m = self._make_member("x", "some_custom_type_xyz")
        result = _base_field_macro(m, TAXONOMY)
        assert result is None


# ---------------------------------------------------------------------------
# Line building tests
# ---------------------------------------------------------------------------

class TestLineBuild:

    def _make_member(self, name: str, sv_type: str, **kwargs) -> SVMember:
        return SVMember(name=name, sv_type=sv_type, **kwargs)

    def test_int_line_format(self):
        m = self._make_member("addr", "int")
        line = _build_field_macro_line(m, TAXONOMY, "  ")
        assert line == "  `uvm_field_int(addr, UVM_ALL_ON)\n"

    def test_string_line_format(self):
        m = self._make_member("tag", "string")
        line = _build_field_macro_line(m, TAXONOMY, "    ")
        assert line == "    `uvm_field_string(tag, UVM_ALL_ON)\n"

    def test_enum_line_format(self):
        m = self._make_member("kind", "my_enum_t", is_enum=True)
        line = _build_field_macro_line(m, TAXONOMY, "  ")
        assert "uvm_field_enum" in line
        assert "my_enum_t" in line
        assert "kind" in line


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestFieldIntegration:

    @pytest.fixture
    def fixtures_dir(self):
        return Path(__file__).parent / "fixtures"

    def test_fields_added_to_begin_end_block(self, fixtures_dir, tmp_path):
        import shutil
        from scripts.factory_checker import process_file as factory_process
        from scripts.field_macro_adder import process_file as fields_process
        from core.reporter import Reporter

        src = fixtures_dir / "fields_to_add.sv"
        dst = tmp_path / "fields_to_add.sv"
        shutil.copy(src, dst)

        rep = Reporter()
        # First run factory to ensure begin/end block is present
        factory_process(dst, TAXONOMY, rep, backup=False)
        # Then run field adder
        fields_process(dst, TAXONOMY, rep, backup=False)

        content = dst.read_text()
        assert "`uvm_field_int(addr" in content
        assert "`uvm_field_int(data" in content
        assert "`uvm_field_string(tag" in content
        assert "`uvm_field_int(rw" in content   # bit → int

    def test_no_duplicate_fields(self, fixtures_dir, tmp_path):
        """Running field_macro_adder twice should not add duplicate macros."""
        import shutil
        from scripts.factory_checker import process_file as factory_process
        from scripts.field_macro_adder import process_file as fields_process
        from core.reporter import Reporter

        src = fixtures_dir / "fields_to_add.sv"
        dst = tmp_path / "fields_to_add.sv"
        shutil.copy(src, dst)

        rep = Reporter()
        factory_process(dst, TAXONOMY, rep, backup=False)
        fields_process(dst, TAXONOMY, rep, backup=False)
        content1 = dst.read_text()
        fields_process(dst, TAXONOMY, rep, backup=False)
        content2 = dst.read_text()

        # Content should be identical after second run
        assert content1 == content2
