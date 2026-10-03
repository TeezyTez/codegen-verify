method Count(n: int) returns (r: int)
  requires n >= 0
  ensures r == n
{
  var i := 0;
  r := 0;
  while i < n
    decreases n - i
// repair-begin count_invariants
    invariant 0 <= i <= n
// repair-end count_invariants
  {
    i := i + 1;
    r := r + 1;
  }
}

method Twice(n: int) returns (r: int)
  requires n >= 0
  ensures r == 2 * n
{
  var a := Count(n);
  var b := Count(n);
  r := a + b;
}

method Client(n: int) returns (r: int)
  requires n >= 0
  ensures r == 2 * n + 1
{
  r := Twice(n);
  r := r + 1;
}
