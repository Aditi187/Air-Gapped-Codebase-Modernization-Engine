"""
Semantic Guard Node
===================
Runs BEFORE the LLM transform step to detect structural and semantic risks in the
current modernization plan.  It never blocks the workflow—it only populates warning
fields in state so the repair node (and human reviewers) have richer context.

Checks performed (all rule-based, no LLM call):
  1. Container-consistency — manual size tracking alongside std::vector
  2. Ownership conflicts  — smart pointers mixed with delete/free
  3. Type conflicts        — raw arrays mixed with STL equivalents
  4. Behaviour changes     — parameter-count drift vs original signatures
  5. Destructor gap        — class with manual memory but no destructor

Results are written to:
  state["semantic_issues"]       – general issues list
  state["behavior_changes"]      – behaviour-altering changes
  state["type_conflicts"]        – type-system conflicts
  state["ownership_conflicts"]   – mixed ownership problems
"""

import re
from typing import Dict, List, Any

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from core.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Internal checkers
# ---------------------------------------------------------------------------

def _check_container_consistency(source: str) -> List[str]:
    """Detect std::vector used alongside manual size tracking."""
    issues: List[str] = []
    if "std::vector" not in source:
        return issues
    # Manual counter variable assignment (size = …, count = …, etc.)
    if re.search(r"\b(?:size|count|capacity|len)\b\s*=", source):
        if ".size()" not in source:
            issues.append(
                "std::vector detected with apparent manual size tracking; "
                "prefer .size() instead of a separate counter."
            )
    return issues


def _check_ownership_conflicts(source: str) -> List[str]:
    """Detect smart pointers mixed with manual deallocation."""
    conflicts: List[str] = []
    if "std::unique_ptr" in source and "delete " in source:
        conflicts.append(
            "std::unique_ptr used alongside manual `delete`; RAII handles deallocation."
        )
    if "std::shared_ptr" in source and "free(" in source:
        conflicts.append(
            "std::shared_ptr used alongside manual `free()`; RAII handles deallocation."
        )
    if "std::unique_ptr" in source and "malloc(" in source:
        conflicts.append(
            "std::unique_ptr used alongside `malloc()`; prefer std::make_unique."
        )
    return conflicts


def _check_type_conflicts(source: str) -> List[str]:
    """Detect raw arrays mixed with STL container types."""
    conflicts: List[str] = []
    has_raw_array = bool(re.search(r"\w+\s*\[\d*\]", source))
    has_stl = "std::vector" in source or "std::array" in source
    if has_raw_array and has_stl:
        conflicts.append(
            "Mix of raw C-arrays and STL containers detected; "
            "consider consistent migration to std::vector / std::array."
        )
    return conflicts


def _check_destructor_gap(source: str) -> List[str]:
    """Detect classes that allocate memory but lack a destructor."""
    issues: List[str] = []
    has_manual_alloc = "new " in source or "malloc(" in source
    has_class_or_struct = "class " in source or "struct " in source
    if has_manual_alloc and has_class_or_struct and "~" not in source:
        issues.append(
            "Class/struct with manual memory allocation detected but no destructor (~); "
            "risk of resource leak."
        )
    return issues


def _check_behaviour_changes(
    source: str,
    functions_info: List[Dict[str, Any]],
    original_signatures: Dict[str, str],
) -> List[str]:
    """
    Detect parameter-count drift by comparing current parse results against
    the original signatures captured at analysis time.
    """
    changes: List[str] = []
    for fn_info in functions_info:
        fn_name = str(fn_info.get("name", ""))
        orig_sig = original_signatures.get(fn_name, "")
        if not orig_sig:
            continue

        # Count parameters in original signature (rough heuristic: commas + 1
        # inside the first parenthesised group, guarded against no-param "()")
        orig_param_match = re.search(r"\(([^)]*)\)", orig_sig)
        if orig_param_match:
            orig_params_str = orig_param_match.group(1).strip()
            orig_param_count = 0 if orig_params_str in ("", "void") else (
                orig_params_str.count(",") + 1
            )
        else:
            orig_param_count = -1  # unknown

        current_params = fn_info.get("parameters", [])
        current_param_count = (
            len(current_params) if isinstance(current_params, list) else -1
        )

        if orig_param_count >= 0 and current_param_count >= 0:
            if orig_param_count != current_param_count:
                changes.append(
                    f"Function `{fn_name}`: parameter count changed "
                    f"(original {orig_param_count} → current {current_param_count})."
                )
    return changes


