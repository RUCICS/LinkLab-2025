#include "argparse.hpp"
#include "fle.hpp"
#include "string_utils.hpp"
#include <csignal>
#include <cstdint>
#include <cstdio>
#include <execinfo.h>
#include <fstream>
#include <iostream>
#include <regex>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std::string_literals;

void segv_handler(int sig, siginfo_t* si, void* ctx)
{
    fprintf(stderr, "Caught SIGSEGV at address: %p\n", si->si_addr);
    fflush(stderr);
    fprintf(stderr, "Error code: %d\n", si->si_code);
    fflush(stderr);

    auto uctx = reinterpret_cast<ucontext_t*>(ctx);

    // 发生段错误的指令地址
    auto rip = uctx->uc_mcontext.gregs[REG_RIP];

    // call 指令前，会先往栈里压入返回地址，RSP 指向栈顶。
    // 这里尝试从栈顶读取 8 字节（对于 x86_64）当作返回地址
    auto rsp = uctx->uc_mcontext.gregs[REG_RSP];
    void* call_site_next = 0;
    // 这里要确保 rsp 是可读，且内存布局正常
    // 对于因为错误跳转而崩溃的大多数场景，下面的读取通常可行
    if (rsp != 0) {
        // 取到栈顶存放的返回地址
        call_site_next = reinterpret_cast<void*>(*reinterpret_cast<uint64_t*>(rsp));
    }

    fprintf(stderr, "Instruction at: %p\n", reinterpret_cast<void*>(rip));
    fflush(stderr);
    // call_site_next 是 call 指令推入的“返回地址”，即 call 指令自身之后的那条指令地址
    // 它通常比 call 指令的开头多 5~7 个字节（具体看是否是 call rel32 或 call r/m64 等）
    // 因此可用 call_site_next - offset 推算出 call 指令的开头
    fprintf(stderr, "Likely return address: %p\n", call_site_next);
    fflush(stderr);

    // 恢复默认的信号处理程序
    signal(SIGSEGV, SIG_DFL);
    // 重新抛出信号
    raise(sig);
}

namespace fs = std::filesystem;

/**
 * 检查文件是否存在
 */
bool file_exists(const std::string& path)
{
    std::error_code ec;
    return fs::exists(path, ec) && fs::is_regular_file(path, ec);
}

// 辅助函数：解析程序头
static void parse_program_headers(const json& j, FLEObject& obj)
{
    if (j.contains("phdrs")) {
        for (const auto& phdr_json : j["phdrs"]) {
            ProgramHeader phdr;
            phdr.name = phdr_json["name"].get<std::string>();
            phdr.vaddr = phdr_json["vaddr"].get<uint64_t>();
            phdr.size = phdr_json["size"].get<uint32_t>();
            phdr.flags = phdr_json["flags"].get<uint32_t>();
            obj.phdrs.push_back(phdr);
        }
    }
}

// 辅助函数：解析节头
static void parse_section_headers(const json& j, FLEObject& obj)
{
    if (j.contains("shdrs")) {
        for (const auto& shdr_json : j["shdrs"]) {
            SectionHeader shdr;
            shdr.name = shdr_json["name"].get<std::string>();
            shdr.type = shdr_json["type"].get<uint32_t>();
            shdr.flags = shdr_json["flags"].get<uint32_t>();
            shdr.addr = shdr_json["addr"].get<uint64_t>();
            shdr.offset = shdr_json["offset"].get<uint64_t>();
            shdr.size = shdr_json["size"].get<uint64_t>();
            obj.shdrs.push_back(shdr);
        }
    }
}

// 辅助函数：解析重定位类型
static RelocationType parse_relocation_type(const std::string& type_str)
{
    if (type_str == "rel" || type_str == "dynrel")
        return RelocationType::R_X86_64_PC32;
    if (type_str == "abs64" || type_str == "dynabs64")
        return RelocationType::R_X86_64_64;
    if (type_str == "abs" || type_str == "dynabs32" || type_str == "abs32")
        return RelocationType::R_X86_64_32;
    if (type_str == "abs32s")
        return RelocationType::R_X86_64_32S;
    if (type_str == "gotpcrel")
        return RelocationType::R_X86_64_GOTPCREL;
    throw std::runtime_error("Invalid relocation type: " + type_str);
}
static int64_t parse_addend_literal(std::string literal)
{
    literal = trim(literal);
    if (literal.empty()) {
        throw std::runtime_error("Empty relocation addend");
    }

    if (literal.size() > 2 && literal[0] == '0' && (literal[1] == 'x' || literal[1] == 'X')) {
        literal = literal.substr(2);
    }

    try {
        return std::stoll(literal, nullptr, 16);
    } catch (const std::invalid_argument&) {
        return std::stoll(literal, nullptr, 10);
    }
}



