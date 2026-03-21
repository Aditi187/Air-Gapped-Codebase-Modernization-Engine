import re
from typing import Any, Dict, List, Set, Optional

from agents.workflow.config import WorkflowConfig
from agents.workflow.validation.ast_validator import (
    extract_function_objects,
    parse_project_map_from_source,
    check_garbage_tokens,
)


def normalize_signature_text(signature: str) -> str:
    """
    Strip comments and extract the part before the function body.
    Returns a compact, space-normalized signature string.
    """
    if not signature:
        return ""
    # Remove /* ... */ comments
    s = re.sub(r"/\*.*?\*/", " ", str(signature), flags=re.DOTALL)
    # Remove // comments
    s = re.sub(r"//[^\n]*", " ", s)
    # Keep only the part before the opening brace
    s = s.split("{", 1)[0]
    # Collapse whitespace
    return re.sub(r"\s+", " ", s).strip()


def normalize_signature_relaxed(signature: str) -> str:
    """
    Relaxed normalization: remove 'const', normalize pointer/reference syntax.
    Useful for comparing signatures with optional const correctness.
    """
    s = normalize_signature_text(signature)
    # Remove const (both leading and in parameter lists)
    s = re.sub(r"\bconst\b", " ", s)
    # Normalize spacing around & and *
    s = s.replace(" &", "&").replace("& ", "&")
    s = s.replace(" *", "*").replace("* ", "*")
    # Collapse whitespace again
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def build_structure_snapshot(source: str) -> Dict[str, Any]:
    """
    Extract high-level structural information from source code:
    - function signatures (normalized)
    - function names
    - global variable names
    - struct/class/union names
    """
    pm = parse_project_map_from_source(source)
    functions = extract_function_objects(pm.get("functions") or {})
    signatures: Dict[str, str] = {}
    fn_names: Set[str] = set()
    for fn in functions:
        name = str(fn.get("name") or "")
        if name:
            fn_names.add(name)
            signatures[name] = normalize_signature_text(str(fn.get("signature") or ""))

    globals_raw = pm.get("global_variables") or []
    global_names = {
        str(item.get("name") or "")
        for item in globals_raw
        if isinstance(item, dict) and item.get("name")
    }

    types_raw = pm.get("types") or []
    struct_names = {
        str(item.get("name") or "")
        for item in types_raw
        if isinstance(item, dict)
        and item.get("name")
        and str(item.get("kind") or "").lower() in {"struct", "class", "union", ""}
    }

    return {
        "function_signatures": signatures,
        "function_names": fn_names,
        "global_names": global_names,
        "struct_names": struct_names,
    }


def validate_structure_consistency(
    baseline_snapshot: dict,
    candidate_source: str,
    config: WorkflowConfig
) -> List[str]:
    """
    Compare a baseline snapshot with a candidate source to detect structural changes.
    Returns a list of error messages.
    """
    if not baseline_snapshot:
        return []

    candidate = build_structure_snapshot(candidate_source)
    errors: List[str] = []

    # Global variable set must match exactly
    if set(baseline_snapshot.get("global_names", set())) != set(candidate.get("global_names", set())):
        errors.append("global variables changed")

    # Struct/class/union declarations must match exactly
    if set(baseline_snapshot.get("struct_names", set())) != set(candidate.get("struct_names", set())):
        errors.append("struct/class declarations changed")

    # Function names must match exactly
    baseline_names = set(baseline_snapshot.get("function_names", set()))
    candidate_names = set(candidate.get("function_names", set()))
    if baseline_names != candidate_names:
        errors.append("function set changed (name added/removed/renamed)")

    # If signature changes are disallowed, check each function's signature
    if not config.allow_signature_refactor:
        baseline_sig = dict(baseline_snapshot.get("function_signatures", {}))
        candidate_sig = dict(candidate.get("function_signatures", {}))
        for name, sig in baseline_sig.items():
            csig = candidate_sig.get(name, "")
            if sig and csig and sig != csig:
                errors.append(f"signature changed for function '{name}'")
            elif sig and not csig:
                errors.append(f"signature missing for function '{name}'")

    return errors


def signature_exact_match(original: str, candidate_code: str) -> bool:
    """
    Compare original signature (string) with the signature of the first function
    found in candidate_code after relaxed normalization.
    """
    orig = normalize_signature_relaxed(original)
    if not orig:
        return False

    parsed_map = parse_project_map_from_source(candidate_code)
    funcs = extract_function_objects(parsed_map.get("functions") or {})
    if funcs:
        cand_sig = normalize_signature_text(str(funcs[0].get("signature") or ""))
    else:
        cand_sig = normalize_signature_text(candidate_code)

    cand = normalize_signature_relaxed(cand_sig)
    return orig == cand


def is_code_syntactically_complete(code: str) -> bool:
    """
    Heuristic check that the code is not a broken fragment.
    Returns True if it appears to be a complete C++ function/block.
    """
    code = code.strip()
    if not code:
        return False

    # Simple cases: macro or statement (no braces)
    if "{" not in code and "}" not in code and ";" in code:
        return True

    # Brace balance
    if code.count("{") != code.count("}"):
        return False

    # Ensure there is at least one brace early (avoids trailing junk)
    has_brace_early = "{" in code[:200]
    if not has_brace_early:
        return False

    # No stray non‑comment code after the last closing brace
    last_brace_idx = code.rfind("}")
    if last_brace_idx >= 0:
        after_last_brace = code[last_brace_idx + 1:].strip()
        after_lines = after_last_brace.split("\n")
        for line in after_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith(("//", "/*", "*")) and not stripped.endswith("*/") and not stripped.startswith("#"):
                return False
    return True


