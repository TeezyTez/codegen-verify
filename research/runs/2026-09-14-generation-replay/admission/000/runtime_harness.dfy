method Main() {
  var v0_0 := Clamp(12, 8);
  expect v0_0 == 8;
  var v1_0 := Clamp(3, 8);
  expect v1_0 == 3;
  var v2_0 := Clamp(0, 0);
  expect v2_0 == 0;
  print "GENERATION_WITNESSES_PASSED\n";
}
