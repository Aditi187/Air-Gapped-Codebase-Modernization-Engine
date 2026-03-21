import json
from typing import Any, Dict, List

from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext
from core.logger import get_logger
from core.parser import CppParser, detect_legacy_patterns
from core.graph import DependencyGraph, build_analysis_report

logger = get_logger(__name__)


def analyzer_node(state: ModernizationState) -> ModernizationState:
    logger.info("🔍 ANALYZER NODE START")

    
    context: WorkflowContext = state.get("context")
    if context is None:
        raise ValueError("WorkflowContext missing in state")

    code: str = state.get("code", "")
    language: str = state.get("language", "").lower()
    source_file: str = state.get("source_file") or ""

    is_cpp = language in {"cpp", "c++", "c++17", "c++20", "c++23"}

   
    functions_info: List[Dict[str, Any]] = []
    dependency_map: Dict[str, Any] = {}
    parser_error: str = ""
    orphans: List[str] = []
    cycles: List[Any] = []
    legacy_findings: List[Any] = []
    project_map: Dict[str, Any] = {}
    call_graph_data: Dict[str, Any] = {}
    analysis_report: str = ""

    
    if is_cpp and code.strip():
        try:
            parser = CppParser()

            project_map = parser.parse_string(code, source_file=source_file) or {}

            parsed_functions = project_map.get("functions", {})
            if isinstance(parsed_functions, dict):
                functions_info = list(parsed_functions.values())
            else:
                logger.warning("Unexpected functions format from parser")

            # Detect legacy patterns safely
            try:
                legacy_findings = detect_legacy_patterns(code) or []
            except Exception as lf_err:
                logger.warning("Legacy detection failed: %s", lf_err)

            # Dependency analysis
            if functions_info:
                dep_graph = DependencyGraph(functions_info)

                dependency_map = dep_graph.dependency_map or {}

                try:
                    graph_metrics = dep_graph.analyze() or {}
                    orphans = list(graph_metrics.get("orphans", []))
                    cycles = list(graph_metrics.get("cycles", []))
                except Exception as g_err:
                    logger.warning("Graph analysis failed: %s", g_err)

                try:
                    analysis_report = build_analysis_report(
                        functions_info,
                        dependency_map,
                        orphans,
                        cycles,
                    )
                except Exception as r_err:
                    logger.warning("Report generation failed: %s", r_err)

                try:
                    call_graph_data = dep_graph.to_dict() or {}
                except Exception as cg_err:
                    logger.warning("Call graph serialization failed: %s", cg_err)

        except Exception as exc:
            parser_error = f"Analyzer failed: {exc!r}"
            logger.exception("Analyzer parsing error")

    elif not is_cpp:
        logger.info("Skipping analyzer: Non-C++ language detected")

    else:
        logger.warning("Skipping analyzer: Empty code input")

    
    analysis = {
        "language": language,
        "functions": functions_info,
        "dependency_map": dependency_map,
        "call_graph_data": call_graph_data,
        "orphans": orphans,
        "cycles": cycles,
        "analysis_report": analysis_report,
        "parser_error": parser_error,
        "legacy_findings": legacy_findings,
    }


    try:
        state["analysis"] = json.dumps(analysis)
    except Exception:
        logger.warning("JSON serialization failed, storing raw analysis")
        state["analysis"] = str(analysis)


    state["dependency_map"] = dependency_map or {}
    state["impact_map"] = dependency_map or {}
    state["legacy_findings"] = legacy_findings or []
    state["functions_info"] = functions_info or []

    state["functions_index"] = {
        str(f.get("name", "")): f
        for f in functions_info
        if isinstance(f, dict) and f.get("name")
    }

    state["project_map"] = project_map or {}
    state["orphans"] = orphans or []

    
    if is_cpp and functions_info:
        try:
            # Prefer dependency-based ordering if possible
            state["modernization_order"] = list(dependency_map.keys()) or [
                f.get("name") for f in functions_info if f.get("name")
            ]
        except Exception:
            state["modernization_order"] = [
                f.get("name") for f in functions_info if f.get("name")
            ]
    else:
        state["modernization_order"] = []

    logger.info(
        "Analyzer complete | functions=%d | orphans=%d | cycles=%d | parser_error=%s",
        len(functions_info),
        len(orphans),
        len(cycles),
        "yes" if parser_error else "no",
    )

    return state