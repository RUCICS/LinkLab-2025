#include "minilibc.h"

// 第一个弱符号定义
__attribute__((weak)) int shared_var = 100;
