import logging
from pathlib import Path
from typing import Optional, Any

from langgraph.graph import StateGraph, END

from agents.workflow.state import ModernizationState, create_initial_state
from agents.workflow.context import WorkflowContext

# Node imports
from agents.workflow.nodes.analyzer import analyzer_node
from agents.workflow.nodes.planner import planner_node
from agents.workflow.nodes.modernizer import modernizer_node
from agents.workflow.nodes.semantic_guard import semantic_guard_node
from agents.workflow.nodes.fixer import fixer_node
from agents.workflow.nodes.verifier import verifier_node

logger = logging.getLogger(__name__)

def verification_router(state: ModernizationState) -> str:
    """
    Router: routes based on verification and semantic results.
    """
    result = state.get("verification_result", {})
    success = result.get("success", False)
    semantic_ok = state.get("semantic_ok", True)
    
    context = state.get("context")
    config = getattr(context, "config", None)
    
    state["attempt_count"] = state.get("attempt_count", 0) + 1
    
    if success and semantic_ok:
        return END
    
    max_attempts = getattr(config, "max_attempts", 5) if config else 5
    if state["attempt_count"] >= max_attempts:
        return END
        
    if state.get("error_log"):
        return "fixer"
        
    if not semantic_ok:
        return "planner"
        
    return "modernizer"

def build_modernization_graph():
    workflow = StateGraph(ModernizationState)
    
    workflow.add_node("analyzer", analyzer_node)
    workflow.add_node("planner", planner_node)
    workflow.add_node("modernizer", modernizer_node)
    workflow.add_node("semantic_guard", semantic_guard_node)
    workflow.add_node("fixer", fixer_node)
    workflow.add_node("verifier", verifier_node)
    
    workflow.set_entry_point("analyzer")
    workflow.add_edge("analyzer", "planner")
    workflow.add_edge("planner", "modernizer")
    workflow.add_edge("modernizer", "semantic_guard")
    workflow.add_edge("semantic_guard", "verifier")
    workflow.add_edge("fixer", "semantic_guard")
    
    workflow.add_conditional_edges(
        "verifier",
        verification_router,
        {
            "fixer": "fixer",
            "planner": "planner",
            "modernizer": "modernizer",
            END: END
        }
    )
    
    return workflow.compile()

def run_modernization_workflow(
    code: str,
    source_file: str,
    output_path: Optional[str] = None,
    config: Optional[Any] = None
) -> ModernizationState:
    logger.info(f"Starting modernization workflow for {source_file}")

    ctx = WorkflowContext(config=config) if config else WorkflowContext()

    initial_state = create_initial_state(
        code=code,
        source_file=source_file,
        output_file_path=output_path or "",
        context=ctx
    )

    app = build_modernization_graph()
    final_state = app.invoke(initial_state)

    # Recovery from non-dict graph result
    if not isinstance(final_state, dict):
        logger.error("Workflow did not return a valid state dict.")
        return initial_state

    # Output Handling
    if not output_path:
        p = Path(source_file)
        if "_modernized.cpp" not in str(p):
            output_path = str(p.parent / f"{p.stem}_modernized.cpp")
        else:
            output_path = str(p)
    
    final_state["output_file_path"] = output_path

    result_code = final_state.get("modernized_code")
    if not result_code or not result_code.strip():
        logger.warning("Modernization produced empty output; using original code.")
        result_code = final_state.get("code", "// empty")

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(result_code)
        logger.info(f"Saved modernized code to {output_path}")
    except Exception as e:
        logger.error(f"Failed to write output file: {e}")

    # Defensive: cast to ModernizationState if needed
    if not isinstance(final_state, dict) or not hasattr(final_state, "keys"):
        logger.error("Workflow did not return a valid state dict. Returning initial state.")
        return initial_state
    return ModernizationState(**final_state)