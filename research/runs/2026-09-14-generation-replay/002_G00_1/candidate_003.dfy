method Refill(used: int, steps: int, cap: int) returns (next: int)
  requires 0 <= used <= cap && steps >= 0
  ensures next == (if used + steps <= cap then used + steps else cap)
{
  var i := 0;
  next := used;
  while i < steps && next < cap
    invariant 0 <= i <= steps
    invariant next == used + i
    invariant next <= cap
  { next := next + 1; i := i + 1; }
}
