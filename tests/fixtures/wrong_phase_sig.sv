// Fixture: classes with wrong UVM phase signatures
// Used by test_prototype_updater.py

// -----------------------------------------------------------------------
// Class 1 : run_phase declared as 'function' instead of 'task' (body only)
//           build_phase has wrong return type (int instead of void)
// -----------------------------------------------------------------------
class my_driver extends uvm_driver;
  `uvm_component_utils(my_driver)

  function new(string name = "my_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // WRONG: run_phase must be a task, not a function
  function void run_phase(uvm_phase phase);
  endfunction

  // WRONG: return type must be void, not int
  function int build_phase(uvm_phase phase);
    super.build_phase(phase);
  endfunction

endclass

// -----------------------------------------------------------------------
// Class 2 : extern declaration wrong, body also wrong
// -----------------------------------------------------------------------
class my_monitor extends uvm_monitor;
  `uvm_component_utils(my_monitor)

  function new(string name = "my_monitor", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // WRONG extern: missing parameter
  extern function void connect_phase();

  // body also wrong (will only be fixed if --force-fix corrects the extern first)
  function void connect_phase();
  endfunction

endclass

// -----------------------------------------------------------------------
// Class 3 : extern CORRECT, body WRONG → body must be auto-fixed
// -----------------------------------------------------------------------
class my_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(my_scoreboard)

  function new(string name = "my_scoreboard", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  // Correct extern
  extern function void build_phase(uvm_phase phase);

  // WRONG body (return type int)
  function int build_phase(uvm_phase phase);
    super.build_phase(phase);
  endfunction

endclass

// -----------------------------------------------------------------------
// Class 4 : all signatures correct — no modification expected
// -----------------------------------------------------------------------
class my_agent extends uvm_agent;
  `uvm_component_utils(my_agent)

  function new(string name = "my_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
  endfunction

  task run_phase(uvm_phase phase);
  endtask

endclass
