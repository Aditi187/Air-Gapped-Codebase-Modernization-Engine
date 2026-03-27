import re
import logging
from typing import Dict, Any, List

from agents.workflow.state import ModernizationState


logger = logging.getLogger(__name__)


# ==========================================================
# HELPERS
# ==========================================================

def _detect_memory_patterns(code: str) -> List[str]:

    findings = []

    if "malloc" in code:

        findings.append(

            "malloc usage detected"
        )

    if "free(" in code:

        findings.append(

            "free usage detected"
        )

    if "new " in code:

        findings.append(

            "raw new detected"
        )

    if "delete " in code:

        findings.append(

            "manual delete detected"
        )

    return findings


# ==========================================================

def _detect_cstyle_patterns(code: str) -> List[str]:

    findings = []

    if "FILE*" in code:

        findings.append(

            "c-style file api detected"
        )

    if "printf(" in code:

        findings.append(

            "printf usage detected"
        )

    if "strcpy(" in code:

        findings.append(

            "strcpy usage detected"
        )

    if re.search(r"\w+\s+\w+\[\d+\]", code):

        findings.append(

            "c-style array detected"
        )

    return findings


# ==========================================================

def _detect_structural_patterns(code: str) -> List[str]:

    findings = []

    if "typedef" in code:

        findings.append(

            "typedef detected"
        )

    if "#define" in code:

        findings.append(

            "macro usage detected"
        )

    if "NULL" in code:

        findings.append(

            "NULL detected"
        )

    if "using namespace std" in code:

        findings.append(

            "global namespace usage"
        )

    return findings


# ==========================================================

def _extract_functions(code: str) -> List[str]:

    """
    basic function name extraction
    """

    pattern = re.compile(

        r"\b([A-Za-z_]\w*)\s*\([^)]*\)\s*\{"

    )

    return list(

        set(pattern.findall(code))
    )


# ==========================================================
# NODE
# ==========================================================

def analyzer_node(

    state: ModernizationState

) -> ModernizationState:

    """
    Phase 4 analyzer.

    responsibilities:

        detect legacy constructs
        identify modernization opportunities
        extract structural info
        produce targets for planner
    """

    logger.info(">>> [ANALYZER] Starting structural analysis of source code")

    code = state.get(

        "code",

        ""
    )

    if not code:

        logger.warning(

            "[analyzer] empty source"
        )

        return state


    # ======================================================
    # DETECT LEGACY PATTERNS
    # ======================================================

    findings: List[str] = []

    findings.extend(

        _detect_memory_patterns(code)
    )

    findings.extend(

        _detect_cstyle_patterns(code)
    )

    findings.extend(

        _detect_structural_patterns(code)
    )


    # ======================================================
    # FUNCTION DISCOVERY
    # ======================================================

    functions = _extract_functions(code)


    # ======================================================
    # TARGET SELECTION
    # ======================================================

    targets = []

    if any("malloc" in f for f in findings):

        targets.append(

            "memory_management"
        )

    if any("printf" in f for f in findings):

        targets.append(

            "iostream_upgrade"
        )

    if any("typedef" in f for f in findings):

        targets.append(

            "typedef_modernization"
        )

    if any("array" in f for f in findings):

        targets.append(

            "container_upgrade"
        )


    # fallback

    if not targets:

        targets.append(

            "general_modernization"
        )


    # ======================================================
    # RISK INDICATORS
    # ======================================================

    risk_flags = {

        "manual_memory":

            any(

                x in code

                for x in ["malloc", "new "]

            ),

        "global_state":

            "static " in code,

        "macro_usage":

            "#define" in code,

    }


    # ======================================================
    # STATE UPDATE
    # ======================================================

    state["legacy_findings"] = findings

    state["functions_info"] = functions

    state["modernization_targets"] = targets

    state["risk_flags"] = risk_flags


    # initialize empty structures used later

    state.setdefault(

        "dependency_graph",

        {}
    )

    state.setdefault(

        "semantic_report",

        {}
    )


    # metrics integration

    metrics = state.get(

        "metrics",

        {}
    )

    metrics["legacy_pattern_count"] = len(findings)

    metrics["function_count"] = len(functions)

    state["metrics"] = metrics


    logger.info(f">>> [ANALYZER] Analysis complete: {len(findings)} legacy patterns found, {len(functions)} functions identified.")

    return state