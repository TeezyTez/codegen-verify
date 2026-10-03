method Main() {
  var v0_0, v0_1 := Release(7, 7);
  expect v0_0 == 0;
  expect v0_1 == true;
  var v1_0, v1_1 := Release(3, 5);
  expect v1_0 == 3;
  expect v1_1 == false;
  var v2_0, v2_1 := Release(0, 0);
  expect v2_0 == 0;
  expect v2_1 == true;
  print "GENERATION_WITNESSES_PASSED\n";
}