static FLEObject parse_fle_from_json(const json& j, const std::string& name)
{
    FLEObject obj;
    obj.name = name;
    obj.type = j["type"].get<std::string>();

    if (obj.type == ".ar") {
        if (j.contains("members")) {
            for (const auto& member_json : j["members"]) {
                std::string member_name = "";
                if (member_json.contains("name")) {
                    member_name = member_json["name"].get<std::string>();
                }
                obj.members.push_back(parse_fle_from_json(member_json, member_name));
            }
        }
        return obj;
    }

    // 如果是可执行文件，读取入口点和程序头
    if (obj.type == ".exe") {
        if (j.contains("entry")) {
            obj.entry = j["entry"].get<size_t>();
        }
        parse_program_headers(j, obj);
    }

    // 如果是共享库，读取程序头
    if (obj.type == ".so") {
        parse_program_headers(j, obj);
    }

    // 读取依赖库列表（可执行文件和共享库都可能有）
    if (j.contains("needed")) {
        for (const auto& lib : j["needed"]) {
            obj.needed.push_back(lib.get<std::string>());
        }
    }

    std::vector<Relocation> legacy_dyn_relocs;
    std::vector<Relocation> inline_dyn_relocs;

    parse_section_headers(j, obj);

    std::unordered_map<std::string, Symbol> symbol_table;
    std::unordered_map<std::string, uint64_t> section_base_addrs;

    for (const auto& shdr : obj.shdrs) {
        section_base_addrs[shdr.name] = shdr.addr;
    }
    for (const auto& phdr : obj.phdrs) {
        section_base_addrs.emplace(phdr.name, phdr.vaddr);
    }

    // 第一遍：收集所有符号定义并计算偏移量
    for (auto& [key, value] : j.items()) {
        if (key == "type" || key == "entry" || key == "phdrs" || key == "shdrs" || key == "members" || key == "name" || key == "needed" || key == "dyn_relocs")
            continue;

        // size_t current_offset = 0;
        for (const auto& line : value) {
            std::string line_str = line.get<std::string>();
            size_t colon_pos = line_str.find(':');
            std::string prefix = line_str.substr(0, colon_pos);
            std::string content = line_str.substr(colon_pos + 1);

            if (prefix == "🏷️" || prefix == "📎" || prefix == "📤") {
                std::string name;
                size_t size, offset;
                std::istringstream ss(content);
                ss >> name >> size >> offset;

                name = trim(name);
                SymbolType type = prefix == "🏷️" ? SymbolType::LOCAL : prefix == "📎" ? SymbolType::WEAK
                                                                                      : SymbolType::GLOBAL;

                Symbol sym {
                    type,
                    std::string(key),
                    offset,
                    size,
                    name
                };

                symbol_table[name] = sym;
                obj.symbols.push_back(sym);
            }
        }
    }

    // 第二遍：处理节的内容和重定位
    for (auto& [key, value] : j.items()) {
        if (key == "type" || key == "entry" || key == "phdrs" || key == "shdrs" || key == "members" || key == "name" || key == "needed" || key == "dyn_relocs")
            continue;

        FLESection section;
        section.has_symbols = false;

        for (const auto& line : value) {
            std::string line_str = line.get<std::string>();
            size_t colon_pos = line_str.find(':');
            std::string prefix = line_str.substr(0, colon_pos);
            std::string content = line_str.substr(colon_pos + 1);

            if (prefix == "🔢") {
                std::stringstream ss(content);
                uint32_t byte;
                while (ss >> std::hex >> byte) {
                    section.data.push_back(static_cast<uint8_t>(byte));
                }
            } else if (prefix == "❓") {
                std::string reloc_str = trim(content);
                std::regex reloc_pattern(R"(\.(rel|abs64|abs|abs32s|gotpcrel|dynrel|dynabs64|dynabs32)\(([\w.@$]+)\s*([-+])\s*([0-9a-fA-FxX]+)\))");
                std::smatch match;

                if (!std::regex_match(reloc_str, match, reloc_pattern)) {
                    throw std::runtime_error("Invalid relocation: " + reloc_str);
                }

                RelocationType type = parse_relocation_type(match[1].str());
                std::string symbol_name = match[2].str();
                std::string sign = match[3].str();
                int64_t append_value = parse_addend_literal(match[4].str());
                if (sign == "-") {
                    append_value = -append_value;
                }

                auto ensure_symbol_exists = [&](const std::string& name) {
                    auto it = symbol_table.find(name);
                    if (it == symbol_table.end()) {
                        Symbol sym {
                            SymbolType::UNDEFINED,
                            "",
                            0,
                            0,
                            name
                        };
                        symbol_table[name] = sym;
                        obj.symbols.push_back(sym);
                    }
                };

                bool is_dynamic_reloc = match[1].str().rfind("dyn", 0) == 0;
                if (is_dynamic_reloc) {
                    ensure_symbol_exists(symbol_name);

                    auto base_it = section_base_addrs.find(key);
                    if (base_it == section_base_addrs.end()) {
                        throw std::runtime_error("Dynamic relocation section has no base address: " + key);
                    }

                    Relocation reloc {
                        type,
                        base_it->second + section.data.size(),
                        symbol_name,
                        append_value
                    };

                    inline_dyn_relocs.push_back(reloc);

                    size_t size = (type == RelocationType::R_X86_64_64) ? 8 : 4;
                    section.data.insert(section.data.end(), size, 0);
                    continue;
                }

                Relocation reloc {
                    type,
                    section.data.size(),
                    symbol_name,
                    append_value
                };

                ensure_symbol_exists(symbol_name);

                section.relocs.push_back(reloc);

                // 根据重定位类型预留空间
                size_t size = (type == RelocationType::R_X86_64_64) ? 8 : 4;
                section.data.insert(section.data.end(), size, 0);
            } else if (prefix == "🏷️" || prefix == "📎" || prefix == "📤") {
                section.has_symbols = true;
            }
        }

        section.name = key;
        obj.sections[key] = section;
    }

    if (!inline_dyn_relocs.empty()) {
        obj.dyn_relocs = std::move(inline_dyn_relocs);
    } else {
        obj.dyn_relocs = std::move(legacy_dyn_relocs);
    }

    return obj;
}

