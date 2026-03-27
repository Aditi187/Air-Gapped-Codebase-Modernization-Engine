import logging
from typing import Dict, Any, List

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)

def planner_node(state: ModernizationState) -> ModernizationState:
    """
    Phase 4 planner.
    Defines the modernization strategy based on analysis findings.
    """
    logger.info(">>> [PLANNER] Building modernization strategy based on analysis findings")
    findings = state.get("legacy_findings", [])
    
    # Simple default plan
    plan = {
        "strategy": "balanced",
        "risk_score": 0.3 if findings else 0.1,
        "targets": ["manual_memory", "file_io", "time_handling"],
        "signature_preservation": True
    }
    
    state["modernization_plan"] = plan
    state["plan_summary"] = "Modernize memory (RAII), file I/O (ofstream), and time (localtime_s)."
    
    logger.info(f">>> [PLANNER] Strategy finalized: {str(plan['strategy']).upper()} approach. Targets: {', '.join(plan['targets'])}")
    return state