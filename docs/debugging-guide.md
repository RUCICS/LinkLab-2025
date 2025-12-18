# LinkLab 调试指南

在实现链接器的过程中，你可能会遇到各种各样的问题。本指南将介绍实验框架提供的调试工具和一些实用的调试技巧，帮助你更高效地定位和解决问题。

## 基础工具

实验框架提供了两个基础的调试工具：`readfle` 和 `disasm`。

`readfle` 工具可以显示 FLE 格式文件的详细信息，包括：
- 节表：每个节的名称、大小、权限和地址
- 符号表：所有符号的名称、类型、所在节和偏移
- 重定位表：每个重定位项的位置、类型、目标符号和附加值
- 程序头：（仅可执行文件）各个段的名称、地址、大小和权限

例如，要查看一个目标文件的内容：

```bash
❯ ./readfle tests/cases/4-no-pie/build/main.fo
File: main.fo
Type: .obj

Sections:
Name           Size        Flags                 Addr        Offset
--------------------------------------------------------------------
.data          0x0004      ALLOC                 0x0000      0x00
.text.startup  0x0023      ALLOC                 0x0000      0x04

Symbols:
Name          Type    Section       Offset     Size
------------------------------------------------------------------
global_var    GLOBAL  .data         0x0000     0x0004
.text.startup LOCAL   .text.startup 0x0000     0x0000
main          GLOBAL  .text.startup 0x0000     0x0023
get_value     UNDEF                 0x0000     0x0000
print_value   UNDEF                 0x0000     0x0000

Relocations:
.text.startup:
  Offset    Type           Symbol        Addend
------------------------------------------------
  0x05      R_X86_64_PC32  get_value     0xfffffffffffffffc
  0x0b      R_X86_64_PC32  global_var    0xfffffffffffffffc
  0x16      R_X86_64_PC32  print_value   0xfffffffffffffffc
```

`disasm` 工具可以反汇编指定节的内容。对于代码段，它会显示汇编指令；对于数据段，它会以十六进制显示原始数据。每个指令或数据块旁边都会标注相关的符号和重定位信息。使用方法：

```bash
❯ ./disasm tests/cases/4-no-pie/build/main.fo .text.startup      # 反汇编代码段
Disassembly of section .text.startup:

main:
0000: 48 83 ec 18                   sub    $0x18,%rsp             
0004: e8 00 00 00 00                call   0x9                    # R_X86_64_PC32 get_value-4 
0009: 03 05 00 00 00 00             add    0x0(%rip),%eax         # R_X86_64_PC32 global_var-4 
000f: 89 c7                         mov    %eax,%edi              
0011: 89 44 24 0c                   mov    %eax,0xc(%rsp)         
0015: e8 00 00 00 00                call   0x1a                   # R_X86_64_PC32 print_value-4 
001a: 8b 44 24 0c                   mov    0xc(%rsp),%eax         
001e: 48 83 c4 18                   add    $0x18,%rsp             
0022: c3                            ret

❯ ./disasm tests/cases/5-fpie/build/main.fo .rodata.str1.1       # 查看数据段内容
Disassembly of section .rodata.str1.1:

.LC1:
0000: 50 49 20 3d 20 25 64 0a 00                          # "PI = %d\n"

.LC2:
0009: 45 20 3d 20 25 64 0a 00                             # "E = %d\n"

.LC3:
0011: 61 64 64 28 25 64 2c 20 25 64 29 20 3d 20 25 64     # "add(%d, %d) = %d\n"
0021: 0a 00                                             

.LC4:
0023: 73 75 62 74 72 61 63 74 28 25 64 2c 20 25 64 29     # "subtract(%d, %d) = %d\n"
0033: 20 3d 20 25 64 0a 00                              

.LC5:
003a: 6d 75 6c 74 69 70 6c 79 28 25 64 2c 20 25 64 29     # "multiply(%d, %d) = %d\n"
004a: 20 3d 20 25 64 0a 00                              

.LC6:
0051: 64 69 76 69 64 65 28 25 64 2c 20 25 64 29 20 3d     # "divide(%d, %d) = %d\n"
0061: 20 25 64 0a 00                                    

.LC7:
0066: 66 61 63 74 6f 72 69 61 6c 28 35 29 20 3d 20 25     # "factorial(5) = %d\n"
0076: 64 0a 00                                          

.LC8:
0079: 66 69 62 6f 6e 61 63 63 69 28 37 29 20 3d 20 25     # "fibonacci(7) = %d\n"
0089: 64 0a 00                                          

.LC9:
008c: 67 63 64 28 34 38 2c 20 31 38 29 20 3d 20 25 64     # "gcd(48, 18) = %d\n"
009c: 0a 00                                             

.LC10:
009e: 6c 63 6d 28 34 38 2c 20 31 38 29 20 3d 20 25 64     # "lcm(48, 18) = %d\n"
00ae: 0a 00                                             

.LC11:
00b0: 61 72 72 61 79 5f 73 75 6d 20 3d 20 25 64 0a 00     # "array_sum = %d\n"

.LC12:
00c0: 61 72 72 61 79 5f 73 6f 72 74 65 64 20 3d 20 00     # "array_sorted = "

.LC13:
00d0: 25 64 20 00                                         # "%d "

.LC14:
00d4: 0a 00                                               # "\n"
```

