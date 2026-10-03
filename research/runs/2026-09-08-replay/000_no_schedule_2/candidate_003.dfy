method Increment(x: int) returns (r: int)
  ensures r == x + 1
{
// repair-begin increment_body
  r := x + 1;
// repair-end increment_body
}

method Double(x: int) returns (r: int)
  ensures r == 2 * x
{
// repair-begin double_body
  r := 2 * x;
// repair-end double_body
}

method Compose(x: int) returns (r: int)
  ensures r == 2 * x + 1
{
  var d := Double(x);
  r := Increment(d);
}

method Stable(x: int) returns (r: int)
  ensures r == x
{
// repair-begin stable_body
  r := x;
// repair-end stable_body
}
