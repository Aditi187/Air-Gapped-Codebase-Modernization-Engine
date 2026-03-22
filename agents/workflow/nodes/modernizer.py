"""
Modernizer node — applies deterministic C++17 transformations to the full source file.
Production-grade: minimal code, maximum efficiency, no LLM required in air-gapped mode.
"""
import logging
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from core.rule_modernizer import RuleModernizer

logger = logging.getLogger(__name__)

_rule_engine = RuleModernizer()


def modernizer_node(state: ModernizationState) -> ModernizationState:
    logger.info("\n⚙️  MODERNIZER NODE")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("No WorkflowContext in state")
        return state

    source = (
        state.get("modernized_code")
        or state.get("last_working_code")
        or state.get("code")
        or ""
    ).strip()

    if not source:
        logger.warning("No source code to modernize")
        return state

    # --- Try LLM first (if configured), else fall back to rule engine ---
    client = ModelClient(context)
    modernized = None

    if context.config.use_llm:
        prompt = (
            "Rewrite this entire C++ file to modern C++17.\n"
            "Use RAII, std::unique_ptr, std::string, nullptr, range-based for, auto.\n"
            "Return ONLY valid C++ code, no explanation, no markdown fences.\n\n"
            f"```cpp\n{source}\n```"
        )
        try:
            raw = client.call(
                "You are a C++17 modernization engine. Return ONLY valid C++17 code.",
                prompt,
                role="modernizer",
            )
            if raw and raw.strip() and raw.strip() != "NO_CHANGE":
                modernized = raw.strip()
                logger.info("LLM modernization applied.")
        except Exception as e:
            logger.warning(f"LLM call failed, falling back to rules: {e}")

    if not modernized:
        # Deterministic rule engine — always safe
        modernized = _rule_engine.modernize_text(source)
        logger.info("RuleModernizer applied.")

    # Auto-inject any missing standard headers
    modernized = _auto_inject_includes(modernized)

    state["modernized_code"] = modernized
    state["attempt_count"] = state.get("attempt_count", 0) + 1
    # Mark all functions as processed so the orchestrator moves on
    order = state.get("modernization_order") or []
    state["current_function_index"] = len(order)

    return state


def _auto_inject_includes(source: str) -> str:
    import re
    existing = set(re.findall(r'#include\s*[<"]([^>"]+)[>"]', source))
    needed = []
    checks = {
        "memory":   ("std::unique_ptr", "std::shared_ptr", "std::make_unique"),
        "string":   ("std::string",),
        "vector":   ("std::vector",),
        "array":    ("std::array",),
        "optional": ("std::optional",),
        "iostream": ("std::cout", "std::cerr", "std::cin"),
    }
    for header, tokens in checks.items():
        if header not in existing and any(t in source for t in tokens):
            needed.append(f"#include <{header}>")
    if not needed:
        return source
    lines = source.splitlines()
    idx = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("#include"):
            idx = i + 1
    for inc in reversed(needed):
        lines.insert(idx, inc)
    return "\n".join(lines)