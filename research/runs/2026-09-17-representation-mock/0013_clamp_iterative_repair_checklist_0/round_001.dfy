method Clamp(request: int, cap: int) returns (r: int)
  requires request >= 0
  requires cap >= 0
  ensures r == (if request <= cap then request else cap)
{
r := request;
}
