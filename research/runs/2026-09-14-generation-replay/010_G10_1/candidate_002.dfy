method Snapshot(left: int, right: int) returns (a: int, b: int)
  ensures a == left
  ensures b == right
{
  a, b := right, left;
}
