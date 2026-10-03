method Main() {
  var v0_0 := Refill(7, 5, 10);
  expect v0_0 == 10;
  var v1_0 := Refill(2, 3, 10);
  expect v1_0 == 5;
  var v2_0 := Refill(0, 0, 0);
  expect v2_0 == 0;
  print "GENERATION_WITNESSES_PASSED\n";
}
