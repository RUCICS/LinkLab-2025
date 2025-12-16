#include "minilibc.h"

// 声明外部变量
extern int shared_var;

int main()
{
    // 打印弱符号的值
    printf("shared_var = %d\n", shared_var);
    return 0;
}