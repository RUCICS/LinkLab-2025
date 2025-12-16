#include "minilibc.h"
#include <stdint.h>

// 在只读节中定义一个常量数组
const uint8_t read_only_data[] = { 1, 2, 3, 4, 5 };

// 声明外部函数
void modify_data(uint8_t* data);

int main()
{
    // 测试场景1：写入只读段
    modify_data((uint8_t*)read_only_data);
    return 0;
}