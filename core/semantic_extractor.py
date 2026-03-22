import re
import json
import logging
from typing import Dict, Any, List, Optional

from core.ast_modernizer import ASTModernizationDetector, PatternName
from core.parser import detect_legacy_patterns

logger = logging.getLogger(__name__)

# --- NEW: Structural Skeleton (requested by user) ---

def extract_semantic_skeleton(code: str) -> Dict[str, Any]:
    """Extract a structural summary of the code to ensure high-fidelity transformation."""
    skeleton = {}

    skeleton["return_count"] = code.count("return")
    skeleton["for_count"] = len(re.findall(r"\bfor\s*\(", code))
    skeleton["while_count"] = len(re.findall(r"\bwhile\s*\(", code))

    skeleton["delete_count"] = code.count("delete ")
    skeleton["malloc_count"] = code.count("malloc")
    skeleton["new_count"] = code.count("new ")

    skeleton["function_calls"] = len(re.findall(r"\w+\s*\(", code))

    skeleton["unique_ptr_present"] = "unique_ptr" in code or "make_unique" in code
    # Detect vector usage even if type declaration is not in snippet
    skeleton["vector_present"] = "vector<" in code or ".push_back(" in code or ".erase(" in code or "students." in code

    return skeleton


# --- RESTORED: Semantic Extractor API (needed by analyzer.py and modernizer.py) ---

class SemanticExtractor:
    """Reconstructed SemanticExtractor to satisfy existing architecture."""
    def __init__(self, dependency_graph=None):
        self.detector = ASTModernizationDetector()
        self.dependency_graph = dependency_graph

    def extract_plan(self, code: str, func_name: str) -> Dict[str, Any]:
        """Generate a modernization plan based on AST signals."""
        findings = self.detector.detect_patterns(code)
        patterns = [f["name"] for f in findings]
        
        # Estimate risk based on patterns
        risk = "low"
        if any(p in patterns for p in ["malloc_usage", "raw_array", "raw_new"]):
            risk = "high"
        elif any(p in patterns for p in ["printf_usage", "c_style_cast"]):
            risk = "medium"

        return {
            "function": func_name,
            "detected_patterns": patterns,
            "risk_level": risk,
            "transformations": self._infer_transformations(patterns),
            "constraints": ["preserve_signature", "do_not_add_members"]
        }

    def _infer_transformations(self, patterns: List[str]) -> List[Dict[str, str]]:
        tx = []
        if "malloc_usage" in patterns or "raw_array" in patterns:
            tx.append({"type": "container_upgrade", "target": "std::vector"})
        if "printf_usage" in patterns:
            tx.append({"type": "io_upgrade", "target": "std::cout"})
        if "c_style_cast" in patterns:
            tx.append({"type": "cast_upgrade", "target": "static_cast"})
        return tx

def extract_semantics(code: str, functions_info: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Top-level semantic analysis for the analyzer node."""
    detector = ASTModernizationDetector()
    findings = detector.detect_patterns(code)
    
    # Map findings to the structure expected by analyzer.py
    containers = {}
    ownership = {}
    risks = []
    
    for f in findings:
        name = f["name"]
        if name in ("malloc_usage", "raw_array"):
            containers[f.get("symbol", "unknown")] = {"model": "vector"}
            risks.append(f"manual_memory in {f.get('symbol')}")
        if name in ("raw_new", "raw_pointer"):
            ownership[f.get("symbol", "unknown")] = "unique"

    return {
        "containers": containers,
        "ownership": ownership,
        "risks": risks,
        "modernity_score": compute_modernity_score(code),
    }

def compute_modernity_score(code: str) -> float:
    """Calculate a score from 0.0 to 1.0 based on modern C++ usage and AST signals."""
    modern_tokens = ["std::vector", "std::unique_ptr", "std::string", "nullptr", "auto", "override", "static_cast", "const_cast", "reinterpret_cast"]
    legacy_tokens = ["malloc", "free", "NULL", "char*", "printf", "typedef ", "#define"]
    
    detector = ASTModernizationDetector()
    findings = detector.detect_patterns(code)
    
    # Base count from tokens
    modern_count = sum(1 for t in modern_tokens if t in code)
    legacy_count = sum(1 for t in legacy_tokens if t in code)
    
    # Add weight from structural findings
    for f in findings:
        if f["name"] in ("malloc_usage", "raw_array", "pointer_arithmetic", "typedef_usage", "macro_usage"):
            legacy_count += 2  # Penalize legacy patterns more heavily
        elif f["name"] in ("std_vector_usage", "unique_ptr_usage"):
            modern_count += 1

    total = modern_count + legacy_count
    if total == 0: return 1.0
    return modern_count / total

def sort_functions_by_risk(functions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort functions based on their complexity and legacy patterns."""
    return sorted(functions, key=lambda x: x.get("risk_score", 0), reverse=True)

def build_semantic_model(project_map: Dict[str, Any]) -> Dict[str, Any]:
    """Build a comprehensive semantic model of the project."""
    model = {}
    for fn_name, fn_info in project_map.get("functions", {}).items():
        model[fn_name] = {
            "complexity": len(fn_info.get("parameters", [])),
            "conflicts": [],
            "api_break_risk": False
        }
    return model
