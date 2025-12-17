#include "fle.hpp"
#include "string_utils.hpp"
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <stdexcept>
#include <sys/mman.h>
#include <unistd.h>
#include <unordered_set>
#include <vector>

namespace {

struct LoadedModule {
    std::string name;
    FLEObject obj;
    uint64_t load_base;
    std::map<std::string, uint64_t> section_addrs;
};

// Global list of loaded modules to maintain loading order
// Order: Main Execution -> Dependency 1 -> Dependency 2 ...
std::vector<LoadedModule> loaded_modules;
std::unordered_set<std::string> loaded_module_names;

// Flag: true if any SO has PC32 dyn_relocs (requires all SOs in low address space)
bool need_low_address = false;
std::unordered_set<std::string> scanned_names;

// Helper to load FLE from file (searches FLE_LIBRARY_PATH)
FLEObject load_fle_with_path(const std::string& filename)
{
    // Try direct path
    try {
        return load_fle(filename);
    } catch (...) {
    }

    try {
        return load_fle(filename + ".fle");
    } catch (...) {
    }

    // Search in FLE_LIBRARY_PATH
    const char* lib_path_env = std::getenv("FLE_LIBRARY_PATH");
    if (lib_path_env != nullptr) {
        std::string lib_path(lib_path_env);
        std::string basename = filename;
        size_t last_slash = filename.rfind('/');
        if (last_slash != std::string::npos) {
            basename = filename.substr(last_slash + 1);
        }

        std::vector<std::string> paths;
        size_t start = 0;
        size_t end = lib_path.find(':');
        while (end != std::string::npos) {
            if (end > start)
                paths.push_back(lib_path.substr(start, end - start));
            start = end + 1;
            end = lib_path.find(':', start);
        }
        if (start < lib_path.size())
            paths.push_back(lib_path.substr(start));

        for (const auto& path : paths) {
            try {
                return load_fle(path + "/" + basename);
            } catch (...) {
            }
            try {
                return load_fle(path + "/" + filename);
            } catch (...) {
            }
        }
    }
    throw std::runtime_error("Could not load: " + filename);
}

// Pre-scan dependencies to check if any SO has PC32 dyn_relocs
void scan_dependencies_recursive(const std::string& filename)
{
    if (scanned_names.count(filename))
        return;

    FLEObject obj;
    try {
        obj = load_fle_with_path(filename);
    } catch (...) {
        return; // Will fail later during actual load
    }

    scanned_names.insert(filename);

    // Check for PC32 dyn_relocs
    if (obj.type == ".so") {
        for (const auto& reloc : obj.dyn_relocs) {
            if (reloc.type == RelocationType::R_X86_64_PC32) {
                need_low_address = true;
                break;
            }
        }
    }

    // Recurse into dependencies
    for (const auto& dep : obj.needed) {
        scan_dependencies_recursive(dep);
    }
}

// Helper to resolve a symbol across all loaded modules
uint64_t resolve_symbol(const std::string& name)
{
    for (const auto& mod : loaded_modules) {
        for (const auto& sym : mod.obj.symbols) {
            // We search for GLOBAL or WEAK symbols that are defined (not UNDEFINED)
            if (sym.name == name && (sym.type == SymbolType::GLOBAL || sym.type == SymbolType::WEAK)) {
                auto it = mod.section_addrs.find(sym.section);
                if (it != mod.section_addrs.end()) {
                    return it->second + sym.offset;
                }
            }
        }
    }
    throw std::runtime_error("Symbol not found: " + name);
}

void load_module_recursive(const std::string& filename)
{
    if (loaded_module_names.count(filename)) {
        return;
    }

    // Load FLE file
    // Try direct path first, then search in FLE_LIBRARY_PATH
    FLEObject obj;
    bool loaded = false;

    // Try direct path
    try {
        obj = load_fle(filename);
        loaded = true;
    } catch (...) {
        // Try with extensions
        try {
            obj = load_fle(filename + ".fle");
            loaded = true;
        } catch (...) {
            // Continue to search in library path
        }
    }

    // If not found, search in FLE_LIBRARY_PATH
    if (!loaded) {
        const char* lib_path_env = std::getenv("FLE_LIBRARY_PATH");
        if (lib_path_env != nullptr) {
            std::string lib_path(lib_path_env);
            std::string basename = filename;
            // Extract basename from path if it contains directory separators
            size_t last_slash = filename.rfind('/');
            if (last_slash != std::string::npos) {
                basename = filename.substr(last_slash + 1);
            }

            // Split FLE_LIBRARY_PATH by ':'
            std::vector<std::string> paths;
            size_t start = 0;
            size_t end = lib_path.find(':');
            while (end != std::string::npos) {
                if (end > start) {
                    paths.push_back(lib_path.substr(start, end - start));
                }
                start = end + 1;
                end = lib_path.find(':', start);
            }
            if (start < lib_path.size()) {
                paths.push_back(lib_path.substr(start));
            }

            // Try each path
            for (const auto& path : paths) {
                std::string full_path = path + "/" + basename;
                try {
                    obj = load_fle(full_path);
                    loaded = true;
                    break;
                } catch (...) {
                    // Try original filename (maybe it's a relative path)
                    try {
                        obj = load_fle(path + "/" + filename);
                        loaded = true;
                        break;
                    } catch (...) {
                        // Continue searching
                    }
                }
            }
        }
    }

    if (!loaded) {
        throw std::runtime_error("Could not load dependency: " + filename);
    }

    loaded_module_names.insert(filename);

    // Prepare LoadedModule structure
    LoadedModule mod;
    mod.name = filename;
    mod.obj = obj;

    // Determine load base and map memory
    if (obj.type == ".exe") {
        mod.load_base = 0; // Exe has absolute addresses usually
    } else {
        // For shared objects, we need to find a space.
        // Calculate total size required
        uint64_t min_vaddr = UINT64_MAX;
        uint64_t max_end = 0;
        bool has_segments = false;

        for (const auto& phdr : obj.phdrs) {
            if (phdr.size > 0) {
                if (phdr.vaddr < min_vaddr)
                    min_vaddr = phdr.vaddr;
                uint64_t end = phdr.vaddr + phdr.size;
                if (end > max_end)
                    max_end = end;
                has_segments = true;
            }
        }

        if (has_segments) {
            uint64_t total_size = max_end;

            void* addr;
            if (need_low_address) {
                // Use MAP_32BIT for PC32 text relocations (can only reach ±2GB)
                std::cerr << "Warning: Loading " << filename << " into low 32-bit address space due to PC32 relocations." << std::endl;
                addr = mmap(NULL, total_size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_32BIT, -1, 0);
                if (addr == MAP_FAILED) {
                    // Fallback without MAP_32BIT
                    addr = mmap(NULL, total_size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
                }
            } else {
                // PIC code (GOT/PLT with R_X86_64_64) can be loaded anywhere
                addr = mmap(NULL, total_size, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
            }

            if (addr == MAP_FAILED) {
                throw std::runtime_error("Failed to reserve memory for shared library");
            }
            mod.load_base = (uint64_t)addr;
        } else {
            mod.load_base = 0;
        }
    }

    // Map segments
    for (const auto& phdr : obj.phdrs) {
        if (phdr.size == 0)
            continue;

        void* target_addr = (void*)(mod.load_base + phdr.vaddr);
        void* map_res = mmap(target_addr, phdr.size,
            PROT_READ | PROT_WRITE, // Always RW initially for copying and relocation
            MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0);

        if (map_res == MAP_FAILED) {
            throw std::runtime_error("Failed to map segment " + phdr.name);
        }

        // Copy section data
        auto it = obj.sections.find(phdr.name);
        if (it != obj.sections.end()) {
            // Skip BSS copying
            if (phdr.name != ".bss" && !starts_with(phdr.name, ".bss.")) {
                if (it->second.data.size() > phdr.size) {
                    // Should not happen if FLE is valid, but safety check
                    memcpy(target_addr, it->second.data.data(), phdr.size);
                } else {
                    memcpy(target_addr, it->second.data.data(), it->second.data.size());
                }
            }
        } else {
            throw std::runtime_error("Section data not found for segment: " + phdr.name);
        }

        // Record section address
        mod.section_addrs[phdr.name] = (uint64_t)target_addr;
    }

    // Add to specific list location (Global symbol resolution order)
    loaded_modules.push_back(mod);

    // Recursively load dependencies
    for (const auto& dep : obj.needed) {
        load_module_recursive(dep);
    }
}

} // namespace

void FLE_exec(const FLEObject& obj)
{
    if (obj.type != ".exe") {
        throw std::runtime_error("File is not an executable FLE.");
    }

    // Clear globals for fresh execution
    loaded_modules.clear();
    loaded_module_names.clear();
    scanned_names.clear();
    need_low_address = false;

    // Pre-scan all dependencies to check if any SO has PC32 dyn_relocs
    // This must be done BEFORE loading so we know whether to use MAP_32BIT
    for (const auto& dep : obj.needed) {
        scan_dependencies_recursive(dep);
    }

    // 1. Load Main Executable (Manual setup for the main object provided)
    // We treat the passed object as the first module but we need its name.
    // Since we don't have the filename here, we use a placeholder or obj.name if valid.

    // Actually, recursive loader expects loading from disk.
    // But we already have the main object in memory.
    // We should initialize the main module manually.

    LoadedModule main_mod;
    main_mod.name = obj.name.empty() ? "main" : obj.name;
    main_mod.obj = obj;
    main_mod.load_base = 0;

    // Map Main Executable segments
    for (const auto& phdr : obj.phdrs) {
        if (phdr.size == 0)
            continue;

        void* addr = mmap((void*)phdr.vaddr, phdr.size,
            PROT_READ | PROT_WRITE, // RW for relocations
            MAP_PRIVATE | MAP_FIXED | MAP_ANONYMOUS, -1, 0);

        if (addr == MAP_FAILED) {
            throw std::runtime_error(std::string("mmap failed: ") + strerror(errno));
        }

        auto it = obj.sections.find(phdr.name);
        if (it == obj.sections.end()) {
            throw std::runtime_error("Section not found: " + phdr.name);
        }

        if (phdr.name != ".bss" && !starts_with(phdr.name, ".bss.")) {
            memcpy(addr, it->second.data.data(), phdr.size);
        }

        main_mod.section_addrs[phdr.name] = phdr.vaddr;
    }

    loaded_modules.push_back(main_mod);
    loaded_module_names.insert(main_mod.name);

    // Load dependencies of main
    for (const auto& dep : obj.needed) {
        load_module_recursive(dep);
    }

    // 2. Perform Relocations for ALL modules
    for (auto& mod : loaded_modules) {

        // A. Dynamic Relocations (Bonus 1 - Text Relocations for SO, Bonus 2 - GOT for EXE)
        // For .so: dyn_relocs.offset is relative to merged section data (typically .text)
        // For .exe: dyn_relocs.offset is VMA (already resolved during linking)
        for (const auto& reloc : mod.obj.dyn_relocs) {
            uint64_t reloc_addr;

            if (mod.obj.type == ".exe") {
                // For executables, offset is the VMA
                reloc_addr = reloc.offset;
            } else {
                // For shared objects, offset is VMA relative to Load Base
                reloc_addr = mod.load_base + reloc.offset;
            }

            uint64_t sym_addr = resolve_symbol(reloc.symbol);

            switch (reloc.type) {
            case RelocationType::R_X86_64_64:
                *(uint64_t*)reloc_addr = sym_addr + reloc.addend;
                break;
            case RelocationType::R_X86_64_32:
                *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend);
                break;
            case RelocationType::R_X86_64_32S:
                *(int32_t*)reloc_addr = (int32_t)(sym_addr + reloc.addend);
                break;
            case RelocationType::R_X86_64_PC32:
                // S + A - P
                *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend - reloc_addr);
                break;
            case RelocationType::R_X86_64_GOTPCREL:
                *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend - reloc_addr);
                break;
            }
        }

