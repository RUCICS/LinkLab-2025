# C程序员的C++实用指南

如果你主要使用C语言编程，LinkLab的框架代码可能会让你感到有些陌生。但你不需要学习整个C++语言——这份指南会解释你在实验中会遇到的那些C++特性，让你能够读懂框架、写出需要的代码。

C++在很大程度上是C的超集，你熟悉的大部分C语言特性在C++中都能使用。这个实验的框架使用了一些C++的便利特性来简化内存管理和数据操作，但核心的思维方式和你在C语言中建立的编程习惯是一致的。完成这个实验后，你会自然地对C++有了初步的了解，这本身也是一次很好的学习机会。

## 容器：不需要手动管理内存的数据结构

在C语言中，如果你想使用动态数组，通常需要这样写：

```c
int *numbers = malloc(capacity * sizeof(int));
size_t size = 0;

// 添加元素
if (size >= capacity) {
    capacity *= 2;
    numbers = realloc(numbers, capacity * sizeof(int));
}
numbers[size++] = 42;

// 使用完毕
free(numbers);
```

你需要自己追踪数组的大小和容量，在需要时扩展空间，并记得在最后释放内存。如果忘记释放，就会内存泄漏；如果使用了已经释放的内存，就会出现段错误。

C++提供了容器（container）来自动处理这些细节。最常用的是`std::vector`，它本质上就是一个会自动扩展的数组：

```cpp
#include <vector>

std::vector<int> numbers;  // 创建一个空的整数向量

numbers.push_back(42);     // 添加元素，自动处理扩展
numbers.push_back(17);
numbers.push_back(99);

// 访问元素
int x = numbers[0];        // 和数组一样用下标访问
size_t count = numbers.size();  // 获取元素个数

// 使用完毕，自动释放内存，不需要手动free
```

这里的关键是自动内存管理。当`numbers`这个变量离开作用域时（比如函数返回），它会自动释放占用的内存。你不需要也不应该对`std::vector`调用`free`——它自己会处理。

在这个实验中，你会大量使用`std::vector<uint8_t>`来存储字节数据，比如节的内容。你也会看到`std::vector<Symbol>`这样的用法，这表示一个符号结构体的数组。

### vector的常用操作

除了基本的添加和访问，`std::vector`还提供了很多实用的操作。在实验中，你可能会需要这些：

**检查vector是否为空**，这在处理可选内容时很有用：

```cpp
if (symbols.empty()) {
    // 没有符号，可能需要报错或特殊处理
    std::cerr << "Warning: no symbols found" << std::endl;
}
```

**清空vector的所有内容**，在需要重置状态时使用：

```cpp
symbols.clear();  // 删除所有元素，size()变为0
```

**访问首尾元素**，这比用下标稍微安全一些，因为对空vector调用会触发断言：

```cpp
if (!sections.empty()) {
    auto& first_section = sections.front();
    auto& last_section = sections.back();
}
```

**合并两个vector**，当你需要把一个vector的内容追加到另一个后面时：

```cpp
std::vector<uint8_t> section_a = {0x48, 0x89, 0xe5};
std::vector<uint8_t> section_b = {0x5d, 0xc3};

// 把section_b的内容追加到section_a后面
section_a.insert(section_a.end(), section_b.begin(), section_b.end());
// 现在section_a包含 {0x48, 0x89, 0xe5, 0x5d, 0xc3}
```

这个操作在合并多个节的内容时特别有用。你也可以追加单个元素的多个副本：

```cpp
// 追加4个零字节（比如为重定位预留空间）
data.insert(data.end(), 4, 0x00);
```

**预留容量**，如果你大概知道会添加多少元素，可以预先分配空间避免多次重新分配：

```cpp
std::vector<Symbol> symbols;
symbols.reserve(100);  // 预留100个元素的空间，但size()仍是0

// 之后添加元素就不会频繁重新分配内存
for (int i = 0; i < 50; i++) {
    symbols.push_back(some_symbol);
}
```

**删除特定位置的元素**，虽然不太常用，但有时会需要：

```cpp
// 删除第3个元素（索引2）
if (symbols.size() > 2) {
    symbols.erase(symbols.begin() + 2);
}
```

**调整大小**，可以扩大或缩小vector，新元素会被默认初始化：

```cpp
std::vector<uint8_t> buffer;
buffer.resize(256);  // 现在有256个字节，都初始化为0

// 如果你想指定初始值
buffer.resize(256, 0xFF);  // 256个字节，都是0xFF
```

