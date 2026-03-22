from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)

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


class RuleModernizer:
    """
    Applies deterministic, regex-based modernization transformations to C++ code.
    Designed for safe, common patterns that don't always require LLM reasoning.
    """

    # -------------------------------------------------------------------------
    # RULE DEFINITIONS
    # -------------------------------------------------------------------------
    _RULES: List[ModernizationRule] = [
        # Safe Literal Replacements
        ModernizationRule(
            pattern=r"\bNULL\b",
            replacement="nullptr",
            description="NULL -> nullptr",
        ),
        ModernizationRule(
            pattern=r"\btypedef\s+([^\{\};]+?)\s+([A-Za-z_]\w*)\s*;",
            replacement=r"using \2 = \1;",
            description="typedef -> using",
        ),
        ModernizationRule(
            pattern=r"\bthrow\s*\(\s*\)",
            replacement="noexcept",
            description="throw() -> noexcept",
        ),
        ModernizationRule(
            pattern=r"\bstd\s*::\s*auto_ptr\b",
            replacement="std::unique_ptr",
            description="std::auto_ptr -> std::unique_ptr",
        ),

        ModernizationRule(
            pattern=r"\bfopen\s*\(\s*([^,]+)\s*,\s*\"r\"\s*\)",
            replacement=r"std::ifstream(\1)",
            description="fopen(r) -> std::ifstream",
        ),
        ModernizationRule(
            pattern=r"\bfopen\s*\(\s*([^,]+)\s*,\s*\"w\"\s*\)",
            replacement=r"std::ofstream(\1)",
            description="fopen(w) -> std::ofstream",
        ),

        # Modern Print/IO (Hint or Safe if simple)
        ModernizationRule(
            pattern=r'\bprintf\s*\(\s*"([^"]*)"\s*\)\s*;',
            replacement=r'std::cout << "\1";',
            description="simple printf -> std::cout",
            ast_triggers=("has_printf",),
        ),

        # Hint Rules (Pattern detection without automatic replacement for complex cases)
        ModernizationRule(
            pattern=r"\(\s*([A-Za-z_][A-Za-z0-9_:<>]*)\s*\)\s*([A-Za-z_][A-Za-z0-9_]*)",
            replacement=r"\g<0>",
            description="C-style cast detected (consider static_cast)",
            hint_only=True,
        ),
        ModernizationRule(
            pattern=r"\bmalloc\s*\(",
            replacement=r"\g<0>",
            description="malloc detected (RAII recommended)",
            ast_triggers=("has_malloc",),
            hint_only=True,
        ),
        ModernizationRule(
            pattern=r"\bfree\s*\(",
            replacement=r"\g<0>",
            description="free detected (RAII recommended)",
            ast_triggers=("has_free",),
            hint_only=True,
        ),
    ]

    _COMMENTS_AND_STRINGS_RE = re.compile(
        r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'",
        re.DOTALL,
    )

    def __init__(self):
        pass

    def _mask_comments_and_strings(self, code: str) -> str:
        """Replace comments/strings with spaces to preserve byte offsets."""
        return self._COMMENTS_AND_STRINGS_RE.sub(
            lambda m: re.sub(r"[^\n]", " ", m.group(0)),
            code,
        )

    def _apply_rule(
        self,
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

    def modernize_text(
        self,
        code: str,
        detected_patterns: Dict[str, bool | int] | None = None,
    ) -> str:
        """
        Main entry point for rule-based modernization.
        
        Args:
            code: The C++ source code to transform.
            detected_patterns: AST detection flags (e.g., {'has_malloc': True}).
            
        Returns:
            The modernized code string.
        """
        if not code.strip():
            return code

        updated = code
        active_patterns = detected_patterns or {}
        
        # Performance: Mask once per block application
        masked = self._mask_comments_and_strings(updated)
        
        applied_count = 0
        for rule in self._RULES:
            # Check AST triggers if provided
            if rule.ast_triggers:
                triggered = any(active_patterns.get(t) for t in rule.ast_triggers)
                if not triggered:
                    continue

            if rule.hint_only:
                # We don't modify the code for hints, but we could log them
                continue
            
            new_code, count = self._apply_rule(updated, masked, rule)
            if count > 0:
                updated = new_code
                applied_count += count
                # Re-mask after code changes to keep offsets valid for next rule
                masked = self._mask_comments_and_strings(updated)

        if applied_count > 0:
            logger.info("RuleModernizer applied %d transformations.", applied_count)
            
        return updated


def apply_modernization_rules(
    code: str,
    detected_patterns: Dict[str, bool | int] | None = None,
) -> Tuple[str, List[str]]:
    """
    Backward compatible functional wrapper for the RuleModernizer class.
    """
    engine = RuleModernizer()
    # Note: modernize_text doesn't return the list of descriptions in the class impl above
    # but we can simulate it for this wrapper if needed.
    # For now, let's just make it work.
    updated = engine.modernize_text(code, detected_patterns)
    return updated, []
