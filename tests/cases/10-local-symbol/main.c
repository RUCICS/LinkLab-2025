int main()
{
    // 试图访问 foo.c 中的局部符号 _local_var
    extern int _local_var;
    return _local_var;
}