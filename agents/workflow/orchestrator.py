import os
from typing import Any, Dict, Optional

from langgraph.graph import StateGraph, END

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.nodes.analyzer import analyzer_node
from agents.workflow.nodes.planner import planner_node
from agents.workflow.nodes.modernizer import modernizer_node
# global_refactor_node is missing; stubbing it out.
def global_refactor_node(state: ModernizationState) -> ModernizationState:
    logger.warning("global_refactor_node skipped (file missing)")
    state["global_refactor_done"] = True
    return state
from agents.workflow.nodes.verifier import verifier_node

import logging

logger = logging.getLogger(__name__)


def surgical_router(state: ModernizationState) -> str:
    """Route after verification: continue to next function, try global refactor, or finish."""
    verification_success = bool(state.get("verification_result", {}).get("success"))
    attempt_count = int(state.get("attempt_count", 0))
    current_index = int(state.get("current_function_index", 0))
    modernization_order = state.get("modernization_order") or []

    context: WorkflowContext = state.get("context")
    config = context.config

    if verification_success:
        no_remaining_functions = current_index >= len(modernization_order)
        global_refactor_done = bool(state.get("global_refactor_done", False))

        if no_remaining_functions and not global_refactor_done and config.allow_signature_refactor:
            return "global_modernizer"

        if current_index < len(modernization_order):
            # Reset attempt counter for the next function
            state["attempt_count"] = 0
            state["error_log"] = ""
            return "transform"

        return "end"

    # Verification failed
    if attempt_count >= config.max_attempts:
        # Move to the next function, marking partial success for this one
        state["current_function_index"] = current_index + 1
        state["partial_success"] = True
        return "end"

    # Retry current function
    return "transform"


def build_workflow() -> StateGraph:
    """Build the LangGraph workflow."""
    workflow = StateGraph(ModernizationState)

    workflow.add_node("analyze", analyzer_node)
    workflow.add_node("plan", planner_node)
    workflow.add_node("transform", modernizer_node)
    workflow.add_node("global_modernizer", global_refactor_node)
    workflow.add_node("verify", verifier_node)

    workflow.add_edge("analyze", "plan")
    workflow.add_edge("plan", "transform")
    workflow.add_edge("transform", "verify")
    workflow.add_edge("global_modernizer", "verify")

    workflow.add_conditional_edges(
        "verify",
        surgical_router,
        {
            "transform": "transform",
            "global_modernizer": "global_modernizer",
            "end": END
        }
    )

    workflow.set_entry_point("analyze")
    return workflow.compile()


def run_modernization_workflow(
    code: str,
    language: str = "c++17",
    source_file: str = "",
    output_file_path: str = "",
    aggressive_mode: bool = False,
    config_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Run the entire modernization pipeline.

    Args:
        code: The source code to modernize.
        language: The source language (e.g., "c++17").
        source_file: Path to the original source file (used for differential testing).
        output_file_path: Where to save the modernized code (if empty, auto‑generated).
        aggressive_mode: If True, allow signature refactoring.
        config_overrides: Dictionary of config fields to override.

    Returns:
        The final ModernizationState (as a dict).
    """
    logger.info("=" * 60)
    logger.info("🚀 STARTING CODE MODERNIZATION WORKFLOW (MODULAR)")
    logger.info("=" * 60)

    # Create context with optional overrides
    context = WorkflowContext()
    if config_overrides:
        for key, value in config_overrides.items():
            if hasattr(context.config, key):
                setattr(context.config, key, value)
                logger.debug(f"Overriding config.{key} = {value}")
            else:
                logger.warning(f"Unknown config override key: {key}")

    # Apply aggressive mode
    if aggressive_mode:
        context.config.allow_signature_refactor = True
        context.config.modernization_mode = "aggressive"
        logger.info("Aggressive mode enabled (signature refactoring allowed)")

    logger.info("Mode: %s", context.config.modernization_mode.upper())

    source_abs = os.path.abspath(source_file) if source_file else ""
    normalized_output_path = os.path.abspath(output_file_path) if output_file_path else ""

    # Build initial state
    initial_state = ModernizationState(
        code=code,
        language=language,
        analysis="",
        dependency_map={},
        call_graph_data={},
        impact_map={},
        orphans=[],
        analysis_report="",
        modernized_code="",
        verification_result={},
        error_log="",
        attempt_count=0,
        is_parity_passed=False,
        is_functionally_equivalent=False,
        diff_output="",
        feedback_loop_count=0,
        modernization_order=[],
        modernized_functions={},
        current_function_index=0,
        partial_success=False,
        last_working_code=code,
        current_target_function="",
        functions_info=[],
        functions_index={},
        current_function_name="",
        current_function_span=(0, 0),
        project_map={},
        source_file=source_abs,
        output_file_path=normalized_output_path,
        legacy_findings=[],
        compliance_report={},
        batched_target_functions=[],
        current_target_stable_key="",
        global_refactor_done=False,
        global_last_score=-1,
        global_stagnation_count=0,
        analyzer_plan="",
        modernization_plan="",
        original_function_signatures={},
        original_structure_snapshot={},
        static_validation_errors=[],
        context=context,
    )

    # Build and run the graph
    graph = build_workflow()
    try:
        final_state = graph.invoke(initial_state)
    except Exception as e:
        logger.exception("Workflow graph execution failed")
        # Return a minimal state with error information
        final_state = initial_state.copy()
        final_state["error_log"] = f"Graph execution failed: {e}"
        final_state["verification_result"] = {"success": False, "errors": [str(e)]}
    # Log results

    logger.info("\n" + "=" * 60)
    logger.info("📊 MODERNIZATION COMPLETE")
    logger.info("=" * 60)
    logger.info("Total Attempts: %d", final_state.get("attempt_count", 0))
    verification_ok = final_state.get("verification_result", {}).get("success", False)
    logger.info("Verification Success: %s", verification_ok)

    # Determine output path if not provided
    output_path = final_state.get("output_file_path", "")
    if not output_path:
        if source_abs:
            base, ext = os.path.splitext(source_abs)
            output_path = f"{base}_modernized{ext}"
        else:
            output_path = os.path.join(os.getcwd(), "output_modernized.cpp")

    # Save modernized code (even if verification failed – we still have the last working code)
    modernized_code = final_state.get("modernized_code") or final_state.get("last_working_code") or code
    try:
        with open(output_path, "w", encoding="utf-8") as out:
            out.write(modernized_code)
        logger.info("💾 Modernized code saved to: %s", output_path)
        final_state["output_file_path"] = output_path
    except OSError as err:
        logger.warning("Could not save output file: %s", err)

    return final_state