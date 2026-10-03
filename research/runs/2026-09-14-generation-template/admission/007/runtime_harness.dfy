method Main() {
  var v0_0 := ReserveRelease(3, 4, 10);
  expect v0_0 == 3;
  var v1_0 := ReserveRelease(3, 8, 10);
  expect v1_0 == 3;
  var v2_0, v2_1 := Reserve(3, 4, 10);
  expect v2_0 == 7;
  expect v2_1 == true;
  var v3_0, v3_1 := Release(7, 4);
  expect v3_0 == 3;
  expect v3_1 == true;
  print "GENERATION_WITNESSES_PASSED\n";
}
