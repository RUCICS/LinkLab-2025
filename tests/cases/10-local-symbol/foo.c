#include "minilibc.h"

// 定义一个局部符号
static int _local_var = 41;

void foo()
{
    _local_var++;
    printf("foo.c: %d\n", _local_var);
}