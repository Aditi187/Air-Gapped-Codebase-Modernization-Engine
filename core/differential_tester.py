import os
import subprocess
import tempfile
import time
import shutil
from dataclasses import dataclass
from difflib import unified_diff


def resolve_gpp_exe(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path
    env_path = os.environ.get("GPP_EXE")
    if env_path:
        return env_path
    which_path = shutil.which("g++")
    if which_path:
        return which_path
    return "g++"


def _verify_compiler(gpp_exe: str, timeout_seconds: int = 5) -> None:
    try:
        result = subprocess.run(
            [gpp_exe, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise RuntimeError(f"g++ sanity check failed: {exc!r}") from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"g++ sanity check failed with exit code {result.returncode}: {result.stderr}"
        )


def compile_cpp_source(
    code: str,
    gpp_exe: str | None = None,
    timeout_seconds: int = 10,
) -> dict:
    compiler = resolve_gpp_exe(gpp_exe)
    _verify_compiler(compiler)

    start_time = time.time()

    with tempfile.TemporaryDirectory() as tmp_dir:
        cpp_path = os.path.join(tmp_dir, "modernized.cpp")
        exe_path = os.path.join(tmp_dir, "modernized.exe")

        with open(cpp_path, "w", encoding="utf-8") as cpp_file:
            cpp_file.write(code)

        cmd = [compiler, "-std=c++20", "-Wall", cpp_path, "-o", exe_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "errors": [f"Compilation timed out after {timeout_seconds} seconds."],
                "warnings": [],
                "compilation_time_ms": elapsed_ms,
                "raw_stdout": "",
                "raw_stderr": "",
                "compiler": compiler,
            }
        except FileNotFoundError:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "errors": [
                    "g++ compiler not found. Please install a C++ compiler "
                    "and ensure it is on your PATH or set GPP_EXE."
                ],
                "warnings": [],
                "compilation_time_ms": elapsed_ms,
                "raw_stdout": "",
                "raw_stderr": "",
                "compiler": compiler,
            }
        except Exception as exc:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {
                "success": False,
                "errors": [f"Compilation failed: {exc!r}"],
                "warnings": [],
                "compilation_time_ms": elapsed_ms,
                "raw_stdout": "",
                "raw_stderr": "",
                "compiler": compiler,
            }

    elapsed_ms = int((time.time() - start_time) * 1000)
    stdout_text = (result.stdout or "").strip()
    stderr_text = (result.stderr or "").strip()

    success = result.returncode == 0
    error_lines = stderr_text.splitlines() if stderr_text else []
    warning_lines = stdout_text.splitlines() if stdout_text else []

    return {
        "success": success,
        "errors": error_lines,
        "warnings": warning_lines,
        "compilation_time_ms": elapsed_ms,
        "raw_stdout": stdout_text,
        "raw_stderr": stderr_text,
        "compiler": compiler,
    }


def _compile_and_run_cpp(
    source_path: str,
    gpp_exe: str,
    tmp_dir: str,
    exe_name: str,
    input_data: str | None = None,
) -> dict:
    _verify_compiler(gpp_exe)

    exe_path = os.path.join(tmp_dir, exe_name)

    compile_start = time.time()
    compile_cmd = [gpp_exe, "-std=c++20", "-Wall", source_path, "-o", exe_path]

    try:
        compile_result = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "compile_success": False,
            "run_success": False,
            "stdout": "",
            "stderr": f"Compilation timed out: {exc!r}",
            "compile_time_ms": int((time.time() - compile_start) * 1000),
            "run_time_ms": 0,
        }
    except Exception as exc:
        return {
            "compile_success": False,
            "run_success": False,
            "stdout": "",
            "stderr": f"Compilation failed: {exc!r}",
            "compile_time_ms": int((time.time() - compile_start) * 1000),
            "run_time_ms": 0,
        }

    compile_time_ms = int((time.time() - compile_start) * 1000)

    if compile_result.returncode != 0:
        stderr_text = (compile_result.stderr or "").strip()
        return {
            "compile_success": False,
            "run_success": False,
            "stdout": (compile_result.stdout or "").strip(),
            "stderr": stderr_text,
            "compile_time_ms": compile_time_ms,
            "run_time_ms": 0,
        }

    run_start = time.time()

    try:
        run_result = subprocess.run(
            [exe_path],
            input=input_data if input_data is not None else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "compile_success": True,
            "run_success": False,
            "stdout": "",
            "stderr": f"Execution timed out: {exc!r}",
            "compile_time_ms": compile_time_ms,
            "run_time_ms": int((time.time() - run_start) * 1000),
        }
    except Exception as exc:
        return {
            "compile_success": True,
            "run_success": False,
            "stdout": "",
            "stderr": f"Execution failed: {exc!r}",
            "compile_time_ms": compile_time_ms,
            "run_time_ms": int((time.time() - run_start) * 1000),
        }

    run_time_ms = int((time.time() - run_start) * 1000)

    stdout_text = (run_result.stdout or "").strip()
    stderr_text = (run_result.stderr or "").strip()
    run_success = run_result.returncode == 0

    return {
        "compile_success": True,
        "run_success": run_success,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "compile_time_ms": compile_time_ms,
        "run_time_ms": run_time_ms,
    }


