from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Set

from core.parser import CppParser

_log = logging.getLogger(__name__)
_POSIX_FILE_FUNCTIONS = {"fopen", "fclose", "fread", "fwrite", "fscanf", "fprintf"}


class PatternName(Enum):
    RAW_NEW = "raw_new"
    RAW_DELETE = "raw_delete"
    PRINTF_USAGE = "printf_usage"
    RAW_POINTER = "raw_pointer"
    MALLOC_USAGE = "malloc_usage"
    FREE_USAGE = "free_usage"
    NULL_MACRO = "null_macro"
    C_STYLE_CAST = "c_style_cast"
    INDEX_LOOP = "index_loop"
    CHAR_POINTER = "char_pointer"
    MEMCPY_USAGE = "memcpy_usage"
    AUTO_PTR_USAGE = "auto_ptr_usage"
    THROW_SPEC = "throw_spec"
    RAW_ARRAY = "raw_array"
    C_STRING = "c_string"
    POSIX_FILE = "posix_file"
    MANUAL_INIT = "manual_init"

    def __str__(self) -> str:
        return self.value


class ASTNodeType(Enum):
    FUNCTION_DEFINITION = "function_definition"
    NEW_EXPRESSION = "new_expression"
    DELETE_EXPRESSION = "delete_expression"
    POINTER_DECLARATOR = "pointer_declarator"
    PARAMETER_DECLARATION = "parameter_declaration"
    DECLARATION = "declaration"
    CAST_EXPRESSION = "cast_expression"
    C_STYLE_CAST_EXPRESSION = "c_style_cast_expression"
    FOR_STATEMENT = "for_statement"
    CALL_EXPRESSION = "call_expression"
    IDENTIFIER = "identifier"
    TYPE_IDENTIFIER = "type_identifier"
    QUALIFIED_IDENTIFIER = "qualified_identifier"
    SCOPED_IDENTIFIER = "scoped_identifier"
    NOEXCEPT = "noexcept"
    THROW_SPECIFIER = "throw_specifier"
    DYNAMIC_EXCEPTION_SPECIFICATION = "dynamic_exception_specification"

    def __str__(self) -> str:
        return self.value


class ASTNode:
    def __init__(self, node: Any) -> None:
        self._node = node

    @property
    def node_type(self) -> str:
        if self._node is None: return ""
        if isinstance(self._node, dict): return str(self._node.get("type", ""))
        return str(getattr(self._node, "type", ""))

    @property
    def start_byte(self) -> int:
        if self._node is None: return 0
        if isinstance(self._node, dict): return int(self._node.get("start_byte", 0))
        return int(getattr(self._node, "start_byte", 0))

    @property
    def end_byte(self) -> int:
        if self._node is None: return 0
        if isinstance(self._node, dict): return int(self._node.get("end_byte", 0))
        return int(getattr(self._node, "end_byte", 0))

    @property
    def start_point(self) -> tuple[int, int]:
        if self._node is None: return (0, 0)
        try:
            p = self._node.get("start_point", (0, 0)) if isinstance(self._node, dict) else getattr(self._node, "start_point", (0, 0))
            return (int(p[0]), int(p[1]))
        except Exception:
            return (0, 0)

    @property
    def end_point(self) -> tuple[int, int]:
        if self._node is None: return (0, 0)
        try:
            p = self._node.get("end_point", (0, 0)) if isinstance(self._node, dict) else getattr(self._node, "end_point", (0, 0))
            return (int(p[0]), int(p[1]))
        except Exception:
            return (0, 0)

    @property
    def parent(self) -> Optional[ASTNode]:
        if self._node is None: return None
        try:
            parent_node = self._node.get("parent") if isinstance(self._node, dict) else getattr(self._node, "parent", None)
            return ASTNode(parent_node) if parent_node is not None else None
        except Exception:
            return None

    @property
    def children(self) -> List[ASTNode]:
        if self._node is None: return []
        try:
            raw_children = self._node.get("children", []) if isinstance(self._node, dict) else getattr(self._node, "children", ())
            return [ASTNode(child) for child in raw_children if child is not None]
        except Exception:
            return []

    def child_by_field_name(self, field_name: str) -> Optional[ASTNode]:
        if self._node is None: return None
        try:
            if isinstance(self._node, dict):
                val = self._node.get(field_name)
                return ASTNode(val) if val is not None else None
            method = getattr(self._node, "child_by_field_name", None)
            if method is None: return None
            child = method(field_name)
            return ASTNode(child) if child is not None else None
        except Exception:
            return None

    def get_text(self, source_bytes: bytes) -> str:
        start = self.start_byte
        end = self.end_byte
        if start < 0 or end < 0 or start > end or end > len(source_bytes):
            return ""
        try:
            return source_bytes[start:end].decode("utf-8", errors="replace")
        except Exception:
            _log.warning(f"Failed to decode node text at bytes {start}:{end}")
            return ""

    def ancestor_of_type(self, target_type: str) -> Optional[ASTNode]:
        current = self.parent
        while current is not None:
            if current.node_type == target_type:
                return current
            current = current.parent
        return None


