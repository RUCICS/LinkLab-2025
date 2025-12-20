import argparse
import json
import os
import re
import subprocess
import sys
import time
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Tuple

# --- BOOTSTRAP: Auto-setup environment ---
import bootstrap

bootstrap.initialize()
# -----------------------------------------

import tomli  # noqa: E402
from rich.console import Console, RenderableType  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.progress import Progress, SpinnerColumn, Task, TextColumn  # noqa: E402
from rich.table import Table  # noqa: E402
from rich.text import Text  # noqa: E402


@dataclass
class TestResult:
    success: bool
    message: str
    time: float
    score: float
    max_score: float
    step_scores: List[Tuple[str, float, float]] = None
    error_details: Optional[List[Dict[str, Any]]] = None

    @property
    def status(self) -> str:
        if not self.success:
            return "FAIL"
        if self.score == self.max_score:
            return "PASS"
        return "PARTIAL"

    def to_dict(self):
        return {
            "success": self.success,
            "status": self.status,
            "message": self.message,
            "time": self.time,
            "score": self.score,
            "max_score": self.max_score,
            "step_scores": self.step_scores,
            "error_details": self.error_details,
        }


@dataclass
class TestCase:
    path: Path
    meta: Dict[str, Any]
    run_steps: List[Dict[str, Any]]


class Config:
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        config_path = self.project_root / "grader_config.toml"
        if not config_path.exists():
            return {
                "paths": {
                    "tests_dir": "tests",
                    "cases_dir": "tests/cases",
                    "common_dir": "tests/common",
                },
                "debug": {
                    "default_type": "gdb",  # or "lldb", "python"
                },
            }
        with open(config_path, "rb") as f:
            return tomli.load(f)

    @property
    def paths(self) -> Dict[str, Path]:
        return {
            "tests_dir": self.project_root / self._config["paths"]["tests_dir"],
            "cases_dir": self.project_root / self._config["paths"]["cases_dir"],
            "common_dir": self.project_root / self._config["paths"]["common_dir"],
        }

    @property
    def setup_steps(self) -> List[Dict[str, Any]]:
        return self._config.get("setup", {}).get("steps", [])

    @property
    def groups(self) -> Dict[str, List[str]]:
        """获取测试组配置"""
        return self._config.get("groups", {})

    @property
    def debug_config(self) -> Dict[str, Any]:
        """Get debug configuration from config file"""
        return self._config.get(
            "debug",
            {
                "default_type": "gdb",
            },
        )


class OutputChecker(Protocol):
    def check(
        self,
        step: Dict[str, Any],
        output: str,
        error: str,
        return_code: int,
        test_dir: Path,
    ) -> Tuple[bool, str, Optional[float]]:
        pass


class StandardOutputChecker:
    def check(
        self,
        step: Dict[str, Any],
        output: str,
        error: str,
        return_code: int,
        test_dir: Path,
    ) -> Tuple[bool, str, Optional[float]]:
        check = step.get("check", {})

        # 检查返回值
        if "return_code" in check and return_code != check["return_code"]:
            return (
                False,
                f"Expected return code {check['return_code']}, got {return_code}",
                None,
            )

        # 检查文件是否存在
        if "files" in check:
            for file_path in check["files"]:
                resolved_path = Path(self._resolve_path(file_path, test_dir))
                if not resolved_path.exists():
                    return False, f"Required file '{file_path}' not found", None

        # 检查标准输出
        if "stdout" in check:
            expect_file = test_dir / check["stdout"]
            if not expect_file.exists():
                return False, f"Expected output file {check['stdout']} not found", None
            with open(expect_file) as f:
                expected = f.read()
            if check.get("ignore_whitespace", False):
                output = " ".join(output.split())
                expected = " ".join(expected.split())
            if output.rstrip() != expected.rstrip():
                return False, "Output does not match expected content", None

        # 检查标准错误
        if "stderr" in check:
            expect_file = test_dir / check["stderr"]
            if not expect_file.exists():
                return False, f"Expected error file {check['stderr']} not found", None
            with open(expect_file) as f:
                expected = f.read()
            if check.get("ignore_whitespace", False):
                error = " ".join(error.split())
                expected = " ".join(expected.split())
            if error.rstrip() != expected.rstrip():
                return False, "Error output does not match expected content", None

        return True, "All checks passed", None

    def _resolve_path(self, path: str, test_dir: Path) -> str:
        build_dir = test_dir / "build"
        build_dir.mkdir(exist_ok=True)

        replacements = {
            "${test_dir}": str(test_dir),
            "${build_dir}": str(build_dir),
        }

        for var, value in replacements.items():
            path = path.replace(var, value)
        return path


class StatusSpinnerColumn(SpinnerColumn):
    """Spinner that swaps to a custom status icon when provided."""

    def render(self, task: Task) -> RenderableType:
        icon = task.fields.get("status_icon")
        if icon:
            return Text.from_markup(icon)
        return super().render(task)


class SpecialJudgeChecker:
    def check(
        self,
        step: Dict[str, Any],
        output: str,
        error: str,
        return_code: int,
        test_dir: Path,
    ) -> Tuple[bool, str, Optional[float]]:
        check = step.get("check", {})
        if "special_judge" not in check:
            return True, "No special judge specified", None

        judge_script = test_dir / check["special_judge"]
        if not judge_script.exists():
            return (
                False,
                f"Special judge script {check['special_judge']} not found",
                None,
            )

        input_data = {
            "stdout": output,
            "stderr": error,
            "return_code": return_code,
            "test_dir": str(test_dir),
            "max_score": step.get("score", 0),
        }

        try:
            process = subprocess.run(
                [sys.executable, str(judge_script)],
                input=json.dumps(input_data),
                capture_output=True,
                text=True,
            )
            result = json.loads(process.stdout)
            if "score" in result:
                result["score"] = min(result["score"], step.get("score", 0))
            return (
                result["success"],
                result.get("message", "No message provided"),
                result.get("score", None),
            )
        except Exception as e:
            return False, f"Special judge failed: {str(e)}", None


class PatternChecker:
    def check(
        self,
        step: Dict[str, Any],
        output: str,
        error: str,
        return_code: int,
        test_dir: Path,
    ) -> Tuple[bool, str, Optional[float]]:
        check = step.get("check", {})

        if "stdout_pattern" in check:
            if not re.search(check["stdout_pattern"], output, re.MULTILINE):
                return (
                    False,
                    f"Output does not match pattern {check['stdout_pattern']!r}",
                    None,
                )

        if "stderr_pattern" in check:
            if not re.search(check["stderr_pattern"], error, re.MULTILINE):
                return (
                    False,
                    f"Error output does not match pattern {check['stderr_pattern']!r}",
                    None,
                )

        return True, "All pattern checks passed", None


class CompositeChecker:
    def __init__(self):
        self.checkers = [
            StandardOutputChecker(),
            SpecialJudgeChecker(),
            PatternChecker(),
        ]

    def check(
        self,
        step: Dict[str, Any],
        output: str,
        error: str,
        return_code: int,
        test_dir: Path,
    ) -> Tuple[bool, str, Optional[float]]:
        for checker in self.checkers:
            success, message, score = checker.check(
                step, output, error, return_code, test_dir
            )
            if not success:
                return success, message, score
        return True, "All checks passed", None


