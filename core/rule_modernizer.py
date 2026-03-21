from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Tuple, Dict


@dataclass(slots=True)
class ModernizationRule:
    pattern: re.Pattern[str]
    replacement: str
    description: str
    ast_triggers: Tuple[str, ...] = ()
    hint_only: bool = False

    def __init__(
        self,
        pattern: str,
        replacement: str,
        description: str,
        ast_triggers: Tuple[str, ...] = (),
        hint_only: bool = False,
    ):
        object.__setattr__(self, "pattern", re.compile(pattern, re.MULTILINE))
        object.__setattr__(self, "replacement", replacement)
        object.__setattr__(self, "description", description)
        object.__setattr__(self, "ast_triggers", ast_triggers)
        object.__setattr__(self, "hint_only", hint_only)


# -------------------------------------------------------------------------
# RULES (Safe + Production-ready)
# -------------------------------------------------------------------------
_RULES: List[ModernizationRule] = [
    ModernizationRule(
        pattern=r"\bNULL\b",
        replacement="nullptr",
        description="NULL -> nullptr",
        ast_triggers=("null_macro",),
    ),
    ModernizationRule(
        # safer typedef regex (avoids structs/classes)
        pattern=r"\btypedef\s+([^\{\};]+?)\s+([A-Za-z_]\w*)\s*;",
        replacement=r"using \2 = \1;",
        description="typedef -> using",
    ),
    ModernizationRule(
        pattern=r"\bthrow\s*\(\s*\)",
        replacement="noexcept",
        description="throw() -> noexcept",
    ),
    # ---------------- HINT RULES ----------------
    ModernizationRule(
        pattern=r"\(\s*([A-Za-z_][A-Za-z0-9_:<>]*)\s*\)\s*([A-Za-z_][A-Za-z0-9_]*)",
        replacement=r"\g<0>",
        description="C-style cast detected (consider static_cast)",
        ast_triggers=("c_style_cast",),
        hint_only=True,
    ),
    ModernizationRule(
        pattern=r"\bchar\s*\*\s*[A-Za-z_]\w*",
        replacement=r"\g<0>",
        description="char* detected (consider std::string/std::span)",
        ast_triggers=("char_pointer",),
        hint_only=True,
    ),
    ModernizationRule(
        pattern=r"\bstd\s*::\s*auto_ptr\b",
        replacement="std::unique_ptr",
        description="std::auto_ptr -> std::unique_ptr",
    ),
    ModernizationRule(
        pattern=r"^\s*#\s*define\s+[A-Z][A-Z0-9_]*\s+[^\n]+$",
        replacement=r"\g<0>",
        description="#define constant detected (consider constexpr)",
        hint_only=True,
    ),
    ModernizationRule(
        pattern=r"\bprintf\s*\(",
        replacement=r"\g<0>",
        description="printf usage detected",
        ast_triggers=("printf_usage",),
        hint_only=True,
    ),
    ModernizationRule(
        pattern=r"\bmalloc\s*\(",
        replacement=r"\g<0>",
        description="malloc detected (use smart pointers/containers)",
        ast_triggers=("malloc_usage",),
        hint_only=True,
    ),
    ModernizationRule(
        pattern=r"\bfree\s*\(",
        replacement=r"\g<0>",
        description="free detected (RAII recommended)",
        ast_triggers=("free_usage",),
        hint_only=True,
    ),
]


# -------------------------------------------------------------------------
# COMMENT + STRING MASKING (critical for safe regex ops)
# -------------------------------------------------------------------------
_COMMENTS_AND_STRINGS_RE = re.compile(
    r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
    re.DOTALL,
)


def _mask_comments_and_strings(code: str) -> str:
    """Replace comments/strings with spaces to preserve positions."""
    return _COMMENTS_AND_STRINGS_RE.sub(
        lambda m: re.sub(r"[^\n]", " ", m.group(0)),
        code,
    )


# -------------------------------------------------------------------------
# RULE APPLICATION ENGINE
# -------------------------------------------------------------------------
def _apply_rule(
    original_code: str,
    masked_code: str,
    rule: ModernizationRule,
) -> Tuple[str, int]:
    matches = list(rule.pattern.finditer(masked_code))
    if not matches:
        return original_code, 0

    chunks: List[str] = []
    cursor = 0

    for match in matches:
        start, end = match.span()
        chunks.append(original_code[cursor:start])
        chunks.append(match.expand(rule.replacement))
        cursor = end

    chunks.append(original_code[cursor:])
    return "".join(chunks), len(matches)


# -------------------------------------------------------------------------
# MAIN API
# -------------------------------------------------------------------------
def apply_modernization_rules(
    code: str,
    detected_patterns: Dict[str, int] | None = None,
) -> Tuple[str, List[str]]:
    """
    Applies safe regex-based modernization rules.

    Returns:
        updated_code, applied_rule_descriptions
    """
    if not code.strip():
        return code, []

    updated = code
    applied: List[str] = []
    active = detected_patterns or {}

    # Mask once (BIG performance improvement)
    masked = _mask_comments_and_strings(updated)

    for rule in _RULES:
        # Skip rule if AST triggers not satisfied
        if rule.ast_triggers and active:
            if not any(int(active.get(name, 0)) > 0 for name in rule.ast_triggers):
                continue

        if rule.hint_only:
            count = sum(1 for _ in rule.pattern.finditer(masked))
        else:
            updated, count = _apply_rule(updated, masked, rule)
            # re-mask after modification
            if count:
                masked = _mask_comments_and_strings(updated)

        if count:
            applied.append(f"{rule.description} ({count}x)")

    return updated, applied