method BadMax(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
{
    return x; // 当 y > x 时违反规约
}
