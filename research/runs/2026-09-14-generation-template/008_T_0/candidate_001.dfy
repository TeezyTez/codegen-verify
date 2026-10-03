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

method ReserveTwice(used: int, q1: int, q2: int, cap: int) returns (next: int, ok1: bool, ok2: bool)
  requires 0 <= used <= cap && q1 >= 0 && q2 >= 0
  ensures ok1 == (used + q1 <= cap)
  ensures ok2 == ((if ok1 then used + q1 else used) + q2 <= cap)
  ensures next == (if ok1 then used + q1 else used) + (if ok2 then q2 else 0)
  ensures 0 <= next <= cap
{
  ok1 := used + q1 <= cap;
  var mid := if ok1 then used + q1 else used;
  ok2 := mid + q2 <= cap;
  next := if ok2 then mid + q2 else mid;
}
