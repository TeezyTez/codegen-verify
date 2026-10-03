method IntegerSqrt(n: int) returns (r: int)
  requires n >= 0
  ensures r >= 0
  ensures r * r <= n
  ensures n < (r + 1) * (r + 1)
{
var lo: int := 0;
var hi: int := n + 1;
while (lo + 1 < hi)
    invariant 0 <= lo <= hi
    invariant lo * lo <= n
    invariant n < hi * hi
    decreases hi - lo
{
    var mid: int := lo + (hi - lo) / 2;
    if (mid * mid <= n) {
        lo := mid;
    } else {
        hi := mid;
    }
}
r := lo;
}
