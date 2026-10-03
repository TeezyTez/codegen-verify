method Main() {
  var v0_0, v0_1, v0_2 := Transfer(7, 2, 3, 10);
  expect v0_0 == 4;
  expect v0_1 == 5;
  expect v0_2 == true;
  var v1_0, v1_1, v1_2 := Transfer(2, 2, 3, 10);
  expect v1_0 == 2;
  expect v1_1 == 2;
  expect v1_2 == false;
  var v2_0, v2_1, v2_2 := Transfer(7, 9, 3, 10);
  expect v2_0 == 7;
  expect v2_1 == 9;
  expect v2_2 == false;
  print "GENERATION_WITNESSES_PASSED\n";
}
