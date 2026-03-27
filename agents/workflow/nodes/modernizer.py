import logging
from typing import Dict, Any, Optional

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from core.rule_modernizer import RuleModernizer

logger = logging.getLogger(__name__)

def extract_code(text: str) -> str:
    """
    Extracts code from markdown fences if present.
    """
    match = re.search(r"```(?:cpp|c\+\+)?\s*\n?(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()

import re

def modernizer_node(state: ModernizationState) -> ModernizationState:
    """
    Phase 4 modernizer.
    Using LLM with 'perfect' C++17 prompts.
    """
    logger.info(">>> [MODERNIZER] Executing C++17 transformation phase via LLM")
    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("[modernizer] missing workflow context")
        return state

    source = state.get("code", "")
    client = ModelClient(context)
    
    prompt = (
        "Modernize this C++ file to PERFECT C++17 standards.\n"
        "MANDATORY REQUIREMENTS:\n"
        "1. Use RAII for all resource management (smart pointers, containers, file streams).\n"
        "2. Use 'mutable' for logical const-ness in member variables (e.g., mutable std::ofstream) to allow logging from const methods.\n"
        "3. Use 'std::string_view' for read-only string parameters for maximum efficiency.\n"
        "4. Use thread-safe 'localtime_s' (Windows style) or 'localtime_r' (POSIX style) for time conversion.\n"
        "5. Replicate legacy formatting character-for-character relative to original output (check printf/fprintf calls).\n"
        "6. Use nullptr, auto, and range-based for loops.\n"
        "Return ONLY valid C++17 code, no markdown fences, no explanation.\n\n"
        f"Source to Modernize:\n```cpp\n{source}\n```"
    )

    try:
        raw_output = client.call(
            "You are AGENT 2: MODERNIZER. Convert legacy C++ to idiomatic C++17. Output valid code only.",
            prompt,
            role="modernizer"
        )
        if raw_output:
            modernized = extract_code(raw_output)
            state["modernized_code"] = modernized
            logger.info(">>> [MODERNIZER] LLM-based modernization successful.")
        else:
            logger.warning(">>> [MODERNIZER] LLM returned empty output; invoking RuleModernizer safety fallback.")
            rm = RuleModernizer()
            state["modernized_code"] = rm.modernize(source)
    except Exception as e:
        logger.error(f"[modernizer] LLM call failed: {e}. Using RuleModernizer fallback.")
        rm = RuleModernizer()
        state["modernized_code"] = rm.modernize(source)

    return state