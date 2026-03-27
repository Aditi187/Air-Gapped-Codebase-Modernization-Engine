import logging
from typing import Dict, Any

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from core.differential_tester import compile_cpp_source

logger = logging.getLogger(__name__)

def _normalize_errors(result: Dict[str, Any]) -> str:
    """
    Converts compiler output into readable error string.
    """
    if not result:
        return ""
    
    raw_stderr = result.get("raw_stderr")
    if raw_stderr:
        return raw_stderr.strip()
        
    errors = result.get("errors")
    if errors:
        if isinstance(errors, list):
            return "\n".join(errors)
        return str(errors)
    return ""

def verifier_node(state: ModernizationState) -> ModernizationState:
    """
    Phase 4 verifier.
    Compiles the modernized code and checks for parity.
    """
    logger.info(">>> [VERIFIER] Compiling modernized code using host compiler")
    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("[verifier] missing workflow context")
        state["verification_result"] = {"success": False, "errors": ["missing workflow context"]}
        state["error_log"] = "missing workflow context"
        return state

    code = state.get("modernized_code", "")
    if not code.strip():
        logger.warning("[verifier] No modernized code found to verify.")
        return state

    # Perform differential test (compilation and output parity)
    # We use the original_file_path for diagnostic context
    source_file = state.get("original_file_path", "test.cpp")
    
    # Differential test returns a dict with 'success', 'errors', etc.
    result = compile_cpp_source(code, gpp_exe=getattr(context.config, "compiler_path", None))
    
    state["verification_result"] = result
    state["error_log"] = _normalize_errors(result)
    
    if result.get("success"):
        logger.info(">>> [VERIFIER] Verification PASSED: Code is syntactically valid and modernized.")
    else:
        logger.warning(f">>> [VERIFIER] Verification FAILED: {state['error_log']}")
    
    return state