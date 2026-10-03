method Main() {
  var v0_0, v0_1, v0_2 := ReleaseTwice(10, 6, 6);
  expect v0_0 == 4;
  expect v0_1 == true;
  expect v0_2 == false;
  var v1_0, v1_1, v1_2 := ReleaseTwice(3, 5, 2);
  expect v1_0 == 1;
  expect v1_1 == false;
  expect v1_2 == true;
  var v2_0, v2_1 := Release(3, 5);
  expect v2_0 == 3;
  expect v2_1 == false;
  print "GENERATION_WITNESSES_PASSED\n";
}
