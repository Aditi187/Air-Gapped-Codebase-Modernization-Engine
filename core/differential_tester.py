from __future__ import annotations

import logging
import os
import platform
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from difflib import unified_diff
from typing import Any

try:
    import psutil  # type: ignore[import-not-found]

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

_log = logging.getLogger(__name__)

_VERIFIED_COMPILERS: set[str] = set()
_VERIFIED_COMPILERS_LOCK = threading.Lock()
_SANITIZER_COMPILE_FLAGS = [
    "-fsanitize=address,undefined",
    "-fno-omit-frame-pointer",
]
_CRASH_STDERR_PATTERN = re.compile(
    r"(?:segmentation fault|access violation|illegal instruction|"
    r"floating point exception|aborted|stack overflow|core dumped|"
    r"SUMMARY:|ERROR:\s*(?:address|leak|undefined))",
    re.IGNORECASE,
)

@dataclass(frozen=True)
class TesterConfig:
    compile_timeout_seconds: int = 30
    run_timeout_seconds: int = 30
    enable_sanitizers_modernized: bool = True
    sanitize_original: bool = False
    compiler_path: str = ""
    sanitizer_flags: list[str] = field(default_factory=lambda: [
        "-fsanitize=address,undefined",
        "-fno-omit-frame-pointer",
    ])
    filter_sanitizer_stderr: bool = True
    max_test_cases: int = 0
    debug: bool = False
    link_flags: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> TesterConfig:

        def _env_int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(f"TESTER_{name}".upper(), str(default)))
            except ValueError:
                return default

        def _env_bool(name: str, default: bool) -> bool:
            val = os.environ.get(f"TESTER_{name}".upper(), "").lower()
            if val in ("true", "1", "yes"):
                return True
            if val in ("false", "0", "no"):
                return False
            return default

        return cls(
            compile_timeout_seconds=_env_int("compile_timeout_seconds", 30),
            run_timeout_seconds=_env_int("run_timeout_seconds", 30),
            enable_sanitizers_modernized=_env_bool("enable_sanitizers_modernized", True),
            sanitize_original=_env_bool("sanitize_original", False),
            compiler_path=os.environ.get("TESTER_COMPILER_PATH", "").strip(),
            filter_sanitizer_stderr=_env_bool("filter_sanitizer_stderr", True),
            max_test_cases=_env_int("max_test_cases", 0),
            debug=_env_bool("debug", False),
            link_flags=os.environ.get("TESTER_LINK_FLAGS", "").split(),
        )


@dataclass
class CompilerCapabilities:
    compiler_path: str
    version_string: str
    supports_cpp17: bool = False
    supports_sanitizers: bool = False
    supports_asan_stderr_capture: bool = False


_COMPILER_CAPABILITIES_CACHE: dict[str, CompilerCapabilities] = {}
_COMPILER_CAPABILITIES_LOCK = threading.Lock()


