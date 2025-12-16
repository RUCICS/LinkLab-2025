#include "minilibc.h"
#include <stdint.h>

// 声明外部函数
void execute_data();

int main()
{
    // 测试场景2：执行数据段
    execute_data();
    return 0;
}