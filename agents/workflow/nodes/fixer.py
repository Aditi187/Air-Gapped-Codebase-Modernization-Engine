import re
from typing import Dict, Any, Tuple

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from core.logger import get_logger
from core.differential_tester import compile_cpp_source

logger = get_logger(__name__)

_CODE_FENCE_RE = re.compile(r"```(?:cpp|c\+\+)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_code(text: str) -> str:
    if not text:
        return ""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()


def build_error_context_snippets(error_text: str, code_snapshot: str) -> str:
    line_numbers = set()


    for match in re.finditer(r":(\d+)(?::\d+)?:", error_text):
        try:
            line_numbers.add(int(match.group(1)))
        except ValueError:
            continue

    lines = sorted(line_numbers)
    if not lines:
        return ""

    code_lines = code_snapshot.splitlines()
    snippets = []

    for ln in lines[:3]:  # limit to avoid huge prompt
        start = max(1, ln - 2)
        end = min(len(code_lines), ln + 2)

        snippet_lines = []
        for idx in range(start, end + 1):
            if 1 <= idx <= len(code_lines):
                snippet_lines.append(f"{idx:4d}: {code_lines[idx - 1]}")

        if snippet_lines:
            snippets.append(f"Line {ln}:\n" + "\n".join(snippet_lines))

    return "\n\n".join(snippets)


def is_valid_cpp_code(code: str) -> bool:
    if not code or len(code.strip()) < 20:
        return False

    
    if not any(token in code for token in [";", "{", "}", "#include"]):
        return False

    return True


def attempt_compiler_error_autofix(
    state: ModernizationState,
    compile_errors: str
) -> Tuple[str, Dict[str, Any], str]:

    code_snapshot = str(state.get("modernized_code") or "")
    if not code_snapshot.strip():
        return "", {}, "no code available for autofix"

    context: WorkflowContext = state.get("context")
    if context is None:
        return "", {}, "missing workflow context"

    tracer = context.tracer
    span = tracer.start_span(
        name="compiler_autofix",
        input_payload={"error_chars": len(compile_errors or "")},
        span_type="generation"
    )

    try:
        client = ModelClient(context)

  
        error_context = build_error_context_snippets(compile_errors, code_snapshot)

        autofix_prompt_parts = [
            "Fix this full C++17 file based on compiler errors.",
            "Output ONLY corrected C++ code (no explanation, no markdown).",
            "Preserve function names and behavior.",
            "Compiler errors:",
            compile_errors,
        ]

        if error_context:
            autofix_prompt_parts.extend([
                "Error context:",
                error_context
            ])

        autofix_prompt_parts.extend([
            "Code:",
            "```cpp",
            code_snapshot,
            "```"
        ])

        autofix_prompt = "\n\n".join(autofix_prompt_parts)

        raw_text = client.call(
            "You are AGENT 3: FIXER. Fix ONLY compiler errors minimally. Output valid C++17.",
            autofix_prompt,
            role="fixer"
        )

        if not raw_text:
            tracer.finish_span(span, err=RuntimeError("empty LLM response"))
            return "", {}, "compile-autofix returned empty output"

        candidate = extract_code(raw_text)


        if not is_valid_cpp_code(candidate):
            tracer.finish_span(span, err=RuntimeError("invalid code"))
            return "", {}, "compile-autofix returned invalid code"


        retry_verification = compile_cpp_source(candidate)

        if not retry_verification.get("success"):
            tracer.finish_span(
                span,
                output="failed",
                err=RuntimeError("autofix did not compile")
            )
            return "", retry_verification, "compile-autofix did not compile"

        tracer.finish_span(span, output="success")

        return candidate, retry_verification, ""

    except Exception as e:
        logger.exception("Fixer exception")
        tracer.finish_span(span, err=e)
        return "", {}, f"fixer failed: {e}"