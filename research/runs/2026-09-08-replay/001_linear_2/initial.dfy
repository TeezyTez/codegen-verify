// Adapted from DafnyBench/Clover, Apache-2.0; see research/THIRD_PARTY.md.
// Modified 2026-09-08: missing invariant, edit markers, synthetic ArrayClient.
method arraySum(a: array<int>, b: array<int>) returns (c: array<int> )
  requires a.Length==b.Length
  ensures c.Length==a.Length
  ensures forall i:: 0 <= i< a.Length==> a[i] + b[i]==c[i]
{
  c:= new int[a.Length];
  var i:=0;
  while i<a.Length
// repair-begin array_invariants
    invariant 0<=i<=a.Length
// repair-end array_invariants
  {
    c[i]:=a[i]+b[i];
    i:=i+1;
  }
}

method ArrayClient(a: array<int>, b: array<int>) returns (c: array<int>)
  requires a.Length == b.Length
  ensures c.Length == a.Length
  ensures forall i :: 0 <= i < a.Length ==> c[i] == a[i] + b[i]
{
  c := arraySum(a, b);
}