> [!TIP]
> 如果你需要在vector中间频繁插入或删除元素，`std::vector`可能不是最佳选择，因为这些操作需要移动后面的所有元素。但在链接器实验中，大部分操作都是顺序添加和遍历，`std::vector`完全够用。

### 字符串也是容器

在C语言中，字符串是以空字符结尾的字符数组。你需要用`malloc`分配空间，用`strcpy`复制字符串，用`strlen`获取长度，用`strcmp`比较字符串。C++提供了`std::string`来简化这些操作：

```cpp
#include <string>

std::string name = "hello";     // 创建字符串
name += " world";                // 连接字符串，自动扩展空间
size_t len = name.size();        // 获取长度，不包括空字符
char first = name[0];            // 可以像数组一样访问

// 字符串比较
if (name == "hello world") {     // 直接用==比较内容
    // ...
}

// 字符串查找和处理
if (name.find("world") != std::string::npos) {
    // 找到了子串
}
```

在实验中，符号名、节名都是`std::string`类型。你可以直接用`==`比较它们，不需要`strcmp`。当你需要连接字符串时，可以直接用`+`运算符。当函数需要C风格的字符串（`const char*`）时，可以调用`.c_str()`方法：

```cpp
std::string filename = "output.fle";
FILE* fp = fopen(filename.c_str(), "wb");  // 转换为C风格字符串
```

> [!NOTE]
> C++17引入了`std::string_view`，它是字符串的非拥有式视图，在某些场景下比`std::string`更高效。但在本实验中，`std::string`已经足够使用。如果你在阅读更现代的C++代码时看到`string_view`，可以把它理解为"指向字符串的轻量级引用"。

### 关联容器：映射表

有时你需要建立键值对应关系。在C语言中，你可能会实现一个哈希表或者使用数组加线性查找。C++提供了`std::map`：

```cpp
#include <map>

std::map<std::string, size_t> symbol_addresses;  // 符号名 -> 地址

// 插入键值对
symbol_addresses["main"] = 0x400000;
symbol_addresses["printf"] = 0x400100;

// 查找
if (symbol_addresses.count("main") > 0) {
    size_t addr = symbol_addresses["main"];
    // 使用地址
}

// 也可以这样查找，避免意外创建不存在的键
auto it = symbol_addresses.find("main");
if (it != symbol_addresses.end()) {
    size_t addr = it->second;  // it->first是键，it->second是值
}
```

在实验中，你可能会用`std::map`来维护全局符号表，键是符号名，值是符号的信息（地址、类型等）。

### map的常用操作

`std::map`的使用有一些需要注意的细节。理解这些操作能帮你避免常见的陷阱：

**插入或更新键值对**有几种方式。最直接的是用下标操作符，但它有个副作用：如果键不存在，会创建一个默认值：

```cpp
std::map<std::string, Symbol> symbol_table;

// 如果"main"不存在，这会创建一个默认构造的Symbol
symbol_table["main"] = some_symbol;

// 更明确的插入方式，不会有意外创建
symbol_table.insert({"main", some_symbol});

// 或者使用insert_or_assign（C++17），明确表达"插入或更新"的意图
symbol_table.insert_or_assign("main", some_symbol);
```

**检查键是否存在**有两种常用方法。前面看到的`count()`返回键出现的次数（对于`map`要么是0要么是1）：

```cpp
if (symbol_table.count("main") > 0) {
    // "main"存在
}

// 或者使用find()，它返回迭代器
auto it = symbol_table.find("main");
if (it != symbol_table.end()) {
    // 找到了，可以通过it->second访问值
    Symbol& sym = it->second;
}
```

使用`find()`的好处是，如果键存在，你立即就有了指向它的迭代器，可以直接访问值，不需要再次查找。

**删除键**也很简单：

```cpp
// 删除"main"这个键
symbol_table.erase("main");

// 或者通过迭代器删除
auto it = symbol_table.find("main");
if (it != symbol_table.end()) {
    symbol_table.erase(it);
}
```

**遍历所有键值对**使用范围循环最方便。每个元素是一个`std::pair`，第一个成员是键，第二个成员是值：

```cpp
for (const auto& pair : symbol_table) {
    std::string name = pair.first;   // 键
    Symbol symbol = pair.second;      // 值
    
    // 处理每个符号
}

// 也可以用结构化绑定（C++17），更清晰
for (const auto& [name, symbol] : symbol_table) {
    // 直接使用name和symbol
    std::cout << "Symbol " << name << " at offset " << symbol.offset << std::endl;
}
```

**获取map的大小**和vector一样：

```cpp
size_t count = symbol_table.size();

if (symbol_table.empty()) {
    // map是空的
}
```

**清空map**：

