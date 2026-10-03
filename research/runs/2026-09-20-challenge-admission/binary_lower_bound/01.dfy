method LowerBound(s: seq<int>, key: int) returns (p: int)
  requires forall i, j :: 0 <= i < j < |s| ==> s[i] <= s[j]
  ensures 0 <= p <= |s|
  ensures forall i :: 0 <= i < p ==> s[i] < key
  ensures forall i :: p <= i < |s| ==> s[i] >= key
{
p := 0;
}
