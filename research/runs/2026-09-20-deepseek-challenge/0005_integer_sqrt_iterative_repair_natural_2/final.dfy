method IntegerSqrt(n: int) returns (r: int)
  requires n >= 0
  ensures r >= 0
  ensures r * r <= n
  ensures n < (r + 1) * (r + 1)
{
var i: int := 0;
while ((i + 1) * (i + 1) <= n)
    invariant 0 <= i
    invariant i * i <= n
    decreases n - i * i
{
    i := i + 1;
}
r := i;
assert r * r <= n;
assert (r + 1) * (r + 1) > n;
}
