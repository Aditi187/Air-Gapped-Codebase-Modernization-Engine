import os
from typing import List, Optional
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from agents.workflow.validation.structure import strict_gate
from agents.workflow.nodes.fixer import attempt_compiler_error_autofix
from core.logger import get_logger
from core.differential_tester import compile_cpp_source, run_differential_test
from core.inspect_parser import score_cpp17_compliance

logger = get_logger(__name__)


def pre_compile_validator(
    code: str, expected_func_name: str, original_signature: str, config
) -> List[str]:
    """
    Run static checks on the code before compilation.
    Returns a list of error strings (empty if passes).
    """
    # Use strict_gate for structural validation; pass original signature if needed
    return strict_gate(code, expected_func_name, original_signature, config)


def tester_node(state: ModernizationState) -> ModernizationState:
    """Run differential testing between original and modernized code."""
    logger.info("\n🧪 TESTER NODE (Differential Testing)")

    # Initialize parity flags
    state["is_parity_passed"] = True
    state["is_functionally_equivalent"] = True
    state["diff_output"] = ""

    # If compilation failed, skip testing
    verification = state.get("verification_result", {})
    if not verification.get("success"):
        logger.warning("Compilation failed – parity test skipped.")
        state["is_parity_passed"] = False
        state["is_functionally_equivalent"] = False
        return state

    original_cpp_path = state.get("source_file")
    if not original_cpp_path or not os.path.isfile(original_cpp_path):
        logger.warning(
            f"Original C++ file not found: {original_cpp_path}. Parity test skipped."
        )
        state["is_parity_passed"] = False
        state["is_functionally_equivalent"] = False
        return state

    try:
        parity_result = run_differential_test(original_cpp_path, state["modernized_code"])
        parity_ok = bool(parity_result.get("parity_ok"))
        state["is_parity_passed"] = parity_ok
        state["is_functionally_equivalent"] = parity_ok

        if parity_ok:
            logger.info("✅ Parity Test PASSED")
        else:
            logger.warning("❌ Parity Test FAILED")
            state["diff_output"] = parity_result.get("diff_text", "")
            state["error_log"] = parity_result.get("diff_text", "")
    except Exception as e:
        logger.error(f"Differential testing failed: {e}")
        state["is_parity_passed"] = False
        state["is_functionally_equivalent"] = False

    return state


def verifier_node(state: ModernizationState) -> ModernizationState:
    """Verify that the modernized code compiles, and optionally run auto‑fix and parity test."""
    logger.info("\n✅ VERIFIER NODE")

    context: WorkflowContext = state.get("context")
    if not context:
        logger.error("Missing workflow context – cannot verify.")
        state["verification_result"] = {"success": False, "errors": ["No context"]}
        return state

    code_to_verify = state.get("modernized_code", "").strip()
    if not code_to_verify:
        logger.warning("No code to verify.")
        state["verification_result"] = {"success": False, "errors": ["Empty code"]}
        return state

    current_func = str(state.get("current_function_name") or "")
    original_signatures = state.get("original_function_signatures", {})
    original_sig = original_signatures.get(current_func, "")

    # Pre‑compile structural checks
    pre_errors = pre_compile_validator(
        code_to_verify, current_func, original_sig, context.config
    )
    if pre_errors:
        logger.warning(f"Pre‑compile validation failed: {pre_errors}")
        state["error_log"] = "PRE-COMPILE VALIDATION FAILED: " + "; ".join(pre_errors)
        # We still proceed to actual compilation to get more precise errors

    # Actual compilation
    verification_result = compile_cpp_source(code_to_verify)
    state["verification_result"] = verification_result

    if verification_result.get("success"):
        logger.info("✅ Verification PASSED")
        state["error_log"] = ""
        state["last_working_code"] = code_to_verify

        # Calculate C++17 compliance score
        try:
            report = score_cpp17_compliance(code_to_verify)
            state["compliance_report"] = report
            raw_score = report.get("percent", 0)
            current_score = int(raw_score) if raw_score else 0
            logger.info(f"Modernization score: {current_score}%")
        except Exception as e:
            logger.warning(f"Failed to compute compliance score: {e}")
            state["compliance_report"] = {"error": str(e)}

    else:
        logger.error("❌ Verification FAILED")
        raw_stderr = verification_result.get("raw_stderr", "")
        errors_list = verification_result.get("errors") or []
        state["error_log"] = raw_stderr or "\n".join(errors_list)

        # Attempt to fix compiler errors using LLM
        if (
            context.config.enable_compiler_error_autofix
            and context.config.use_llm
        ):
            logger.info("Attempting compiler‑error autofix...")
            fixed_code, retry_verified, autofix_reason = attempt_compiler_error_autofix(
                state, state["error_log"]
            )
            if fixed_code and retry_verified.get("success"):
                logger.info("Compiler‑error autofix succeeded!")
                state["modernized_code"] = fixed_code
                state["verification_result"] = retry_verified
                state["error_log"] = ""
                state["last_working_code"] = fixed_code
                # Compute compliance for the fixed code
                try:
                    state["compliance_report"] = score_cpp17_compliance(fixed_code)
                except Exception as e:
                    logger.warning(f"Failed to compute compliance after fix: {e}")
            else:
                logger.warning(f"Autofix failed: {autofix_reason}")

    # Run differential testing (parity) – this will also update parity flags
    return tester_node(state)