> [!WARNING]
> 如果你将所有的段都合并到了一个 `.load` 段中，那么 `disasm` 工具将无法正确反编译出代码和数据。

## 评测脚本功能

评测脚本 `grader.py` 提供了多个便于调试的功能。

### 详细模式

使用 `-v` 参数可以让评测脚本显示更多调试信息：

```bash
python3 grader.py -v test_case_name
```

这会显示每个测试步骤的详细输出，包括运行的命令、标准输出、标准错误和返回值。

### 预运行模式

使用 `-d` 参数可以让评测脚本进入预运行模式：

```bash
python3 grader.py -d test_case_name
```

这种模式下，评测脚本只会显示将要执行的命令，而不会真正运行它们。这可以帮助你理解测试的执行流程。

### 定位失败的测试

当运行 `make test` 后发现某个测试未通过时，你可以快速定位到第一个失败的测试点：

```bash
# 对于 bash/zsh
eval "$(python3 grader.py -l)"

# 对于 fish shell
python3 grader.py -l | source
```

这个命令会设置环境变量 `TEST_BUILD`，指向失败测试的工作目录。你可以在这个目录下找到测试的输入文件、期望输出和实际输出。

### 重新运行失败的测试

找到失败的测试点后，你可以：

1. 手动运行链接器，查看具体输出：
```bash
./ld ${TEST_BUILD}/a.fo ${TEST_BUILD}/b.fo -o ${TEST_BUILD}/out.fle
```

2. 使用 `readfle` 和 `disasm` 检查输出文件：
```bash
./readfle ${TEST_BUILD}/out.fle     # 查看文件结构
./disasm ${TEST_BUILD}/out.fle .text # 检查生成的代码
```

3. 对照测试配置文件（`config.toml`）或使用预运行模式（`-d`）了解测试的具体步骤和预期结果。

你可以使用 `make retest` 命令重新运行所有失败的测试点，这在反复调试某个问题时特别有用。

## 使用 VS Code 调试

评测脚本还可以自动生成 VS Code 的调试配置。当测试失败时，使用 `--vscode` 参数：

```bash
python3 grader.py --vscode [test_case_name]
```

评测脚本会自动为每个失败的测试点的失败步骤生成调试配置。这会在 `.vscode` 目录下生成两个配置文件：
- `launch.json`：定义调试配置，包括程序路径、参数等
- `tasks.json`：定义构建任务，确保在调试前重新编译代码

生成配置后，你可以在 VS Code 中：

1. 安装必要的扩展：
   - C/C++：使用 GDB 调试 C++ 代码
   - CodeLLDB：使用 LLDB 调试 C/C++ 代码

