# tools/mcp_server.py

import os
import re
import json
import glob
import shlex
import subprocess
import threading

from pathlib import Path
from typing import Dict, List, Any

from dotenv import load_dotenv
from fastmcp import FastMCP

from core.logger import get_logger
from core.parser import CppParser
from core.openai_bridge import OpenAIBridge


# ============================================================
# CONFIGURATION
# ============================================================

logger = get_logger(__name__)

load_dotenv()

ROOT = Path.cwd().resolve()
ROOT_STR = str(ROOT)

CPP_EXTENSIONS = (".cpp", ".cc", ".cxx", ".hpp", ".h")

TIMEOUT = 30

ALLOWED_COMPILERS = {
    "g++",
    "gcc",
    "clang++",
    "clang",
    "c++"
}

MAX_ERROR_SIZE = 2000


# ============================================================
# INIT
# ============================================================

mcp = FastMCP("cpp-modernizer")

parser = CppParser()

llm = OpenAIBridge.from_env(log_fn=logger.info)


# ============================================================
# SANDBOX
# ============================================================

def safe_path(path: str) -> str:

    p = Path(path).resolve()

    if not str(p).startswith(ROOT_STR):

        raise ValueError("Path outside project")

    return str(p)


def result(status: str, **kwargs):

    data = {"status": status}

    data.update(kwargs)

    return json.dumps(data, indent=2)


# ============================================================
# PROJECT INDEX
# ============================================================

class ProjectIndex:

    def __init__(self):

        self.types: Dict[str, str] = {}

        self.functions: Dict[str, Dict] = {}

        self.file_map: Dict[str, float] = {}

        self.lock = threading.Lock()


    def scan_file(self, file_path: str):

        try:

            parsed = parser.parse_file(file_path)

        except Exception:

            return

        with self.lock:

            self.file_map[file_path] = os.path.getmtime(file_path)

            for t, code in parsed.get("type_definitions", {}).items():

                self.types[t] = code

            for fqn, meta in parsed.get("functions", {}).items():

                self.functions[fqn] = meta


    def build_index(self):

        for ext in CPP_EXTENSIONS:

            pattern = str(ROOT / "**" / f"*{ext}")

            for f in glob.glob(pattern, recursive=True):

                self.scan_file(f)


    def update_if_needed(self):

        for f in list(self.file_map):

            try:

                if os.path.getmtime(f) != self.file_map[f]:

                    self.scan_file(f)

            except OSError:

                pass


INDEX = ProjectIndex()

INDEX.build_index()


# ============================================================
# COMPILER
# ============================================================

def validate_compiler(cmd):

    exe = Path(cmd[0]).name.lower()

    exe = exe.replace(".exe", "")

    exe = re.sub(r"-\d+(\.\d+)*$", "", exe)

    if exe not in ALLOWED_COMPILERS:

        return f"compiler not allowed: {exe}"


def run_process(cmd, cwd=None):

    try:

        r = subprocess.run(

            cmd,

            cwd=cwd,

            capture_output=True,

            text=True,

            timeout=TIMEOUT

        )

        return {

            "code": r.returncode,

            "stdout": r.stdout,

            "stderr": r.stderr

        }

    except subprocess.TimeoutExpired:

        return {"error": "timeout"}

    except Exception as e:

        return {"error": str(e)}


def parse_errors(text: str):

    pattern = re.compile(

        r'([^:\n]+):(\d+):(?:\d+:)?\s*(fatal error|error|warning):\s*(.*)'

    )

    errors = []

    for m in pattern.finditer(text):

        errors.append({

            "file": m.group(1),

            "line": int(m.group(2)),

            "message": m.group(4)

        })

    if not errors:

        errors.append({

            "file": "<unknown>",

            "line": 0,

            "message": text[:MAX_ERROR_SIZE]

        })

    return errors


# ============================================================
# TYPE BUNDLE
# ============================================================

PRIMITIVES = {

    "int","float","double","char","bool",

    "void","auto","const","return",

    "if","else","for","while","std"

}


