// Adapted from DafnyBench/Clover, Apache-2.0; see research/THIRD_PARTY.md.
// Modified 2026-09-08: operator mutation, edit markers, synthetic Consumer.
method DoubleQuadruple(x: int) returns (a: int, b: int)
  ensures a == 2 * x && b == 4 * x
{
// repair-begin arithmetic
  a := 2 * x;
  b := 2 * a;
// repair-end arithmetic
}

method Consumer(x: int) returns (r: int)
  ensures r == 6 * x
{
  var a, b := DoubleQuadruple(x);
  r := a + b;
}
