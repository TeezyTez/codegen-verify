method Reverse(s: seq<int>) returns (r: seq<int>)
  ensures |r| == |s|
  ensures forall k :: 0 <= k < |s| ==> r[k] == s[|s| - 1 - k]
{
r := s;
}
