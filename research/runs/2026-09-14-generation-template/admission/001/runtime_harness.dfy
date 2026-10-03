method Main() {
  var v0_0, v0_1 := Partial(7, 5, 10);
  expect v0_0 == 10;
  expect v0_1 == 3;
  var v1_0, v1_1 := Partial(2, 3, 10);
  expect v1_0 == 5;
  expect v1_1 == 3;
  print "GENERATION_WITNESSES_PASSED\n";
}
