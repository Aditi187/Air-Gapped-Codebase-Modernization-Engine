import re
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from core.logger import get_logger
from core.differential_tester import compile_cpp_source

logger = get_logger(__name__)

GLOBAL_MODERNIZER_PROMPT = "\n\n".join(
    [
        "You are an ARCHITECT-LEVEL C++17 modernization engine.",
        "Your GLOBAL mission:",
        "1. Refactor the ENTIRE translation unit holistically for maximum C++17 compliance.",
        "2. Eliminate ALL malloc/free/char* patterns—replace with std::vector, std::string, std::unique_ptr.",
        "3. Add necessary #include directives (e.g., <memory>, <string>, <vector>) where required.",
        "4. Preserve the original program behavior exactly.",
    ]
)


def build_constraints(config) -> str:
    """
    Build a constraint string based on the configuration.
    """
    if not config.allow_signature_refactor:
        return (
            "CRITICAL: Function signatures MUST remain EXACTLY the same. "
            "Do NOT change return types, parameter types, or add std::optional. "
            "Keep the function interface identical to the original."
        )
    else:
        return (
            "AGGRESSIVE MODE: You may change signatures to use RAII types (std::unique_ptr, std::string, etc.), "
            "but ensure the behavior remains identical. std::optional may be used for optional return values."
        )


def auto_inject_includes(source: str) -> str:
    """
    Add missing C++ standard library includes based on usage.
    (Copied from modernizer.py to keep self‑contained; could be imported from a shared module.)
    """
    # Detect currently included headers
    includes = set()
    for match in re.finditer(r'#include\s*[<"]([^>"]+)[>"]', source):
        includes.add(match.group(1))

    needed = []
    if "std::unique_ptr" in source or "std::make_unique" in source:
        needed.append("#include <memory>")
    if "std::optional" in source:
        needed.append("#include <optional>")
    if "std::string" in source:
        needed.append("#include <string>")
    if "std::vector" in source:
        needed.append("#include <vector>")
    if "std::array" in source:
        needed.append("#include <array>")
    if "std::cout" in source or "std::cerr" in source:
        needed.append("#include <iostream>")

    # Filter out already present
    needed = [inc for inc in needed if inc[10:-1] not in includes]

    if not needed:
        return source

    # Insert after the last existing include (or at top if none)
    lines = source.splitlines()
    insert_idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#include"):
            insert_idx = i + 1

    for inc in reversed(needed):
        lines.insert(insert_idx, inc)

    return "\n".join(lines)


def global_refactor_node(state: ModernizationState) -> ModernizationState:
    logger.info("\n🌐 GLOBAL_MODERNIZER NODE")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("No context in state; cannot perform global refactor.")
        state["global_refactor_done"] = True
        return state

    config = context.config

    # Skip if signature refactoring is not allowed (global refactor often changes signatures)
    if not config.allow_signature_refactor:
        logger.info("Global refactor skipped (signature changes not allowed).")
        state["global_refactor_done"] = True
        return state

    source_to_improve = state.get("modernized_code") or state.get("last_working_code") or state.get("code") or ""
    if not source_to_improve.strip():
        logger.info("No source code to refactor.")
        state["global_refactor_done"] = True
        return state

    client = ModelClient(context)

    constraints = build_constraints(config)
    global_prompt = (
        f"{GLOBAL_MODERNIZER_PROMPT}\n\n"
        f"{constraints}\n\n"
        f"Current code:\n```cpp\n{source_to_improve}\n```"
    )

    try:
        raw_text = client.call(
            "You are a senior C++ engineer. Output only the refactored code, no explanations.",
            global_prompt,
            role="modernizer",
        )

        # Clean markdown fences
        cleaned_candidate = re.sub(r"```[^\n]*\n?", "", raw_text).replace("```", "").strip()

        if not cleaned_candidate:
            state["error_log"] = "Global modernizer returned empty output."
            state["global_refactor_done"] = True
            return state

        # Check for malloc (simple but effective gate)
        if re.search(r"\bmalloc\s*\(", cleaned_candidate):
            state["error_log"] = "❌ REJECTED: Global modernizer output contains malloc()."
            state["global_refactor_done"] = True
            return state

        # Auto‑inject includes to improve compile chances
        candidate_with_includes = auto_inject_includes(cleaned_candidate)

        # Compile test
        compile_result = compile_cpp_source(candidate_with_includes)
        if not compile_result.get("success"):
            # Option: try to inject includes more aggressively? Already did.
            # Log the error snippet for debugging (first few lines)
            error_msg = compile_result.get("error", "Unknown compilation error")
            state["error_log"] = f"Global modernizer code did not compile.\n{error_msg[:500]}"
            logger.warning(f"Global refactor failed compilation:\n{error_msg[:200]}...")
            state["global_refactor_done"] = True
            return state

        # Success
        state["modernized_code"] = candidate_with_includes
        state["last_working_code"] = candidate_with_includes
        state["error_log"] = ""  # clear any previous errors
        state["global_refactor_done"] = True

        logger.info("✅ Global refactor successful.")
        return state

    except Exception as exc:
        logger.exception("Global modernizer failed with exception")
        state["error_log"] = f"Global modernizer failed: {exc!r}"
        state["global_refactor_done"] = True
        return state