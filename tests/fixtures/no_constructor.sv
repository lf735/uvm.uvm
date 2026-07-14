// Fixture: component class missing constructor entirely
// Expected: constructor injected after factory macro

class my_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(my_scoreboard)

  int pass_count;
  int fail_count;

endclass
