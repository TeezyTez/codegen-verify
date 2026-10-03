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
  invariant forall i :: 0 <= i < lo ==> s[i] < key
  invariant forall i :: hi <= i < |s| ==> s[i] >= key
  decreases hi - lo
{
  var mid := lo + (hi - lo) / 2;
  if s[mid] < key {
    assert forall i :: 0 <= i <= mid ==> s[i] < key;
    lo := mid + 1;
  } else {
    assert forall i :: mid <= i < |s| ==> s[i] >= key;
    hi := mid;
  }
}
p := lo;
}
