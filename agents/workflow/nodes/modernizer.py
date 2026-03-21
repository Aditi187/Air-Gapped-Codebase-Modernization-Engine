import re
import difflib
from typing import Tuple, List, Dict, Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.infra.model_provider import ModelClient
from agents.workflow.validation.similarity import compute_function_diff_ratio
from agents.workflow.validation.structure import strict_gate
from core.logger import get_logger
from core.differential_tester import compile_cpp_source

logger = get_logger(__name__)

def clean_model_code_block(text: str) -> str:
    """Remove markdown code fences and strip whitespace."""
    text = re.sub(r"```[^\n]*\n?", "", text)
    text = text.replace("```", "")
    return text.strip()

def process_function_modernization(
    function_source: str, 
    current_function_name: str,
    original_signature: str,
    original_param_count: int,
    state: ModernizationState,
    client: ModelClient,
    context: WorkflowContext
) -> Tuple[str, str, int]:
    """
    Attempt to modernize a single function.

    Returns:
        tuple: (candidate_code, error_reason, confidence_score)
    """
    # Get or initialize function memory
    mem = context.get_function_memory(current_function_name)
    if mem is None:
        mem = {"stagnation_count": 0, "attempts": 0, "best_version": ""}
        context.update_function_memory(current_function_name, 0, 0, "")

    # Check stagnation limit
    if mem.get("stagnation_count", 0) >= context.config.stagnant_score_limit:
        return function_source, f"Stagnation limit reached ({mem['stagnation_count']})", 0

    # Build prompt based on whether we have a previous error
    prompt_parts = []
    error_log = state.get("error_log")
    if error_log and isinstance(error_log, str):
        prompt_parts = [
            "RETRY MODE: Fix the following compiler errors.",
            "Make MINIMAL EDITS to fix the errors. Do NOT attempt further deep modernization. Just make it compile.",
            f"Compiler feedback from previous attempt:\n{error_log}\n",
            f"Function name: {current_function_name}",
            "Target function:\n```cpp\n" + function_source + "\n```"
        ]
        # Include diff to the best version if available
        best = mem.get("best_version")
        if best and best != function_source:
            diff = list(difflib.unified_diff(
                function_source.splitlines(),
                best.splitlines(),
                lineterm=""
            ))
            if diff:
                prompt_parts.append(
                    "For context, here was the best modernized version so far:\n" +
                    "\n".join(diff[:20])
                )
    else:
        # Initial deep modernization
        prompt_parts = [
            "Rewrite ONLY this function to deeply modern C++17 while preserving behavior.",
            "Prefer RAII, std::unique_ptr, std::string, nullptr, and safer interfaces.",
            f"Function name: {current_function_name}",
            "Target function:\n```cpp\n" + function_source + "\n```"
        ]

    full_prompt = "\n\n".join(prompt_parts)

    try:
        raw_text = client.call(
            "You are a C++17 modernization engine. Return ONLY valid C++17 code.", 
            full_prompt, 
            role="modernizer"
        )
        cleaned_candidate = clean_model_code_block(raw_text).strip()
        if not cleaned_candidate:
            return function_source, "LLM returned empty output", 0

        # ---- Confidence scoring ----
        rejection_reason = ""
        confidence = 0

        # 1. Diff ratio guard
        diff_ratio = compute_function_diff_ratio(function_source, cleaned_candidate)
        if diff_ratio > context.config.max_function_diff_ratio:
            rejection_reason = f"confidence gate: diff ratio too high ({diff_ratio:.2f})"
        else:
            # 2. Structural guard (signature, etc.)
            strict_errors = strict_gate(
                cleaned_candidate,
                current_function_name,
                original_signature,
                context.config
            )
            if strict_errors:
                rejection_reason = "; ".join(strict_errors)

        if rejection_reason:
            # Update memory with penalty
            context.update_function_memory(
                current_function_name,
                score=-1,
                attempt_count=mem.get("attempts", 0) + 1,
                best_version=""
            )
            return function_source, rejection_reason, 0

        # 3. Optional compilation test (lightweight if possible)
        #    This adds confidence but may be expensive.
        compile_result = compile_cpp_source(cleaned_candidate)
        if compile_result.get("success"):
            confidence = 100
        else:
            confidence = 50  # passes structure but fails isolated compile

        # Update memory with success
        context.update_function_memory(
            current_function_name,
            score=confidence,
            attempt_count=mem.get("attempts", 0) + 1,
            best_version=cleaned_candidate
        )

        return cleaned_candidate, "", confidence

    except Exception as e:
        logger.error(f"LLM call for {current_function_name} failed: {e}")
        return function_source, f"LLM Call Failed: {e}", 0