def _normalize_output(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.split("\n")
    stripped_lines = [line.rstrip() for line in lines]
    while stripped_lines and stripped_lines[-1] == "":
        stripped_lines.pop()
    return "\n".join(stripped_lines)


def _extract_error_location(stderr_text: str, source_label: str) -> str | None:
    for line in stderr_text.splitlines():
        if source_label in line:
            return line.strip()
    return None


@dataclass
class DifferentialTestResult:
    parity_ok: bool
    diff_text: str
    original: dict
    modernized: dict
    gpp_exe: str


def run_differential_test(
    original_cpp_path: str,
    modernized_code: str,
    gpp_exe: str | None = None,
    input_data: str | None = None,
) -> dict:
    compiler = resolve_gpp_exe(gpp_exe)
    _verify_compiler(compiler)

    if not os.path.isfile(original_cpp_path):
        return DifferentialTestResult(
            parity_ok=False,
            diff_text="",
            original={
                "compile_success": False,
                "run_success": False,
                "stdout": "",
                "stderr": f"Original file not found: {original_cpp_path}",
                "compile_time_ms": 0,
                "run_time_ms": 0,
            },
            modernized={
                "compile_success": False,
                "run_success": False,
                "stdout": "",
                "stderr": "",
                "compile_time_ms": 0,
                "run_time_ms": 0,
            },
            gpp_exe=compiler,
        ).__dict__

    if not modernized_code.strip():
        return DifferentialTestResult(
            parity_ok=False,
            diff_text="",
            original={
                "compile_success": False,
                "run_success": False,
                "stdout": "",
                "stderr": "",
                "compile_time_ms": 0,
                "run_time_ms": 0,
            },
            modernized={
                "compile_success": False,
                "run_success": False,
                "stdout": "",
                "stderr": "No modernized code provided.",
                "compile_time_ms": 0,
                "run_time_ms": 0,
            },
            gpp_exe=compiler,
        ).__dict__

    with tempfile.TemporaryDirectory() as tmp_dir:
        modernized_cpp_path = os.path.join(tmp_dir, "modernized.cpp")

        with open(modernized_cpp_path, "w", encoding="utf-8") as f:
            f.write(modernized_code)

        original_result = _compile_and_run_cpp(
            original_cpp_path,
            compiler,
            tmp_dir,
            "original.exe",
            input_data=input_data,
        )

        if not (original_result["compile_success"] and original_result["run_success"]):
            return DifferentialTestResult(
                parity_ok=False,
                diff_text="",
                original=original_result,
                modernized={
                    "compile_success": False,
                    "run_success": False,
                    "stdout": "",
                    "stderr": "",
                    "compile_time_ms": 0,
                    "run_time_ms": 0,
                },
                gpp_exe=compiler,
            ).__dict__

        modernized_result = _compile_and_run_cpp(
            modernized_cpp_path,
            compiler,
            tmp_dir,
            "modernized.exe",
            input_data=input_data,
        )

        if not modernized_result["compile_success"]:
            location = _extract_error_location(
                modernized_result["stderr"], os.path.basename(modernized_cpp_path)
            )
            if location:
                modernized_result["stderr"] = (
                    modernized_result["stderr"] + "\n" + f"First error location: {location}"
                )
            return DifferentialTestResult(
                parity_ok=False,
                diff_text="",
                original=original_result,
                modernized=modernized_result,
                gpp_exe=compiler,
            ).__dict__

        if not modernized_result["run_success"]:
            return DifferentialTestResult(
                parity_ok=False,
                diff_text="",
                original=original_result,
                modernized=modernized_result,
                gpp_exe=compiler,
            ).__dict__

        norm_orig = _normalize_output(original_result["stdout"])
        norm_mod = _normalize_output(modernized_result["stdout"])

        if norm_orig == norm_mod:
            return DifferentialTestResult(
                parity_ok=True,
                diff_text="",
                original=original_result,
                modernized=modernized_result,
                gpp_exe=compiler,
            ).__dict__

        orig_lines = (norm_orig + "\n").splitlines(keepends=True)
        mod_lines = (norm_mod + "\n").splitlines(keepends=True)

        diff_lines = unified_diff(
            orig_lines,
            mod_lines,
            fromfile="Original (test.cpp)",
            tofile="Modernized",
        )

        diff_text_parts: list[str] = []
        for line in diff_lines:
            diff_text_parts.append(line)

        diff_text = "".join(diff_text_parts)

        return DifferentialTestResult(
            parity_ok=False,
            diff_text=diff_text,
            original=original_result,
            modernized=modernized_result,
            gpp_exe=compiler,
        ).__dict__