#include "minilibc.h"

// 强符号定义
char shared_var[] = "42";

int main()
{
    // 如果使用了强符号，应该打印42
    print("shared_var = ", shared_var, NULL);
    return 0;
}