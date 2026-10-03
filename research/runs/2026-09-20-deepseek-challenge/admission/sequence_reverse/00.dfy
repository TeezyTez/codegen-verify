method Reverse(s: seq<int>) returns (r: seq<int>)
  ensures |r| == |s|
  ensures forall k :: 0 <= k < |s| ==> r[k] == s[|s| - 1 - k]
{
r := [];
var i := |s|;
while i > 0
  invariant 0 <= i <= |s|
  invariant |r| == |s| - i
  invariant forall k :: 0 <= k < |r| ==> r[k] == s[|s| - 1 - k]
  decreases i
{
  i := i - 1;
  r := r + [s[i]];
}
}