def extract_identifiers(text: str):

    tokens = re.findall(r'[A-Za-z_]\w*', text)

    return [t for t in tokens if t not in PRIMITIVES]


def type_bundle(code: str):

    ids = extract_identifiers(code)

    bundle = {}

    for t in ids:

        if t in INDEX.types:

            bundle[t] = INDEX.types[t]

    return bundle


# ============================================================
# FILE TOOLS
# ============================================================

@mcp.tool()
def read_code(file_path: str) -> str:

    try:

        p = safe_path(file_path)

        content = Path(p).read_text()

        return result("success", content=content)

    except Exception as e:

        return result("error", message=str(e))


@mcp.tool()
def write_code(file_path: str, content: str) -> str:

    try:

        p = safe_path(file_path)

        Path(p).parent.mkdir(parents=True, exist_ok=True)

        Path(p).write_text(content)

        INDEX.scan_file(p)

        return result("success", bytes=len(content))

    except Exception as e:

        return result("error", message=str(e))


# ============================================================
# COMPILER TOOLS
# ============================================================

@mcp.tool()
def run_compiler(command: str, cwd: str | None = None) -> str:

    try:

        cmd = shlex.split(command)

        err = validate_compiler(cmd)

        if err:

            return result("error", message=err)

        cwd_path = safe_path(cwd) if cwd else None

        r = run_process(cmd, cwd_path)

        if "error" in r:

            return result("error", message=r["error"])

        return result(

            "success" if r["code"] == 0 else "error",

            stdout=r["stdout"],

            stderr=r["stderr"],

            exit_code=r["code"]

        )

    except Exception as e:

        return result("error", message=str(e))


@mcp.tool()
def get_compilation_errors(command: str) -> str:

    r = json.loads(run_compiler(command))

    if r["status"] == "success":

        return result("success", errors=[])

    text = r.get("stdout","") + r.get("stderr","")

    return result(

        "error",

        errors=parse_errors(text)

    )


# ============================================================
# SEMANTIC CONTEXT
# ============================================================
@mcp.tool()
def get_context_for_function(file_path: str, function_fqn: str) -> str:

    try:

        p = safe_path(file_path)

        INDEX.update_if_needed()

        parsed = parser.parse_file(p)

        functions = parsed.get("functions", {})

        if function_fqn not in functions:

            return result(
                "error",
                available=list(functions.keys())
            )

        ctx = functions[function_fqn]

        code_text = ctx["signature"] + "\n" + ctx["body"]

        types = type_bundle(code_text, parsed)

        include_requirements = parsed.get(
            "include_requirements",
            {}
        ).get(function_fqn, [])

        return result(

            "success",

            context=ctx,

            types=types,

            include_requirements=include_requirements,

            dependency_calls=ctx.get("calls", []),

            complexity=ctx.get("complexity", 0),

            legacy_patterns=ctx.get("legacy_patterns", [])
        )

    except Exception as e:

        return result("error", message=str(e))



# ============================================================
# INCLUDE MANAGEMENT
# ============================================================

@mcp.tool()
def get_include_graph(file_path: str) -> str:

    try:

        p = safe_path(file_path)

        parsed = parser.parse_file(p)

        return result(

            "success",

            includes=parsed.get("headers", [])

        )

    except Exception as e:

        return result("error", message=str(e))


@mcp.tool()
def add_header(file_path: str, header: str) -> str:

    try:

        p = safe_path(file_path)

        code = Path(p).read_text()

        include = f"#include {header}"

        if include in code:

            return result("success", message="exists")

        lines = code.splitlines()

        idx = 0

        for i,l in enumerate(lines):

            if l.startswith("#include"):

                idx = i + 1

        lines.insert(idx, include)

        Path(p).write_text("\n".join(lines))

        return result("success", added=include)

    except Exception as e:

        return result("error", message=str(e))


if __name__ == "__main__":

    logger.info("MCP ready for multi-file modernization")

    mcp.run()