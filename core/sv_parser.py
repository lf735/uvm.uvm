"""
core/sv_parser.py
=================
Structural parser for SystemVerilog files used by the UVM transpiler suite.

Strategy
--------
We use a two-pass approach:
  1. A regex-based line scanner that finds class boundaries, macros,
     function boundaries, and variable declarations.  This is robust against
     the many SV constructs that a partial Lark grammar cannot handle.
  2. Optional Lark parse for finer-grained structure if the grammar matches.

The line scanner is always the primary engine because SV real-world files
contain too many preprocessor directives and construct variations for a
partial grammar to handle reliably without error recovery.

Public API
----------
    parse_file(path: str | Path) -> list[SVClass]
    parse_text(source: str, filename: str = "<string>") -> list[SVClass]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ===========================================================================
# Data classes
# ===========================================================================

@dataclass
class SVPort:
    direction: str       # input / output / inout / ref / ""
    sv_type: str
    name: str
    default: Optional[str] = None


@dataclass
class SVFunction:
    name: str
    port_list: list[SVPort] = field(default_factory=list)
    has_super_call: bool = False
    super_call_line: Optional[int] = None
    start_line: int = 0      # 1-based
    end_line: int = 0
    return_type: str = ""    # e.g. "void", "int", "" (empty for tasks)
    is_task: bool = False    # True if declared as 'task', False if 'function'
    is_extern: bool = False  # True if prefixed with 'extern'


@dataclass
class SVMacro:
    name: str                # e.g. "uvm_component_utils"
    args: list[str] = field(default_factory=list)
    line: int = 0            # 1-based


@dataclass
class SVMember:
    name: str
    sv_type: str             # e.g. "int", "string", "my_seq_item"
    is_array: bool = False
    is_dynamic_array: bool = False
    is_queue: bool = False
    is_enum: bool = False
    visibility: str = "public"   # public / protected / local
    line: int = 0


@dataclass
class SVClass:
    name: str
    is_virtual: bool = False
    is_parameterized: bool = False
    param_str: str = ""          # raw param string e.g. "#(parameter int N=8)"
    parent: Optional[str] = None # normalised parent name
    parent_params: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    macros: list[SVMacro] = field(default_factory=list)
    members: list[SVMember] = field(default_factory=list)
    functions: list[SVFunction] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)  # 0-based slice of file

    @property
    def constructor(self) -> Optional[SVFunction]:
        for f in self.functions:
            if f.name == "new":
                return f
        return None


# ===========================================================================
# Regex patterns
# ===========================================================================

# Match class header (possibly split across line continuations)
_RE_CLASS_HEADER = re.compile(
    r"""
    (?P<virtual>virtual\s+)?
    class\s+
    (?P<name>[A-Za-z_]\w*)
    (?P<params>\s*\#\s*\([^)]*(?:\([^)]*\)[^)]*)*\))?  # optional #(...)
    (?P<extends>\s+extends\s+[\w:$#(),\s]+?)?             # optional extends
    (?P<implements>\s+implements\s+[\w:,\s]+?)?           # optional implements
    \s*;
    """,
    re.VERBOSE,
)

_RE_ENDCLASS = re.compile(r"^\s*endclass\b")

# Backtick macros
_RE_MACRO = re.compile(
    r"`(?P<name>[A-Za-z_]\w*)\s*(?:\(\s*(?P<args>[^)]*)\s*\))?"
)

# Function/task declaration
_RE_FUNC_START = re.compile(
    r"""
    ^\s*
    (?P<extern>extern\s+)?
    (?:virtual\s+)?
    (?:automatic\s+|static\s+)?
    function\s+
    (?:(?P<rettype>void|automatic|[\w:]+)\s+)?  # optional return type
    (?P<name>[A-Za-z_]\w*)  # function name
    \s*\(
    """,
    re.VERBOSE,
)
_RE_TASK_START = re.compile(
    r"""
    ^\s*
    (?P<extern>extern\s+)?
    (?:virtual\s+)?
    (?:automatic\s+)?
    task\s+
    (?P<name>[A-Za-z_]\w*)
    \s*[;(]
    """,
    re.VERBOSE,
)
_RE_ENDFUNCTION = re.compile(r"^\s*endfunction\b")
_RE_ENDTASK = re.compile(r"^\s*endtask\b")

# super.new call
_RE_SUPER_NEW = re.compile(r"\bsuper\s*\.\s*new\s*\(")

# Variable member — simplified but covers common SV types
_KNOWN_TYPES = (
    r"int|integer|longint|unsigned|shortint|byte|bit|logic|reg|wire|"
    r"real|shortreal|string|chandle|event"
)
_RE_VAR_DECL = re.compile(
    r"""
    ^\s*
    (?:(?:local|protected|static|rand|randc)\s+)*   # visibility / qualifiers
    (?P<vis>local|protected)?
    \s*
    (?:(?:local|protected|static|rand|randc)\s+)*   # may appear before type too
    (?P<type>
        (?:""" + _KNOWN_TYPES + r""")               # primitive types
        (?:\s*\[[\w\s:$+\-*\/]+\])*                 # optional packed dims
      | [A-Za-z_]\w*(?:::[A-Za-z_]\w*)*             # user-defined type
        (?:\s*\#\s*\([^)]*\))?                       # optional params
    )
    (?:\s*\[[\w\s:$+\-*\/]+\])*                     # unpacked dims in type
    \s+
    (?P<name>[A-Za-z_]\w*)                           # variable name
    (?P<dims>(?:\s*\[[\w\s:$+\-*\/]*\])*)?          # unpacked array dims
    \s*(?:=\s*(?P<default>[^;]+))?
    \s*;
    """,
    re.VERBOSE,
)

# typedef enum detection
_RE_TYPEDEF_ENUM = re.compile(r"^\s*typedef\s+enum\b")

# Compiler directives to skip whole line
_RE_DIRECTIVE = re.compile(r"^\s*`(?:include|define|ifdef|ifndef|endif|else|elsif|undef|timescale|default_nettype)\b")

# Comment lines
_RE_COMMENT = re.compile(r"^\s*//")
_RE_BLOCK_COMMENT_START = re.compile(r"/\*")
_RE_BLOCK_COMMENT_END = re.compile(r"\*/")

# detect if line is inside a begin/end utils block
_RE_UTILS_BEGIN = re.compile(r"`uvm_\w+_utils_begin\b")
_RE_UTILS_END = re.compile(r"`uvm_\w+_utils_end\b")


# ===========================================================================
# Helper: extract port list from function header
# ===========================================================================

def _parse_port_list(port_str: str) -> list[SVPort]:
    """Parse a simplified port list string into SVPort objects."""
    ports: list[SVPort] = []
    if not port_str.strip():
        return ports

    for item in port_str.split(","):
        item = item.strip()
        if not item:
            continue
        # direction?
        direction = ""
        for d in ("input", "output", "inout", "ref"):
            if item.startswith(d):
                direction = d
                item = item[len(d):].strip()
                break
        # default value?
        default = None
        if "=" in item:
            item, default = item.split("=", 1)
            item = item.strip()
            default = default.strip()
        # type + name
        parts = item.rsplit(None, 1)
        if len(parts) == 2:
            sv_type, name = parts
        else:
            sv_type = ""
            name = parts[0] if parts else ""
        ports.append(SVPort(direction=direction, sv_type=sv_type.strip(), name=name.strip(), default=default))
    return ports


# ===========================================================================
# Main line-scanner parser
# ===========================================================================

class _LineScanner:
    """Scan SV source line by line and extract SVClass objects."""

    def __init__(self, lines: list[str], filename: str) -> None:
        self.lines = lines
        self.filename = filename
        self.n = len(lines)
        self.classes: list[SVClass] = []
        self._known_enum_types: set[str] = set()

    def scan(self) -> list[SVClass]:
        i = 0
        in_block_comment = False
        while i < self.n:
            raw = self.lines[i]
            # handle block comments
            if in_block_comment:
                if "*/" in raw:
                    in_block_comment = False
                i += 1
                continue
            if "/*" in raw and "*/" not in raw:
                in_block_comment = True

            # skip directives and single-line comments
            if _RE_DIRECTIVE.match(raw) or _RE_COMMENT.match(raw):
                i += 1
                continue

            # detect typedef enum for later member classification
            if _RE_TYPEDEF_ENUM.match(raw):
                self._known_enum_types.update(self._extract_enum_type(i))

            # class header — may span multiple lines (join if no semicolon)
            cls_match = _RE_CLASS_HEADER.search(raw)
            if cls_match and "endclass" not in raw:
                cls, i = self._parse_class(i, cls_match)
                if cls:
                    self.classes.append(cls)
                continue

            i += 1
        return self.classes

    # ------------------------------------------------------------------
    # Class parsing
    # ------------------------------------------------------------------

    def _parse_class(self, start_i: int, header_match: re.Match) -> tuple[Optional[SVClass], int]:
        """Parse a class block starting at start_i. Returns (SVClass, next_i)."""
        g = header_match.groupdict()
        name = g["name"]
        is_virtual = bool(g.get("virtual"))
        param_str = (g.get("params") or "").strip()
        is_parameterized = bool(param_str)

        # parse parent
        parent: Optional[str] = None
        parent_params: list[str] = []
        if g.get("extends"):
            extends_str = g["extends"].strip().removeprefix("extends").strip()
            # split off any #() parameter
            m_hash = re.match(r"([\w:]+)\s*(?:#\s*\(([^)]*)\))?", extends_str)
            if m_hash:
                parent = m_hash.group(1)
                if m_hash.group(2):
                    parent_params = [p.strip() for p in m_hash.group(2).split(",")]

        cls = SVClass(
            name=name,
            is_virtual=is_virtual,
            is_parameterized=is_parameterized,
            param_str=param_str,
            parent=parent,
            parent_params=parent_params,
            start_line=start_i + 1,  # 1-based
        )

        # scan body
        i = start_i + 1
        depth = 1  # track begin/end nesting for nested classes
        in_utils_block = False
        in_block_comment = False

        while i < self.n:
            raw = self.lines[i]
            stripped = raw.strip()

            # block comments
            if in_block_comment:
                if "*/" in raw:
                    in_block_comment = False
                i += 1
                continue
            if "/*" in raw and "*/" not in raw:
                in_block_comment = True

            # endclass
            if _RE_ENDCLASS.match(raw):
                cls.end_line = i + 1
                cls.raw_lines = self.lines[start_i: i + 1]
                i += 1
                break

            # nested class (increment depth but don't recurse here)
            if _RE_CLASS_HEADER.search(raw) and "endclass" not in raw and i != start_i:
                depth += 1

            # macros
            for mac_match in _RE_MACRO.finditer(raw):
                mac_name = mac_match.group("name")
                if not mac_name:
                    continue
                args_raw = mac_match.group("args") or ""
                args = [a.strip() for a in args_raw.split(",") if a.strip()]
                macro = SVMacro(name=mac_name, args=args, line=i + 1)
                cls.macros.append(macro)
                if _RE_UTILS_BEGIN.search(raw):
                    in_utils_block = True
                if _RE_UTILS_END.search(raw):
                    in_utils_block = False

            # function/task
            f_match = _RE_FUNC_START.match(raw)
            if f_match and depth == 1:
                func, i = self._parse_function(i, f_match.group("name"), is_task=False,
                                               return_type=(f_match.group("rettype") or "").strip(),
                                               is_extern=bool(f_match.group("extern")))
                cls.functions.append(func)
                continue

            t_match = _RE_TASK_START.match(raw)
            if t_match and depth == 1:
                func, i = self._parse_function(i, t_match.group("name"), is_task=True,
                                               return_type="",
                                               is_extern=bool(t_match.group("extern")))
                cls.functions.append(func)
                continue

            # variable members (skip if inside utils begin/end block)
            if not in_utils_block and depth == 1:
                var = self._try_parse_member(raw, i + 1)
                if var:
                    cls.members.append(var)

            i += 1
        else:
            # EOF without endclass
            cls.end_line = self.n
            cls.raw_lines = self.lines[start_i:]

        return cls, i

    # ------------------------------------------------------------------
    # Function parsing
    # ------------------------------------------------------------------

    def _parse_function(self, start_i: int, name: str, is_task: bool,
                         return_type: str = "", is_extern: bool = False) -> tuple[SVFunction, int]:
        """Parse a function body, detect super.new calls."""
        func = SVFunction(name=name, start_line=start_i + 1,
                          is_task=is_task, return_type=return_type, is_extern=is_extern)
        i = start_i

        # collect full port list (may span lines)
        full_line = self.lines[i]
        # look for closing ) on same or subsequent lines
        depth = full_line.count("(") - full_line.count(")")
        j = i + 1
        while depth > 0 and j < self.n:
            full_line += " " + self.lines[j].strip()
            depth += self.lines[j].count("(") - self.lines[j].count(")")
            j += 1

        # extract ports
        m_ports = re.search(r"\(([^)]*)\)", full_line)
        if m_ports:
            func.port_list = _parse_port_list(m_ports.group(1))

        # handle extern (no body)
        if "extern" in self.lines[start_i]:
            func.end_line = start_i + 1
            return func, j

        # scan body for super.new and endfunction/endtask
        end_kw = _RE_ENDTASK if is_task else _RE_ENDFUNCTION
        i = j
        while i < self.n:
            line = self.lines[i]
            if _RE_SUPER_NEW.search(line):
                func.has_super_call = True
                func.super_call_line = i + 1
            if end_kw.match(line):
                func.end_line = i + 1
                return func, i + 1
            i += 1

        func.end_line = i
        return func, i

    # ------------------------------------------------------------------
    # Member variable parsing
    # ------------------------------------------------------------------

    def _try_parse_member(self, line: str, lineno: int) -> Optional[SVMember]:
        """Try to parse a variable member declaration from a line."""
        # Skip obvious non-members
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            return None
        # Skip lines that are function/task/class keywords
        skip_keywords = ("function", "task", "class", "endclass", "endfunction",
                         "endtask", "module", "endmodule", "begin", "end",
                         "if", "else", "for", "foreach", "case", "endcase",
                         "return", "assert", "super", "typedef", "import",
                         "parameter", "localparam", "assign", "always", "initial")
        first_word = stripped.split()[0].lstrip("`") if stripped.split() else ""
        if first_word in skip_keywords:
            return None
        if stripped.startswith("`"):
            return None

        m = _RE_VAR_DECL.match(line)
        if not m:
            return None

        sv_type = m.group("type").strip()
        name = m.group("name").strip()
        dims = (m.group("dims") or "").strip()
        visibility = m.group("vis") or "public"

        # Detect array kinds
        is_dynamic = "[]" in dims or "[]" in sv_type
        is_queue = "[$]" in dims or "[$]" in sv_type
        is_array = bool(dims) or is_dynamic or is_queue

        # Detect enum
        is_enum = sv_type in self._known_enum_types

        return SVMember(
            name=name,
            sv_type=sv_type,
            is_array=is_array,
            is_dynamic_array=is_dynamic,
            is_queue=is_queue,
            is_enum=is_enum,
            visibility=visibility,
            line=lineno,
        )

    # ------------------------------------------------------------------
    # Enum type extraction
    # ------------------------------------------------------------------

    def _extract_enum_type(self, i: int) -> list[str]:
        """Extract typedef enum names from the file."""
        # collect until semicolon
        text = ""
        j = i
        while j < self.n and ";" not in text:
            text += self.lines[j]
            j += 1
        m = re.search(r"typedef\s+enum[^}]*\}\s*([A-Za-z_]\w*)\s*;", text, re.DOTALL)
        if m:
            return [m.group(1)]
        return []


# ===========================================================================
# Public API
# ===========================================================================

def parse_file(path: "str | Path") -> list[SVClass]:
    """Parse a SystemVerilog file and return a list of SVClass objects."""
    path = Path(path)
    source = path.read_text(encoding="utf-8", errors="replace")
    return parse_text(source, filename=str(path))


def parse_text(source: str, filename: str = "<string>") -> list[SVClass]:
    """Parse SV source text and return a list of SVClass objects."""
    lines = source.splitlines(keepends=True)
    scanner = _LineScanner(lines, filename)
    return scanner.scan()