def _check_function_effect_preservation(
    functions_info: List[Dict[str, Any]],
    original_structure_snapshot: Dict[str, Any],
) -> List[str]:
    """
    Compare the set of functions present now vs the original snapshot.
    Missing functions are flagged as potential behaviour changes.
    """
    issues: List[str] = []
    orig_fns = set(original_structure_snapshot.get("function_names", []))
    current_fns = {str(f.get("name", "")) for f in functions_info if f.get("name")}
    missing = orig_fns - current_fns
    for fn in sorted(missing):
        issues.append(f"Function `{fn}` present in original but missing from current code.")
    return issues


# ---------------------------------------------------------------------------
# Node entry point
# ---------------------------------------------------------------------------

def semantic_guard_node(state: ModernizationState) -> ModernizationState:
    """
    Pre-flight semantic validation node.

    Populates state with categorised warning lists.
    Always returns state (never raises / never blocks the workflow).
    """
    logger.info("\n🛡️ SEMANTIC GUARD NODE")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.warning("No WorkflowContext — semantic guard skipped.")
        state["semantic_issues"] = []
        state["behavior_changes"] = []
        state["type_conflicts"] = []
        state["ownership_conflicts"] = []
        return state

    # Grab source code (prefer last working → original)
    source = (
        state.get("modernized_code")
        or state.get("last_working_code")
        or state.get("code")
        or ""
    )

    functions_info: List[Dict[str, Any]] = state.get("functions_info") or []
    original_signatures: Dict[str, str] = state.get("original_function_signatures") or {}
    original_structure: Dict[str, Any] = state.get("original_structure_snapshot") or {}

    # --- Run all checks ---
    semantic_issues: List[str] = []
    behavior_changes: List[str] = []
    type_conflicts: List[str] = []
    ownership_conflicts: List[str] = []

    # Container consistency
    semantic_issues.extend(_check_container_consistency(source))

    # Destructor gap
    semantic_issues.extend(_check_destructor_gap(source))

    # Ownership conflicts
    ownership_conflicts.extend(_check_ownership_conflicts(source))

    # Type conflicts
    type_conflicts.extend(_check_type_conflicts(source))

    # Behaviour changes: parameter-count drift
    behavior_changes.extend(
        _check_behaviour_changes(source, functions_info, original_signatures)
    )

    # Behaviour changes: missing functions
    behavior_changes.extend(
        _check_function_effect_preservation(functions_info, original_structure)
    )

    # --- Persist results ---
    state["semantic_issues"] = semantic_issues
    state["behavior_changes"] = behavior_changes
    state["type_conflicts"] = type_conflicts
    state["ownership_conflicts"] = ownership_conflicts

    # --- Summary logging ---
    total = (
        len(semantic_issues)
        + len(behavior_changes)
        + len(type_conflicts)
        + len(ownership_conflicts)
    )
    if total == 0:
        logger.info("✅ Semantic guard: no issues detected.")
    else:
        logger.warning(
            "⚠️ Semantic guard found %d issue(s): "
            "%d semantic, %d behaviour, %d type, %d ownership.",
            total,
            len(semantic_issues),
            len(behavior_changes),
            len(type_conflicts),
            len(ownership_conflicts),
        )
        for issue in semantic_issues:
            logger.warning("  [semantic]   %s", issue)
        for issue in behavior_changes:
            logger.warning("  [behaviour]  %s", issue)
        for issue in type_conflicts:
            logger.warning("  [type]       %s", issue)
        for issue in ownership_conflicts:
            logger.warning("  [ownership]  %s", issue)

    return state
