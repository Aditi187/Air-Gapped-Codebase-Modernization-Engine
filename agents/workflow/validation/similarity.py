"""
Similarity utilities for comparing code strings.

This module provides a function to compute the difference ratio between
two code snippets using the project's core similarity module.
"""

from core.similarity import code_similarity_ratio


def compute_function_diff_ratio(original_code: str, candidate_code: str) -> float:
    """
    Compute the difference ratio between two code strings.

    The ratio is a float between 0.0 and 1.0:
        - 0.0 means the two strings are identical (similarity = 1.0)
        - 1.0 means they are completely different (similarity = 0.0)

    This function wraps code_similarity_ratio from core.similarity and inverts
    the result to produce a "difference" measure.

    Args:
        original_code: The baseline code string.
        candidate_code: The code string to compare against.

    Returns:
        A float in [0.0, 1.0] representing the difference ratio.
        In case of any error (e.g., invalid similarity value), returns 1.0.
    """
    try:
        # Ensure inputs are strings and handle None
        orig = str(original_code or "")
        cand = str(candidate_code or "")
        similarity = code_similarity_ratio(orig, cand)
        # The similarity function should return a number in [0,1]
        similarity = float(similarity)
        ratio = 1.0 - similarity
        # Clamp to the valid range due to possible floating point errors
        return max(0.0, min(1.0, ratio))
    except Exception:
        # If anything goes wrong, assume the worst (completely different)
        return 1.0