method Scale(units: int, rate: int) returns (r: int)
  requires units >= 0 && rate >= 0
  ensures r == units * rate
{
  r := units + rate;
}
