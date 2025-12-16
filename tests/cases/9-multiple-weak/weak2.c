#include "minilibc.h"

// 第二个弱符号定义，与第一个定义值不同
__attribute__((weak)) int shared_var = 200;