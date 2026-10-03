method Reserve(used: int, req: int, cap: int) returns (next: int, ok: bool)
  requires 0 <= used <= cap
  requires req >= 0
  ensures ok == (used + req <= cap)
  ensures next == (if ok then used + req else used)
  ensures 0 <= next <= cap
{
  ok := used + req <= cap;
  next := if ok then used + req else used;
}

method Release(used: int, req: int) returns (next: int, ok: bool)
  requires used >= 0 && req >= 0
  ensures ok == (req <= used)
  ensures next == (if ok then used - req else used)
  ensures next >= 0
{
  ok := req <= used;
  next := if ok then used - req else used;
}

method ReserveRelease(used: int, req: int, cap: int) returns (next: int)
  requires 0 <= used <= cap && req >= 0
  ensures next == used
{
  next := used;
}
