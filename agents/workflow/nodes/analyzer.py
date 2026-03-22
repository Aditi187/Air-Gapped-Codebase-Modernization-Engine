import logging
import re
from typing import Dict, Any, List
from agents.workflow.state import ModernizationState
from agents.workflow.context import WorkflowContext

logger = logging.getLogger(__name__)

# Minimal regex-based parser stub since core.parser is deleted
class CppParser:
    def parse_string(self, code: str, language: str = "cpp") -> list:
        # Simple regex to find class blocks for demonstration
        classes = re.findall(r"(class\s+(\w+)\s*\{[\s\S]*?\};)", code)
        functions = []
        for full_match, name in classes:
            start_off = code.find(full_match)
            end_off = start_off + len(full_match)
            functions.append({
                "name": name,
                "range": (start_off, end_off),
                "start_byte": start_off,
                "end_byte": end_off,
                "source": full_match
            })
        return functions

def detect_legacy_patterns(code: str) -> list:
    patterns = []
    if "malloc" in code: patterns.append("C-style allocation")
    if "free" in code: patterns.append("C-style deallocation")
    if "char*" in code: patterns.append("Raw character pointers")
    return patterns

# Stub out missing graph components
class DependencyGraph:
    def __init__(self, functions): self.functions = functions
    def build_map(self): return {}
    def get_call_graph(self): return {}
    def get_orphans(self): return []
    def get_cycles(self): return []

def build_analysis_report(graph):
    return "Analysis report unavailable (core.graph deleted)"

def analyzer_node(state: ModernizationState) -> ModernizationState:
    """Perform static analysis on the source code."""
    logger.info("\n🔍 ANALYZER NODE")
    
    code = state.get("modernized_code") or state.get("code", "")
    if not code:
        logger.error("No code found in state to analyze")
        return state

    # Static analysis logic
    try:
        parser = CppParser()
        functions_info = parser.parse_string(code, language="cpp")
        
        if not functions_info:
            logger.warning("No functions/classes detected by minimal regex parser.")
        
        # Build dependency graph stub
        graph = DependencyGraph(functions_info)
        dependency_map = graph.build_map()
        call_graph_data = graph.get_call_graph()
        orphans = graph.get_orphans()
        cycles = graph.get_cycles()
        analysis_report = build_analysis_report(graph)
        legacy_findings = detect_legacy_patterns(code)
        
        # Update state
        state["functions_info"] = functions_info
        state["dependency_map"] = dependency_map
        state["call_graph_data"] = call_graph_data
        state["orphans"] = orphans
        state["cycles"] = cycles
        state["analysis_report"] = analysis_report
        state["legacy_findings"] = legacy_findings
        
        # Also need modernization_order if expected by later nodes
        state["modernization_order"] = [fn["name"] for fn in functions_info]
        
        return state

    except Exception as e:
        logger.exception(f"Analyzer failed: {e}")
        state["error_log"] = f"Analyzer error: {str(e)}"
        return state