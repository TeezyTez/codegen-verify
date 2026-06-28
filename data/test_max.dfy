// 测试文件：求最大值
method Max(x: int, y: int) returns (result: int)
    ensures result >= x && result >= y
    ensures result == x || result == y
{
    if x >= y {
        return x;
    } else {
        return y;
    }
}
