method IntegerSqrt(n: int) returns (r: int)
  requires n >= 0
  ensures r >= 0
  ensures r * r <= n
  ensures n < (r + 1) * (r + 1)
{
r := n;
}
