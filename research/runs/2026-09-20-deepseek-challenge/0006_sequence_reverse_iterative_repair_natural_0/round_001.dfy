method Reverse(s: seq<int>) returns (r: seq<int>)
  ensures |r| == |s|
  ensures forall k :: 0 <= k < |s| ==> r[k] == s[|s| - 1 - k]
{
r := [];
var i := |s| - 1;
while i >= 0
    invariant 0 <= i + 1 <= |s|
    invariant |r| == |s| - 1 - i
    invariant forall k :: 0 <= k < |r| ==> r[k] == s[|s| - 1 - k]
    decreases i + 1
{
    r := r + [s[i]];
    i := i - 1;
}
assert |r| == |s|;
assert forall k :: 0 <= k < |s| ==> r[k] == s[|s| - 1 - k];
}
