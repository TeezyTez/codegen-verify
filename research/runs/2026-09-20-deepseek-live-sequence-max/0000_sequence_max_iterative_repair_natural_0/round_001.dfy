method Maximum(s: seq<int>) returns (m: int)
  requires |s| > 0
  ensures forall k :: 0 <= k < |s| ==> s[k] <= m
  ensures exists k :: 0 <= k < |s| && m == s[k]
{
m := s[0];
var i := 1;
while i < |s|
  invariant 1 <= i <= |s|
  invariant forall j :: 0 <= j < i ==> s[j] <= m
  invariant exists j :: 0 <= j < i && s[j] == m
  decreases |s| - i
{
  if s[i] > m {
    m := s[i];
  }
  i := i + 1;
}
assert forall j :: 0 <= j < |s| ==> s[j] <= m;
assert exists j :: 0 <= j < |s| && s[j] == m;
return m;
}
