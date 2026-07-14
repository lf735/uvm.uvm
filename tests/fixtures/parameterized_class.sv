// Fixture: parameterized driver class
// Expected: `uvm_component_param_utils(my_param_driver #(DATA_WIDTH))

class my_param_driver #(parameter int DATA_WIDTH = 8) extends uvm_driver #(my_seq_item);
  int timeout;

  function new(string name = "my_param_driver", uvm_component parent = null);
    super.new(name, parent);
  endfunction

endclass
