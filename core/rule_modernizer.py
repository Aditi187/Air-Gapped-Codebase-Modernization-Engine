import re
import logging
from typing import List, Tuple, Dict, Optional


logger = logging.getLogger(__name__)


# ==========================================================
# RULE STRUCTURE
# ==========================================================

class ModernizationRule:

    def __init__(

        self,

        pattern: str,

        replacement: str,

        description: str,

        safe: bool = True

    ):

        self.pattern = re.compile(

            pattern,

            re.MULTILINE
        )

        self.replacement = replacement

        self.description = description

        self.safe = safe


# ==========================================================
# RULE ENGINE
# ==========================================================

class RuleModernizer:

    """
    deterministic regex-based modernization engine.

    applies safe mechanical transformations
    without altering program logic.
    """

    # ======================================================
    # SAFE RULE SET
    # ======================================================

    RULES: List[ModernizationRule] = [

        # typedef → using
        ModernizationRule(

            r"\btypedef\s+(.+?)\s+([A-Za-z_]\w*)\s*;",

            r"using \2 = \1;",

            "typedef -> using"
        ),

        # NULL → nullptr
        ModernizationRule(

            r"\bNULL\b",

            "nullptr",

            "NULL -> nullptr"
        ),

        # char array → std::string
        ModernizationRule(

            r"char\s+([A-Za-z_]\w*)\s*\[\s*\d+\s*\]\s*;",

            r"std::string \1;",

            "char[] -> std::string"
        ),

        # strcpy → assignment
        ModernizationRule(

            r"strcpy\s*\(\s*(\w+)\s*,\s*\"([^\"]*)\"\s*\)\s*;",

            r'\1 = "\2";',

            "strcpy -> assignment"
        ),

        # strlen → size()
        ModernizationRule(

            r"strlen\s*\(\s*(\w+)\s*\)",

            r"\1.size()",

            "strlen -> size"
        ),

        # std::auto_ptr → std::unique_ptr
        ModernizationRule(

            r"std::auto_ptr<",

            "std::unique_ptr<",

            "auto_ptr -> unique_ptr"
        ),

        # throw() → noexcept
        ModernizationRule(

            r"\bthrow\s*\(\s*\)",

            "noexcept",

            "throw() -> noexcept"
        ),

        # simple printf → cout
        ModernizationRule(

            r'printf\s*\(\s*"([^"]*)"\s*\)\s*;',

            r'std::cout << "\1";',

            "printf -> cout"
        ),

        # fopen read → ifstream
        ModernizationRule(

            r'FILE\s*\*\s*(\w+)\s*=\s*fopen\(([^,]+),\s*"r"\);',

            r"std::ifstream \1(\2);",

            "fopen -> ifstream"
        ),

        # fopen write → ofstream
        ModernizationRule(

            r'FILE\s*\*\s*(\w+)\s*=\s*fopen\(([^,]+),\s*"w"\);',

            r"std::ofstream \1(\2);",

            "fopen -> ofstream"
        ),

        # fclose removal
        ModernizationRule(

            r'fclose\s*\(\s*(\w+)\s*\)\s*;',

            r"// handled by RAII",

            "fclose removed"
        ),

        # malloc char buffer → vector
        ModernizationRule(

            r'char\s*\*\s*(\w+)\s*=\s*\(char\*\)\s*malloc\s*\(([^)]*)\);',

            r"std::vector<char> \1(\2);",

            "malloc buffer -> vector"
        ),

        # new → make_unique
        ModernizationRule(

            r'(\w+)\s*=\s*new\s+([A-Za-z_]\w*)\s*\(([^)]*)\);',

            r"auto \1 = std::make_unique<\2>(\3);",

            "new -> make_unique"
        ),

        # delete removal
        ModernizationRule(

            r"delete\s+(\w+)\s*;",

            r"// handled by smart pointer",

            "delete removed"
        ),
    ]

    # ======================================================
    # COMMENT MASKING
    # ======================================================

    COMMENT_PATTERN = re.compile(

        r"//.*?$|/\*.*?\*/|\"(?:\\.|[^\"\\])*\"",

        re.DOTALL | re.MULTILINE
    )

    def _mask_comments(

        self,

        code: str

    ) -> str:

        return self.COMMENT_PATTERN.sub(

            lambda m: " " * len(m.group()),

            code
        )

    # ======================================================
    # APPLY RULES
    # ======================================================

    def modernize_text(

        self,

        code: str

    ) -> str:

        if not code:

            return code

        updated = code

        masked = self._mask_comments(updated)

        total_changes = 0

        for rule in self.RULES:

            matches = list(

                rule.pattern.finditer(masked)
            )

            if not matches:

                continue

            pieces = []

            cursor = 0

            for match in matches:

                start, end = match.span()

                pieces.append(

                    updated[cursor:start]
                )

                pieces.append(

                    match.expand(
                        rule.replacement
                    )
                )

                cursor = end

            pieces.append(

                updated[cursor:]
            )

            updated = "".join(pieces)

            masked = self._mask_comments(updated)

            total_changes += len(matches)

        if total_changes > 0:

            logger.info(

                f"[rule_modernizer] applied {total_changes} transformations"

            )

        # never return empty string
        if not updated.strip():

            return code

        return updated


# ==========================================================
# FUNCTION WRAPPER
# ==========================================================

def apply_modernization_rules(

    code: str

) -> Tuple[str, List[str]]:

    engine = RuleModernizer()

    updated = engine.modernize_text(code)

    return updated, []