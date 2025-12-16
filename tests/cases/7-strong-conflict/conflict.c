#include "minilibc.h"
#include <stddef.h>

int global_var = 100; // 另一个强符号，会导致链接错误

void unused()
{
    print("This should not be printed\n", NULL);
}