class TestRunner:
    def __init__(
        self,
        config: Config,
        console: Optional[Console] = None,
        verbose: bool = False,
        dry_run: bool = False,
        no_check: bool = False,
    ):
        self.config = config
        self.console = console
        self.checker = CompositeChecker()
        self.verbose = verbose
        self.dry_run = dry_run
        self.no_check = no_check

    def run_test(self, test: TestCase) -> TestResult:
        start_time = time.perf_counter()
        try:
            # 清理和创建构建目录
            build_dir = test.path / "build"
            if build_dir.exists():
                for file in build_dir.iterdir():
                    if file.is_file():
                        file.unlink()
            build_dir.mkdir(exist_ok=True)

            # 在dry-run模式下，显示测试点信息
            if self.dry_run:
                if self.console and not isinstance(self.console, type):
                    self.console.print(f"[bold]Test case:[/bold] {test.meta['name']}")
                    if "description" in test.meta:
                        self.console.print(
                            f"[bold]Description:[/bold] {test.meta['description']}"
                        )
                return self._execute_test_steps(test)

            result = None
            if self.console and not isinstance(self.console, type):
                # 在 rich 环境下显示进度条
                status_icons = {
                    "PASS": "[green]✓[/green]",
                    "PARTIAL": "[yellow]~[/yellow]",
                    "FAIL": "[red]✗[/red]",
                }
                with Progress(
                    SpinnerColumn(finished_text=status_icons["FAIL"]),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console,
                ) as progress:
                    total_steps = len(test.run_steps)
                    task = progress.add_task(
                        f"Running {test.meta['name']} [0/{total_steps}]...",
                        total=total_steps,
                    )
                    result = self._execute_test_steps(test, progress, task)
                    # 根据状态设置图标
                    progress.columns[0].finished_text = status_icons[result.status]
                    # 更新最终状态，移除Running字样，加上结果提示
                    final_status = {
                        "PASS": "[green]Passed[/green]",
                        "PARTIAL": "[yellow]Partial[/yellow]",
                        "FAIL": "[red]Failed[/red]",
                    }[result.status]
                    progress.update(
                        task,
                        completed=total_steps,
                        description=f"{test.meta['name']} [{total_steps}/{total_steps}]: {final_status}",
                    )

                # 如果测试失败，在进度显示完成后输出失败信息
                if not result.success and not self.dry_run:
                    for error_details in result.error_details:
                        # 获取失败的步骤信息
                        step_index = error_details["step"]

                        self.console.print(
                            f"\n[red]Test '{test.meta['name']}' failed at step {step_index}:[/red]"
                        )
                        self.console.print(f"Command: {error_details['command']}")

                        if "stdout" in error_details:
                            self.console.print("\nActual output:")
                            self.console.print(error_details["stdout"].strip())

                        if "stderr" in error_details:
                            self.console.print("\nError output:")
                            self.console.print(error_details["stderr"].strip())

                        if "expected_output" in error_details:
                            self.console.print("\nExpected output:")
                            self.console.print(error_details["expected_output"])

                        if "error_message" in error_details:
                            self.console.print("\nError details:")
                            self.console.print(f"  {error_details['error_message']}")

                        if "return_code" in error_details:
                            self.console.print(
                                f"\nReturn code: {error_details['return_code']}"
                            )

                        self.console.print()  # 添加一个空行作为分隔
                return result
            else:
                # 在非 rich 环境下直接执行
                return self._execute_test_steps(test)
        except Exception as e:
            print(e)
            print(traceback.format_exc())
            return TestResult(
                success=False,
                message=f"Error: {str(e)}",
                time=time.perf_counter() - start_time,
                score=0,
                max_score=test.meta["score"],
            )

    def _execute_test_steps(
        self,
        test: TestCase,
        progress: Optional[Progress] = None,
        task: Optional[Any] = None,
    ) -> TestResult:
        start_time = time.perf_counter()
        step_scores = []
        total_score = 0
        has_step_scores = any("score" in step for step in test.run_steps)
        max_possible_score = (
            sum(step.get("score", 0) for step in test.run_steps)
            if has_step_scores
            else test.meta["score"]
        )
        steps_error_details = []

        for i, step in enumerate(test.run_steps, 1):
            if progress is not None and task is not None:
                step_name = step.get("name", step["command"])
                progress.update(
                    task,
                    description=f"Running {test.meta['name']} [{i}/{len(test.run_steps)}]: {step_name}",
                    completed=i - 1,
                )

            result = self._execute_single_step(test, step, i)
            if not result.success and not self.dry_run:
                steps_error_details.append(result.error_details)
                if progress is not None and task is not None:
                    progress.update(task, completed=i)
                if step.get("must_pass", True):
                    # 返回包含所有已收集的错误详情的结果
                    return TestResult(
                        success=False,
                        message=result.message,
                        time=time.perf_counter() - start_time,
                        score=total_score,
                        max_score=max_possible_score,
                        step_scores=step_scores,
                        error_details=steps_error_details,
                    )
            total_score += result.score
            if result.step_scores:
                step_scores.extend(result.step_scores)

            if progress is not None and task is not None:
                progress.update(
                    task,
                    description=f"Running {test.meta['name']} [{i}/{len(test.run_steps)}]: {step_name}",
                    completed=i,
                )

        # 如果有分步给分，确保总分不超过测试用例的总分
        if has_step_scores:
            total_score = min(total_score, test.meta["score"])
        else:
            total_score = test.meta["score"]
            step_scores = None

        success = True if self.dry_run else total_score > 0
        return TestResult(
            success=success,
            message="All steps completed" if success else "Some steps failed",
            time=time.perf_counter() - start_time,
            score=total_score,
            max_score=max_possible_score,
            step_scores=step_scores,
            error_details=steps_error_details if steps_error_details else None,
        )

    def _execute_single_step(
        self, test: TestCase, step: Dict[str, Any], step_index: int
    ) -> TestResult:
        start_time = time.perf_counter()

        # 在dry-run模式下，只打印命令
        if self.dry_run:
            cmd = [self._resolve_path(step["command"], test.path)]
            args = [
                self._resolve_path(str(arg), test.path) for arg in step.get("args", [])
            ]
            if self.console and not isinstance(self.console, type):
                self.console.print(f"\n[bold cyan]Step {step_index}:[/bold cyan]")
                if "name" in step:
                    self.console.print(f"[bold]Name:[/bold] {step['name']}")
                self.console.print(f"[bold]Command:[/bold] {' '.join(cmd + args)}")
                if "stdin" in step:
                    self.console.print(f"[bold]Input file:[/bold] {step['stdin']}")
                if "check" in step and not self.no_check:
                    self.console.print("[bold]Checks:[/bold]")
                    for check_type, check_value in step["check"].items():
                        if check_type == "files":
                            check_value = [
                                self._resolve_path(file, test.path)
                                for file in check_value
                            ]

                        self.console.print(f"  - {check_type}: {check_value}")
            return TestResult(
                success=True,
                message="Dry run",
                time=time.perf_counter() - start_time,
                score=0,
                max_score=0,
            )

        # 获取相对于测试目录的命令路径
        cmd = [self._resolve_path(step["command"], test.path, test.path)]
        args = [
            self._resolve_path(str(arg), test.path, test.path)
            for arg in step.get("args", [])
        ]

        # 构建环境变量
        step_env = os.environ.copy()
        if "env" in step:
            for key, value in step["env"].items():
                step_env[key] = self._resolve_path(str(value), test.path, test.path)

        try:
            process = subprocess.run(
                cmd + args,
                cwd=test.path,
                input=self._get_stdin_data(test, step),
                capture_output=True,
                text=True,
                timeout=step.get("timeout", 5.0),
                env=step_env,
            )

            # 如果启用了详细输出模式
            if self.verbose and self.console and not isinstance(self.console, type):
                self.console.print(f"[bold cyan]Step {step_index} Output:[/bold cyan]")
                self.console.print("[bold]Command:[/bold]", " ".join(cmd + args))
                if process.stdout:
                    self.console.print("[bold]Standard Output:[/bold]")
                    self.console.print(process.stdout)
                if process.stderr:
                    self.console.print("[bold]Standard Error:[/bold]")
                    self.console.print(process.stderr)
                self.console.print(f"[bold]Return Code:[/bold] {process.returncode}\n")

        except subprocess.TimeoutExpired:
            return self._create_timeout_result(test, step, step_index, start_time)

        # 在no_check模式下，只要命令执行成功就认为通过
        if self.no_check:
            return self._create_success_result(
                test,
                step,
                step.get("score", test.meta["score"]) if process.returncode == 0 else 0,
                start_time,
            )

        if "check" in step:
            success, message, score = self.checker.check(
                step,
                process.stdout,
                process.stderr,
                process.returncode,
                test.path,
            )

            if not success:
                return self._create_failure_result(
                    test,
                    step,
                    step_index,
                    message,
                    start_time,
                    process.stdout,
                    process.stderr,
                    process.returncode,
                    process.stdout
                    if "expected_output" in step.get("check", {})
                    else "",
                )

        return self._create_success_result(test, step, score, start_time)

    def _resolve_relative_path(self, path: str, cwd: Path = Path.cwd()) -> str:
        result = path
        if isinstance(path, Path):
            result = str(path.resolve())

        try:
            result = str(path.relative_to(cwd, walk_up=True))
        except:
            try:
                result = str(path.relative_to(cwd))
            except:
                result = str(path)

        if len(result) > len(str(path)):
            result = str(path)

        return result

    def _resolve_path(self, path: str, test_dir: Path, cwd: Path = Path.cwd()) -> str:
        build_dir = test_dir / "build"
        build_dir.mkdir(exist_ok=True)

        replacements = {
            "${test_dir}": self._resolve_relative_path(test_dir, cwd),
            "${common_dir}": self._resolve_relative_path(
                self.config.paths["common_dir"], cwd
            ),
            "${root_dir}": self._resolve_relative_path(self.config.project_root, cwd),
            "${build_dir}": self._resolve_relative_path(build_dir, cwd),
        }

        for var, value in replacements.items():
            path = path.replace(var, value)

        return path

    def _get_stdin_data(self, test: TestCase, step: Dict[str, Any]) -> Optional[str]:
        if "stdin" not in step:
            return None

        stdin_file = test.path / step["stdin"]
        if not stdin_file.exists():
            raise FileNotFoundError(f"Input file {step['stdin']} not found")

        with open(stdin_file) as f:
            return f.read()

    def _create_timeout_result(
        self, test: TestCase, step: Dict[str, Any], step_index: int, start_time: float
    ) -> TestResult:
        error_message = f"Step {step_index} '{step.get('name', step['command'])}' timed out after {step.get('timeout', 5.0)}s"
        # 构造命令字符串
        cmd = [self._resolve_path(step["command"], test.path, os.getcwd())]
        if "args" in step:
            cmd.extend(
                [
                    self._resolve_path(str(arg), test.path, os.getcwd())
                    for arg in step.get("args", [])
                ]
            )
        command_str = " ".join(cmd)
        return TestResult(
            success=False,
            message=error_message,
            time=time.perf_counter() - start_time,
            score=0,
            max_score=step.get("score", test.meta["score"]),
            error_details={
                "step": step_index,
                "step_name": step.get("name", step["command"]),
                "error_message": error_message,
                "command": command_str,  # 添加实际运行的命令
            },
        )

    def _create_failure_result(
        self,
        test: TestCase,
        step: Dict[str, Any],
        step_index: int,
        message: str,
        start_time: float,
        stdout: str = "",
        stderr: str = "",
        return_code: Optional[int] = None,
        expected_output: str = "",
    ) -> TestResult:
        # 构造命令字符串
        cmd = [self._resolve_path(step["command"], test.path, os.getcwd())]
        if "args" in step:
            cmd.extend(
                [
                    self._resolve_path(str(arg), test.path, os.getcwd())
                    for arg in step.get("args", [])
                ]
            )
        command_str = " ".join(cmd)

        error_details = {
            "step": step_index,
            "step_name": step.get("name", step["command"]),
            "error_message": message,
            "command": command_str,  # 添加实际运行的命令
        }
        if stdout:
            error_details["stdout"] = stdout
        if stderr:
            error_details["stderr"] = stderr
        if return_code is not None:
            error_details["return_code"] = return_code
        if expected_output:
            error_details["expected_output"] = expected_output

        return TestResult(
            success=False,
            message=f"Step {step_index} '{step.get('name', step['command'])}' failed: {message}",
            time=time.perf_counter() - start_time,
            score=0,
            max_score=step.get("score", test.meta["score"]),
            error_details=error_details,
        )

    def _create_success_result(
        self,
        test: TestCase,
        step: Dict[str, Any],
        score: Optional[float],
        start_time: float,
    ) -> TestResult:
        step_score = score if score is not None else step.get("score", 0)
        return TestResult(
            success=True,
            message="Step completed successfully",
            time=time.perf_counter() - start_time,
            score=step_score,
            max_score=step.get("score", test.meta["score"]),
            step_scores=[
                (step.get("name", step["command"]), step_score, step.get("score", 0))
            ]
            if step.get("score", 0) > 0
            else None,
        )


