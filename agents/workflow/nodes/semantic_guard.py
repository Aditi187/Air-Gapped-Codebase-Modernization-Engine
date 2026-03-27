import logging
from typing import List, Dict, Any

from agents.workflow.state import ModernizationState

logger = logging.getLogger("semantic_guard")

def semantic_guard_node(state: ModernizationState) -> ModernizationState:
    """
    Phase 4 semantic guard.
    Checks for risky transformations (e.g. malloc still present).
    """
    logger.info(">>> [SEMANTIC_GUARD] Auditing modernized code for safety and legacy leaks")
    code = state.get("modernized_code", "")
    if not code.strip():
        state["semantic_ok"] = True
        return state

    issues = []
    if "malloc" in code:
        issues.append({"category": "memory", "message": "malloc still present", "severity": "medium"})
    if "free(" in code:
        issues.append({"category": "memory", "message": "free still present", "severity": "medium"})

    state["semantic_ok"] = len(issues) == 0
    state["semantic_report"] = {"issues": issues, "risk_score": 0.1 * len(issues)}
    
    if issues:
        logger.warning(f">>> [SEMANTIC_GUARD] Found {len(issues)} modernization risks.")
    else:
        logger.info(">>> [SEMANTIC_GUARD] Audit PASSED: No critical legacy patterns detected in output.")
        
    return state