FLEObject load_fle(const std::string& file)
{
    std::ifstream infile(file);
    std::string content((std::istreambuf_iterator<char>(infile)),
        std::istreambuf_iterator<char>());

    if (content.substr(0, 2) == "#!") {
        content = content.substr(content.find('\n') + 1);
    }

    json j = json::parse(content);
    return parse_fle_from_json(j, get_basename(file));
}

/**
 * 库文件搜索逻辑
 * @param lib_name 库名，如 "m" (对应 -lm)
 * @param library_paths 搜索路径列表 (-L)
 * @param force_static 是否强制静态链接 (-static)
 * @return 找到的库文件的完整路径
 * @throw std::runtime_error 如果找不到库
 */
std::string find_library(const std::string& lib_name,
    const std::vector<std::string>& library_paths,
    bool force_static)
{
    // 1. 名字扩展 (Name Expansion)
    // 我们的实验约定：动态库是 .so，静态库是 .ar
    std::string dynamic_name = "lib" + lib_name + ".fso";
    std::string static_name = "lib" + lib_name + ".fa";

    // 2. 遍历搜索路径
    for (const auto& dir_str : library_paths) {
        fs::path dir(dir_str); // 使用 fs::path 自动处理路径分隔符

        // 构造完整路径
        // operator/ 会自动处理中间的 '/'，比字符串拼接更安全
        fs::path dylib_full_path = dir / dynamic_name;
        fs::path static_full_path = dir / static_name;

        // 3. 应用优先级规则

        // 策略 A: 强制静态链接 (-static)
        // 只找 .ar，完全忽略 .so
        if (force_static) {
            if (file_exists(static_full_path.string())) {
                return static_full_path.string();
            }
            // 当前目录没找到 .ar，去下一个目录找
            continue;
        }

        // 策略 B: 默认模式 (Dynamic Mode)
        // 优先找 .so，其次找 .ar
        // 注意：ld 的行为是在同一个目录下，.so 优先级高于 .ar
        bool has_so = file_exists(dylib_full_path.string());
        bool has_ar = file_exists(static_full_path.string());

        if (has_so) {
            return dylib_full_path.string();
        }
        if (has_ar) {
            // 虽然是默认模式，但只找到了静态库，那也可以用
            return static_full_path.string();
        }
    }

    // 4. 找遍所有目录都没找到 -> 报错
    throw std::runtime_error("cannot find -l" + lib_name);
}

void FLE_ar(const std::vector<std::string>& args)
{
    if (args.size() < 2) {
        throw std::runtime_error("Usage: ar <output.fa> <input1.fo> ...");
    }

    std::string outfile = args[0];
    json ar_json;
    ar_json["type"] = ".ar";
    ar_json["name"] = get_basename(outfile);

    json members = json::array();
    for (size_t i = 1; i < args.size(); ++i) {
        std::ifstream infile(args[i]);
        std::string content((std::istreambuf_iterator<char>(infile)),
            std::istreambuf_iterator<char>());

        if (content.substr(0, 2) == "#!") {
            content = content.substr(content.find('\n') + 1);
        }

        json member_json = json::parse(content);
        // Ensure name is set in the member JSON so it can be recovered
        member_json["name"] = get_basename(args[i]);
        members.push_back(member_json);
    }

    ar_json["members"] = members;

    std::ofstream out(outfile);
    out << ar_json.dump(4) << std::endl;
}