def replace_function_by_span(source_code: str, start_byte: int, end_byte: int, replacement: str) -> str:
    """Replace a byte range in source_code with replacement text."""
    source_bytes = source_code.encode("utf-8")
    if start_byte < 0 or end_byte > len(source_bytes):
        raise ValueError(f"Byte range {start_byte}:{end_byte} out of bounds for source of length {len(source_bytes)}")
    prefix = source_bytes[:start_byte]
    suffix = source_bytes[end_byte:]
    replacement_bytes = replacement.encode("utf-8")
    updated_bytes = prefix + replacement_bytes + suffix
    return updated_bytes.decode("utf-8", errors="strict")


def auto_inject_includes(source: str) -> str:
    """Add missing C++ standard library includes based on usage."""
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
    needed = [inc for inc in needed if inc[10:-1] not in includes]  # extract header name from "#include <...>"

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


def modernizer_node(state: ModernizationState) -> ModernizationState:
    logger.info("\n⚙️ MODERNIZER NODE (WITH PARALLEL PROCESSING)")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("No context in state")
        return state

    # Get the latest source code
    source_to_improve = (
        state.get("modernized_code") or
        state.get("last_working_code") or
        state.get("code") or
        ""
    )
    if not source_to_improve.strip():
        logger.warning("No source code to modernize")
        return state

    functions_info = state.get("functions_info") or []
    if not functions_info:
        logger.warning("No function info available; cannot modernize")
        return state

    modernization_order = state.get("modernization_order") or []
    current_index = state.get("current_function_index", 0)

    if current_index >= len(modernization_order):
        # All functions processed
        state["modernized_code"] = source_to_improve
        state["attempt_count"] = state.get("attempt_count", 0) + 1
        return state

    batch_size = context.config.batch_size
    target_functions = modernization_order[current_index : current_index + batch_size]

    logger.info(f"Processing batch of {len(target_functions)} functions in parallel...")
    client = ModelClient(context)

    # Prepare function extraction using the current source and function info
    # (functions_info is from the latest parse, so offsets are correct)
    futures = {}
    with ThreadPoolExecutor(max_workers=batch_size) as executor:
        for func_name in target_functions:
            # Find the function info in the current functions_info
            fn_info = None
            for f in functions_info:
                if str(f.get("name")) == func_name:
                    fn_info = f
                    break
            if not fn_info:
                logger.warning(f"Function {func_name} not found in current functions_info")
                continue

            start_byte = fn_info.get("start_byte")
            end_byte = fn_info.get("end_byte")
            if not isinstance(start_byte, int) or not isinstance(end_byte, int):
                logger.warning(f"Invalid byte offsets for {func_name}")
                continue

            # Extract the function source from the current source
            try:
                source_bytes = source_to_improve.encode("utf-8")
                function_source = source_bytes[start_byte:end_byte].decode("utf-8", errors="strict")
            except Exception as e:
                logger.error(f"Failed to extract {func_name}: {e}")
                continue

            original_signature = state.get("original_function_signatures", {}).get(func_name, "")
            original_params = fn_info.get("parameters", [])
            original_param_count = len(original_params) if isinstance(original_params, list) else -1

            future = executor.submit(
                process_function_modernization,
                function_source,
                func_name,
                original_signature,
                original_param_count,
                state,
                client,
                context
            )
            futures[future] = (func_name, start_byte, end_byte)

    # Process results
    results = []   # (start_byte, end_byte, candidate)
    error_logs = []
    for future in as_completed(futures):
        func_name, start_byte, end_byte = futures[future]
        candidate, error_reason, confidence = future.result()
        if not error_reason and candidate != function_source:
            results.append((start_byte, end_byte, candidate))
            logger.debug(f"{func_name} modernized (confidence {confidence})")
        else:
            if error_reason:
                error_logs.append(f"{func_name}: {error_reason}")
                logger.warning(f"{func_name} failed: {error_reason}")
            else:
                logger.debug(f"{func_name} unchanged")

    # Apply replacements in reverse order to keep offsets valid
    new_source = source_to_improve
    for start_byte, end_byte, candidate in sorted(results, key=lambda x: x[0], reverse=True):
        try:
            new_source = replace_function_by_span(new_source, start_byte, end_byte, candidate)
        except Exception as e:
            logger.error(f"Failed to replace function at {start_byte}:{end_byte}: {e}")

    # Auto‑inject missing includes
    new_source = auto_inject_includes(new_source)

    # Update state
    state["modernized_code"] = new_source
    if error_logs:
        state["error_log"] = "\n".join(error_logs)
    else:
        # Clear error log if no errors remain (optional)
        state.pop("error_log", None)

    # Re‑parse to keep function info up‑to‑date for next batches
    try:
        from core.parser import CppParser
        new_project_map = CppParser().parse_string(new_source)
        new_functions = list(new_project_map.get("functions", {}).values())
        if new_functions:
            state["functions_info"] = new_functions
            # Rebuild index for quick lookup (optional)
            state["functions_index"] = {str(f.get("name", "")): f for f in new_functions if f.get("name")}
    except Exception as e:
        logger.warning(f"Failed to re-parse code after modernizer batch: {e}")

    state["current_function_index"] = current_index + len(target_functions)
    state["attempt_count"] = state.get("attempt_count", 0) + 1

    return state