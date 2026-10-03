method LowerBound(s: seq<int>, key: int) returns (p: int)
  requires forall i, j :: 0 <= i < j < |s| ==> s[i] <= s[j]
  ensures 0 <= p <= |s|
  ensures forall i :: 0 <= i < p ==> s[i] < key
  ensures forall i :: p <= i < |s| ==> s[i] >= key
{
var lo := 0;
var hi := |s|;
while lo < hi
    invariant 0 <= lo <= hi <= |s|
    invariant forall i: int, j: int :: 0 <= i < j < |s| ==> s[i] <= s[j]
    invariant forall i: int :: 0 <= i < lo ==> s[i] < key
    invariant forall i: int :: hi <= i < |s| ==> key <= s[i]
    decreases hi - lo
{
    var mid := lo + (hi - lo) / 2;
    if s[mid] < key {
        lo := mid + 1;
    } else {
        hi := mid;
    }
}
p := lo;
assert 0 <= p <= |s|;
assert forall i: int :: 0 <= i < p ==> s[i] < key;
assert forall i: int :: p <= i < |s| ==> key <= s[i];
}
