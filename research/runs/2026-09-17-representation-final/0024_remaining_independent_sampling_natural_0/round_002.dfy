method Remaining(cap: int, used: int) returns (r: int)
  requires 0 <= used <= cap
  ensures r == cap - used
{
r := cap - used;
}
