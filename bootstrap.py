import os
import sys
import subprocess
import venv
import time
import urllib.request
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
VENV_DIR_NAME = ".venv"
REQUIREMENTS_FILE = "requirements.txt"
REQUIRED_IMPORTS = ["rich", "tomli"]
REQUIRED_PACKAGES = ["rich", "tomli"]

# 定义待测速的 PyPI 源列表
PYPI_MIRRORS = {
    "Official": "https://pypi.org/simple",
    "Tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "Aliyun": "https://mirrors.aliyun.com/pypi/simple",
    "Tencent": "https://mirrors.cloud.tencent.com/pypi/simple",
}
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
    """检查 venv 里的 Python 是否已经安装了必要的包。"""
    if not python_executable.exists():
        return False

    check_script = "; ".join([f"import {pkg}" for pkg in REQUIRED_IMPORTS])
    try:
        subprocess.run(
            [str(python_executable), "-c", check_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def create_venv_if_missing(venv_dir: Path):
    if not venv_dir.exists():
        print(f"[Bootstrap] Creating virtual environment at: {venv_dir}...", flush=True)
        venv.create(venv_dir, with_pip=True)


def test_mirror_latency(name, url, timeout=2):
    """测试单个镜像源的延迟"""
    start_time = time.time()
    try:
        # 使用 HEAD 请求或者极小的 GET 请求来测试连接
        # 标准库 urllib 发送请求
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                latency = (time.time() - start_time) * 1000  # ms
                return name, url, latency
    except Exception:
        pass
    return name, url, float("inf")


def get_fastest_mirror():
    """并发测试所有源，返回速度最快的源 URL"""
    print("[Bootstrap] Selecting the fastest PyPI mirror...", flush=True)
    
    fastest_url = None
    min_latency = float("inf")
    best_name = "Unknown"

    # 使用线程池并发测速，避免串行等待
    with ThreadPoolExecutor(max_workers=len(PYPI_MIRRORS)) as executor:
        futures = [
            executor.submit(test_mirror_latency, name, url) 
            for name, url in PYPI_MIRRORS.items()
        ]
        
        for future in as_completed(futures):
            name, url, latency = future.result()
            if latency < float("inf"):
                # print(f"  - {name}: {latency:.2f} ms") # 调试时可打开
                if latency < min_latency:
                    min_latency = latency
                    fastest_url = url
                    best_name = name

    if fastest_url:
        print(f"[Bootstrap] Selected {best_name} (Latency: {min_latency:.0f}ms)", flush=True)
        return fastest_url
    else:
        print("[Bootstrap] Warning: All mirrors check failed. Fallback to Official.", flush=True)
        return PYPI_MIRRORS["Official"]


def install_dependencies(root_dir: Path, pip_executable: Path):
    req_path = root_dir / REQUIREMENTS_FILE
    
    # === 获取最快源 ===
    mirror_url = get_fastest_mirror()
    # ================

    base_cmd = [
        str(pip_executable),
        "install",
        "--disable-pip-version-check",
        "-i",
        mirror_url, # 使用动态获取的源
    ]

    # 如果选中的不是官方源，通常需要信任该 host，避免 pip 报 SSL 警告
    if "pypi.org" not in mirror_url:
        from urllib.parse import urlparse
        hostname = urlparse(mirror_url).hostname
        base_cmd.extend(["--trusted-host", hostname])

    print("[Bootstrap] Installing dependencies...", flush=True)
    try:
        if req_path.exists():
            subprocess.run(base_cmd + ["-r", str(req_path)], check=True)
        else:
            subprocess.run(base_cmd + REQUIRED_PACKAGES, check=True)
    except subprocess.CalledProcessError:
        print("[Bootstrap] Error: Failed to install dependencies.", file=sys.stderr)
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
    # 1. Fast Path
    try:
        for pkg in REQUIRED_IMPORTS:
            __import__(pkg)
        return
    except ImportError:
        pass

    root_dir = Path(__file__).parent.absolute()
    venv_dir, venv_python, venv_pip = get_venv_paths(root_dir)
    is_in_venv = os.environ.get("GRADER_BOOTSTRAPPED") == "1"

    # 2. 修复损坏环境
    if is_in_venv:
        print("[Bootstrap] In venv but dependencies missing. Repairing...", flush=True)
        install_dependencies(root_dir, venv_pip)
        return

    # 3. 创建与首次安装
    create_venv_if_missing(venv_dir)

    if not check_venv_integrity(venv_python):
        install_dependencies(root_dir, venv_pip)

    restart_in_venv(venv_python)

# 示例用法，实际使用时这里可能是 main()
if __name__ == "__main__":
    initialize()
    # 下面写你的正常业务逻辑
    import rich
    print("[Success] Environment is ready!")
