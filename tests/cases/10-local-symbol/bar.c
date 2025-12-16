#include "minilibc.h"

// 定义一个局部符号
static int _local_var = 67;

void bar()
{
    _local_var--;
    printf("bar.c: %d\n", _local_var);
}