```cpp
symbol_table.clear();  // 删除所有键值对
```

> [!TIP]
> `std::map`内部是一个有序的树结构，查找时间是对数级别的。如果你需要更快的查找速度，可以使用`std::unordered_map`，它是基于哈希表的，平均查找时间是常数级别。在本实验中，符号数量通常不会很大，两者性能差异不明显，使用哪个都可以。`std::unordered_map`的用法和`std::map`几乎完全相同，只需要在include时换成`<unordered_map>`即可。

**一个实用的模式**是使用`find()`来检查键是否存在，如果不存在就插入默认值：

```cpp
auto it = symbol_table.find("helper");
if (it == symbol_table.end()) {
    // "helper"不存在，插入一个新符号
    Symbol new_sym;
    new_sym.name = "helper";
    new_sym.offset = 0;
    symbol_table.insert({"helper", new_sym});
}
```

或者更简洁地，利用`insert()`的返回值。`insert()`返回一个pair，第一个元素是指向插入位置的迭代器，第二个元素是bool表示是否真的插入了（false表示键已存在）：

```cpp
auto result = symbol_table.insert({"helper", new_symbol});
if (!result.second) {
    // 键已存在，插入失败，可以选择更新或报错
    std::cerr << "Symbol 'helper' already exists" << std::endl;
}
```

## 遍历容器：三种方式

遍历容器是你在实验中最常做的操作之一。C++提供了几种遍历方式，从传统到现代依次是：

### 传统的索引循环

这和C语言完全一样：

```cpp
std::vector<int> numbers = {1, 2, 3, 4, 5};

for (size_t i = 0; i < numbers.size(); i++) {
    std::cout << numbers[i] << std::endl;
}
```

这种方式的优点是你知道当前的索引位置，可以根据索引做一些特殊处理。缺点是需要写得稍微啰嗦一些。

### 迭代器

迭代器是C++容器的通用访问方式。你可以把迭代器理解为"指向容器元素的指针"：

```cpp
for (std::vector<int>::iterator it = numbers.begin(); 
     it != numbers.end(); ++it) {
    std::cout << *it << std::endl;  // 用*解引用，就像指针
}
```

迭代器的优点是它适用于所有容器，不只是支持下标访问的容器。比如`std::map`就不能用下标遍历所有元素，但可以用迭代器。

### 范围循环（推荐）

C++11引入了范围循环（range-based for loop），这是最简洁的遍历方式：

```cpp
for (int num : numbers) {
    std::cout << num << std::endl;
}
```

这段代码的意思是"对于`numbers`中的每个元素，将它命名为`num`并执行循环体"。这种写法清晰直观，没有索引或迭代器的噪音。

在实验中，你会经常看到这样的代码：

```cpp
for (const auto& symbol : symbols) {
    // 处理每个符号
    if (symbol.type == SymbolType::GLOBAL) {
        // ...
    }
}
```

让我们拆解这个语法：

- `auto`让编译器自动推断类型。这里`symbol`的类型是`Symbol`，编译器会自动判断。
- `&`表示引用，意思是`symbol`是容器中元素的别名，而不是一个拷贝。这避免了复制大对象的开销。
- `const`表示我们不会修改这个元素，只是读取。这既是性能优化（编译器知道不会修改），也是意图表达（告诉代码阅读者我们只是遍历查看）。

如果你需要在循环中修改元素，去掉`const`：

```cpp
for (auto& symbol : symbols) {
    symbol.offset += base_address;  // 调整每个符号的地址
}
```

如果元素很小（比如`int`、`size_t`），直接拷贝而不用引用也完全可以：

```cpp
for (auto offset : offsets) {
    // 处理偏移量
}
```

## 结构体的增强能力

在C语言中，结构体只能包含数据成员：

```c
struct Symbol {
    char name[100];
    int type;
    size_t offset;
};
```

在C++中，结构体可以包含函数（称为成员函数或方法），也可以有构造函数来初始化数据。但在实验的框架代码中，大部分结构体都很简单，主要还是数据的集合。你会看到这样的定义：

```cpp
struct Symbol {
    SymbolType type;       // 符号类型（枚举）
    std::string section;   // 所在的节
    size_t offset;         // 偏移量
    size_t size;           // 大小
    std::string name;      // 符号名
};
```

使用结构体的方式和C语言基本相同：

```cpp
Symbol sym;
sym.name = "main";
sym.type = SymbolType::GLOBAL;
sym.offset = 0;
```

或者使用初始化列表：

```cpp
Symbol sym = {
    .type = SymbolType::GLOBAL,
    .section = ".text",
    .offset = 0,
    .size = 32,
    .name = "main"
};
```

