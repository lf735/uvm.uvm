"""
core/uvm_taxonomy.py
====================
UVM class hierarchy and classification rules.

Provides:
  - UVMFamily enum: COMPONENT, OBJECT, UNKNOWN
  - UVMTaxonomy: resolves a parent class name to its UVM family
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum, auto


class UVMFamily(Enum):
    COMPONENT = auto()
    OBJECT = auto()
    UNKNOWN = auto()


@dataclass
class PhaseProto:
    """Expected prototype for a UVM phase method."""
    name: str
    is_task: bool          # True = task, False = function void
    return_type: str       # "" for tasks, "void" for function phases
    param: str             # canonical parameter string, e.g. "uvm_phase phase"
    is_main: bool          # True if in the 'main' subset (build/connect/run)


# ---------------------------------------------------------------------------
# UVM standard phase prototypes
# ---------------------------------------------------------------------------
_FUNCTION_PHASES = {
    "build_phase":               True,   # is_main
    "connect_phase":             True,
    "end_of_elaboration_phase":  False,
    "start_of_simulation_phase": False,
    "extract_phase":             False,
    "check_phase":               False,
    "report_phase":              False,
    "final_phase":               False,
}
_TASK_PHASES = {
    "run_phase":            True,   # is_main
    "pre_reset_phase":      False,
    "reset_phase":          False,
    "post_reset_phase":     False,
    "pre_configure_phase":  False,
    "configure_phase":      False,
    "post_configure_phase": False,
    "pre_main_phase":       False,
    "main_phase":           False,
    "post_main_phase":      False,
    "pre_shutdown_phase":   False,
    "shutdown_phase":       False,
    "post_shutdown_phase":  False,
}

UVM_PHASE_PROTOTYPES: dict[str, PhaseProto] = {}
for _name, _is_main in _FUNCTION_PHASES.items():
    UVM_PHASE_PROTOTYPES[_name] = PhaseProto(
        name=_name, is_task=False, return_type="void",
        param="uvm_phase phase", is_main=_is_main,
    )
for _name, _is_main in _TASK_PHASES.items():
    UVM_PHASE_PROTOTYPES[_name] = PhaseProto(
        name=_name, is_task=True, return_type="",
        param="uvm_phase phase", is_main=_is_main,
    )
del _name, _is_main


# ---------------------------------------------------------------------------
# Known UVM component base classes (and common derivatives)
# ---------------------------------------------------------------------------
_COMPONENT_CLASSES: set[str] = {
    "uvm_component",
    "uvm_driver",
    "uvm_monitor",
    "uvm_agent",
    "uvm_env",
    "uvm_test",
    "uvm_scoreboard",
    "uvm_subscriber",
    "uvm_sequencer",
    "uvm_sequencer_base",
    "uvm_push_driver",
    "uvm_push_sequencer",
    "uvm_pull_sequencer",
    "uvm_checker",
    "uvm_coverage_collector",
}

# ---------------------------------------------------------------------------
# Known UVM object base classes (and common derivatives)
# ---------------------------------------------------------------------------
_OBJECT_CLASSES: set[str] = {
    "uvm_object",
    "uvm_transaction",
    "uvm_sequence_item",
    "uvm_sequence",
    "uvm_base_sequence",
    "uvm_reg",
    "uvm_reg_block",
    "uvm_reg_field",
    "uvm_reg_map",
    "uvm_reg_sequence",
    "uvm_mem",
    "uvm_phase",
    "uvm_report_object",
    "uvm_config_object",
    "uvm_resource",
}


def strip_package_prefix(name: str) -> str:
    """Remove package scope: 'pkg::class' -> 'class'."""
    return name.split("::")[-1]


def strip_param(name: str) -> str:
    """Remove parameter list from a type: 'uvm_driver #(T)' -> 'uvm_driver'."""
    return name.split("#")[0].strip()


class UVMTaxonomy:
    """
    Resolves UVM family for a given parent class name.

    Maintains a user-extendable registry of known base classes so that
    derived classes in the same project can be resolved transitively.

    Example::

        tax = UVMTaxonomy()
        tax.resolve("uvm_driver")      # -> UVMFamily.COMPONENT
        tax.resolve("my_driver")       # -> UVMFamily.UNKNOWN (unless registered)

        tax.register("my_driver", UVMFamily.COMPONENT)
        tax.resolve("my_driver")       # -> UVMFamily.COMPONENT
    """

    def __init__(self) -> None:
        self._registry: dict[str, UVMFamily] = {}
        # seed with known classes
        for cls in _COMPONENT_CLASSES:
            self._registry[cls] = UVMFamily.COMPONENT
        for cls in _OBJECT_CLASSES:
            self._registry[cls] = UVMFamily.OBJECT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, parent_name: str | None) -> UVMFamily:
        """
        Resolve a parent class name to its UVM family.

        The name is normalised by stripping package prefixes and parameters.
        Returns UNKNOWN if the class is not in the registry.
        """
        if parent_name is None:
            return UVMFamily.UNKNOWN

        normalised = strip_param(strip_package_prefix(parent_name))
        return self._registry.get(normalised, UVMFamily.UNKNOWN)

    def register(self, class_name: str, family: UVMFamily) -> None:
        """Register a user-defined class in the taxonomy."""
        self._registry[class_name] = family

    def expected_factory_macro(
        self, family: UVMFamily, is_parameterized: bool
    ) -> str | None:
        """
        Return the base name of the expected factory macro.

        Returns None if family is UNKNOWN.

        Examples::
            expected_factory_macro(COMPONENT, False) -> "uvm_component_utils"
            expected_factory_macro(OBJECT, True)     -> "uvm_object_param_utils"
        """
        if family == UVMFamily.UNKNOWN:
            return None
        base = "uvm_component" if family == UVMFamily.COMPONENT else "uvm_object"
        suffix = "_param_utils" if is_parameterized else "_utils"
        return f"{base}{suffix}"

    def expected_factory_macro_begin(
        self, family: UVMFamily, is_parameterized: bool
    ) -> str | None:
        """Return the _utils_begin variant of the expected macro name."""
        base_macro = self.expected_factory_macro(family, is_parameterized)
        if base_macro is None:
            return None
        return f"{base_macro}_begin"

    def is_factory_macro(self, macro_name: str) -> bool:
        """Return True if macro_name is any form of UVM factory macro."""
        factory_prefixes = (
            "uvm_component_utils",
            "uvm_object_utils",
            "uvm_component_param_utils",
            "uvm_object_param_utils",
        )
        return any(macro_name.startswith(p) for p in factory_prefixes)

    def classify_factory_macro(self, macro_name: str) -> tuple[UVMFamily, bool, bool]:
        """
        Classify an existing factory macro.

        Returns:
            (family, is_parameterized, is_begin_end)
        """
        is_begin = macro_name.endswith("_begin")
        name = macro_name.removesuffix("_begin")

        if "component_param" in name:
            return UVMFamily.COMPONENT, True, is_begin
        elif "object_param" in name:
            return UVMFamily.OBJECT, True, is_begin
        elif "component" in name:
            return UVMFamily.COMPONENT, False, is_begin
        elif "object" in name:
            return UVMFamily.OBJECT, False, is_begin
        return UVMFamily.UNKNOWN, False, is_begin

    @staticmethod
    def get_phase_prototype(name: str) -> "PhaseProto | None":
        """Return the PhaseProto for a UVM standard phase method, or None if unknown."""
        return UVM_PHASE_PROTOTYPES.get(name)
