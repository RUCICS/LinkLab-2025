import sys
import shutil
import subprocess
from pathlib import Path

# --- BOOTSTRAP ---
import bootstrap
bootstrap.initialize()
# -----------------

from rich.console import Console
from rich.panel import Panel
from rich.prompt import IntPrompt
from rich.table import Table
from rich import box

console = Console()

# 配置文件
CONFIG_STD = "cxx_std"
CONFIG_COMPILER = "cxx_compiler"

# 候选标准
CANDIDATES = ["c++23", "c++20", "c++17"]

def get_available_compilers() -> list[str]:
    """扫描系统中的可用编译器"""
    compilers = []
    # 优先检查环境变量 CXX
    # env_cxx = os.environ.get("CXX")
    # if env_cxx and shutil.which(env_cxx):
    #     compilers.append(env_cxx)
    
    # 检查常见编译器
    if shutil.which("g++"):
        compilers.append("g++")
    if shutil.which("clang++"):
        compilers.append("clang++")
    
    # 去重并排序
    return sorted(list(set(compilers)))

def get_compiler_version(compiler_cmd: str) -> str:
    """获取编译器版本信息"""
    try:
        result = subprocess.run([compiler_cmd, "--version"], capture_output=True, text=True)
        # 取第一行作为版本信息
        return result.stdout.splitlines()[0]
    except Exception:
        return "Unknown Version"

def check_support(compiler: str, std: str) -> bool:
    """使用指定的编译器检测是否支持某个标准"""
    try:
        # Clang 和 GCC 都支持 -std=... -E -x c++ /dev/null
        cmd = [compiler, f"-std={std}", "-x", "c++", "-E", "/dev/null"]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def main():
    console.clear()
    console.print(Panel.fit(
        "[bold cyan]C++ Lab Configurator[/bold cyan]\n[dim]Compiler & Standard Selection[/dim]", 
        box=box.ROUNDED
    ))
    
    # ---------------- Step 1: 选择编译器 ----------------
    compilers = get_available_compilers()
    
    if not compilers:
        console.print("[bold red]Error: No C++ compiler (g++ or clang++) found![/bold red]")
        sys.exit(1)

    selected_compiler = compilers[0]
    
    # 如果有多个编译器，让用户选择
    if len(compilers) > 1:
        console.print(f"\n[bold]Step 1: Select Compiler[/bold]")
        table = Table(show_header=True, box=box.SIMPLE)
        table.add_column("#", style="yellow", width=4)
        table.add_column("Compiler", style="green")
        table.add_column("Version Details", style="dim")
        
        for idx, comp in enumerate(compilers, 1):
            ver = get_compiler_version(comp)
            table.add_row(str(idx), comp, ver)
        
        console.print(table)
        
        # 读取旧配置作为默认值
        default_idx = 1
        if Path(CONFIG_COMPILER).exists():
            old_comp = Path(CONFIG_COMPILER).read_text().strip()
            if old_comp in compilers:
                default_idx = compilers.index(old_comp) + 1
        
        idx = IntPrompt.ask("Choose compiler", choices=[str(i) for i in range(1, len(compilers)+1)], default=default_idx)
        selected_compiler = compilers[idx-1]
    else:
        console.print(f"\n[bold]Compiler:[/bold] [green]{selected_compiler}[/green] (Auto-detected)")

    console.print(f"Using compiler: [bold cyan]{selected_compiler}[/bold cyan]\n")

    # ---------------- Step 2: 选择标准 ----------------
    console.print(f"[bold]Step 2: Select C++ Standard[/bold]")
    
    supported_options = []
    table = Table(show_header=True, box=box.SIMPLE)
    table.add_column("#", style="yellow", width=4)
    table.add_column("Standard", style="cyan")
    table.add_column("Status", justify="left")
    
    with console.status(f"[bold green]Checking {selected_compiler} support...[/bold green]"):
        idx_count = 1
        for std in CANDIDATES:
            is_supported = check_support(selected_compiler, std)
            if is_supported:
                icon = "[green]✔ Supported[/green]"
                if idx_count == 1: icon += " (Recommended)"
                table.add_row(str(idx_count), std, icon)
                supported_options.append(std)
                idx_count += 1
            else:
                table.add_row("-", std, "[dim red]✘ Not Supported[/dim red]")

    if not supported_options:
        console.print(f"[bold red]Error: {selected_compiler} does not support C++17![/bold red]")
        sys.exit(1)

    console.print(table)

    # 读取旧配置
    default_choice = "1"
    if Path(CONFIG_STD).exists():
        old_std = Path(CONFIG_STD).read_text().strip()
        if old_std in supported_options:
            default_choice = str(supported_options.index(old_std) + 1)

    sel_idx = IntPrompt.ask("Choose standard", choices=[str(i) for i in range(1, len(supported_options)+1)], default=int(default_choice))
    selected_std = supported_options[sel_idx-1]

    # ---------------- Step 3: 保存配置 ----------------
    try:
        Path(CONFIG_COMPILER).write_text(selected_compiler)
        Path(CONFIG_STD).write_text(selected_std)
        
        console.print(Panel(
            f"[bold green]Configuration Saved![/bold green]\n\n"
            f"Compiler: [green]{selected_compiler}[/green]  -> stored in [yellow]{CONFIG_COMPILER}[/yellow]\n"
            f"Standard: [cyan]{selected_std}[/cyan]      -> stored in [yellow]{CONFIG_STD}[/yellow]\n\n"
            f"[bold white on red] IMPORTANT [/bold white on red] Don't forget to commit:\n"
            f"> [bold]git add {CONFIG_COMPILER} {CONFIG_STD}[/bold]",
            border_style="green"
        ))
    except Exception as e:
        console.print(f"[bold red]Failed to save config: {e}[/bold red]")

if __name__ == "__main__":
    main()