struct InputItem {
    enum Type { File,
        Library } type;
    std::string value;
};

int main(int argc, char* argv[])
{
    // singlestack
    constexpr size_t SIGSTACK_BUFFER_SIZE = 1024 * 1024;
    uint8_t sigstack_buffer[SIGSTACK_BUFFER_SIZE];
    stack_t sigstack;
    sigstack.ss_sp = sigstack_buffer;
    sigstack.ss_size = sizeof(sigstack_buffer);
    sigstack.ss_flags = 0;
    sigaltstack(&sigstack, NULL);

    struct sigaction sa;
    sa.sa_flags = SA_SIGINFO | SA_ONSTACK;
    sa.sa_sigaction = segv_handler;
    if (sigaction(SIGSEGV, &sa, NULL) == -1) {
        std::cerr << "Failed to set up signal handler for SIGSEGV" << std::endl;
        return 1;
    }

    if (argc < 2) {
        std::cerr << "Usage: " << argv[0] << " <command> [args...]\n"
                  << "Commands:\n"
                  << "  objdump <input>                  Display contents of FLE file\n"
                  << "  nm <input>                       Display symbol table\n"
                  << "  ld [-o output] input1 input2...  Link FLE files (.fo/.fa/.fle)\n"
                  << "  exec <input.fle>                 Execute FLE file\n"
                  << "  cc [-o output.o] input.c...      Compile C files (outputs .fo)\n"
                  << "  ar <output.fa> <input.fo>...     Create static archive\n"
                  << "  readfle <input>                  Display FLE file information\n"
                  << "  disasm <input> <section>         Disassemble section\n";
        return 1;
    }

    std::string tool = "FLE_"s + get_basename(argv[0]);
    std::vector<std::string> args(argv + 1, argv + argc);

    try {
        if (tool == "FLE_objdump") {
            if (args.size() != 1) {
                throw std::runtime_error("Usage: objdump <input>");
            }
            FLEWriter writer;
            FLE_objdump(load_fle(args[0]), writer);
            writer.write_to_file(args[0] + ".objdump");
        } else if (tool == "FLE_nm") {
            if (args.size() != 1) {
                throw std::runtime_error("Usage: nm <input>");
            }
            FLE_nm(load_fle(args[0]));
        } else if (tool == "FLE_exec") {
            if (args.size() != 1) {
                throw std::runtime_error("Usage: exec <input.fle>");
            }
            FLE_exec(load_fle(args[0]));
        } else if (tool == "FLE_ld") {
            LinkerOptions options;
            std::vector<InputItem> ordered_inputs;
            std::vector<std::string> lib_paths;

            ArgParser parser("ld");

            parser.add_option(options.outputFile, "-o, --output", "Output file");
            parser.add_option(options.entryPoint, "-e, --entry", "Entry point");
            parser.add_flag(options.shared, "-shared", "Create shared library");
            parser.add_flag(options.is_static, "-static", "Static linking");
            parser.add_multi_option(lib_paths, "-L", "Add library search path");

            parser.add_option_cb("-l", "Link library", [&](std::string lib_name) {
                ordered_inputs.push_back({ InputItem::Library, lib_name });
            });

            parser.on_positional([&](std::string file_path) {
                ordered_inputs.push_back({ InputItem::File, file_path });
            });

            try {
                parser.parse(args);
            } catch (const ArgParser::HelpRequested&) {
                return 0;
            } catch (const std::exception& e) {
                std::cerr << "Error: " << e.what() << "\n";
                return 1;
            }

            if (ordered_inputs.empty()) {
                std::cerr << "Error: No inputs\n";
                return 1;
            }

            std::vector<FLEObject> objects;
            lib_paths.push_back("./");

            for (const auto& item : ordered_inputs) {
                if (item.type == InputItem::File) {
                    objects.push_back(load_fle(item.value));
                } else if (item.type == InputItem::Library) {
                    std::string path = find_library(item.value, lib_paths, options.is_static);
                    objects.push_back(load_fle(path));
                }
            }

            FLEObject result = FLE_ld(objects, options);

            FLEWriter writer;
            FLE_objdump(result, writer);
            writer.write_to_file(options.outputFile);
        } else if (tool == "FLE_cc") {
            FLE_cc(args);
        } else if (tool == "FLE_readfle") {
            if (args.size() != 1) {
                throw std::runtime_error("Usage: readfle <input>");
            }
            FLE_readfle(load_fle(args[0]));
        } else if (tool == "FLE_disasm") {
            if (args.size() != 2) {
                throw std::runtime_error("Usage: disasm <input> <section>");
            }
            FLE_disasm(load_fle(args[0]), args[1]);
        } else if (tool == "FLE_ar") {
            FLE_ar(args);
        } else {
            std::cerr << "Unknown tool: " << tool << std::endl;
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        return 1;
    }

    return 0;
}
