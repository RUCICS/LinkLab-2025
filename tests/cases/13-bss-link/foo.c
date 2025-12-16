// 未初始化的全局数组（放在.bss段）
int large_array[1000];

// 未初始化的全局变量（放在.bss段）
int global_counter;

// 静态未初始化变量（放在.bss段）
static int static_value;

// 初始化静态数组中的元素
void init_array(void)
{
    for (int i = 0; i < 1000; i++) {
        large_array[i] = i;
    }
    static_value = 42;
}

// 计算数组元素和
int calculate_sum(void)
{
    int sum = 0;
    for (int i = 0; i < 1000; i++) {
        sum += large_array[i];
    }
    return sum + static_value;
}

// 增加并获取计数器值
int increment_counter(void)
{
    return ++global_counter;
}