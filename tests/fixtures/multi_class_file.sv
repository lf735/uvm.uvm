// Fixture: file with multiple classes
// Class 1: component, no macro
// Class 2: object, correct macro, no fields

class my_agent extends uvm_agent;
  my_driver drv;
  my_monitor mon;

  function new(string name = "my_agent", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass

class my_config extends uvm_object;
  `uvm_object_utils_begin(my_config)
  `uvm_object_utils_end

  int active;
  string tag;

  function new(string name = "my_config");
    super.new(name);
  endfunction

endclass
