method Release(used: int, req: int) returns (next: int, ok: bool)
  requires used >= 0 && req >= 0
  ensures ok == (req <= used)
  ensures next == (if ok then used - req else used)
  ensures next >= 0
{
  next := used - req; ok := true;
}
