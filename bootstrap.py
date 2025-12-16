import os
import sys
import subprocess
import venv
from pathlib import Path

# ================= 配置 =================
VENV_DIR_NAME = ".venv"
REQUIREMENTS_FILE = "requirements.txt"
# 这里的包名必须是 import 时使用的名字 (例如 "tomli" 而不是 "tomli>=2.0")
REQUIRED_IMPORTS = ["rich", "tomli"] 
REQUIRED_PACKAGES = ["rich", "tomli"] # 如果需要安装，传给 pip 的包名
# =======================================

def get_venv_paths(root_dir: Path):
    """获取虚拟环境的路径"""
    venv_dir = root_dir / VENV_DIR_NAME
    if sys.platform == "win32":
        python_executable = venv_dir / "Scripts" / "python.exe"
        pip_executable = venv_dir / "Scripts" / "pip.exe"
    else:
        python_executable = venv_dir / "bin" / "python"
        pip_executable = venv_dir / "bin" / "pip"
    return venv_dir, python_executable, pip_executable

def check_venv_integrity(python_executable: Path) -> bool:
    """
    检查 venv 里的 Python 是否已经安装了必要的包。
    通过调用 venv python 执行尝试导入的脚本来验证。
    """
    if not python_executable.exists():
        return False
    
    # 构建检查脚本: "import rich; import tomli;"
    check_script = "; ".join([f"import {pkg}" for pkg in REQUIRED_IMPORTS])
    
    try:
        # 使用 -c 执行导入检查，stdout/stderr 扔掉，只看返回码
        subprocess.run(
            [str(python_executable), "-c", check_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False

def create_venv_if_missing(venv_dir: Path):
    if not venv_dir.exists():
        print(f"[Bootstrap] Creating virtual environment at: {venv_dir}...", flush=True)
        venv.create(venv_dir, with_pip=True)

def install_dependencies(root_dir: Path, pip_executable: Path):
    req_path = root_dir / REQUIREMENTS_FILE
    base_cmd = [str(pip_executable), "install", "--disable-pip-version-check", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"]
    
    print(f"[Bootstrap] Installing dependencies...", flush=True)
    try:
        if req_path.exists():
            subprocess.run(base_cmd + ["-r", str(req_path)], check=True)
        else:
            subprocess.run(base_cmd + REQUIRED_PACKAGES, check=True)
    except subprocess.CalledProcessError:
        print(f"[Bootstrap] Error: Failed to install dependencies.", file=sys.stderr)
        sys.exit(1)

def restart_in_venv(python_executable: Path):
    """重启当前脚本到 venv 环境"""
    env = os.environ.copy()
    env["GRADER_BOOTSTRAPPED"] = "1"
    args = [str(python_executable)] + sys.argv
    
    if sys.platform == "win32":
        subprocess.run(args, env=env, check=True)
        sys.exit(0)
    else:
        os.execv(str(python_executable), args)

def initialize():
    # 1. Fast Path: 如果当前环境(无论是否venv)已经能用，直接通过
    try:
        for pkg in REQUIRED_IMPORTS:
            __import__(pkg)
        return
    except ImportError:
        pass

    root_dir = Path(__file__).parent.absolute()
    venv_dir, venv_python, venv_pip = get_venv_paths(root_dir)
    is_in_venv = os.environ.get("GRADER_BOOTSTRAPPED") == "1"

    # 2. 如果已经在 venv 里但还是缺包，说明环境坏了，强制修复
    if is_in_venv:
        print("[Bootstrap] In venv but dependencies missing. Repairing...", flush=True)
        install_dependencies(root_dir, venv_pip)
        return

    # 3. 如果在系统环境 (用户没激活 venv 直接跑脚本)
    #    逻辑：先检查 venv 是否存在且完好，如果是，直接重启进去，不要跑 install
    
    create_venv_if_missing(venv_dir)

    # === 关键优化点 ===
    # 只有当 venv 里的 python 无法导入指定包时，才运行 pip install
    if not check_venv_integrity(venv_python):
        install_dependencies(root_dir, venv_pip)
    # =================
    
    restart_in_venv(venv_python)
