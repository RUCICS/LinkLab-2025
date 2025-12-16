#include "minilibc.h"
#include <stdint.h>

// 测试场景1：尝试修改只读段
void modify_data(uint8_t* data)
{
    data[0] = 42; // 尝试写入只读数据，应触发段错误
}

// 测试场景2：尝试执行数据段
void execute_data()
{
    // 构造一些数据，看起来像指令但实际上在数据段
    uint8_t fake_code[] = { 0x55, 0x48, 0x89, 0xe5, 0xc3 }; // 一些x86-64指令
    void (*func)() = (void (*)())fake_code; // 尝试将数据当作代码执行
    func(); // 应触发段错误
}

// 测试场景3：尝试修改代码段
void write_code()
{
    // 获取当前函数的地址并尝试修改它
    void* code_ptr = (void*)write_code;
    *(uint8_t*)code_ptr = 0x90; // 尝试写入NOP指令，应触发段错误
}