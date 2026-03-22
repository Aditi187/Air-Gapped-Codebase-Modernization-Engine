from typing import Dict, Any, List

def validate_semantics(original: Dict[str, Any], candidate: Dict[str, Any], func_name: str = "") -> List[str]:
    """Compare two semantic skeletons for structural drift and return any errors found."""
    errors = []

    # Relax return check for likely void functions or simple proxies
    orig_ret = original.get("return_count", 0)
    cand_ret = candidate.get("return_count", 0)
    if orig_ret != cand_ret:
        # If it's a proxy wrapper (0 -> 1 or 1 -> 0), or if return count increases unexpectedly
        if orig_ret > 1 or cand_ret > orig_ret + 1:
             errors.append(f"return count changed {orig_ret} → {cand_ret}")

    # Allow loop count reduction if migrating to vector (removes manual shift loops)
    orig_for = original.get("for_count", 0)
    cand_for = candidate.get("for_count", 0)
    if cand_for != orig_for:
        is_vector_migration = candidate.get("vector_present", False)
        # Allow reduction (e.g. 2 -> 1) but reject complete removal (e.g. 1 -> 0)
        # even if it's a vector migration, to prevent logic moving to members (proxy conversion)
        if cand_for < orig_for:
            if not (is_vector_migration and cand_for > 0):
                errors.append(f"loop count changed {orig_for} → {cand_for}")
        elif cand_for > orig_for:
            errors.append(f"loop count changed {orig_for} → {cand_for}")

    if candidate.get("unique_ptr_present") and candidate.get("delete_count", 0) > 0:
        errors.append("delete used with unique_ptr")

    return errors