def strict_gate(
    code: str,
    expected_name: str,
    original_signature: str,
    config: WorkflowConfig
) -> List[str]:
    """
    Basic checks before attempting compilation.
    Returns list of error strings (empty if passes).
    """
    if not config.enable_strict_gate:
        return []

    errors = []
    if not is_code_syntactically_complete(code):
        errors.append("code is syntactically incomplete (missing braces or extra trailing code)")
    errors.extend(check_garbage_tokens(code))

    if original_signature and not signature_exact_match(original_signature, code):
        errors.append("signature mismatch")
    if expected_name and expected_name not in code:
        errors.append(f"function '{expected_name}' missing")

    parsed = parse_project_map_from_source(code)
    if not parsed.get("functions"):
        errors.append("no functions parsed")
    return errors


def validate_single_function_candidate(
    candidate_code: str,
    expected_function_name: str,
    original_param_count: int,
    config: WorkflowConfig,
    original_signature: str = "",
) -> Optional[str]:
    """
    Perform in-depth validation on a candidate that is supposed to represent
    a single function definition. Returns None on success, else an error string.
    """
    # Reject whole-file output (contains #include)
    if re.search(r"(?m)^\s*#\s*include\b", candidate_code):
        return "model returned whole-file output with include directives"

    parsed_map = parse_project_map_from_source(candidate_code)
    parsed_functions = extract_function_objects(parsed_map.get("functions") or {})
    if len(parsed_functions) < 1:
        return "model output must contain at least one function definition"

    target_fn = next(
        (f for f in parsed_functions if str(f.get("name") or "") == expected_function_name),
        None
    )
    if not target_fn:
        names = [f.get("name") for f in parsed_functions]
        return f"model output function name mismatch (expected '{expected_function_name}', got {names})"

    # Parameter count check (if signatures not allowed to change)
    if not config.allow_signature_refactor:
        candidate_params = target_fn.get("parameters") or []
        candidate_param_count = len(candidate_params) if isinstance(candidate_params, list) else -1
        if original_param_count >= 0 and candidate_param_count >= 0 and original_param_count != candidate_param_count:
            return f"model changed parameter compatibility (expected {original_param_count} params, got {candidate_param_count})"

        if original_signature:
            candidate_signature = normalize_signature_text(str(target_fn.get("signature") or ""))
            expected_signature = normalize_signature_text(original_signature)
            rel_expected = normalize_signature_relaxed(expected_signature)
            rel_candidate = normalize_signature_relaxed(candidate_signature)
            if rel_expected and rel_candidate and rel_expected != rel_candidate:
                return "model changed function signature"

    # No extra top‑level declarations (structs, classes) allowed
    extra_types = parsed_map.get("types") or []
    if extra_types:
        return "model output contains extra top-level struct/class declarations (unsupported inside function scope replacement)"

    # Function body must be non‑empty
    body_text = str(target_fn.get("body") or "")
    if not body_text.strip():
        return "model output has empty function body"

    # Detect missing semicolon after stream output (common mistake)
    # We look for lines that contain std::cout << ... but don't end with ;
    lines = [line.strip() for line in candidate_code.splitlines() if line.strip()]
    for line in lines:
        if (not line.startswith(("//", "/*", "*", "#", "return "))
                and not line.endswith(("{", "}", ";", ":"))
                and not line.startswith(("if ", "if(", "for ", "for(", "while ", "while(", "switch ", "switch(", "else", "do"))
                and re.search(r"\bstd::(cout|cerr|clog)\b", line)
                and "<<" in line
                and not line.endswith(";")):
            return "likely missing semicolon after stream output statement"

    # Check for #include <iostream> when using iostream objects
    has_iostream_include = bool(re.search(r"(?m)^\s*#\s*include\s*<iostream>\s*$", candidate_code))
    uses_iostream_streams = bool(re.search(r"\bstd::(cout|cerr|clog)\b", candidate_code))
    if uses_iostream_streams and "#include" in candidate_code and not has_iostream_include:
        return "uses std::cout/cerr/clog but missing #include <iostream>"

    return None


def classify_validation_severity(errors: List[str]) -> str:
    """
    Classify a list of validation errors into severity levels:
    - "none"       : no errors
    - "critical"   : structural changes that break semantics
    - "medium"     : mixed errors, or non‑structural issues
    - "minor"      : only cosmetic/token issues
    """
    if not errors:
        return "none"

    critical_markers = (
        "function set changed",
        "global variables changed",
        "struct/class declarations changed",
        "signature changed",
        "signature missing",
        "model output must contain exactly one function definition"
    )
    if any(any(marker in err for marker in critical_markers) for err in errors):
        return "critical"

    minor_markers = (
        "Invalid token 'lstd::'",
        "Incorrect namespace 'std::strcpy'",
        "Malformed type declaration",
        "Garbage numeric statement",
        "Function was incorrectly embedded inside struct definition",
        "Code is syntactically incomplete",
        "likely missing semicolon after stream output statement",
        "uses std::cout/cerr/clog but missing #include <iostream>"
    )
    if all(any(marker in err for marker in minor_markers) for err in errors):
        return "minor"

    return "medium"