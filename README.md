# UVM SV Transpiler Suite

A suite of Python scripts that automatically adds and fixes UVM boilerplate in SystemVerilog (`.sv`) files.

## Features

| Script | What it does |
|--------|--------------|
| `factory_checker.py` | Adds/fixes `` `uvm_component_utils `` / `` `uvm_object_utils `` macros |
| `field_macro_adder.py` | Injects `` `uvm_field_* `` macros inside `_utils_begin/end` blocks |
| `constructor_checker.py` | Adds/fixes `new()` constructors with correct signatures and `super.new()` calls |

## Installation

```bash
pip install -r requirements.txt
```

## Usage

### Run all scripts (recommended)

```bash
python uvm_transpile.py --all path/to/sv/
```

### Run individual scripts

```bash
python uvm_transpile.py --factory    path/to/sv/
python uvm_transpile.py --fields     path/to/sv/
python uvm_transpile.py --constructor path/to/sv/
```

### Common options

| Option | Description |
|--------|-------------|
| `--recursive` / `-r` | Recurse into subdirectories |
| `--no-backup` | Disable automatic `.sv.bak` backups |
| `--dry-run` | Simulate without modifying files |
| `--report FILE` | Write JSON report to FILE |
| `--verbose` / `-v` | Verbose console output |

### Examples

```bash
# Preview changes without modifying files
python uvm_transpile.py --all --dry-run --verbose src/tb/

# Process a single file and write a report
python uvm_transpile.py --all src/tb/my_driver.sv --report out.json

# Recurse into all subdirectories
python uvm_transpile.py --all -r src/
```

## Pipeline Order

```
factory_checker  →  field_macro_adder  →  constructor_checker
```

`field_macro_adder` requires a `_utils_begin/end` block (created by `factory_checker`).

## Backup Policy

By default, before modifying any file, the original is saved as `<filename>.sv.bak`.  
Use `--no-backup` to disable this.

## Report Format

```json
{
  "meta": { "timestamp": "...", "mode": "fix", "scripts_run": [...] },
  "summary": {
    "files_scanned": 12,
    "files_modified": 4,
    "classes_processed": 30,
    "actions": {
      "factory_macros_added": 5,
      "factory_macros_fixed": 2,
      "field_macros_added": 18,
      "constructors_added": 3,
      "constructors_fixed": 1
    },
    "warnings": 2
  },
  "files": [...],
  "warnings": [...]
}
```

## Running Tests

```bash
pytest tests/ -v
```

## Architecture

```
uvm/
├── uvm_transpile.py          # Orchestrator
├── scripts/
│   ├── factory_checker.py
│   ├── field_macro_adder.py
│   └── constructor_checker.py
├── core/
│   ├── sv_parser.py          # Line-scanner parser → SVClass objects
│   ├── sv_grammar.lark       # Lark grammar (reference)
│   ├── uvm_taxonomy.py       # UVM class hierarchy & rules
│   ├── file_io.py            # Read/write with backup
│   └── reporter.py           # JSON + console report
├── tests/
│   ├── fixtures/             # .sv test files
│   ├── test_factory_checker.py
│   ├── test_field_macro_adder.py
│   └── test_constructor_checker.py
└── requirements.txt
```

## Supported UVM Macros

### Factory Macros

| Class family | Macro |
|---|---|
| `uvm_component` and derivatives | `` `uvm_component_utils(ClassName) `` |
| `uvm_object` and derivatives | `` `uvm_object_utils(ClassName) `` |
| Parameterized component | `` `uvm_component_param_utils(ClassName) `` |
| Parameterized object | `` `uvm_object_param_utils(ClassName) `` |

### Field Macros

| SV Type | Macro |
|---|---|
| `int`, `bit`, `logic`, `reg`, ... | `` `uvm_field_int `` |
| `string` | `` `uvm_field_string `` |
| `real`, `shortreal` | `` `uvm_field_real `` |
| `typedef enum` | `` `uvm_field_enum `` |
| `uvm_object` derivative | `` `uvm_field_object `` |
| Dynamic array `[]` | `` `uvm_field_array_* `` |
| Queue `[$]` | `` `uvm_field_queue_* `` |
| Static array `[N]` | `` `uvm_field_sarray_* `` |

## V2 Roadmap

- Automatic UVM environment construction and wiring (`uvm_agent`, `uvm_env`)
- Automatic `typedef ... sequencer` generation
- `uvm_config_db::set/get` verification
