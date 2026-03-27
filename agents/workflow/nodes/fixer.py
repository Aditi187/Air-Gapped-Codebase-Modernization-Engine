import re
import logging
from typing import Dict, Any, Tuple

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from core.differential_tester import compile_cpp_source

logger = logging.getLogger(__name__)

_CODE_FENCE_RE = re.compile(r"```(?:cpp|c\+\+)?\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)

def extract_code(text: str) -> str:
    """
    Extracts C++ code from markdown code fences, or returns the text as-is if no fence is found.
    """
    if not text:
        return ""
    match = _CODE_FENCE_RE.search(text)
    if match:
        return match.group(1).strip()
    return text.strip()

def build_error_context_snippets(error_text: str, code_snapshot: str) -> str:
    """
    Builds code context snippets around error line numbers for LLM prompts.
    """
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
    """
    Checks if the code is plausibly valid C++ (basic heuristics).
    """
    if not code or len(code.strip()) < 20:
        return False
    if not any(token in code for token in [";", "{", "}", "#include"]):
        return False
    return True

def attempt_compiler_error_autofix(
    state: ModernizationState,
    compile_errors: str
) -> Tuple[str, Dict[str, Any], str]:
    """
    Attempts to fix compiler errors using the LLM, with robust error handling and logging.
    Returns (fixed_code, verification_result, reason).
    """
    code_snapshot = str(state.get("modernized_code") or "")
    if not code_snapshot.strip():
        logger.error("[fixer] No code available for autofix.")
        return "", {}, "no code available for autofix"
    context = state.get("context")
    if context is None or not isinstance(context, WorkflowContext):
        logger.error("[fixer] Missing workflow context.")
        return "", {}, "missing workflow context"
    
    try:
        client = ModelClient(context)
        error_context = build_error_context_snippets(compile_errors, code_snapshot)
        autofix_prompt_parts = [
            "Fix this full C++17 file based on compiler errors.",
            "MANDATORY REQUIREMENTS:",
            "1. Output ONLY corrected C++ code.",
            "2. Use 'mutable' for logical const-ness (e.g., mutable std::ofstream) to allow logging from const methods.",
            "3. Use 'std::string_view' for read-only string parameters.",
            "4. Use thread-safe 'localtime_s' (Windows style) for time conversion.",
            "5. Replicate legacy formatting character-for-character relative to original output.",
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
            logger.error("[fixer] LLM returned empty output.")
            return "", {}, "compile-autofix returned empty output"
            
        candidate = extract_code(raw_text)
        if not is_valid_cpp_code(candidate):
            logger.error("[fixer] LLM returned invalid code.")
            return "", {}, "compile-autofix returned invalid code"
            
        retry_verification = compile_cpp_source(candidate)
        if not retry_verification.get("success"):
            logger.error("[fixer] LLM fix did not compile.")
            return "", retry_verification, "compile-autofix did not compile"
            
        logger.info("[fixer] LLM fix successful.")
        return candidate, retry_verification, ""
    except Exception as e:
        logger.exception("[fixer] Exception during autofix.", exc_info=True)
        return "", {}, f"fixer failed: {e}"

def fixer_node(state: ModernizationState) -> ModernizationState:
    """
    Fixer node: Attempts to fix compiler errors reported in state["error_log"].
    Applies LLM-based fix, robust error handling, and logs all outcomes.
    """
    logger.info(">>> [FIXER] Entering error repair phase based on compiler feedback")
    error_log = state.get("error_log", "")
    if not error_log:
        logger.warning("[fixer] No error log found for fixer – skipping.")
        return state
        
    fixed_code, result, reason = attempt_compiler_error_autofix(state, error_log)
    if fixed_code and result.get("success"):
        logger.info(">>> [FIXER] Repair successful: Compiler errors resolved.")
        state["modernized_code"] = fixed_code
        state["verification_result"] = result
        state["error_log"] = ""
    else:
        logger.warning(f"[fixer] Failed to generate a working fix: {reason}")
        
    return state