import json
from typing import List, Set, Dict, Any
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from core.logger import get_logger
from core.parser import CppParser

logger = get_logger(__name__)


def pruner_node(state: ModernizationState) -> ModernizationState:
    logger.info("\n✂️  PRUNER NODE")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("No workflow context; cannot prune.")
        return state

    config = context.config
    if not config.enable_pruner:
        logger.info("Pruner disabled by config.")
        return state

    # Language check
    language = state.get("language", "cpp").lower()
    is_cpp = language in {"cpp", "c++", "c++20", "c++23"}
    if not is_cpp:
        logger.info("Not a C++ file; skipping pruner.")
        return state

    # Load analysis data (could be string or dict)
    analysis = state.get("analysis")
    if not analysis:
        return state
    try:
        if isinstance(analysis, str):
            analysis_obj = json.loads(analysis)
        elif isinstance(analysis, dict):
            analysis_obj = analysis
        else:
            logger.warning("Unexpected analysis type; cannot prune.")
            return state
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse analysis JSON: {e}")
        return state

    # Get functions and orphans from state or analysis
    functions_info = state.get("functions_info") or analysis_obj.get("functions") or []
    orphans = state.get("orphans") or analysis_obj.get("orphans") or []
    if not functions_info or not orphans:
        logger.debug("No functions or orphans to prune.")
        return state

    # Determine which orphans to remove (skip "main")
    orphans_to_prune: Set[str] = {str(name) for name in orphans if str(name) != "main"}
    if not orphans_to_prune:
        return state

    # Locate byte spans of orphan functions that are not exported
    original_code = state.get("code", "")
    original_bytes = original_code.encode("utf-8")
    spans_to_remove: List[tuple] = []

    for fn in functions_info:
        name = str(fn.get("name") or "")
        if name not in orphans_to_prune:
            continue
        if fn.get("is_exported") or fn.get("has_external_linkage"):
            logger.debug(f"Skipping exported function {name}")
            continue
        start_byte = fn.get("start_byte")
        end_byte = fn.get("end_byte")
        if isinstance(start_byte, int) and isinstance(end_byte, int) and 0 <= start_byte <= end_byte <= len(original_bytes):
            spans_to_remove.append((start_byte, end_byte))
            logger.info(f"Will prune function {name} at bytes {start_byte}-{end_byte}")
        else:
            logger.warning(f"Invalid byte range for {name}")

    if not spans_to_remove:
        logger.debug("No removable spans found.")
        return state

    # Remove spans (sorted by start byte, non‑overlapping)
    spans_to_remove.sort(key=lambda pair: pair[0])
    new_chunks = []
    cursor = 0
    for start_byte, end_byte in spans_to_remove:
        if start_byte < cursor:
            continue  # skip overlapping span (shouldn't happen)
        if start_byte > cursor:
            new_chunks.append(original_bytes[cursor:start_byte])
        cursor = end_byte
    if cursor < len(original_bytes):
        new_chunks.append(original_bytes[cursor:])

    pruned_code = b"".join(new_chunks).decode("utf-8", errors="strict")

    # Optionally remove #include lines that reference removed function names
    if getattr(config, "pruner_remove_includes", False):
        removed_lower = {name.lower() for name in orphans_to_prune}
        lines = []
        for line in pruned_code.splitlines():
            stripped = line.strip()
            if stripped.startswith("#include"):
                # Check if the include contains any orphan function name
                if any(name in stripped.lower() for name in removed_lower):
                    logger.debug(f"Removing include line: {line}")
                    continue
            lines.append(line)
        pruned_code = "\n".join(lines)

    # Update state
    state["code"] = pruned_code
    state["last_working_code"] = pruned_code

    # Re‑parse the pruned code to get new function info
    try:
        pruned_project_map = CppParser().parse_string(pruned_code)
        state["project_map"] = dict(pruned_project_map)
        f_list = list(pruned_project_map.get("functions", {}).values()) if isinstance(pruned_project_map.get("functions"), dict) else []
        state["functions_info"] = f_list
        state["functions_index"] = {str(f.get("name", "")): f for f in f_list if f.get("name")}
    except Exception as e:
        logger.warning(f"Failed to re‑parse pruned code: {e}")

    # Remove orphan functions from original signatures map if it exists
    original_sigs = state.get("original_function_signatures")
    if original_sigs and isinstance(original_sigs, dict):
        for name in orphans_to_prune:
            if name in original_sigs:
                del original_sigs[name]
        state["original_function_signatures"] = original_sigs

    # Update modernization order
    existing_order = state.get("modernization_order") or []
    state["modernization_order"] = [name for name in existing_order if name not in orphans_to_prune]

    logger.info(f"✂️  Pruned {len(spans_to_remove)} orphan function(s)")
    return state