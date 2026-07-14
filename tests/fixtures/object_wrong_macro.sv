// Fixture: object class with wrong factory macro (uses component_utils instead of object_utils)
// Expected: `uvm_component_utils → `uvm_object_utils

class my_seq_item extends uvm_sequence_item;
  `uvm_component_utils(my_seq_item)

  int addr;
  int data;
  bit rw;

  function new(string name = "my_seq_item");
    super.new(name);
  endfunction

endclass
