method Clamp(req: int, cap: int) returns (grant: int)
  requires req >= 0 && cap >= 0
  ensures grant == (if req <= cap then req else cap)
{
  grant := if req <= cap then req else cap;
}
