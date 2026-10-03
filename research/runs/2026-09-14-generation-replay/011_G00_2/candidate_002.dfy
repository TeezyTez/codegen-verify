method Transfer(a: int, b: int, req: int, cap: int) returns (na: int, nb: int, ok: bool)
  requires a >= 0 && 0 <= b <= cap && req >= 0
  ensures ok == (req <= a && b + req <= cap)
  ensures na == (if ok then a - req else a)
  ensures nb == (if ok then b + req else b)
  ensures na + nb == a + b
{
  na := a; nb := b + req; ok := true;
}