2. 在代码中设置断点（F9）

3. 启动调试（在调试面板中选择配置运行）：
   - 在代码中单步执行（F10）
   - 进入函数（F11）
   - 在变量面板中查看变量值
   - 在调试控制台中执行表达式

调试器提供的实时反馈可以帮助你更好地理解程序的执行流程，快速定位问题。例如，你可以：
- 在符号解析时检查符号表的构建过程
- 在重定位时验证地址计算是否正确
- 在生成输出时确认节的合并顺序

## 编写调试辅助代码

除了使用工具，在代码中添加调试输出也是很有帮助的。一些建议：

1. 在关键步骤添加日志：
```cpp
std::cerr << "Processing symbol: " << sym.name 
          << " at offset: 0x" << std::hex << sym.offset << std::endl;
```

2. 使用断言验证关键假设：
```cpp
assert(sym.offset < section.size && "Symbol offset out of bounds");
```

3. 实现辅助函数打印数据结构：
```cpp
void dump_symbol_table(const std::vector<Symbol>& symbols) {
    for (const auto& sym : symbols) {
        std::cerr << sym.name << ": " << sym.section 
                  << "+0x" << std::hex << sym.offset << std::endl;
    }
}
```

这些代码可以帮助你追踪程序的执行流程，在问题出现时提供有用的上下文信息。

记住在提交代码前删除或注释掉调试代码，保持代码整洁。如果你觉得某些调试功能可能对其他同学有帮助，欢迎通过 Pull Request 贡献到框架代码中。

## 段错误调试

在实现链接器的过程中，你可能会遇到链接得到的可执行文件运行时出现段错误（Segmentation Fault），这通常说明链接器的实现有误，没有正确处理好重定位。我们的实验框架提供了一个段错误处理器，它会在程序崩溃时输出一些有用的调试信息。让我们来看看如何利用这些信息定位问题。

当程序发生段错误时，处理器会输出以下信息：
```bash
Caught SIGSEGV at address: 0x7fff5c3e1000
Error code: 1
Instruction at: 0x400a1b
Likely return address: 0x400a20
```

这些信息告诉我们：
- 访问非法内存的地址（`0x7fff5c3e1000`）
- 发生错误的指令地址（`0x400a1b`）
- 可能的返回地址（`0x400a20`）

要利用这些信息定位问题，你可以：

1. 使用 `readfle` 工具检查生成的可执行文件，找到发生错误的代码所在的节：
```bash
./readfle out.fle
```
通过比对地址范围，你可以确定错误发生在哪个节中。

2. 使用 `disasm` 工具反汇编相关节的内容：
```bash
./disasm out.fle .text
```
在输出中查找出错的指令地址（`0x400a1b`），观察指令的操作数和上下文。这通常能帮助你发现：
- 重定位是否正确处理
- 地址计算是否出错
- 节的边界是否正确对齐

3. 回溯问题根源：
- 如果是访问数据段出错，检查数据段的地址范围和权限设置
- 如果是执行指令出错，检查代码段的重定位处理
- 如果是函数调用崩溃，检查栈的对齐和函数调用约定

例如，假设你在链接一个调用 `printf` 的程序时遇到段错误：
```bash
Caught SIGSEGV at address: 0x0
```
这个零地址访问通常意味着某个函数指针未被正确重定位。使用 `readfle` 和 `disasm` 工具，你可能会发现：
```bash
./disasm out.fle .text
...
001b: ff 15 00 00 00 00    callq  *0x0(%rip)    # 未处理的重定位
...
```
这表明你可能需要检查相对重定位的处理代码。

通过系统地分析这些信息，你通常可以快速定位到链接器中的问题。段错误通常是内存访问或代码生成的问题，仔细检查地址计算和重定位处理往往能找到答案。

---

通过合理运用这些工具和技巧，你可以更系统地调试问题，而不是盲目修改代码。祝你实验顺利！
