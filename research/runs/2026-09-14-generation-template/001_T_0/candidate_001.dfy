method Partial(used: int, req: int, cap: int) returns (next: int, grant: int)
  requires 0 <= used <= cap && req >= 0
  ensures grant == (if req <= cap - used then req else cap - used)
  ensures next == used + grant
  ensures 0 <= next <= cap
{
  grant := if req <= cap - used then req else cap - used;
  next := used + grant;
}
