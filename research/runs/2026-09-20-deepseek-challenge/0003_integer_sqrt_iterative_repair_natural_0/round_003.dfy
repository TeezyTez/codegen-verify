method IntegerSqrt(n: int) returns (r: int)
  requires n >= 0
  ensures r >= 0
  ensures r * r <= n
  ensures n < (r + 1) * (r + 1)
{
var r := 0;
while ((r + 1) * (r + 1)) <= n
  invariant 0 <= r
  invariant r * r <= n
  decreases n - r * r
{
  r := r + 1;
}
return r;
}
