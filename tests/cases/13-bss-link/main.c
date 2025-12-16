#include "minilibc.h"

// 外部函数声明
extern void init_array(void);
extern int calculate_sum(void);
extern int increment_counter(void);
extern void init_buffer(void);
extern int calculate_checksum(void);

// 未初始化的全局变量（放在.bss段）
int result;

int main(void)
{
    // 初始化数据
    init_array();
    init_buffer();

    // 执行计算
    int sum = calculate_sum();
    int checksum = calculate_checksum();

    // 使用计数器
    int count1 = increment_counter();
    int count2 = increment_counter();

    // 计算最终结果
    result = sum + checksum + count1 + count2;

    // 打印结果
    printf("%d\n", result);

    return 0;
}