method Absolute(x: int) returns (r: int)
  ensures r >= 0
  ensures r == (if x >= 0 then x else -x)
{
r := x;
}
