method Maximum(s: seq<int>) returns (m: int)
  requires |s| > 0
  ensures forall k :: 0 <= k < |s| ==> s[k] <= m
  ensures exists k :: 0 <= k < |s| && m == s[k]
{
m := s[0];
}
