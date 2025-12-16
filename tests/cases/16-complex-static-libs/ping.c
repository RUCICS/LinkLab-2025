int pong(int);

int ping(int x)
{
    if (x == 0)
        return 0;
    return pong(x - 1) + 1;
}
