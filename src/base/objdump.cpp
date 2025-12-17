#include "fle.hpp"
#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <sstream>

void FLE_objdump(const FLEObject& obj, FLEWriter& writer)
{
    writer.set_type(obj.type);

    // 如果是可执行文件，写入程序头和入口点
    if (obj.type == ".exe") {
        writer.write_program_headers(obj.phdrs);
        writer.write_entry(obj.entry);
    }

    // 如果是共享库，也写入程序头和节头
    if (obj.type == ".so") {
        writer.write_program_headers(obj.phdrs);
        writer.write_section_headers(obj.shdrs);

        if (!obj.needed.empty()) {
            writer.write_needed(obj.needed);
        }
    }

    // 如果是可执行文件且有动态依赖，也写入
    if (obj.type == ".exe") {
        if (!obj.needed.empty()) {
            writer.write_needed(obj.needed);
        }
    }

    // 预处理：构建符号表索引
    std::map<std::string, std::map<size_t, std::vector<Symbol>>> symbol_index;
    for (const auto& sym : obj.symbols) {
        if (sym.type != SymbolType::UNDEFINED) {
            symbol_index[sym.section][sym.offset].push_back(sym);
        }
    }

    std::map<std::string, std::pair<uint64_t, uint64_t>> section_ranges;
    for (const auto& shdr : obj.shdrs) {
        section_ranges[shdr.name] = { shdr.addr, shdr.addr + shdr.size };
    }
    for (const auto& phdr : obj.phdrs) {
        section_ranges.emplace(phdr.name, std::make_pair(phdr.vaddr, phdr.vaddr + phdr.size));
    }

    std::map<std::string, std::vector<Relocation>> dyn_relocs_by_section;
    for (const auto& reloc : obj.dyn_relocs) {
        bool assigned = false;
        for (const auto& [sec_name, range] : section_ranges) {
            uint64_t start = range.first;
            uint64_t end = range.second;
            if (start <= reloc.offset && reloc.offset < end) {
                Relocation local = reloc;
                local.offset = static_cast<size_t>(reloc.offset - start);
                dyn_relocs_by_section[sec_name].push_back(local);
                assigned = true;
                break;
            }
        }
        if (!assigned) {
            throw std::runtime_error("Dynamic relocation offset " + std::to_string(reloc.offset) + " outside known sections");
        }
    }

    std::vector<std::tuple<std::string, size_t, FLESection>> sections;
    for (const auto& pair : obj.sections) {
        const auto& name = pair.first;
        const auto& section = pair.second;
        auto shdr = std::find_if(obj.shdrs.begin(), obj.shdrs.end(), [&](const auto& shdr) {
            return shdr.name == name;
        });
        if (shdr == obj.shdrs.end()) {
            sections.push_back({ name, 0, section });
            continue;
        }
        sections.push_back({ name, shdr->offset, section });
    }
    std::sort(sections.begin(), sections.end(), [](const auto& a, const auto& b) {
        return std::get<1>(a) < std::get<1>(b);
    });

    // 写入所有段的内容
    for (const auto& [name, _, section] : sections) {
        writer.begin_section(name);

        struct RelocForOutput {
            Relocation reloc;
            bool dynamic;
        };

        std::map<size_t, std::vector<RelocForOutput>> reloc_index;
        for (const auto& reloc : section.relocs) {
            reloc_index[reloc.offset].push_back({ reloc, false });
        }
        auto dyn_it = dyn_relocs_by_section.find(name);
        if (dyn_it != dyn_relocs_by_section.end()) {
            for (const auto& reloc : dyn_it->second) {
                reloc_index[reloc.offset].push_back({ reloc, true });
            }
        }

        std::vector<size_t> breaks;
        for (const auto& sym : obj.symbols) {
            if (sym.section == name) {
                breaks.push_back(sym.offset);
            }
        }
        for (const auto& [offset, _] : reloc_index) {
            breaks.push_back(offset);
        }
        std::sort(breaks.begin(), breaks.end());
        breaks.erase(std::unique(breaks.begin(), breaks.end()), breaks.end());

        auto format_reloc = [](const RelocForOutput& entry) -> std::string {
            auto type_to_tag = [&](RelocationType type, bool dynamic) -> std::string {
                switch (type) {
                case RelocationType::R_X86_64_PC32:
                    return dynamic ? ".dynrel" : ".rel";
                case RelocationType::R_X86_64_64:
                    return dynamic ? ".dynabs64" : ".abs64";
                case RelocationType::R_X86_64_32:
                    return dynamic ? ".dynabs32" : ".abs";
                case RelocationType::R_X86_64_32S:
                    return dynamic ? ".dynabs32" : ".abs32s";
                case RelocationType::R_X86_64_GOTPCREL:
                    if (!dynamic)
                        return ".gotpcrel";
                    break;
                }
                throw std::runtime_error("Unsupported relocation type in objdump");
            };

            const auto tag = type_to_tag(entry.reloc.type, entry.dynamic);
            const char sign = entry.reloc.addend < 0 ? '-' : '+';
            auto abs_addend = static_cast<uint64_t>(std::llabs(entry.reloc.addend));

            std::ostringstream ss;
            ss << "❓: " << tag << "(" << entry.reloc.symbol << " " << sign << " " << abs_addend << ")";
            return ss.str();
        };

        size_t pos = 0;
        while (pos < section.data.size()) {
            auto section_it = symbol_index.find(name);
            if (section_it != symbol_index.end()) {
                auto offset_it = section_it->second.find(pos);
                if (offset_it != section_it->second.end()) {
                    for (const auto& sym : offset_it->second) {
                        std::string line;
                        switch (sym.type) {
                        case SymbolType::LOCAL:
                            line = "🏷️: " + sym.name;
                            break;
                        case SymbolType::WEAK:
                            line = "📎: " + sym.name;
                            break;
                        case SymbolType::GLOBAL:
                            line = "📤: " + sym.name;
                            break;
                        default:
                            [[unlikely]] throw std::runtime_error("unknown symbol type");
                        }
                        line += " " + std::to_string(sym.size) + " " + std::to_string(sym.offset);
                        writer.write_line(line);
                    }
                }
            }

            auto reloc_it = reloc_index.find(pos);
            if (reloc_it != reloc_index.end()) {
                for (const auto& reloc_entry : reloc_it->second) {
                    writer.write_line(format_reloc(reloc_entry));
                    size_t reloc_size = (reloc_entry.reloc.type == RelocationType::R_X86_64_64) ? 8 : 4;
                    pos += reloc_size;
                }
                continue;
            }

            size_t next_break = section.data.size();
            auto upper = std::upper_bound(breaks.begin(), breaks.end(), pos);
            if (upper != breaks.end()) {
                next_break = *upper;
            }

            while (pos < next_break) {
                std::stringstream ss;
                ss << "🔢: ";
                size_t chunk_size = std::min({
                    size_t(16),
                    next_break - pos,
                    section.data.size() - pos
                });

                for (size_t i = 0; i < chunk_size; ++i) {
                    ss << std::hex << std::setw(2) << std::setfill('0')
                       << static_cast<int>(section.data[pos + i]);
                    if (i < chunk_size - 1) {
                        ss << " ";
                    }
                }
                writer.write_line(ss.str());
                pos += chunk_size;
            }
        }

        writer.end_section();
    }
}
