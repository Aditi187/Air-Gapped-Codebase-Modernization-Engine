from typing import Dict, Any, List
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from core.logger import get_logger

logger = get_logger(__name__)


def planner_node(state: ModernizationState) -> ModernizationState:
    """
    Plan the modernization process by summarising available information.

    This node runs early in the workflow and builds a plain‑text plan that
    is stored in state['modernization_plan'] for logging and debugging.
    """
    logger.info("\n🧠 PLANNER NODE")

    # Get context and config safely
    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("No WorkflowContext found in state")
        state["modernization_plan"] = "ERROR: missing workflow context"
        return state

    config = context.config

    # Extract relevant data from state, with defaults
    functions_info = state.get("functions_info") or []
    legacy_findings = state.get("legacy_findings") or []
    signatures = state.get("original_function_signatures") or {}
    modernization_order = state.get("modernization_order") or []
    current_index = state.get("current_function_index", 0)

    # Safely check signature‑refactor permission
    allow_signature_refactor = getattr(config, "allow_signature_refactor", False)

    # Build the plan lines
    lines = [
        "PLAN:",
        f"- Functions detected: {len(functions_info)}",
        f"- Functions to modernize: {len(modernization_order)}",
        f"- Current function index: {current_index}",
        f"- Legacy findings: {len(legacy_findings)}",
        "- Constraints: keep names/structs/globals unchanged; signatures preserved by default.",
        f"- Signature refactor allowed: {allow_signature_refactor}",
        "- Stage policy: constrained generation → static validation → compile → surgical fix.",
        "- Attempt strategy: 1) full modernization, 2) compiler‑fix only, 3) minimal patch.",
    ]

    # Add a few signature locks (limit to avoid huge plan)
    if isinstance(signatures, dict) and signatures:
        lines.append("- Signature locks (first 8):")
        for fn_name, sig in sorted(signatures.items())[:8]:
            lines.append(f"  - {fn_name}: {sig}")

    # Optionally, include the batch size if available
    if hasattr(config, "batch_size"):
        lines.append(f"- Parallel batch size: {config.batch_size}")

    # Optionally, include the current attempt count
    attempt_count = state.get("attempt_count", 0)
    lines.append(f"- Current attempt: {attempt_count}")

    state["modernization_plan"] = "\n".join(lines)
    return state