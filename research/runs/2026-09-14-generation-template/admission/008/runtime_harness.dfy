method Main() {
  var v0_0, v0_1, v0_2 := ReserveTwice(0, 6, 6, 10);
  expect v0_0 == 6;
  expect v0_1 == true;
  expect v0_2 == false;
  var v1_0, v1_1, v1_2 := ReserveTwice(3, 8, 2, 10);
  expect v1_0 == 5;
  expect v1_1 == false;
  expect v1_2 == true;
  var v2_0, v2_1 := Reserve(3, 8, 10);
  expect v2_0 == 3;
  expect v2_1 == false;
  print "GENERATION_WITNESSES_PASSED\n";
}
