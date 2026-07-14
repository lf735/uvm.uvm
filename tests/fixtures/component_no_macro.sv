// Fixture: component without factory macro
// Expected: `uvm_component_utils(my_driver) should be added

class my_driver extends uvm_driver;
  int timeout;
  string tag;

  function new(string name = "my_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass
