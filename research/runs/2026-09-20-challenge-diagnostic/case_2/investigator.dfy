method Reverse(s: seq<int>) returns (r: seq<int>)
  ensures |r| == |s|
  ensures forall k :: 0 <= k < |s| ==> r[k] == s[|s| - 1 - k]
{
r := [];
var i := 0;
while i < |s|
  invariant 0 <= i <= |s|
  invariant |r| == i
  invariant forall k :: 0 <= k < i ==> r[k] == s[|s| - 1 - k]
  decreases |s| - i
{
  r := r + [s[|s| - 1 - i]];
  i := i + 1;
}
}
