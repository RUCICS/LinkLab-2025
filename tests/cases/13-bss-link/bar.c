#include "minilibc.h"

// 另一个未初始化的全局变量（放在.bss段）
int another_global;

// 静态未初始化数组（放在.bss段）
static char static_buffer[512];

// 初始化静态缓冲区
void init_buffer(void)
{
    for (int i = 0; i < 512; i++) {
        // printf("%p\n", static_buffer + i);
        static_buffer[i] = (char)(i % 256);
    }
    // printf("%p\n", &another_global);
    another_global = 100;
}

// 计算缓冲区校验和
int calculate_checksum(void)
{
    int checksum = 0;
    for (int i = 0; i < 512; i++) {
        checksum += static_buffer[i];
    }
    return checksum + another_global;
}