#include "minilibc.h"

// 全局指针变量，会触发 R_X86_64_64 重定位
char* global_ptr = "Hello World!\n";

int main()
{
    print(global_ptr, NULL);
    return 0;
}