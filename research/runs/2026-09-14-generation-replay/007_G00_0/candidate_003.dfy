method Reserve(used: int, req: int, cap: int) returns (next: int, ok: bool)
  requires 0 <= used <= cap
  requires req >= 0
  ensures ok == (used + req <= cap)
  ensures next == (if ok then used + req else used)
  ensures 0 <= next <= cap
{
  if used + req > cap { next := used; ok := false; }
  else { next := used + req; ok := true; }
}

method Release(used: int, req: int) returns (next: int, ok: bool)
  requires used >= 0 && req >= 0
  ensures ok == (req <= used)
  ensures next == (if ok then used - req else used)
  ensures next >= 0
{
  if req > used { next := used; ok := false; }
  else { next := used - req; ok := true; }
}

method ReserveRelease(used: int, req: int, cap: int) returns (next: int)
  requires 0 <= used <= cap && req >= 0
  ensures next == used
{
  var mid, ok := Reserve(used, req, cap);
  if ok { var released: bool; next, released := Release(mid, req); }
  else { next := used; }
}
