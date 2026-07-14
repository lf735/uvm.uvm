// Fixture: class extending unknown (non-UVM) base — should be skipped with warning
class my_custom_base extends some_external_pkg::base_class;
  int value;

  function new();
  endfunction

endclass
