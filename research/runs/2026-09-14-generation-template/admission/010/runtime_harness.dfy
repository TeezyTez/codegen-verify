method Main() {
  var v0_0, v0_1 := Snapshot(2, 9);
  expect v0_0 == 2;
  expect v0_1 == 9;
  var v1_0, v1_1 := Snapshot(0, 0);
  expect v1_0 == 0;
  expect v1_1 == 0;
  print "GENERATION_WITNESSES_PASSED\n";
}
