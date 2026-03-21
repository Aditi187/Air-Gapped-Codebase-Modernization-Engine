import re
from typing import Any, List, Optional, Dict

from core.parser import CppParser


def extract_function_objects(obj: Any) -> List[Dict[str, Any]]:
    """
    Convert a function container (dict or list) into a list of function dicts.
    """
    if isinstance(obj, dict):
        return list(obj.values())
    elif isinstance(obj, list):
        return [item for item in obj if isinstance(item, dict)]
    else:
        return []


def parse_project_map_from_source(src: str) -> Dict[str, Any]:
    """Parse source code and return the project map (as dict)."""
    try:
        pm = CppParser().parse_string(src)
        return pm if isinstance(pm, dict) else {}
    except Exception:
        return {}


def parse_funcs(src: str) -> List[Dict[str, Any]]:
    """Extract the list of function dicts from the source."""
    try:
        pm = CppParser().parse_string(src)
        functions = pm.get("functions") or {}
        return extract_function_objects(functions)
    except Exception:
        return []


def function_ast_equivalent(
    original_code: str,
    candidate_code: str,
    expected_function_name: str,
    original_param_count: int,
) -> bool:
    """
    Check whether the candidate function is structurally similar to the original.
    Returns True if they match name, parameter count, and basic control flow counts.
    """
    try:
        # Get list of functions from both sources
        original_funcs = parse_funcs(original_code)
        candidate_funcs = parse_funcs(candidate_code)

        # Locate the function by name if provided, otherwise assume single function
        def find_function(funcs, name):
            if name:
                for f in funcs:
                    if f.get("name") == name:
                        return f
                return None
            else:
                return funcs[0] if len(funcs) == 1 else None

        original_fn = find_function(original_funcs, expected_function_name)
        candidate_fn = find_function(candidate_funcs, expected_function_name)

        if not original_fn or not candidate_fn:
            return False

        # Name must match (if provided) or be equal
        if expected_function_name and candidate_fn.get("name") != expected_function_name:
            return False

        # Parameter count
        candidate_params = candidate_fn.get("parameters") or []
        candidate_param_count = len(candidate_params) if isinstance(candidate_params, list) else -1
        if original_param_count >= 0 and candidate_param_count != original_param_count:
            return False

        # Basic structure: count occurrences of control keywords
        structure_tokens = ["if", "for", "while", "switch", "return", "try", "catch"]
        original_body = str(original_fn.get("body") or "")
        candidate_body = str(candidate_fn.get("body") or "")
        for token in structure_tokens:
            pattern = rf"\b{token}\b"
            original_count = len(re.findall(pattern, original_body))
            candidate_count = len(re.findall(pattern, candidate_body))
            # Allow a small difference (e.g., added braces, minor changes)
            if abs(original_count - candidate_count) > 3:
                return False

        return True

    except Exception:
        return False


def check_garbage_tokens(code: str) -> List[str]:
    """
    Look for common C++17 mistakes or typos that indicate incorrect modernization.
    """
    errors = []
    garbage_patterns = [
        (r"\blstd::", "Invalid token 'lstd::' detected (likely a typo)"),
        (r"\bstd::strcpy\b", "Incorrect namespace 'std::strcpy' (use strcpy instead)"),
        (r"\bstd::printf\b", "Incorrect namespace 'std::printf' (use printf instead)"),
        (r"\bstd::free\b", "Incorrect namespace 'std::free' (use free instead)"),
        (r"\bstd::malloc\b", "Incorrect namespace 'std::malloc' (use malloc instead)"),
        (r"\bstd::new\b", "Incorrect namespace 'std::new' (new is not in std)"),
        (r"\bstd::delete\b", "Incorrect namespace 'std::delete' (delete is not in std)"),
    ]
    for pattern, msg in garbage_patterns:
        if re.search(pattern, code):
            errors.append(msg)
    return errors


def check_struct_corruption(code: str, expected_func_name: str) -> Optional[str]:
    """
    Detect if the target function appears inside a struct definition.
    This often indicates the LLM mistakenly merged the function into a struct body.
    """
    # Look for a struct that contains the function definition
    # This regex is heuristic: struct X { ... expected_func_name( ... ) { ... }
    struct_pattern = (
        r"struct\s+\w+\s*\{[^}]*"
        + re.escape(expected_func_name)
        + r"\s*\([^{]*\{"
    )
    if re.search(struct_pattern, code, re.DOTALL):
        return "Function was incorrectly embedded inside struct definition"
    return None