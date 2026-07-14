// Fixture: class with _utils_begin/end block, fields should be added inside
// Expected: uvm_field_int + uvm_field_string added inside the begin/end block

class my_transaction extends uvm_sequence_item;
  `uvm_object_utils_begin(my_transaction)
  `uvm_object_utils_end

  int addr;
  int data;
  string tag;
  bit rw;

  function new(string name = "my_transaction");
    super.new(name);
  endfunction

endclass
