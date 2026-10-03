method Last(s: seq<int>) returns (r: int)
  requires |s| > 0
  ensures r == s[|s|-1]
{
r := s[0];
}