这种带名字的初始化列表是C99引入、C++20正式支持的特性，它让代码更清晰。如果你的编译器支持，推荐使用这种方式。

## 命名空间：避免名字冲突

你会注意到代码中经常出现`std::`前缀，比如`std::vector`、`std::string`。这里的`std`是一个命名空间（namespace），是C++用来组织代码、避免名字冲突的机制。

C++标准库的所有内容都在`std`命名空间中。如果你定义了一个叫`vector`的变量，它不会和标准库的`std::vector`冲突，因为它们在不同的命名空间中。

有些教程会建议在文件开头写`using namespace std;`，这样就可以直接写`vector`而不用`std::vector`。但在大型项目中，这被认为是不好的实践，因为它会把整个命名空间的名字都引入，可能导致意外的冲突。在本实验中，建议保持使用`std::`前缀，这样代码意图更明确。

## 引用：一种特殊的"别名"

C++引入了引用类型，它看起来像指针，但使用起来像普通变量。引用一旦绑定到某个变量，就始终指向那个变量，不能改变指向：

```cpp
int x = 10;
int& ref = x;    // ref是x的引用

ref = 20;        // 修改ref就是修改x
std::cout << x;  // 输出20

// 引用不能"重新绑定"
int y = 30;
ref = y;         // 这不是让ref指向y，而是把y的值赋给x
```

在实验中，你主要会在两个地方遇到引用：

**函数参数**。当函数需要接收大对象但不想复制时，会使用常量引用：

```cpp
void process_object(const FLEObject& obj) {
    // 使用obj，不会复制整个对象
    // const确保我们不会意外修改它
}
```

如果函数需要修改参数，会使用非常量引用：

```cpp
void update_symbols(std::vector<Symbol>& symbols) {
    for (auto& sym : symbols) {
        sym.offset += base_address;
    }
}
```

**范围循环中**。前面已经见过，`for (const auto& item : container)`中的`&`就是引用。

引用和指针的主要区别是：引用必须在创建时初始化，之后不能改变指向；引用在使用时不需要解引用运算符。你可以把引用理解为"一个更安全、更方便的指针"。

## 成员访问：点还是箭头

这和C语言完全一样。如果你有一个对象，用`.`访问成员：

```cpp
Symbol symbol;
symbol.name = "main";
```

如果你有一个指向对象的指针，用`->`访问成员：

```cpp
Symbol* ptr = &symbol;
ptr->name = "main";
```

在实验中，大部分时候你会直接操作对象或引用，使用`.`。只有在需要动态分配或者处理可选对象时才会用到指针。

## 输入输出：两套系统

C++有自己的输入输出库iostream，但完全兼容C的stdio。你可以选择自己熟悉的方式。

### C风格（可能更熟悉）

```cpp
#include <cstdio>

printf("Address: 0x%016lx\n", address);
fprintf(stderr, "Error: %s\n", message.c_str());
```

### C++风格

```cpp
#include <iostream>
#include <iomanip>

std::cout << "Address: 0x" 
          << std::setw(16) << std::setfill('0') 
          << std::hex << address 
          << std::endl;

std::cerr << "Error: " << message << std::endl;
```

C++风格的优点是类型安全（不需要格式说明符），可以直接输出`std::string`等类型。缺点是格式控制稍微啰嗦一些。在本实验中，两种方式都可以使用，选择你觉得舒服的。

> [!TIP]
> 如果你使用C++20或更高版本，可以使用`std::format`和`std::print`，它们结合了两种方式的优点：
> ```cpp
> std::print("Address: 0x{:016x}\n", address);
> ```
> 这种方式既有格式字符串的简洁，又有类型安全的好处。

## 一些方便的字符串操作

`std::string`提供了很多便利的方法，在实验中可能会用到：

```cpp
std::string section_name = ".text.startup";

// 检查前缀（C++20）
if (section_name.starts_with(".text")) {
    // 这是代码段
}

// 如果编译器不支持starts_with，用compare
if (section_name.compare(0, 5, ".text") == 0) {
    // 同样的效果
}

// 提取子串
std::string prefix = section_name.substr(0, 5);  // ".text"

// 查找子串
size_t pos = section_name.find("startup");
if (pos != std::string::npos) {
    // 找到了
}

// 字符串拼接
std::string filename = prefix + ".o";
```

> [!NOTE]
> `std::string::npos`是一个特殊值，表示"未找到"或"无效位置"。它的实际值是`size_t`类型的最大值。当查找函数找不到目标时，就返回这个值。

## 常见错误和解决方法

