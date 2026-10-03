method Main() {
  var v0_0 := Remaining(3, 10);
  expect v0_0 == 7;
  var v1_0 := Remaining(10, 10);
  expect v1_0 == 0;
  var v2_0 := Remaining(0, 0);
  expect v2_0 == 0;
  print "GENERATION_WITNESSES_PASSED\n";
}
