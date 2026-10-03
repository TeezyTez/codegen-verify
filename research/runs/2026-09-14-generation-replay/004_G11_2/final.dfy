method Release(used: int, req: int) returns (next: int, ok: bool)
  requires used >= 0 && req >= 0
  ensures ok == (req <= used)
  ensures next == (if ok then used - req else used)
  ensures next >= 0
{
  if req > used { next := used; ok := false; }
  else { next := used - req; ok := true; }
}

method ReleaseTwice(used: int, q1: int, q2: int) returns (next: int, ok1: bool, ok2: bool)
  requires used >= 0 && q1 >= 0 && q2 >= 0
  ensures ok1 == (q1 <= used)
  ensures ok2 == (q2 <= (if ok1 then used - q1 else used))
  ensures next == (if ok1 then used - q1 else used) - (if ok2 then q2 else 0)
  ensures next >= 0
{
  var mid: int;
  mid, ok1 := Release(used, q1);
  next, ok2 := Release(mid, q2);
}