在使用C++时，有一些常见的错误可能会困扰你。了解它们可以节省大量调试时间。

### 忘记写std::前缀

如果你写了`vector<int> numbers;`而没有`std::`，编译器会报错：

```
error: 'vector' was not declared in this scope
```

解决方法是加上`std::`前缀，或者在文件开头写`using std::vector;`（只引入特定的名字）。

### 混淆点和箭头

如果你对指针使用了`.`，或者对对象使用了`->`，编译器会报类型错误。记住：对象用点，指针用箭头。如果你有一个引用，它的行为像对象，用点。

### 在范围循环中修改容器本身

这是一个更隐蔽的错误：

```cpp
for (auto& item : container) {
    if (should_remove(item)) {
        container.erase(item);  // 危险！
    }
}
```

当你在遍历容器的同时修改容器的结构（添加、删除元素），迭代器可能失效，导致未定义行为。如果需要这样做，应该使用传统的迭代器循环或者收集需要删除的元素，循环结束后再删除。

### 忘记引用的副作用

```cpp
for (const auto& symbol : symbols) {
    symbol.offset = 100;  // 编译错误：symbol是const的
}
```

如果你需要修改元素，记得去掉`const`。反过来，如果你只是读取，加上`const`既能提高性能，也能防止意外修改。

### 比较字符串时用了==指针

如果你有两个C风格字符串（`const char*`），用`==`比较的是指针地址，而不是内容：

```cpp
const char* s1 = "hello";
const char* s2 = "hello";
if (s1 == s2) {  // 可能是真也可能是假，取决于编译器优化
    // ...
}
```

应该用`strcmp(s1, s2) == 0`。但如果是`std::string`，可以直接用`==`比较内容。

## 阅读框架代码的策略

当你打开`include/fle.hpp`或其他框架文件时，可能会看到很多你不熟悉的C++代码。不要被吓到——你不需要理解每一行。这里有一个实用的阅读策略：

**第一步，找到数据结构的定义**。框架的核心是几个关键的结构体：`FLEObject`、`Symbol`、`Relocation`、`FLESection`等。理解这些结构体的字段含义是理解整个系统的基础。注释会帮助你理解每个字段的作用。

**第二步，看你需要实现的函数签名**。比如在`nm.cpp`中，你需要实现`void FLE_nm(const FLEObject& obj)`。从签名你可以知道：这个函数接收一个`FLEObject`的常量引用（不会修改它），没有返回值（可能通过`std::cout`输出结果）。

**第三步，找到helper函数和工具函数**。框架可能提供了一些辅助函数，比如读写文件、解析格式等。浏览一下头文件或文档，了解有哪些可用的工具。不要重新发明轮子。

**第四步，遇到不认识的特性时，尝试根据上下文推测**。比如看到`obj.sections.find("text")`，即使你不知道`map`的`find`方法，从名字也能猜到它是在查找键为`"text"`的项。然后可以查阅文档或搜索引擎确认细节。

**最后，不要试图一次理解所有东西**。聚焦于当前任务需要的部分。随着实验的推进，你对框架的理解会自然加深。

## 关于编译和调试

确保你的编译器支持C++17。大部分现代的g++和clang都默认支持或可以通过`-std=c++17`标志启用。项目的Makefile已经配置好了，你通常不需要修改。

如果你遇到编译错误，仔细阅读错误信息。C++的错误信息有时会很长，特别是涉及模板（template）的时候，但关键信息通常在第一行或最后几行。找到文件名、行号和错误类型，从那里开始排查。

使用调试器（gdb或lldb）时，C++对象可以像C结构体一样查看。你可以用`print symbol.name`查看成员，用`print symbols`查看整个vector的内容（虽然输出可能很长）。现代调试器对STL容器的显示支持已经相当好。

## 小结

这份指南覆盖了实验中会遇到的主要C++特性。总结一下关键点：

使用`std::vector`代替手动管理的动态数组，使用`std::string`代替C风格字符串，使用`std::map`来建立键值映射。这些容器会自动管理内存，你不需要担心`malloc`和`free`。

用范围循环遍历容器，这是最简洁的方式。记得在只读取时加上`const auto&`，在需要修改时用`auto&`。

理解引用是"不能改变指向的指针"，在函数参数中经常使用它来避免复制。

你可以混用C和C++的特性。如果某个C++特性让你困惑，用你熟悉的C方式也完全可以。这个实验不要求你成为C++专家，只要求你能完成链接器的实现。

在实验过程中，如果遇到文档中没有提到的C++特性，可以在讨论区提问。我们会根据反馈持续完善这份指南。祝实验顺利！
