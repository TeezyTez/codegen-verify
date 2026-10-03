method Refill(used: int, steps: int, cap: int) returns (next: int)
  requires 0 <= used <= cap && steps >= 0
  ensures next == (if used + steps <= cap then used + steps else cap)
{
  next := used + steps;
}
