int used_func();
int ping(int);
int chain_a_func();

int main()
{
    if (used_func() != 10)
        return 1;
    if (ping(5) != 5)
        return 2;
    if (chain_a_func() != 25)
        return 3;
    return 0;
}
