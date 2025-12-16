# ================= Configuration Logic =================
# Config file names
COMPILER_CONFIG_FILE := cxx_compiler
STD_CONFIG_FILE := cxx_std

# 1. Determine Compiler
# If config file exists, use it. Otherwise default to g++ or CXX env var.
ifneq ($(wildcard $(COMPILER_CONFIG_FILE)),)
    CXX := $(shell cat $(COMPILER_CONFIG_FILE))
else
    CXX ?= g++
endif

# 2. Determine Standard
# If config file exists, use it. Otherwise default to c++17.
ifeq ($(wildcard $(STD_CONFIG_FILE)),)
    target_std := c++17
    # Only warn if we are not running a clean/help command to avoid noise
    ifneq ($(MAKECMDGOALS),clean)
        $(warning "Warning: Config not found. Using defaults (g++ / C++17). Run 'python3 configure.py'.")
    endif
else
    target_std := $(shell cat $(STD_CONFIG_FILE))
endif

# 3. Validation
# Verify that the SELECTED compiler supports the SELECTED standard
STD_CHECK := $(shell $(CXX) -std=$(target_std) -x c++ -E /dev/null >/dev/null 2>&1 && echo "ok")

ifneq ($(STD_CHECK),ok)
    $(error "Error: Compiler '$(CXX)' does not support flag '-std=$(target_std)'. Please run 'python3 configure.py' to reconfigure.")
endif

# =======================================================

CXXFLAGS = -std=$(target_std) -Wall -Wextra -I./include -fPIE

ifdef DEBUG
    CXXFLAGS += -g -O0
else
    CXXFLAGS += -O2
endif

# Last config tracker (stores both compiler AND flags now to be safe)
LAST_FLAGS_FILE = .last_build_config

# Source & Object definitions
BASE_SRCS = $(shell find src/base -name '*.cpp')
STUDENT_SRCS = $(shell find src/student -name '*.cpp')
HEADERS = $(shell find include -name '*.h' -o -name '*.hpp')
SRCS = $(BASE_SRCS) $(STUDENT_SRCS)
OBJS = $(SRCS:.cpp=.o)

BASE_EXEC = fle_base
TOOLS = cc ld nm objdump readfle exec disasm ar

#=============================================================================
# Auto-recompile logic
# We track "CXX + CXXFLAGS" to detect compiler changes (e.g. g++ -> clang++)
CURRENT_CONFIG_STR := $(CXX) $(CXXFLAGS)
PREV_CONFIG_STR := $(shell cat $(LAST_FLAGS_FILE) 2>/dev/null)

ifneq ($(PREV_CONFIG_STR),$(CURRENT_CONFIG_STR))
ifneq ($(MAKECMDGOALS),clean)
$(warning "Build configuration changed (Compiler: $(CXX), Std: $(target_std)), forcing full recompile...")
$(shell rm -f $(OBJS))
$(shell echo "$(CURRENT_CONFIG_STR)" > $(LAST_FLAGS_FILE))
endif
endif
#=============================================================================

# Default target
all: show_info $(TOOLS)

# Show configuration info
show_info:
	@echo "------------------------"
	@echo "Compiler: $(CXX)"
	@echo "Version : $$($(CXX) --version | head -n 1)"
	@echo "Standard: $(target_std)"
	@echo "------------------------"

# 编译源文件
%.o: %.cpp
	$(CXX) $(CXXFLAGS) -c -o $@ $<

# 先编译基础可执行文件
$(BASE_EXEC): $(OBJS) $(HEADERS)
	$(CXX) $(CXXFLAGS) -o $@ $(OBJS) -pie

# 为每个工具创建符号链接
$(TOOLS): $(BASE_EXEC)
	@if [ ! -L $@ ] || [ ! -e $@ ]; then \
		ln -sf $(BASE_EXEC) $@; \
	fi

config:
	python3 configure.py

# 清理编译产物
clean:
	rm -f $(OBJS) $(BASE_EXEC) $(TOOLS)
	rm -rf tests/cases/*/build
	rm -f $(LAST_FLAGS_FILE)

# 运行测试
test: all
	python3 grader.py

test_1: all
	python3 grader.py --group nm

test_2: all
	python3 grader.py --group basic_linking

test_3: all
	python3 grader.py --group relative_reloc

test_4: all
	python3 grader.py --group symbol_resolution

test_5: all
	python3 grader.py --group addr64

test_6: all
	python3 grader.py --group section_perm

test_8: all
	python3 grader.py --group static_linking

retest: all
	python3 grader.py -f

.PHONY: all clean test show_info test_1 test_2 test_3 test_4 test_5 test_6 test_8 retest config