@dataclass(frozen=True)
class DetectionConfig:
    enabled_patterns: Set[PatternName] = field(default_factory=lambda: set(PatternName))
    enable_cache: bool = True
    debug: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.enabled_patterns, set):
            object.__setattr__(self, "enabled_patterns", set(self.enabled_patterns))

    def is_pattern_enabled(self, pattern: PatternName) -> bool:
        return not self.enabled_patterns or pattern in self.enabled_patterns


@dataclass
class DetectionResult:
    counts: Dict[str, int]
    detected: List[str]
    locations: Dict[str, List[Dict[str, int]]]
    should_modernize: bool


class ASTModernizationDetector:
    def __init__(
        self, parser: Optional[CppParser] = None, config: Optional[DetectionConfig] = None
    ) -> None:
        self.parser = parser or CppParser()
        self.config = config or DetectionConfig()
        self._cache: Dict[str, DetectionResult] = {}

    def get_function_ast_node(self, function_source: str) -> Optional[ASTNode]:
        source_bytes = function_source.encode("utf-8")
        tree = self.parser.parse_bytes(source_bytes)
        for node in self._iter_ast(ASTNode(tree.root_node)):
            if node.node_type == ASTNodeType.FUNCTION_DEFINITION.value:
                return node
        return ASTNode(tree.root_node)

    def detect_legacy_patterns(
        self, function_node: Optional[ASTNode], source_bytes: bytes
    ) -> DetectionResult:
        if function_node is None or not source_bytes:
            empty_result = self._empty_result()
            if self.config.debug:
                _log.debug("Returning empty detection: no function node or source")
            return empty_result

        cache_key = self._compute_function_hash(source_bytes)
        if self.config.enable_cache and cache_key in self._cache:
            if self.config.debug:
                _log.debug(f"Cache hit for function {cache_key[:8]}...")
            return self._cache[cache_key]

        patterns: Dict[str, int] = {str(p): 0 for p in PatternName}
        locations: Dict[str, List[Dict[str, int]]] = defaultdict(list)
        pointers_enabled = self.config.is_pattern_enabled(PatternName.RAW_POINTER) or self.config.is_pattern_enabled(PatternName.CHAR_POINTER)
        calls_enabled = (
            self.config.is_pattern_enabled(PatternName.PRINTF_USAGE)
            or self.config.is_pattern_enabled(PatternName.MALLOC_USAGE)
            or self.config.is_pattern_enabled(PatternName.FREE_USAGE)
            or self.config.is_pattern_enabled(PatternName.MEMCPY_USAGE)
            or self.config.is_pattern_enabled(PatternName.POSIX_FILE)
        )

        for node in self._iter_ast(function_node):
            node_type = node.node_type

            if self.config.is_pattern_enabled(PatternName.RAW_NEW) and node_type == ASTNodeType.NEW_EXPRESSION.value:
                patterns[str(PatternName.RAW_NEW)] += 1
                self._record_location(locations, PatternName.RAW_NEW, node)

            if self.config.is_pattern_enabled(PatternName.RAW_DELETE) and node_type == ASTNodeType.DELETE_EXPRESSION.value:
                patterns[str(PatternName.RAW_DELETE)] += 1
                self._record_location(locations, PatternName.RAW_DELETE, node)

            if pointers_enabled and node_type == ASTNodeType.POINTER_DECLARATOR.value:
                self._detect_pointers(node, source_bytes, patterns, locations)

            if self.config.is_pattern_enabled(PatternName.RAW_ARRAY) and node_type in {"array_declarator", "pointer_declarator"} and self._is_raw_array_decl(node, source_bytes):
                patterns[str(PatternName.RAW_ARRAY)] += 1
                self._record_location(locations, PatternName.RAW_ARRAY, node)

            # C_STRING pattern detection removed due to overzealous and dead code nature

            if self.config.is_pattern_enabled(PatternName.C_STYLE_CAST) and node_type in {
                ASTNodeType.CAST_EXPRESSION.value,
                ASTNodeType.C_STYLE_CAST_EXPRESSION.value,
            }:
                patterns[str(PatternName.C_STYLE_CAST)] += 1
                self._record_location(locations, PatternName.C_STYLE_CAST, node)

            if self.config.is_pattern_enabled(PatternName.INDEX_LOOP) and node_type == ASTNodeType.FOR_STATEMENT.value and self._is_index_based_for_loop(node, source_bytes):
                patterns[str(PatternName.INDEX_LOOP)] += 1
                self._record_location(locations, PatternName.INDEX_LOOP, node)

            if calls_enabled and node_type == ASTNodeType.CALL_EXPRESSION.value:
                self._detect_function_calls(node, source_bytes, patterns, locations)

            if self.config.is_pattern_enabled(PatternName.NULL_MACRO) and node_type == ASTNodeType.IDENTIFIER.value:
                node_text = node.get_text(source_bytes)
                if node_text == "NULL":
                    patterns[str(PatternName.NULL_MACRO)] += 1
                    self._record_location(locations, PatternName.NULL_MACRO, node)

            if self.config.is_pattern_enabled(PatternName.AUTO_PTR_USAGE) and node_type in {
                ASTNodeType.TYPE_IDENTIFIER.value,
                ASTNodeType.QUALIFIED_IDENTIFIER.value,
                ASTNodeType.SCOPED_IDENTIFIER.value,
            }:
                node_text = node.get_text(source_bytes)
                if "std::auto_ptr" in node_text or "auto_ptr" in node_text:
                    patterns[str(PatternName.AUTO_PTR_USAGE)] += 1
                    self._record_location(locations, PatternName.AUTO_PTR_USAGE, node)

            # MANUAL_INIT pattern removed due to false positives on legitimate initialization

            if self.config.is_pattern_enabled(PatternName.THROW_SPEC) and node_type in {
                ASTNodeType.NOEXCEPT.value,
                ASTNodeType.THROW_SPECIFIER.value,
                ASTNodeType.DYNAMIC_EXCEPTION_SPECIFICATION.value,
            }:
                self._detect_throw_spec(node, source_bytes, patterns, locations)

        detected = [name for name, count in patterns.items() if count > 0]
        should_modernize = bool(detected)

        result = DetectionResult(
            counts=patterns,
            detected=detected,
            locations={name: rows for name, rows in locations.items() if rows},
            should_modernize=should_modernize,
        )

        if self.config.enable_cache:
            self._cache[cache_key] = result

        if self.config.debug:
            _log.debug(f"Detected {len(detected)} pattern(s): {detected}")

        return result

    def should_modernize(self, function_node: Optional[ASTNode], source_bytes: bytes) -> bool:
        return self.detect_legacy_patterns(function_node, source_bytes).should_modernize

    def _iter_ast(self, root: Optional[ASTNode]) -> Iterable[ASTNode]:
        if root is None:
            return
        stack: List[ASTNode] = [root]
        while stack:
            current = stack.pop()
            yield current
            for child in reversed(current.children):
                stack.append(child)

    def _record_location(
        self,
        bucket: Dict[str, List[Dict[str, int]]],
        pattern: PatternName,
        node: ASTNode,
    ) -> None:
        start_row, start_col = node.start_point
        end_row, end_col = node.end_point
        bucket[str(pattern)].append(
            {
                "start_line": int(start_row) + 1,
                "start_col": int(start_col) + 1,
                "end_line": int(end_row) + 1,
                "end_col": int(end_col) + 1,
            }
        )

    def _detect_pointers(
        self,
        node: ASTNode,
        source_bytes: bytes,
        patterns: Dict[str, int],
        locations: Dict[str, List[Dict[str, int]]],
    ) -> None:
        decl_text = self._pointer_declaration_text(node, source_bytes)
        lowered = decl_text.lower()
        is_parameter = node.ancestor_of_type(ASTNodeType.PARAMETER_DECLARATION.value) is not None
        is_local_decl = node.ancestor_of_type(ASTNodeType.DECLARATION.value) is not None
        is_const_qualified = bool(re.search(r"\bconst\b", lowered))
        is_manually_managed = bool(re.search(r"\b(?:new|malloc|calloc|realloc)\b", lowered))
        
        if is_local_decl and not is_parameter and not is_const_qualified and is_manually_managed:
            patterns[str(PatternName.RAW_POINTER)] += 1
            self._record_location(locations, PatternName.RAW_POINTER, node)

        if is_local_decl and not is_parameter and "char" in lowered and not is_const_qualified and is_manually_managed:
            patterns[str(PatternName.CHAR_POINTER)] += 1
            self._record_location(locations, PatternName.CHAR_POINTER, node)

    def _detect_function_calls(
        self,
        node: ASTNode,
        source_bytes: bytes,
        patterns: Dict[str, int],
        locations: Dict[str, List[Dict[str, int]]],
    ) -> None:
        func_name = self._extract_function_name(node, source_bytes)
        for pattern, target in (
            (PatternName.PRINTF_USAGE, "printf"),
            (PatternName.MALLOC_USAGE, "malloc"),
            (PatternName.FREE_USAGE, "free"),
            (PatternName.MEMCPY_USAGE, "memcpy"),
        ):
            if self.config.is_pattern_enabled(pattern) and func_name == target:
                patterns[str(pattern)] += 1
                self._record_location(locations, pattern, node)

        if self.config.is_pattern_enabled(PatternName.POSIX_FILE) and func_name in _POSIX_FILE_FUNCTIONS:
            patterns[str(PatternName.POSIX_FILE)] += 1
            self._record_location(locations, PatternName.POSIX_FILE, node)

    def _detect_throw_spec(
        self,
        node: ASTNode,
        source_bytes: bytes,
        patterns: Dict[str, int],
        locations: Dict[str, List[Dict[str, int]]],
    ) -> None:
        node_text = node.get_text(source_bytes)
        if re.search(r"\bthrow\s*\([^)]*\)\s*(?:{|;)", node_text):
            patterns[str(PatternName.THROW_SPEC)] += 1
            self._record_location(locations, PatternName.THROW_SPEC, node)

    def _extract_function_name(self, call_expr: ASTNode, source_bytes: bytes) -> str:
        func_child = call_expr.child_by_field_name("function")
        if func_child is not None:
            func_text = str(func_child.get_text(source_bytes))
            if isinstance(func_text, str):
                for sep in ("::", "."):
                    if sep in func_text:
                        func_text = func_text.split(sep)[-1]
            return func_text.strip()

        call_text = call_expr.get_text(source_bytes)
        match = re.match(r"(?:\w+::)*(\w+)\s*\(", call_text)
        return match.group(1) if match else ""

    def _pointer_declaration_text(self, pointer_node: ASTNode, source_bytes: bytes) -> str:
        if param_decl := pointer_node.ancestor_of_type(ASTNodeType.PARAMETER_DECLARATION.value):
            return param_decl.get_text(source_bytes)
        if decl := pointer_node.ancestor_of_type(ASTNodeType.DECLARATION.value):
            return decl.get_text(source_bytes)
        return pointer_node.get_text(source_bytes)

    def _is_index_based_for_loop(self, for_node: ASTNode, source_bytes: bytes) -> bool:
        init = for_node.child_by_field_name("initializer")
        condition = for_node.child_by_field_name("condition")
        update = for_node.child_by_field_name("update")

        if init is None or condition is None or update is None:
            return False

        init_text = init.get_text(source_bytes)
        cond_text = condition.get_text(source_bytes)
        update_text = update.get_text(source_bytes)

        init_match = re.search(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:0|.*)\b",
            init_text,
        )
        if not init_match:
            return False

        index_var = init_match.group(1)

        return (
            re.search(rf"\b{re.escape(index_var)}\b\s*(?:<|<=)\s*", cond_text) is not None
            and re.search(
                rf"(?:\+\+\s*{re.escape(index_var)}|{re.escape(index_var)}\s*\+\+|{re.escape(index_var)}\s*\+=\s*1)",
                update_text,
            ) is not None
        )

    def _is_raw_array_decl(self, node: ASTNode, source_bytes: bytes) -> bool:
        text = node.get_text(source_bytes).lower()
        return "[]" in text and "std::array" not in text

    def _compute_function_hash(self, source_bytes: bytes) -> str:
        return hashlib.sha256(source_bytes).hexdigest()

    def _empty_result(self) -> DetectionResult:
        return DetectionResult(counts={str(p): 0 for p in PatternName}, detected=[], locations={}, should_modernize=False)