        // B. Section Relocations (Bonus 1 - Text Relocations)
        // Iterate over sections to find relocations
        for (const auto& kv : mod.obj.sections) {
            const auto& name = kv.first;
            const auto& section = kv.second;

            // Check if this section is loaded.
            auto addr_it = mod.section_addrs.find(name);
            if (addr_it == mod.section_addrs.end())
                continue;

            // In FLE, section relocs have offset relative to the section start
            // phdr.vaddr corresponds to the section start VMA relative to Load Base (for SO) or Absolute (for EXE)
            // Wait, for .so, phdr.vaddr is offset from base.
            // But we stored the Absolute Runtime Address in section_addrs.
            // But apply_reloc adds load_base + section_base ...

            // Let's adjust logic.
            // For Main (.exe), load_base = 0. section_addr is absolute.
            // For .so, load_base = allocated. section_addr is absolute = load_base + vaddr.

            // Reloc offset is relative to section start.
            // address = section_absolute_start + reloc.offset.
            // We can pass `section_absolute_start - load_base` as 2nd arg?
            // Or just calculate address and adapt lambda.

            uint64_t section_runtime_addr = addr_it->second;

            for (const auto& reloc : section.relocs) {
                uint64_t sym_addr = resolve_symbol(reloc.symbol);
                uint64_t reloc_addr = section_runtime_addr + reloc.offset;

                switch (reloc.type) {
                case RelocationType::R_X86_64_64:
                    *(uint64_t*)reloc_addr = sym_addr + reloc.addend;
                    break;
                case RelocationType::R_X86_64_32:
                    *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend);
                    break;
                case RelocationType::R_X86_64_32S:
                    *(int32_t*)reloc_addr = (int32_t)(sym_addr + reloc.addend);
                    break;
                case RelocationType::R_X86_64_PC32:
                    *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend - reloc_addr);
                    break;
                case RelocationType::R_X86_64_GOTPCREL:
                    *(uint32_t*)reloc_addr = (uint32_t)(sym_addr + reloc.addend - reloc_addr);
                    break;
                }
            }
        }
    }

    // 3. Set Permissions (after all relocations are done)
    for (const auto& mod : loaded_modules) {
        for (const auto& phdr : mod.obj.phdrs) {
            if (phdr.size == 0)
                continue;

            // Find runtime address
            uint64_t addr = mod.load_base + phdr.vaddr;

            mprotect((void*)addr, phdr.size,
                (phdr.flags & PHF::R ? PROT_READ : 0)
                    | (phdr.flags & PHF::W ? PROT_WRITE : 0)
                    | (phdr.flags & PHF::X ? PROT_EXEC : 0));
        }
    }

    // 4. Jump to Entry
    using FuncType = int (*)();
    // Entry is VMA. Main EXE base is 0. So entry is absolute.
    FuncType func = reinterpret_cast<FuncType>(obj.entry);
    func();

    // Should not reach here
    assert(false);
}