def detect_compiler_capabilities(
    compiler_path: str, timeout_seconds: int = 5
) -> CompilerCapabilities:
    with _COMPILER_CAPABILITIES_LOCK:
        if compiler_path in _COMPILER_CAPABILITIES_CACHE:
            _log.debug(f"Cache hit for compiler capabilities: {compiler_path}")
            return _COMPILER_CAPABILITIES_CACHE[compiler_path]

    _log.debug(f"Detecting compiler capabilities for: {compiler_path}")

    try:
        result = subprocess.run(
            [compiler_path, "--version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        version_string = (result.stdout or "").strip().split("\n")[0]
    except Exception as exc:
        raise RuntimeError(f"Failed to get compiler version: {exc}") from exc

    supports_cpp17 = _test_compiler_flag(compiler_path, "-std=c++17", timeout_seconds)

    supports_sanitizers = _test_compiler_flag(
        compiler_path,
        "-fsanitize=address",
        timeout_seconds,
    )

    supports_asan_stderr = supports_sanitizers
    
    capabilities = CompilerCapabilities(
        compiler_path=compiler_path,
        version_string=version_string,
        supports_cpp17=supports_cpp17,
        supports_sanitizers=supports_sanitizers,
        supports_asan_stderr_capture=supports_asan_stderr,
    )

    with _COMPILER_CAPABILITIES_LOCK:
        _COMPILER_CAPABILITIES_CACHE[compiler_path] = capabilities

    _log.debug(
        f"Compiler capabilities: C++17={supports_cpp17}, Sanitizers={supports_sanitizers}"
    )

    return capabilities


def _test_compiler_flag(
    compiler_path: str, flag: str, timeout_seconds: int
) -> bool:
    test_code = "int main() { return 0; }\n"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            cpp_file = os.path.join(tmp, "test.cpp")
            exe_file = os.path.join(tmp, "test.exe")
            with open(cpp_file, "w") as f:
                f.write(test_code)

            result = subprocess.run(
                [compiler_path, flag, cpp_file, "-o", exe_file],
                capture_output=True,
                timeout=timeout_seconds,
            )
            return result.returncode == 0
    except Exception as exc:
        _log.debug(f"Compiler flag test failed for {flag}: {exc}")
        return False


def _detect_crash_reason(
    exit_code: int | None,
    stderr_text: str,
    timed_out: bool,
    platform_name: str | None = None,
) -> str:
    if timed_out:
        return "timeout"

    if exit_code is None:
        return "execution_error"

    current_platform = platform_name or platform.system()

    if _CRASH_STDERR_PATTERN.search(stderr_text or ""):
        return "Process crashed (detected from stderr)."

    if exit_code != 0:
        if current_platform == "Windows":
            win_exceptions = {
                0xC0000005: "Access Violation",
                0xC000001D: "Illegal Instruction",
                0xC0000094: "Integer Division by Zero",
                0xC0000FD:  "Stack Overflow",
                0xC000002B: "Stack Buffer Overrun",
                0xC0000008: "Invalid Handle",
                0xC0000017: "No Memory",
                0xC000013A: "Control-C Exit",
            }
            # Many Windows exit codes for crashes appear as large positive unsigned 32-bit ints
            unsigned_code = exit_code & 0xFFFFFFFF
            if unsigned_code in win_exceptions:
                return f"Process terminated with exception {unsigned_code:#x} ({win_exceptions[unsigned_code]})."
        
        if exit_code < 0:
            signal_num = -exit_code
            if current_platform != "Windows":
                try:
                    sig_name = signal.Signals(signal_num).name
                    return f"Process terminated by signal {signal_num} ({sig_name})."
                except (ValueError, AttributeError):
                    return f"Process terminated by signal {signal_num}."
            else:
                return f"Process terminated with exception {signal_num:#x}."

        return f"Process exited with non-zero status {exit_code}."

    return ""


def _get_peak_memory_kb(stderr_text: str) -> int | None:
    if not stderr_text:
        return None

    if match := re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", stderr_text):
        return int(match.group(1))
    if match := re.search(r"(\d+)\s+byte\(s\)\s+allocated", stderr_text):
        return max(1, int(match.group(1)) // 1024)
    return None


_SANITIZER_ERROR_PATTERN = re.compile(
    r"(?:AddressSanitizer|UndefinedBehaviorSanitizer|LeakSanitizer|ERROR:\s*(?:address|leak|undefined))",
    re.IGNORECASE,
)

_SANITIZER_STDERR_PATTERN = re.compile(
    r"^(==\d+==|SUMMARY:|ASAN_OPTIONS|UBSAN_OPTIONS|\s*#\d+|Direct leak|Indirect leak)",
    re.MULTILINE,
)


def _detect_sanitizer_errors(stderr_text: str) -> list[str]:
    if not stderr_text:
        return []
    return [line.strip() for line in stderr_text.splitlines() if _SANITIZER_ERROR_PATTERN.search(line)]


# Removed unused _filter_sanitizer_lines


def resolve_cpp_compiler(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path

    env_candidates = [
        os.environ.get("CXX", "").strip(),
        os.environ.get("GPP_EXE", "").strip(),
        os.environ.get("CLANGXX_EXE", "").strip(),
    ]
    for candidate in env_candidates:
        if candidate:
            return candidate

    preferred_bins = ["g++-13", "clang++-16", "g++", "clang++"]
    for binary in preferred_bins:
        found = shutil.which(binary)
        if found:
            return found

    return "g++"


def _verify_compiler(compiler_path: str, timeout_seconds: int = 5) -> None:
    with _VERIFIED_COMPILERS_LOCK:
        if compiler_path in _VERIFIED_COMPILERS:
            return

    try:
        result = subprocess.run(
            [compiler_path, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise RuntimeError(f"C++ compiler sanity check failed: {exc!r}") from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"C++ compiler sanity check failed with exit code {result.returncode}: {result.stderr}"
        )

    with _VERIFIED_COMPILERS_LOCK:
        _VERIFIED_COMPILERS.add(compiler_path)


def _build_compile_command(
    compiler_path: str,
    source_path: str,
    exe_path: str,
    enable_sanitizers: bool,
    link_flags: list[str] | None = None,
) -> list[str]:
    cmd = [compiler_path, "-std=c++17", "-Wall"]
    if enable_sanitizers:
        cmd.extend(_SANITIZER_COMPILE_FLAGS)
    cmd.extend([source_path, "-o", exe_path])
    if link_flags:
        cmd.extend(link_flags)
    return cmd


def _build_run_env(enable_sanitizers: bool) -> dict[str, str]:
    env = dict(os.environ)
    if enable_sanitizers:
        env["ASAN_OPTIONS"] = "detect_leaks=1:print_stats=1:halt_on_error=0"
        env["UBSAN_OPTIONS"] = "print_stacktrace=1:halt_on_error=0"
    return env


def _kill_process_tree(proc: subprocess.Popen) -> None:
    if HAS_PSUTIL:
        try:
            parent = psutil.Process(proc.pid)
            for child in parent.children(recursive=True):
                child.kill()
            parent.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    else:
        try:
            proc.kill()
        except Exception:
            pass
            
def _compile_to_exe(
    source_path: str,
    compiler_path: str,
    tmp_dir: str,
    exe_name: str,
    enable_sanitizers: bool,
    timeout_seconds: int,
    link_flags: list[str] | None = None,
) -> dict[str, Any]:
    exe_path = os.path.join(tmp_dir, exe_name)

    compile_cmd = _build_compile_command(compiler_path, source_path, exe_path, enable_sanitizers, link_flags)
    compile_env = _build_run_env(enable_sanitizers)

    start = time.time()
    try:
        proc = subprocess.Popen(
            compile_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=compile_env,
        )
        stdout_txt, stderr_txt = proc.communicate(timeout=timeout_seconds)
        result_returncode = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        proc.communicate()
        return {
            "compile_success": False,
            "stderr": f"Compilation timed out after {timeout_seconds} seconds.",
            "stdout": "",
            "compile_time_ms": int((time.time() - start) * 1000),
            "exe_path": exe_path,
            "enable_sanitizers": enable_sanitizers,
            "timed_out": True,
        }
    except Exception as exc:
        return {
            "compile_success": False,
            "stderr": f"Compilation failed: {exc!r}",
            "stdout": "",
            "compile_time_ms": int((time.time() - start) * 1000),
            "exe_path": exe_path,
            "enable_sanitizers": enable_sanitizers,
            "timed_out": False,
        }

    return {
        "compile_success": result_returncode == 0,
        "stderr": (stderr_txt or "").strip(),
        "stdout": (stdout_txt or "").strip(),
        "compile_time_ms": int((time.time() - start) * 1000),
        "exe_path": exe_path,
        "enable_sanitizers": enable_sanitizers,
        "timed_out": False,
    }


def _run_exe(
    exe_path: str,
    input_data: str | None,
    timeout_seconds: int,
    env: dict[str, str],
) -> dict[str, Any]:
    run_start = time.time()
    run_cmd = [exe_path]

    try:
        proc = subprocess.Popen(
            run_cmd,
            stdin=subprocess.PIPE if input_data is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        stdout_txt, stderr_txt = proc.communicate(input=input_data, timeout=timeout_seconds)
        result_returncode = proc.returncode
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        proc.communicate()
        return {
            "compile_success": True,
            "run_success": False,
            "stdout": "",
            "stderr": f"Execution timed out after {timeout_seconds} seconds.",
            "run_time_ms": int((time.time() - run_start) * 1000),
            "exit_code": None,
            "sanitizer_findings": [],
            "peak_memory_kb": None,
            "timed_out": True,
            "crash_reason": "timeout",
        }
    except Exception as exc:
        return {
            "compile_success": True,
            "run_success": False,
            "stdout": "",
            "stderr": f"Execution failed: {exc!r}",
            "run_time_ms": int((time.time() - run_start) * 1000),
            "exit_code": None,
            "sanitizer_findings": [],
            "peak_memory_kb": None,
            "timed_out": False,
            "crash_reason": "execution_error",
        }

    run_time_ms = int((time.time() - run_start) * 1000)
    stdout_text = (stdout_txt or "").strip()
    stderr_text = (stderr_txt or "").strip()
    exit_code = int(result_returncode)

    crash_reason = _detect_crash_reason(exit_code, stderr_text, timed_out=False)
    sanitizer_findings = _detect_sanitizer_errors(stderr_text)
    peak_memory_kb = _get_peak_memory_kb(stderr_text)

    return {
        "compile_success": True,
        "run_success": exit_code == 0 and not crash_reason,
        "stdout": stdout_text,
        "stderr": stderr_text,
        "run_time_ms": run_time_ms,
        "exit_code": exit_code,
        "sanitizer_findings": sanitizer_findings,
        "peak_memory_kb": peak_memory_kb,
        "timed_out": False,
        "crash_reason": crash_reason,
    }


def compile_cpp_source(
    code: str,
    gpp_exe: str | None = None,
    timeout_seconds: int = 30,
    enable_sanitizers: bool = True,
    link_flags: list[str] | None = None,
) -> dict:
    if "main" not in code and code.count("{") != code.count("}"):
        return {
            "success": False,
            "errors": ["Compilation skipped: Unbalanced braces."],
            "warnings": [],
            "compilation_time_ms": 0,
            "raw_stdout": "",
            "raw_stderr": "Unbalanced braces detected.",
            "compiler": "none"
        }

    compiler_path = resolve_cpp_compiler(gpp_exe)
    
    caps = detect_compiler_capabilities(compiler_path)
    if not caps.supports_cpp17:
        raise RuntimeError(f"Compiler {compiler_path} does not support -std=c++17")
        
    if enable_sanitizers and not caps.supports_sanitizers:
        _log.warning(f"Sanitizers not supported by compiler {compiler_path}; disabling.")
        enable_sanitizers = False
        
    _verify_compiler(compiler_path)

    start_time = time.time()
    with tempfile.TemporaryDirectory() as tmp_dir:
        cpp_path = os.path.join(tmp_dir, "modernized.cpp")
        
        implicit_headers = "#include <string>\n#include <memory>\n#include <vector>\n#include <optional>\n#include <new>\n#include <iostream>\n"
        if "#include <new>" not in code:
            code = implicit_headers + code

        with open(cpp_path, "w", encoding="utf-8") as cpp_file:
            cpp_file.write(code)

        compile_result = _compile_to_exe(
            source_path=cpp_path,
            compiler_path=compiler_path,
            tmp_dir=tmp_dir,
            exe_name="modernized.exe",
            enable_sanitizers=enable_sanitizers,
            timeout_seconds=timeout_seconds,
            link_flags=link_flags,
        )

    elapsed_ms = int((time.time() - start_time) * 1000)
    stderr_text = str(compile_result.get("stderr") or "")
    stdout_text = str(compile_result.get("stdout") or "")

    success = bool(compile_result.get("compile_success", False))
    return {
        "success": success,
        "errors": [] if success else (stderr_text.splitlines() if stderr_text else ["Compilation failed."]),
        "warnings": stdout_text.splitlines() if success and stdout_text else [],
        "compilation_time_ms": elapsed_ms,
        "raw_stdout": stdout_text,
        "raw_stderr": stderr_text,
        "compiler": compiler_path,
    }


def _normalize_output(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    stripped_lines = [line.rstrip() for line in normalized.split("\n")]
    while stripped_lines and stripped_lines[-1] == "":
        stripped_lines.pop()
    return "\n".join(stripped_lines)


def _extract_error_location(stderr_text: str, source_label: str) -> str | None:
    return next((line.strip() for line in stderr_text.splitlines() if source_label in line), None)


@dataclass
class DifferentialTestResult:
    parity_ok: bool
    diff_text: str
    original: dict
    modernized: dict
    gpp_exe: str
    sanitizer_clean: bool = True
    sanitizer_findings: list[str] | None = None
    memory_delta_kb: int | None = None
    test_cases_run: int = 0
    failed_case_index: int | None = None
    performance_delta_ms: int | None = None


def run_differential_test(
    original_cpp_path: str,
    modernized_code: str,
    gpp_exe: str | None = None,
    input_data: str | None = None,
    input_cases: list[str] | None = None,
    compile_timeout_seconds: int = 30,
    run_timeout_seconds: int = 30,
    link_flags: list[str] | None = None,
) -> dict:
    compiler_path = resolve_cpp_compiler(gpp_exe)
    
    caps = detect_compiler_capabilities(compiler_path)
    if not caps.supports_cpp17:
        raise RuntimeError(f"Compiler {compiler_path} does not support -std=c++17")
        
    _verify_compiler(compiler_path)

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
            gpp_exe=compiler_path,
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
            gpp_exe=compiler_path,
            test_cases_run=0,
        ).__dict__

    effective_input_cases = input_cases if input_cases is not None else []
    if not effective_input_cases:
        effective_input_cases = [input_data if input_data is not None else ""]

    with tempfile.TemporaryDirectory() as tmp_dir:
        modernized_cpp_path = os.path.join(tmp_dir, "modernized.cpp")
        
        implicit_headers = "#include <string>\n#include <memory>\n#include <vector>\n#include <optional>\n#include <new>\n#include <iostream>\n"
        if "#include <new>" not in modernized_code:
            modernized_code = implicit_headers + modernized_code

        with open(modernized_cpp_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(modernized_code)

        original_compile = _compile_to_exe(
            source_path=original_cpp_path,
            compiler_path=compiler_path,
            tmp_dir=tmp_dir,
            exe_name="original.exe",
            enable_sanitizers=False,
            timeout_seconds=compile_timeout_seconds,
            link_flags=link_flags,
        )
        if not original_compile.get("compile_success", False):
            return DifferentialTestResult(
                parity_ok=False,
                diff_text="Original code failed to compile. Please fix legacy source before differential testing.",
                original={
                    "compile_success": False,
                    "run_success": False,
                    "stdout": str(original_compile.get("stdout") or ""),
                    "stderr": str(original_compile.get("stderr") or ""),
                    "compile_time_ms": int(original_compile.get("compile_time_ms", 0) or 0),
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
                gpp_exe=compiler_path,
                test_cases_run=0,
            ).__dict__

        modernized_compile = _compile_to_exe(
            source_path=modernized_cpp_path,
            compiler_path=compiler_path,
            tmp_dir=tmp_dir,
            exe_name="modernized.exe",
            enable_sanitizers=caps.supports_sanitizers,
            timeout_seconds=compile_timeout_seconds,
            link_flags=link_flags,
        )
        if not modernized_compile.get("compile_success", False):
            modernized_stderr = str(modernized_compile.get("stderr") or "")
            location = _extract_error_location(modernized_stderr, os.path.basename(modernized_cpp_path))
            if location:
                modernized_stderr = modernized_stderr + "\n" + f"First error location: {location}"
            return DifferentialTestResult(
                parity_ok=False,
                diff_text="Modernized code failed to compile. See compiler diagnostics.",
                original={
                    "compile_success": True,
                    "run_success": True,
                    "stdout": str(original_compile.get("stdout") or ""),
                    "stderr": str(original_compile.get("stderr") or ""),
                    "compile_time_ms": int(original_compile.get("compile_time_ms", 0) or 0),
                    "run_time_ms": 0,
                },
                modernized={
                    "compile_success": False,
                    "run_success": False,
                    "stdout": str(modernized_compile.get("stdout") or ""),
                    "stderr": modernized_stderr,
                    "compile_time_ms": int(modernized_compile.get("compile_time_ms", 0) or 0),
                    "run_time_ms": 0,
                },
                gpp_exe=compiler_path,
                test_cases_run=0,
            ).__dict__

        original_compile_ms = int(original_compile.get("compile_time_ms", 0) or 0)
        modernized_compile_ms = int(modernized_compile.get("compile_time_ms", 0) or 0)

        original_env = _build_run_env(enable_sanitizers=False)
        modernized_env = _build_run_env(enable_sanitizers=bool(modernized_compile.get("enable_sanitizers")))
        original_exe_path = str(original_compile.get("exe_path") or "")
        modernized_exe_path = str(modernized_compile.get("exe_path") or "")

        original_cases: list[dict[str, Any]] = []
        modernized_cases: list[dict[str, Any]] = []
        all_sanitizer_findings: list[str] = []
        total_original_run_ms = 0
        total_modernized_run_ms = 0
        max_original_peak: int | None = None
        max_modernized_peak: int | None = None

        for case_index, case_input in enumerate(effective_input_cases):
            original_case_result = _run_exe(
                exe_path=original_exe_path,
                input_data=case_input,
                timeout_seconds=run_timeout_seconds,
                env=original_env,
            )
            original_case_result["compile_time_ms"] = original_compile_ms

            modernized_case_result = _run_exe(
                exe_path=modernized_exe_path,
                input_data=case_input,
                timeout_seconds=run_timeout_seconds,
                env=modernized_env,
            )
            modernized_case_result["compile_time_ms"] = modernized_compile_ms

            original_cases.append(original_case_result)
            modernized_cases.append(modernized_case_result)

            total_original_run_ms += int(original_case_result.get("run_time_ms", 0) or 0)
            total_modernized_run_ms += int(modernized_case_result.get("run_time_ms", 0) or 0)

            original_peak_case = original_case_result.get("peak_memory_kb")
            modernized_peak_case = modernized_case_result.get("peak_memory_kb")
            if isinstance(original_peak_case, int):
                max_original_peak = (
                    original_peak_case
                    if max_original_peak is None
                    else max(max_original_peak, original_peak_case)
                )
            if isinstance(modernized_peak_case, int):
                max_modernized_peak = (
                    modernized_peak_case
                    if max_modernized_peak is None
                    else max(max_modernized_peak, modernized_peak_case)
                )

            case_findings = modernized_case_result.get("sanitizer_findings") or []
            all_sanitizer_findings.extend([str(item) for item in case_findings])

            if not original_case_result.get("run_success", False):
                reason = str(original_case_result.get("crash_reason") or "original runtime failure")
                return DifferentialTestResult(
                    parity_ok=False,
                    diff_text=(
                        f"Case {case_index}: original program runtime failure: {reason}.\n"
                        + str(original_case_result.get("stderr", ""))
                    ),
                    original={
                        "compile_success": True,
                        "run_success": False,
                        "compile_time_ms": original_compile_ms,
                        "run_time_ms": total_original_run_ms,
                        "cases": original_cases,
                    },
                    modernized={
                        "compile_success": True,
                        "run_success": False,
                        "compile_time_ms": modernized_compile_ms,
                        "run_time_ms": total_modernized_run_ms,
                        "cases": modernized_cases,
                    },
                    gpp_exe=compiler_path,
                    sanitizer_clean=False,
                    sanitizer_findings=all_sanitizer_findings if all_sanitizer_findings else None,
                    test_cases_run=case_index + 1,
                    failed_case_index=case_index,
                    performance_delta_ms=total_modernized_run_ms - total_original_run_ms,
                ).__dict__

            if not modernized_case_result.get("run_success", False):
                reason = str(modernized_case_result.get("crash_reason") or "modernized runtime failure")
                return DifferentialTestResult(
                    parity_ok=False,
                    diff_text=(
                        f"Case {case_index}: modernized program runtime failure: {reason}.\n"
                        + str(modernized_case_result.get("stderr", ""))
                    ),
                    original={
                        "compile_success": True,
                        "run_success": True,
                        "compile_time_ms": original_compile_ms,
                        "run_time_ms": total_original_run_ms,
                        "cases": original_cases,
                    },
                    modernized={
                        "compile_success": True,
                        "run_success": False,
                        "compile_time_ms": modernized_compile_ms,
                        "run_time_ms": total_modernized_run_ms,
                        "cases": modernized_cases,
                    },
                    gpp_exe=compiler_path,
                    sanitizer_clean=False,
                    sanitizer_findings=all_sanitizer_findings if all_sanitizer_findings else None,
                    test_cases_run=case_index + 1,
                    failed_case_index=case_index,
                    performance_delta_ms=total_modernized_run_ms - total_original_run_ms,
                ).__dict__

            norm_orig = _normalize_output(str(original_case_result.get("stdout", "")))
            norm_mod = _normalize_output(str(modernized_case_result.get("stdout", "")))
            norm_orig_err = _normalize_output(str(original_case_result.get("stderr", "")))
            norm_mod_err = _normalize_output(str(modernized_case_result.get("stderr", "")))
            original_exit = int(original_case_result.get("exit_code", 0) or 0)
            modernized_exit = int(modernized_case_result.get("exit_code", 0) or 0)

            sanitizer_clean = len(case_findings) == 0
            outputs_match = norm_orig == norm_mod
            stderr_match = norm_orig_err == norm_mod_err
            exit_match = original_exit == modernized_exit

            if outputs_match and stderr_match and exit_match and sanitizer_clean:
                continue

            stdout_diff = "".join(
                unified_diff(
                    (norm_orig + "\n").splitlines(keepends=True),
                    (norm_mod + "\n").splitlines(keepends=True),
                    fromfile=f"case_{case_index}_original_stdout",
                    tofile=f"case_{case_index}_modernized_stdout",
                )
            )
            stderr_diff = "".join(
                unified_diff(
                    (norm_orig_err + "\n").splitlines(keepends=True),
                    (norm_mod_err + "\n").splitlines(keepends=True),
                    fromfile=f"case_{case_index}_original_stderr",
                    tofile=f"case_{case_index}_modernized_stderr",
                )
            )

            diff_parts: list[str] = [f"Case {case_index} mismatch diagnostics:\n"]
            if not outputs_match:
                diff_parts.append("stdout diff:\n" + stdout_diff)
            if not stderr_match:
                diff_parts.append("stderr diff:\n" + stderr_diff)
            if not exit_match:
                diff_parts.append(
                    f"exit code mismatch: original={original_exit}, modernized={modernized_exit}\n"
                )
            if not sanitizer_clean:
                diff_parts.append(
                    "sanitizer diagnostics:\n" + "\n".join([str(item) for item in case_findings]) + "\n"
                )

            memory_delta_kb: int | None = None
            if max_original_peak is not None and max_modernized_peak is not None:
                memory_delta_kb = int(max_modernized_peak) - int(max_original_peak)

            return DifferentialTestResult(
                parity_ok=False,
                diff_text="".join(diff_parts),
                original={
                    "compile_success": True,
                    "run_success": True,
                    "compile_time_ms": original_compile_ms,
                    "run_time_ms": total_original_run_ms,
                    "cases": original_cases,
                },
                modernized={
                    "compile_success": True,
                    "run_success": True,
                    "compile_time_ms": modernized_compile_ms,
                    "run_time_ms": total_modernized_run_ms,
                    "cases": modernized_cases,
                },
                gpp_exe=compiler_path,
                sanitizer_clean=not all_sanitizer_findings,
                sanitizer_findings=all_sanitizer_findings if all_sanitizer_findings else None,
                memory_delta_kb=memory_delta_kb,
                test_cases_run=case_index + 1,
                failed_case_index=case_index,
                performance_delta_ms=total_modernized_run_ms - total_original_run_ms,
            ).__dict__

        memory_delta_kb: int | None = None
        if max_original_peak is not None and max_modernized_peak is not None:
            memory_delta_kb = int(max_modernized_peak) - int(max_original_peak)

        sanitizer_clean = len(all_sanitizer_findings) == 0

        return DifferentialTestResult(
            parity_ok=sanitizer_clean,
            diff_text="" if sanitizer_clean else (
                "All outputs matched, but sanitizer detected issues:\n"
                + "\n".join(all_sanitizer_findings)
            ),
            original={
                "compile_success": True,
                "run_success": True,
                "compile_time_ms": original_compile_ms,
                "run_time_ms": total_original_run_ms,
                "cases": original_cases,
            },
            modernized={
                "compile_success": True,
                "run_success": True,
                "compile_time_ms": modernized_compile_ms,
                "run_time_ms": total_modernized_run_ms,
                "cases": modernized_cases,
            },
            gpp_exe=compiler_path,
            sanitizer_clean=sanitizer_clean,
            sanitizer_findings=all_sanitizer_findings if all_sanitizer_findings else None,
            memory_delta_kb=memory_delta_kb,
            test_cases_run=len(effective_input_cases),
            failed_case_index=None,
            performance_delta_ms=total_modernized_run_ms - total_original_run_ms,
        ).__dict__
