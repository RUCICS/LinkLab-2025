#include "minilibc.h"
#include <stddef.h>

int global_var = 42; // 强符号

int main()
{
    print("This should not be printed\n", NULL);
    return 0;
}