class ResultFormatter(ABC):
    @abstractmethod
    def format_results(
        self,
        test_cases: List[TestCase],
        results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        pass


class JsonFormatter(ResultFormatter):
    def format_results(
        self,
        test_cases: List[TestCase],
        results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        json_result = {
            "total_score": round(total_score, 1),
            "max_score": round(max_score, 1),
            "percentage": round(total_score / max_score * 100, 1),
            "tests": results,
        }
        print(json.dumps(json_result, ensure_ascii=False))


class TableFormatter(ResultFormatter):
    def __init__(self, console: Console):
        self.console = console

    def format_results(
        self,
        test_cases: List[TestCase],
        results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        self._format_rich_table(test_cases, results, total_score, max_score)

    def _format_rich_table(
        self,
        test_cases: List[TestCase],
        results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        table = Table(show_header=True, header_style="bold")
        table.add_column("Test Case", style="cyan")
        table.add_column("Result", justify="center")
        table.add_column("Time", justify="right")
        table.add_column("Score", justify="right")
        table.add_column("Message")

        status_style = {
            "PASS": "[green]PASS[/green]",
            "PARTIAL": "[yellow]PARTIAL[/yellow]",
            "FAIL": "[red]FAIL[/red]",
        }

        for test, result in zip(test_cases, results):
            table.add_row(
                test.meta["name"],
                status_style[result["status"]],
                f"{result['time']:.2f}s",
                f"{result['score']:.1f}/{result['max_score']:.1f}",
                result["message"],
            )

        self.console.print(table)
        self._print_summary(total_score, max_score)

    def _format_basic_table(
        self,
        test_cases: List[TestCase],
        results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        # 定义列宽
        col_widths = {
            "name": max(len(test.meta["name"]) for test in test_cases),
            "status": 8,  # PASS/PARTIAL/FAIL
            "time": 10,  # XX.XXs
            "score": 15,  # XX.X/XX.X
            "message": 40,
        }

        # 打印表头
        header = (
            f"{'Test Case':<{col_widths['name']}} "
            f"{'Result':<{col_widths['status']}} "
            f"{'Time':>{col_widths['time']}} "
            f"{'Score':>{col_widths['score']}} "
            f"{'Message':<{col_widths['message']}}"
        )
        self.console.print("-" * len(header))
        self.console.print(header)
        self.console.print("-" * len(header))

        # 打印每一行
        status_text = {
            "PASS": "PASS",
            "PARTIAL": "PARTIAL",
            "FAIL": "FAIL",
        }

        for test, result in zip(test_cases, results):
            row = (
                f"{test.meta['name']:<{col_widths['name']}} "
                f"{status_text[result['status']]:<{col_widths['status']}} "
                f"{result['time']:.2f}s".rjust(col_widths["time"])
                + f" {result['score']:.1f}/{result['max_score']}".rjust(
                    col_widths["score"]
                )
                + " "
                f"{result['message'][: col_widths['message']]:<{col_widths['message']}}"
            )
            self.console.print(row)

        self.console.print("-" * len(header))
        self._print_basic_summary(total_score, max_score)

    def _print_summary(self, total_score: float, max_score: float) -> None:
        summary = Panel(
            f"[bold]Total Score: {total_score:.1f}/{max_score:.1f} "
            f"({total_score / max_score * 100:.1f}%)[/bold]",
            border_style="green" if total_score == max_score else "yellow",
        )
        self.console.print()
        self.console.print(summary)
        self.console.print()

    def _print_basic_summary(self, total_score: float, max_score: float) -> None:
        self.console.print()
        self.console.print(
            f"Total Score: {total_score:.1f}/{max_score:.1f} "
            f"({total_score / max_score * 100:.1f}%)"
        )
        self.console.print()


class VSCodeConfigGenerator:
    """Generate and manage VS Code debug configurations"""

    def __init__(self, project_root: Path, config: Config, verbose: bool = False):
        self.project_root = project_root
        self.config = config
        self.verbose = verbose
        self.vscode_dir = project_root / ".vscode"
        self.launch_file = self.vscode_dir / "launch.json"
        self.tasks_file = self.vscode_dir / "tasks.json"

    def generate_configs(
        self, failed_steps: List[Tuple[TestCase, Dict[str, Any]]], merge: bool = True
    ) -> None:
        """Generate VS Code configurations for debugging a failed test step"""
        self.vscode_dir.mkdir(exist_ok=True)

        launch_config = []
        tasks_config = []

        for test_case, failed_step in failed_steps:
            launch_config.extend(self._generate_launch_config(test_case, failed_step))
            tasks_config.extend(self._generate_tasks_config(test_case))

        launch_config = {"version": "0.2.0", "configurations": launch_config}
        tasks_config = {"version": "2.0.0", "tasks": tasks_config}

        self._write_or_merge_json(
            self.launch_file, launch_config, "configurations", merge
        )

        self._write_or_merge_json(self.tasks_file, tasks_config, "tasks", merge)

    def _generate_launch_config(
        self, test_case: TestCase, failed_step: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate launch configuration based on debug type"""
        target_step = failed_step

        if "debug_step" in failed_step:
            step_name = failed_step["debug_step"]
            # 在测试步骤中查找匹配名字的步骤
            found_step = next(
                (s for s in test_case.run_steps if s.get("name") == step_name), None
            )

            if found_step:
                if self.verbose:
                    print(
                        f"Step '{failed_step.get('name')}' failed. Using debug step '{step_name}'."
                    )

                target_step = found_step
            else:
                print(f"Warning: debug step '{step_name}' not found in steps.")

        debug_type = (
            target_step.get("debug", {}).get("type")
            or test_case.meta.get("debug", {}).get("type")
            or self.config.debug_config["default_type"]
        )

        cwd = str(self.config.project_root)
        program = self._resolve_path(
            target_step["command"], test_case.path, self.config.project_root
        )
        args = [
            self._resolve_path(arg, test_case.path, self.config.project_root)
            for arg in target_step.get("args", [])
        ]

        if debug_type == "cpp":
            configs = []
            base_name = f"Debug {test_case.meta['name']} - Step {target_step.get('name', 'failed step')}"

            # Add GDB configuration
            configs.append(
                {
                    "name": f"{base_name} (GDB)",
                    "type": "cppdbg",
                    "request": "launch",
                    "program": program,
                    "args": args,
                    "stopOnEntry": True,
                    "cwd": cwd,
                    "environment": [],
                    "internalConsoleOptions": "neverOpen",
                    "MIMode": "gdb",
                    "setupCommands": [
                        {
                            "description": "Enable pretty-printing for gdb",
                            "text": "-enable-pretty-printing",
                            "ignoreFailures": True,
                        }
                    ],
                    "preLaunchTask": f"build-{test_case.path.name}",
                }
            )

            # Add LLDB configuration
            configs.append(
                {
                    "name": f"{base_name} (LLDB)",
                    "type": "lldb",
                    "request": "launch",
                    "program": program,
                    "args": args,
                    "cwd": cwd,
                    "internalConsoleOptions": "neverOpen",
                    "preLaunchTask": f"build-{test_case.path.name}",
                }
            )

            return configs
        elif debug_type == "python":
            return [
                {
                    "name": f"Debug {test_case.meta['name']} - Step {target_step.get('name', 'failed step')}",
                    "type": "python",
                    "request": "launch",
                    "program": program,
                    "args": args,
                    "cwd": cwd,
                    "env": {},
                    "console": "integratedTerminal",
                    "justMyCode": False,
                    "preLaunchTask": f"build-{test_case.path.name}",
                }
            ]
        else:
            raise ValueError(f"Unsupported debug type: {debug_type}")

    def _generate_tasks_config(self, test_case: TestCase) -> List[Dict[str, Any]]:
        """Generate tasks configuration for building the test case"""
        return [
            {
                "label": f"build-{test_case.path.name}",
                "type": "shell",
                "command": "python3",
                "args": ["grader.py", "--no-check", test_case.path.name],
                "group": {"kind": "build", "isDefault": True},
                "presentation": {"panel": "shared"},
                "options": {"env": {"DEBUG": "1"}},
            }
        ]

    def _write_or_merge_json(
        self,
        file_path: Path,
        new_config: Dict[str, Any],
        merge_key: str,
        should_merge: bool,
    ) -> None:
        """Write or merge JSON configuration file, overriding items with the same name."""
        # Add comment to mark auto-generated configurations
        if merge_key == "configurations":
            for config in new_config[merge_key]:
                config["name"] = f"{config['name']} [Auto-generated]"
                config["preLaunchTask"] = f"{config['preLaunchTask']} [Auto-generated]"
        elif merge_key == "tasks":
            for task in new_config[merge_key]:
                task["label"] = f"{task['label']} [Auto-generated]"

        if file_path.exists() and should_merge:
            try:
                with open(file_path) as f:
                    existing_config = json.load(f)

                # Merge configurations
                if merge_key in existing_config:
                    # Create a dictionary to map names to their items for quick lookup
                    existing_items_map = {
                        item[
                            "name" if merge_key == "configurations" else "label"
                        ].replace(" [Auto-generated]", ""): item
                        for item in existing_config[merge_key]
                    }

                    # Update existing items or add new items
                    for new_item in new_config[merge_key]:
                        item_key = new_item[
                            "name" if merge_key == "configurations" else "label"
                        ].replace(" [Auto-generated]", "")
                        existing_items_map[item_key] = new_item

                    # Rebuild the list from the updated map
                    existing_config[merge_key] = list(existing_items_map.values())
                else:
                    existing_config[merge_key] = new_config[merge_key]

                config_to_write = existing_config
            except json.JSONDecodeError:
                config_to_write = new_config
        else:
            config_to_write = new_config

        with open(file_path, "w") as f:
            json.dump(config_to_write, f, indent=4)

    def _resolve_relative_path(self, path: str, cwd: Path = Path.cwd()) -> str:
        result = path
        if isinstance(path, Path):
            result = str(path.resolve())

        try:
            result = str(path.relative_to(cwd, walk_up=True))
        except:
            try:
                result = str(path.relative_to(cwd))
            except:
                result = str(path)

        if len(result) > len(str(path)):
            result = str(path)

        return result

    def _resolve_path(self, path: str, test_dir: Path, cwd: Path = Path.cwd()) -> str:
        build_dir = test_dir / "build"
        build_dir.mkdir(exist_ok=True)

        replacements = {
            "${test_dir}": self._resolve_relative_path(test_dir, cwd),
            "${common_dir}": self._resolve_relative_path(
                self.config.paths["common_dir"], cwd
            ),
            "${root_dir}": self._resolve_relative_path(self.config.project_root, cwd),
            "${build_dir}": self._resolve_relative_path(build_dir, cwd),
        }

        for var, value in replacements.items():
            path = path.replace(var, value)

        return path


class Grader:
    def __init__(
        self,
        verbose=False,
        json_output=False,
        dry_run=False,
        no_check=False,
        generate_vscode=False,
        vscode_no_merge=False,
    ):
        self.config = Config(Path.cwd())
        self.verbose = verbose
        self.json_output = json_output
        self.dry_run = dry_run
        self.no_check = no_check
        self.generate_vscode = generate_vscode
        self.vscode_no_merge = vscode_no_merge
        self.console = Console(quiet=json_output)
        self.runner = TestRunner(
            self.config,
            self.console,
            verbose=self.verbose,
            dry_run=self.dry_run,
            no_check=self.no_check,
        )
        self.formatter = (
            JsonFormatter() if json_output else TableFormatter(self.console)
        )
        self.results: Dict[str, TestResult] = {}
        self.vscode_generator = VSCodeConfigGenerator(Path.cwd(), self.config, verbose=self.verbose)

    def _save_test_history(
        self,
        test_cases: List[TestCase],
        test_results: List[Dict[str, Any]],
        total_score: float,
        max_score: float,
    ) -> None:
        """保存测试历史到隐藏文件"""
        history_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "total_score": round(total_score, 1),
            "max_score": round(max_score, 1),
            "percentage": round(total_score / max_score * 100, 1)
            if max_score > 0
            else 0,
            "tests": [],
        }

        for test, result in zip(test_cases, test_results):
            test_data = {
                "name": test.meta["name"],
                "description": test.meta.get("description", ""),
                "path": str(test.path),
                "build_path": str(test.path / "build"),
                "score": result["score"],
                "max_score": result["max_score"],
                "status": result["status"],
                "time": result["time"],
                "message": result["message"],
                "step_scores": result["step_scores"],
            }

            # 如果测试失败，添加详细的错误信息
            if not result["success"] and result["error_details"]:
                error_details = result["error_details"][0]
                test_data["error_details"] = {
                    "step": error_details["step"],
                    "step_name": error_details["step_name"],
                    "error_message": error_details["error_message"],
                    "command": error_details.get("command", ""),  # 添加实际运行的命令
                }
                if "stdout" in error_details:
                    test_data["error_details"]["stdout"] = error_details["stdout"]
                if "stderr" in error_details:
                    test_data["error_details"]["stderr"] = error_details["stderr"]
                if "return_code" in error_details:
                    test_data["error_details"]["return_code"] = error_details[
                        "return_code"
                    ]

            history_data["tests"].append(test_data)

        try:
            # 读取现有历史记录（如果存在）
            history_file = Path(".test_history")
            if history_file.exists():
                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                # 限制历史记录数量为最近10次
                history = history[-9:]
            else:
                history = []

            # 添加新的测试记录
            history.append(history_data)

            # 保存更新后的历史记录
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)

        except Exception as e:
            if not self.json_output:
                self.console.print(
                    f"[yellow]Warning:[/yellow] Failed to save test history: {str(e)}"
                )

    def _print_debug_instructions(
        self, test_case: TestCase, failed_step: Dict[str, Any]
    ) -> None:
        """Print instructions for debugging the failed test case"""
        if self.json_output:
            return

        debug_type = (
            failed_step.get("debug", {}).get("type")
            or test_case.meta.get("debug", {}).get("type")
            or self.config.debug_config["default_type"]
        )

        self.console.print("\n[bold]Debug Instructions:[/bold]")
        self.console.print("1. VS Code configurations have been generated/updated:")
        self.console.print("   - .vscode/launch.json: Debug configurations")
        self.console.print("   - .vscode/tasks.json: Build tasks")
        self.console.print("\n2. To debug the failed step:")
        self.console.print("   a. Open VS Code in the project root directory")
        self.console.print("   b. Install required extensions:")
        if debug_type in ["gdb", "lldb"]:
            self.console.print("      - C/C++: ms-vscode.cpptools")
        elif debug_type == "python":
            self.console.print("      - Python: ms-python.python")
        self.console.print("   c. Press F5 or use the Run and Debug view")
        self.console.print(
            "   d. Select the auto-generated configuration for this test"
        )
        self.console.print("\n3. Debug features available:")
        self.console.print("   - Set breakpoints (F9)")
        self.console.print("   - Step over (F10)")
        self.console.print("   - Step into (F11)")
        self.console.print("   - Step out (Shift+F11)")
        self.console.print("   - Continue (F5)")
        self.console.print("   - Inspect variables in the Variables view")
        self.console.print("   - Use Debug Console for expressions")
        self.console.print(
            "\nNote: The test will be automatically rebuilt before debugging starts"
        )

    def _collect_failed_steps(
        self,
    ) -> List[Tuple[TestCase, Dict[str, Any], Dict[str, Any]]]:
        """收集所有失败的测试步骤"""
        failed_steps = []
        for test_name, result in self.results.items():
            if not result.success and result.error_details:
                test_case = next(
                    test
                    for test in self._load_test_cases()
                    if test.path.name == test_name
                )
                # 处理所有失败步骤的错误信息
                error_details_list = (
                    result.error_details
                    if isinstance(result.error_details, list)
                    else [result.error_details]
                )
                for error_details in error_details_list:
                    step_index = error_details["step"]
                    failed_step = test_case.run_steps[step_index - 1]
                    failed_steps.append((test_case, failed_step, error_details))
        return failed_steps

    def _generate_debug_configs(self) -> None:
        """为所有失败的测试步骤生成调试配置"""
        if not self.generate_vscode:
            return

        failed_steps = self._collect_failed_steps()
        if not failed_steps:
            return

        try:
            self.vscode_generator.generate_configs(
                [
                    (test_case, failed_step)
                    for test_case, failed_step, _ in failed_steps
                ],
                merge=not self.vscode_no_merge,
            )

            if not self.json_output and failed_steps:
                self._print_debug_instructions(failed_steps[0][0], failed_steps[0][1])
                if len(failed_steps) > 1:
                    self.console.print(
                        f"\n[yellow]Note:[/yellow] Debug configurations have been generated for {len(failed_steps)} failed steps."
                    )
        except Exception as e:
            if not self.json_output:
                self.console.print(
                    f"\n[red]Failed to generate VS Code configurations:[/red] {str(e)}"
                )

    def run_all_tests(
        self,
        specific_test: Optional[str] = None,
        prefix_match: bool = False,
        group: Optional[str] = None,
        specific_paths: Optional[List[Path]] = None,
    ):
        try:
            if not self._run_setup_steps():
                sys.exit(1)

            test_cases = self._load_test_cases(
                specific_test, prefix_match, group, specific_paths
            )
            if not self.json_output:
                if self.dry_run:
                    self.console.print(
                        "\n[bold]Dry-run mode enabled. Only showing commands.[/bold]\n"
                    )
                elif group and test_cases:
                    matched_group = next(
                        g
                        for g in self.config.groups
                        if g.lower().startswith(group.lower())
                    )
                    self.console.print(
                        f"\n[bold]Running {len(test_cases)} test cases in group {matched_group}...[/bold]\n"
                    )
                else:
                    self.console.print(
                        f"\n[bold]Running {len(test_cases)} test cases...[/bold]\n"
                    )

            total_score = 0
            max_score = 0
            test_results = []

            for test in test_cases:
                try:
                    result = self.runner.run_test(test)
                except Exception as e:
                    if not self.json_output:
                        self.console.print(
                            f"[red]Error:[/red] Grader script error while running test '{test.meta['name']}': {str(e)}"
                        )
                    else:
                        print(
                            f"Error: Grader script error while running test '{test.meta['name']}': {str(e)}",
                            file=sys.stderr,
                        )
                    sys.exit(1)

                self.results[test.path.name] = result
                result_dict = {
                    "name": test.meta["name"],
                    "success": result.success,
                    "status": result.status,
                    "time": round(result.time, 2),
                    "score": result.score,
                    "max_score": result.max_score,
                    "step_scores": result.step_scores,
                    "message": result.message,
                    "error_details": result.error_details,
                }
                test_results.append(result_dict)
                total_score += result.score
                max_score += result.max_score

            if not self.dry_run:
                self.formatter.format_results(
                    test_cases, test_results, total_score, max_score
                )

                self._save_test_history(
                    test_cases, test_results, total_score, max_score
                )

                # 在所有测试完成后生成调试配置
                self._generate_debug_configs()

            return total_score, max_score

        except Exception as e:
            print(e)
            print(traceback.format_exc())
            if not self.json_output:
                self.console.print(f"[red]Error:[/red] Grader script error: {str(e)}")
            else:
                print(f"Error: Grader script error: {str(e)}", file=sys.stderr)
            sys.exit(1)

    def _run_setup_steps(self) -> bool:
        if not self.config.setup_steps:
            return True

        if self.console and not isinstance(self.console, type):
            spinner_column = StatusSpinnerColumn()
            with Progress(
                spinner_column,
                TextColumn("[progress.description]{task.description}", markup=True),
                console=self.console,
            ) as progress:
                total_steps = len(self.config.setup_steps)
                task = progress.add_task(
                    f"Running setup steps [0/{total_steps}]...",
                    total=total_steps,
                    status_icon="",
                )

                for i, step in enumerate(self.config.setup_steps, 1):
                    step_label = step.get("name") or step.get("command") or "Setup step"
                    running_text = step.get("message") or f"Running {step_label}..."
                    success_text = (
                        step.get("success_message") or f"{step_label} completed"
                    )
                    failure_text = step.get("failure_message") or f"{step_label} failed"
                    step_prefix = f"Running setup steps [{i}/{total_steps}]: "
                    progress.update(
                        task,
                        description=f"{step_prefix}{running_text}",
                        completed=i - 1,
                        status_icon="",
                    )

                    if not self._run_setup_step(step):
                        progress.update(
                            task,
                            description=f"{step_prefix}{failure_text}",
                            completed=i,
                            status_icon="[red]✗[/red]",
                        )
                        return False

                    progress.update(
                        task,
                        description=f"{step_prefix}{success_text}",
                        completed=i,
                        status_icon="[green]✓[/green]",
                    )
                return True
        else:
            for step in self.config.setup_steps:
                if not self._run_setup_step(step):
                    return False
            return True

    def _run_setup_step(self, step: Dict[str, Any]) -> bool:
        try:
            if step["type"] != "command":
                if not self.json_output:
                    self.console.print(
                        f"[red]Error:[/red] Unknown setup step type: {step['type']}"
                    )
                return False

            cmd = [step["command"]]
            if "args" in step:
                args = step["args"]
                if isinstance(args, (list, tuple)):
                    cmd.extend(str(arg) for arg in args)
                elif args is not None:
                    cmd.append(str(args))

            process = subprocess.run(
                cmd,
                cwd=self.config.project_root,
                capture_output=True,
                text=True,
                timeout=step.get("timeout", 5.0),
            )

            if process.returncode != 0:
                if not self.json_output:
                    self.console.print("[red]Error:[/red] Command failed:")
                    self.console.print(process.stderr)
                return False

            return True

        except Exception as e:
            if not self.json_output:
                self.console.print(f"[red]Error:[/red] Command failed: {str(e)}")
            return False

    def _load_test_cases(
        self,
        specific_test: Optional[str] = None,
        prefix_match: bool = False,
        group: Optional[str] = None,
        specific_paths: Optional[List[Path]] = None,
    ) -> List[TestCase]:
        # 如果指定了具体的测试路径，直接加载这些测试
        if specific_paths:
            test_cases = []
            for test_path in specific_paths:
                if test_path.is_dir() and (test_path / "config.toml").exists():
                    test_cases.append(self._load_single_test(test_path))
            if not test_cases:
                if not self.json_output:
                    self.console.print(
                        "[red]Error:[/red] No valid test cases found in specified paths"
                    )
                else:
                    print(
                        "Error: No valid test cases found in specified paths",
                        file=sys.stderr,
                    )
                sys.exit(1)
            return test_cases

        # 如果指定了组，则从组配置中获取测试点列表
        if group:
            # 查找匹配的组名
            matching_groups = []
            for group_name in self.config.groups:
                if group_name.lower().startswith(group.lower()):
                    matching_groups.append(group_name)

            if not matching_groups:
                if not self.json_output:
                    self.console.print(
                        f"[red]Error:[/red] No group matching '{group}' found in config"
                    )
                else:
                    print(
                        f"Error: No group matching '{group}' found in config",
                        file=sys.stderr,
                    )
                sys.exit(1)
            elif len(matching_groups) > 1:
                if not self.json_output:
                    message = (
                        f"[yellow]Warning:[/yellow] Multiple groups match '{group}':"
                        if prefix_match and specific_test.isdigit()
                        else f"[yellow]Warning:[/yellow] Multiple test cases start with '{specific_test}':"
                    )
                    self.console.print(message)
                    for g in matching_groups:
                        self.console.print(f"  - {g}")
                    self.console.print("Please be more specific in your group name.")
                else:
                    message = (
                        f"Error: Multiple groups match '{group}'"
                        if prefix_match and specific_test.isdigit()
                        else f"Error: Multiple test cases start with '{specific_test}'"
                    )
                    print(message, file=sys.stderr)
                sys.exit(1)

            group = matching_groups[0]
            test_cases = []
            for test_id in self.config.groups[group]:
                cases = self._load_test_cases(test_id, True)
                test_cases.extend(cases)

            if not test_cases:
                if not self.json_output:
                    self.console.print(
                        f"[red]Error:[/red] No test cases found in group '{group}'"
                    )
                else:
                    print(
                        f"Error: No test cases found in group '{group}'",
                        file=sys.stderr,
                    )
                sys.exit(1)

            return test_cases

        if specific_test:
            # 获取所有匹配的测试目录
            matching_tests = []
            for test_dir in self.config.paths["cases_dir"].iterdir():
                if test_dir.is_dir() and (test_dir / "config.toml").exists():
                    if prefix_match and specific_test.isdigit():
                        # 使用数字前缀精确匹配模式
                        prefix_match = re.match(r"^(\d+)", test_dir.name)
                        if prefix_match and prefix_match.group(1) == specific_test:
                            matching_tests.append(test_dir)
                    else:
                        # 使用常规的开头匹配
                        if test_dir.name.lower().startswith(specific_test.lower()):
                            matching_tests.append(test_dir)

            if not matching_tests:
                if not self.json_output:
                    message = (
                        f"[red]Error:[/red] No test cases with prefix number '{specific_test}' found"
                        if prefix_match and specific_test.isdigit()
                        else f"[red]Error:[/red] No test cases starting with '{specific_test}' found"
                    )
                    self.console.print(message)
                else:
                    message = (
                        f"Error: No test cases with prefix number '{specific_test}' found"
                        if prefix_match and specific_test.isdigit()
                        else f"Error: No test cases starting with '{specific_test}' found"
                    )
                    print(message, file=sys.stderr)
                sys.exit(1)
            elif len(matching_tests) > 1:
                # 如果找到多个匹配项，列出所有匹配的测试用例
                if not self.json_output:
                    message = (
                        f"[yellow]Warning:[/yellow] Multiple test cases have prefix number '{specific_test}':"
                        if prefix_match and specific_test.isdigit()
                        else f"[yellow]Warning:[/yellow] Multiple test cases start with '{specific_test}':"
                    )
                    self.console.print(message)
                    for test_dir in matching_tests:
                        config = tomli.load(open(test_dir / "config.toml", "rb"))
                        self.console.print(
                            f"  - {test_dir.name}: {config['meta']['name']}"
                        )
                    self.console.print(
                        "Please be more specific in your test case name."
                    )
                else:
                    message = (
                        f"Error: Multiple test cases have prefix number '{specific_test}'"
                        if prefix_match and specific_test.isdigit()
                        else f"Error: Multiple test cases start with '{specific_test}'"
                    )
                    print(message, file=sys.stderr)
                sys.exit(1)

            return [self._load_single_test(matching_tests[0])]

        if not self.config.paths["cases_dir"].exists():
            if not self.json_output:
                self.console.print("[red]Error:[/red] tests/cases directory not found")
            else:
                print("Error: tests/cases directory not found", file=sys.stderr)
            sys.exit(1)

        def get_sort_key(path: Path) -> tuple:
            # 尝试从文件夹名称中提取数字前缀
            match = re.match(r"(\d+)", path.name)
            if match:
                # 如果有数字前缀，返回 (0, 数字值, 文件夹名) 元组
                # 0 表示优先级最高
                return (0, int(match.group(1)), path.name)
            else:
                # 如果没有数字前缀，返回 (1, 0, 文件夹名) 元组
                # 1 表示优先级较低，这些文件夹会按字母顺序排在有数字前缀的文件夹后面
                return (1, 0, path.name)

        test_cases = []
        # 使用自定义排序函数
        for test_dir in sorted(
            self.config.paths["cases_dir"].iterdir(), key=get_sort_key
        ):
            if test_dir.is_dir() and (test_dir / "config.toml").exists():
                test_cases.append(self._load_single_test(test_dir))

        if not test_cases:
            if not self.json_output:
                self.console.print(
                    "[red]Error:[/red] No test cases found in tests/cases/"
                )
            else:
                print("Error: No test cases found in tests/cases/", file=sys.stderr)
            sys.exit(1)

        return test_cases

    def _load_single_test(self, test_path: Path) -> TestCase:
        try:
            with open(test_path / "config.toml", "rb") as f:
                config = tomli.load(f)

            if "meta" not in config:
                raise ValueError("Missing 'meta' section in config")
            if "name" not in config["meta"]:
                raise ValueError("Missing 'name' in meta section")
            if "score" not in config["meta"]:
                raise ValueError("Missing 'score' in meta section")
            if "run" not in config:
                raise ValueError("Missing 'run' section in config")

            return TestCase(
                path=test_path, meta=config["meta"], run_steps=config["run"]
            )
        except Exception as e:
            if not self.json_output:
                self.console.print(
                    f"[red]Error:[/red] Failed to load test '{test_path.name}': {str(e)}"
                )
            else:
                print(
                    f"Error: Failed to load test '{test_path.name}': {str(e)}",
                    file=sys.stderr,
                )
            sys.exit(1)


def get_current_shell() -> str:
    """
    获取当前用户使用的shell类型
    优先检查父进程，然后检查SHELL环境变量
    返回值: 'bash', 'zsh', 'fish' 等
    """
    # 方法1: 检查父进程
    try:
        parent_pid = os.getppid()
        with open(f"/proc/{parent_pid}/comm", "r") as f:
            shell = f.read().strip()
            if shell in ["bash", "zsh", "fish"]:
                return shell
    except:
        pass

    # 方法2: 通过SHELL环境变量
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        shell = os.path.basename(shell_path)
        if shell in ["bash", "zsh", "fish"]:
            return shell

    # 默认返回bash
    return "bash"


def main():
    parser = argparse.ArgumentParser(description="Grade student submissions")
    parser.add_argument(
        "-j", "--json", action="store_true", help="Output results in JSON format"
    )
    parser.add_argument(
        "-w",
        "--write-result",
        action="store_true",
        help="Write percentage score to .autograder_result file",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        action="store_true",
        help="Use number prefix exact matching mode for test case selection",
    )
    parser.add_argument(
        "-g",
        "--group",
        help="Run all test cases in the specified group",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show detailed output of each test step",
    )
    parser.add_argument(
        "-l",
        "--get-last-failed",
        action="store_true",
        help="Read last test result and output command to set TEST_BUILD environment variable",
    )
    parser.add_argument(
        "-f",
        "--rerun-failed",
        action="store_true",
        help="Only run the test cases that failed in the last run",
    )
    parser.add_argument(
        "--shell",
        choices=["bash", "zsh", "fish"],
        help="Manually specify shell type for environment variable commands",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Only show commands that would be executed (only works with single test case)",
    )
    parser.add_argument(
        "-n",
        "--no-check",
        action="store_true",
        help="Run test cases without performing checks specified in config",
    )
    parser.add_argument(
        "--vscode",
        action="store_true",
        help="Generate VS Code debug configurations for failed test cases",
    )
    parser.add_argument(
        "--vscode-no-merge",
        action="store_true",
        help="Overwrite existing VS Code configurations instead of merging",
    )
    parser.add_argument("test", nargs="?", help="Specific test to run")
    args = parser.parse_args()

    try:
        # 如果是获取上次失败测试点的模式
        if args.get_last_failed:
            try:
                history_file = Path(".test_history")
                if not history_file.exists():
                    print("No test history found", file=sys.stderr)
                    sys.exit(1)

                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if not history:
                        print("Test history is empty", file=sys.stderr)
                        sys.exit(1)

                    # 获取最近一次的测试结果
                    last_result = history[-1]

                    # 查找第一个失败的测试点
                    for test in last_result["tests"]:
                        if test["status"] != "PASS":
                            # 获取shell类型
                            shell_type = args.shell or get_current_shell()

                            # 根据不同shell类型生成相应的命令
                            if shell_type == "fish":
                                print(f"set -x TEST_BUILD {test['build_path']}")
                            else:  # bash 或 zsh
                                print(f"export TEST_BUILD={test['build_path']}")
                            sys.exit(0)

                    print("No failed test found in last run", file=sys.stderr)
                    sys.exit(1)

            except Exception as e:
                print(f"Error reading test history: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # 如果是重新运行失败测试点的模式
        if args.rerun_failed:
            try:
                history_file = Path(".test_history")
                if not history_file.exists():
                    print("No test history found", file=sys.stderr)
                    sys.exit(1)

                with open(history_file, "r", encoding="utf-8") as f:
                    history = json.load(f)
                    if not history:
                        print("Test history is empty", file=sys.stderr)
                        sys.exit(1)

                    # 获取最近一次的测试结果
                    last_result = history[-1]

                    # 获取所有失败的测试点路径
                    failed_paths = []
                    for test in last_result["tests"]:
                        if test["status"] != "PASS":
                            failed_paths.append(Path(test["path"]))

                    if not failed_paths:
                        print("No failed test found in last run", file=sys.stderr)
                        sys.exit(0)

                    # 直接传入失败测试点的路径
                    grader = Grader(json_output=args.json)
                    grader.runner = TestRunner(
                        grader.config, grader.console, verbose=args.verbose
                    )
                    grader.run_all_tests(specific_paths=failed_paths)

                    # 检查是否所有测试都通过
                    total_score = sum(
                        result.score for result in grader.results.values()
                    )
                    max_score = sum(
                        test.meta["score"]
                        for test in grader._load_test_cases(specific_paths=failed_paths)
                    )
                    percentage = (total_score / max_score * 100) if max_score > 0 else 0

                    # 如果需要写入结果文件
                    if args.write_result:
                        with open(".autograder_result", "w") as f:
                            f.write(f"{percentage:.2f}")

                    # 只要有测试点失败，输出提示信息
                    if total_score < max_score:
                        if not args.json:
                            console = Console()
                            shell_type = args.shell or get_current_shell()

                            console.print(
                                "\n[bold yellow]To set TEST_BUILD environment variable to the failed test case's build directory:[/bold yellow]"
                            )

                            if shell_type == "fish":
                                console.print(
                                    "$ [bold green]python3 grader.py -l | source[/bold green]"
                                )
                            else:
                                console.print(
                                    '$ [bold green]eval "$(python3 grader.py -l)"[/bold green]'
                                )
                        else:
                            shell_type = args.shell or get_current_shell()
                            print(
                                "\nTo set TEST_BUILD to the first failed test case's build directory, run:"
                            )
                            if shell_type == "fish":
                                print("python3 grader.py -l | source")
                            else:
                                print('eval "$(python3 grader.py -l)"')

                    # 只要不是0分就通过
                    sys.exit(0 if percentage > 0 else 1)

            except Exception as e:
                print(f"Error reading test history: {str(e)}", file=sys.stderr)
                sys.exit(1)

        # 检查dry-run模式是否与单个测试点一起使用
        if args.dry_run and not args.test:
            print(
                "Error: --dry-run can only be used with a single test case",
                file=sys.stderr,
            )
            sys.exit(1)

        grader = Grader(
            json_output=args.json,
            dry_run=args.dry_run,
            no_check=args.no_check,
            verbose=args.verbose,
            generate_vscode=args.vscode,
            vscode_no_merge=args.vscode_no_merge,
        )
        total_score, max_score = grader.run_all_tests(
            args.test, prefix_match=args.prefix, group=args.group
        )

        # 如果是dry-run模式，直接退出
        if args.dry_run:
            sys.exit(0)

        percentage = (total_score / max_score * 100) if max_score > 0 else 0

        # 如果需要写入结果文件
        if args.write_result:
            with open(".autograder_result", "w") as f:
                f.write(f"{percentage:.2f}")

        # 如果有测试点失败，输出提示信息
        if total_score < max_score:
            if not args.json:
                console = Console()
                shell_type = args.shell or get_current_shell()

                console.print(
                    "\n[bold yellow]To set TEST_BUILD environment variable to the failed test case's build directory:[/bold yellow]"
                )

                if shell_type == "fish":
                    console.print(
                        "$ [bold green]python3 grader.py -l | source[/bold green]"
                    )
                else:
                    console.print(
                        '$ [bold green]eval "$(python3 grader.py -l)"[/bold green]'
                    )
            else:
                shell_type = args.shell or get_current_shell()
                print(
                    "\nTo set TEST_BUILD to the first failed test case's build directory, run:"
                )
                if shell_type == "fish":
                    print("python3 grader.py -l | source")
                else:
                    print('eval "$(python3 grader.py -l)"')

        # 只要不是0分就通过
        sys.exit(0 if percentage > 0 else 1)
    except subprocess.CalledProcessError as e:
        print(
            f"Error: Command execution failed with return code {e.returncode}",
            file=sys.stderr,
        )
        sys.exit(1)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
