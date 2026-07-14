// Fixture: constructor present but missing super.new call
// Expected: super.new(name, parent) inserted

class my_monitor extends uvm_monitor;
  `uvm_component_utils(my_monitor)

  int item_count;

  function new(string name = "my_monitor", uvm_component parent = null);
    // missing super.new
  endfunction

endclass
