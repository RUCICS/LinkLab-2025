#include "minilibc.h"

// 弱符号定义，会被强符号覆盖
__attribute__((weak)) char shared_var[] = "100";

void unused_func()
{
    print("unused_func", NULL);
}
