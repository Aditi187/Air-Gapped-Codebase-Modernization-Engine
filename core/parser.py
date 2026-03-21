from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from pathlib import Path
from typing import Any, Iterable

from tree_sitter import Language, Parser

logger = logging.getLogger(__name__)


_CPP_KEYWORDS_TO_IGNORE = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
    "alignof",
    "decltype",
    "new",
    "delete",
    "throw",
    "catch",
    "static_cast",
    "dynamic_cast",
    "reinterpret_cast",
    "const_cast",
}

_MODIFIER_TOKENS = ("virtual", "static", "inline", "constexpr", "consteval", "noexcept", "override", "final")
MAX_AST_NODES: int = max(1_000_000, int(os.environ.get("CPP_PARSER_MAX_AST_NODES", "1000000")))

_thread_local = threading.local()

_STD_HEADER_SYMBOLS: dict[str, set[str]] = {
    "<vector>": {"std::vector", "vector"},
    "<string>": {"std::string", "string"},
    "<map>": {"std::map", "map"},
    "<unordered_map>": {"std::unordered_map", "unordered_map"},
    "<set>": {"std::set", "set"},
    "<unordered_set>": {"std::unordered_set", "unordered_set"},
    "<memory>": {"std::unique_ptr", "std::shared_ptr", "unique_ptr", "shared_ptr"},
    "<optional>": {"std::optional", "optional"},
    "<variant>": {"std::variant", "variant"},
    "<tuple>": {"std::tuple", "tuple"},
    "<utility>": {"std::move", "std::forward", "move", "forward"},
    "<algorithm>": {"std::sort", "std::find", "sort", "find"},
    "<iostream>": {"std::cout", "std::cin", "std::cerr", "cout", "cin", "cerr"},
    "<sstream>": {"std::stringstream", "std::ostringstream", "std::istringstream"},
    "<thread>": {"std::thread", "thread"},
    "<mutex>": {"std::mutex", "std::lock_guard", "mutex", "lock_guard"},
    "<chrono>": {"std::chrono", "chrono"},
    "<span>": {"std::span", "span"},
    "<expected>": {"std::expected", "expected"},
    "<format>": {"std::format", "format"},
    "<print>": {"std::print", "print"},
    "<ranges>": {"std::ranges", "ranges", "views"},
}


_TEMPLATE_SYMBOL_BASES: dict[str, set[str]] = {
    "<vector>": {"vector"},
    "<string>": {"string", "string_view"},
    "<map>": {"map", "multimap"},
    "<unordered_map>": {"unordered_map", "unordered_multimap"},
    "<set>": {"set", "multiset"},
    "<unordered_set>": {"unordered_set", "unordered_multiset"},
    "<optional>": {"optional"},
    "<variant>": {"variant"},
    "<tuple>": {"tuple"},
    "<memory>": {"unique_ptr", "shared_ptr", "weak_ptr"},
    "<span>": {"span"},
    "<expected>": {"expected", "unexpected"},
    "<format>": {"format", "vformat"},
    "<print>": {"print", "println"},
    "<ranges>": {"ranges", "views"},
}


class CppParser:
    def __init__(self) -> None:
        self._parser = self._create_cpp_parser()
        self._last_project_map: dict[str, Any] | None = None
        self._workspace_root: Path | None = None
        self._current_file_path: str = ""

    @staticmethod
    def _create_cpp_parser() -> Parser:
        existing = getattr(_thread_local, "cpp_parser", None)
        if existing is not None:
            return existing
        try:
            import tree_sitter_cpp
        except ImportError as e:
            raise RuntimeError("tree-sitter-cpp not installed") from e
        cpp_lang = Language(tree_sitter_cpp.language())
        parser = Parser()
        if hasattr(parser, "language"):
            parser.language = cpp_lang
        elif hasattr(parser, "set_language"):
            parser.set_language(cpp_lang)  # type: ignore[attr-defined]
        else:
            raise RuntimeError("Unsupported tree-sitter Parser API")
        _thread_local.cpp_parser = parser
        return parser

    def parse_file(self, file_path: str | Path, workspace_root: str | Path | None = None) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"C++ file not found: {path}")
        if workspace_root is not None:
            self._workspace_root = Path(workspace_root)
        self._current_file_path = str(path)
        return self.parse_string(path.read_text(encoding="utf-8"), source_file=str(path))

    def parse_string(self, source_text: str, source_file: str = "") -> dict[str, Any]:
        try:
            tree = self._parser.parse(source_text.encode("utf-8"))
        except Exception:
            project_map = {"functions": {}, "type_definitions": {}, "dependency_order": [], "include_requirements": {}, "headers": [], "types": [], "global_context": {}, "global_variables": []}
            self._last_project_map = project_map
            return project_map
        source_b = source_text.encode("utf-8")
        project_map = self._collect_semantic_map_single_pass(tree.root_node, source_text, source_b, source_file=source_file or self._current_file_path)
        project_map["module_imports"] = detect_module_imports(source_text)
        self._last_project_map = project_map
        return project_map

    def parse_bytes(self, source_bytes: bytes) -> Any:
        return self._parser.parse(source_bytes)

    def iter_nodes(self, root: Any) -> Iterable[Any]:
        return self._iter_nodes(root)

    def node_text(self, node: Any, source_bytes: bytes) -> str:
        return self._node_text(node, source_bytes)

    def get_context_for_function(self, fqn: str) -> dict[str, Any]:
        if self._last_project_map is None:
            raise ValueError("No ProjectMap available")
        funcs = self._last_project_map.get("functions", {})
        if not isinstance(funcs, dict):
            raise KeyError(f"Function not found: {fqn}")
        if fqn not in funcs:
            legacy = [k for k, m in funcs.items() if str(m.get("fqn") or "") == fqn]
            if len(legacy) == 1:
                fqn = legacy[0]
            elif len(legacy) > 1:
                raise KeyError(f"FQN ambiguous: {fqn}")
            else:
                raise KeyError(f"Function not found: {fqn}")
        func = funcs[fqn]
        body = str(func.get("body") or "")
        internal_calls = func.get("internal_calls", [])
        called_sigs = {cf: str(funcs[cf].get("signature") or "") for cf in internal_calls if isinstance(funcs.get(cf), dict)}
        type_defs = self._last_project_map.get("type_definitions", {})
        ref_types = {tn: str(ts) for tn, ts in (type_defs.items() if isinstance(type_defs, dict) else []) if self._symbol_in_text(tn, body)}
        return {"fqn": fqn, "body": body, "called_function_signatures": called_sigs, "referenced_type_definitions": ref_types}

    @staticmethod
    def _compute_signature_hash(params: list[dict[str, Any]], sig_text: str = "", function_name: str = "") -> str:
        if sig_text:
            norm = re.sub(r"/\*.*?\*/", " ", sig_text, flags=re.DOTALL)
            norm = re.sub(r"//[^\n]*", " ", norm)
            norm = re.sub(r"\s+", " ", norm).strip()
            if norm:
                norm = f"{function_name}|{norm}"
                return hashlib.md5(norm.encode()).hexdigest()[:8]
        type_str = ",".join(str(p.get("type") or "") for p in params)
        norm = f"{function_name}|{type_str}"
        norm = re.sub(r"\s+", " ", norm).strip()
        return hashlib.md5(norm.encode()).hexdigest()[:8]

    def _process_ast_node(self, node: Any, scope_stack: list[str], source_text: str, source_bytes: bytes, line_starts: list[int], source_file: str, functions: list[dict[str, Any]], headers: list[str], types: list[dict[str, Any]], global_context: dict[str, list[dict[str, Any]]]) -> str | None:
        if node.type == "function_definition":
            functions.append(self._build_function_record(node, scope_stack, source_text, source_bytes, line_starts, source_file))
        if node.type == "preproc_include":
            h = self._extract_include_directive(node, source_bytes)
            if h and h not in headers:
                headers.append(h)
        t = self._build_type_record(node, scope_stack, source_bytes, line_starts)
        if t is not None:
            types.append(t)
            ctx_bucket = t.get("type")
            if isinstance(ctx_bucket, str) and ctx_bucket in global_context:
                global_context[ctx_bucket].append(t)
        return self._scope_name(node, source_bytes)

    def _collect_semantic_map_single_pass(self, root_node: Any, source_text: str, source_bytes: bytes, source_file: str = "") -> dict[str, Any]:
        scope_stack, funcs, types, headers = [], [], [], []
        global_ctx = {"struct": [], "class": [], "enum": [], "typedef": [], "type_alias": []}
        line_starts = self._compute_line_start_bytes(source_text)
        stack = [(root_node, 0, False)]
        while stack:
            node, phase, pushed = stack.pop()
            if phase == 1:
                if pushed and scope_stack:
                    scope_stack.pop()
                continue
            scope_name = self._process_ast_node(node, scope_stack, source_text, source_bytes, line_starts, source_file, funcs, headers, types, global_ctx)
            pushed_now = scope_name is not None
            if pushed_now:
                scope_stack.append(scope_name)
            stack.append((node, 1, pushed_now))
            for child in reversed(node.children):
                stack.append((child, 0, False))
        glob_vars = self._collect_global_variables(root_node, source_bytes, line_starts)
        return self._build_project_map(funcs, types, headers, global_ctx, glob_vars)

    def _build_project_map(
        self,
        functions: list[dict[str, Any]],
        types: list[dict[str, Any]],
        headers: list[str],
        global_context: dict[str, list[dict[str, Any]]],
        global_variables: list[dict[str, Any]],
    ) -> dict[str, Any]:
        function_map: dict[str, dict[str, Any]] = {}
        type_definitions: dict[str, str] = {}

        for t in types:
            type_name = str(t.get("name") or "")
            if type_name and type_name not in type_definitions:
                type_definitions[type_name] = str(t.get("source_code") or "")

        all_function_ids = {
            str(f.get("unique_fqn") or f.get("fqn") or "")
            for f in functions
            if f.get("unique_fqn") or f.get("fqn")
        }
        name_to_function_ids: dict[str, list[str]] = {}
        legacy_fqn_to_ids: dict[str, list[str]] = {}
        for f in functions:
            name = str(f.get("name") or "")
            function_id = str(f.get("unique_fqn") or f.get("fqn") or "")
            legacy_fqn = str(f.get("fqn") or "")
            if name and function_id:
                name_to_function_ids.setdefault(name, []).append(function_id)
            if legacy_fqn and function_id:
                legacy_fqn_to_ids.setdefault(legacy_fqn, []).append(function_id)
        inbound: dict[str, set[str]] = {function_id: set() for function_id in all_function_ids}
        include_requirements: dict[str, list[str]] = {}

        for f in functions:
            function_id = str(f.get("unique_fqn") or f.get("fqn") or "")
            if not function_id:
                continue
            call_details = f.get("call_details", [])
            internal_calls: list[str] = []
            external_calls: list[str] = []

            if isinstance(call_details, list):
                for entry in call_details:
                    if not isinstance(entry, dict):
                        continue
                    call_name = str(entry.get("name") or "")
                    call_display = str(entry.get("display") or call_name)
                    normalized = self._normalize_call_target(call_name, call_display)

                    if normalized in all_function_ids:
                        if normalized != function_id:
                            internal_calls.append(normalized)
                            inbound[normalized].add(function_id)
                        continue

                    if normalized in legacy_fqn_to_ids:
                        for candidate_id in legacy_fqn_to_ids[normalized]:
                            if candidate_id != function_id:
                                internal_calls.append(candidate_id)
                                inbound[candidate_id].add(function_id)
                        continue

                    if normalized in name_to_function_ids:
                        overload_candidates = name_to_function_ids[normalized]
                        for candidate_id in overload_candidates:
                            if candidate_id != function_id:
                                internal_calls.append(candidate_id)
                                inbound[candidate_id].add(function_id)
                        continue
                    if call_display:
                        external_calls.append(call_display)

            internal_calls = sorted(set(internal_calls))
            external_calls = sorted(set(external_calls))

            includes_for_function = self._compute_include_requirements_for_function(f, headers)
            include_requirements[function_id] = includes_for_function

            out_degree = len(internal_calls)
            in_degree = len(inbound.get(function_id, set()))
            is_leaf = out_degree == 0
            is_root = in_degree >= 2 and out_degree <= 1

            merged = dict(f)
            merged["internal_calls"] = internal_calls
            merged["external_calls"] = external_calls
            merged["incoming_calls_count"] = in_degree
            merged["outgoing_calls_count"] = out_degree
            merged["is_leaf"] = is_leaf
            merged["is_root"] = is_root
            function_map[function_id] = merged

        dependency_order = self._compute_modernization_priority(function_map)

        return {
            "functions": function_map,
            "type_definitions": type_definitions,
            "dependency_order": dependency_order,
            "include_requirements": include_requirements,
            "headers": headers,
            "types": types,
            "global_context": global_context,
            "global_variables": global_variables,
        }

    def _normalize_call_target(self, call_name: str, call_display: str) -> str:
        if "::" in call_display:
            return call_display
        return call_name or call_display

    def _compute_modernization_priority(self, function_map: dict[str, dict[str, Any]]) -> list[str]:
        leaves: list[str] = []
        roots: list[str] = []
        middles: list[str] = []

        for fqn, meta in function_map.items():
            in_degree = int(meta.get("incoming_calls_count", 0))
            out_degree = int(meta.get("outgoing_calls_count", 0))
            if out_degree == 0:
                leaves.append(fqn)
            elif in_degree >= 2 and out_degree <= 1:
                roots.append(fqn)
            else:
                middles.append(fqn)
        leaves.sort(key=lambda f: (function_map[f].get("incoming_calls_count", 0), f))
        middles.sort(key=lambda f: (function_map[f].get("outgoing_calls_count", 0), -int(function_map[f].get("incoming_calls_count", 0)), f))
        roots.sort(key=lambda f: (-int(function_map[f].get("incoming_calls_count", 0)), int(function_map[f].get("outgoing_calls_count", 0)), f))
        return [*leaves, *middles, *roots]

    def _compute_include_requirements_for_function(
        self,
        function_meta: dict[str, Any],
        headers: list[str],
    ) -> list[str]:
        body = str(function_meta.get("body") or "")
        signature = str(function_meta.get("signature") or "")
        joined_calls = "\n".join(
            str(entry.get("display") or entry.get("name") or "")
            for entry in (function_meta.get("call_details") or [])
            if isinstance(entry, dict)
        )
        text = "\n".join([signature, body, joined_calls])
        required: list[str] = []
        candidate_headers: set[str] = {
            name
            for hl in headers
            if (name := self._extract_header_name(hl))
        }
        candidate_headers.update(_STD_HEADER_SYMBOLS.keys())
        candidate_headers.update(_TEMPLATE_SYMBOL_BASES.keys())

        for header_name in sorted(candidate_headers):
            if not header_name:
                continue

            known_symbols = _STD_HEADER_SYMBOLS.get(header_name)
            if known_symbols:
                if any(self._symbol_in_text(symbol, text) for symbol in known_symbols):
                    required.append(header_name)
                    continue

            template_bases = _TEMPLATE_SYMBOL_BASES.get(header_name)
            if template_bases:
                if any(self._symbol_or_template_use(base_symbol, text) for base_symbol in template_bases):
                    required.append(header_name)
                    continue
            if header_name.startswith('"') and header_name.endswith('"'):
                base = Path(header_name.strip('"')).stem
                if base and self._symbol_in_text(base, text):
                    required.append(header_name)

        return sorted(set(required))

    @staticmethod
    def _extract_header_name(inc_line: str) -> str:
        m = re.search(r"#\s*include\s*([<\"].*[>\"])", inc_line)
        return m.group(1).strip() if m else ""

    @staticmethod
    def _symbol_in_text(sym: str, text: str) -> bool:
        if not sym:
            return False
        pattern = r"(?<!\w)" + re.escape(sym) + r"(?!\w)"
        return re.search(pattern, text) is not None

    @staticmethod
    def _symbol_or_template_use(base_sym: str, text: str) -> bool:
        if not base_sym:
            return False
        plain = r"(?<!\w)(?:std::)?" + re.escape(base_sym) + r"(?!\w)"
        template = r"(?<!\w)(?:std::)?" + re.escape(base_sym) + r"\s*<"
        return re.search(plain, text) is not None or re.search(template, text) is not None

    @staticmethod
    def _extract_include_directive(node: Any, source_bytes: bytes) -> str:
        return CppParser._node_text(node, source_bytes).strip()

    @staticmethod
    def _scope_name(node: Any, source_bytes: bytes) -> str | None:
        if node.type == "namespace_definition":
            nn = node.child_by_field_name("name")
            if nn is None:
                return None
            return CppParser._node_text(nn, source_bytes).strip() or None
        if node.type in {"class_specifier", "struct_specifier"}:
            nn = node.child_by_field_name("name")
            if nn is None:
                for child in node.children:
                    if child.type in {"type_identifier", "identifier"}:
                        nn = child
                        break
            if nn is None:
                return None
            return CppParser._node_text(nn, source_bytes).strip() or None
        return None

    def _build_function_record(
        self,
        node: Any,
        scope_stack: list[str],
        source_text: str,
        source_bytes: bytes,
        line_starts: list[int],
        source_file: str = "",
    ) -> dict[str, Any]:
        owner_node = self._ownership_node(node)
        qual_parts = self._extract_function_qualified_parts(node, source_bytes)
        function_name = qual_parts[-1]
        if len(qual_parts) > 1:
            best_overlap = 0
            for overlap_len in range(min(len(scope_stack), len(qual_parts)), 0, -1):
                if list(scope_stack[-overlap_len:]) == qual_parts[:overlap_len]:
                    best_overlap = overlap_len
                    break
            fqn = "::".join([*scope_stack, *qual_parts[best_overlap:]])
        else:
            fqn = "::".join([*scope_stack, function_name]) if scope_stack else function_name

        body_node = node.child_by_field_name("body")
        body_text = self._node_text(body_node, source_bytes).strip() if body_node else ""

        signature_end_byte = body_node.start_byte if body_node is not None else node.end_byte
        ownership_start = self._ownership_start_byte(owner_node, source_text, source_bytes, line_starts)
        signature_text = source_bytes[ownership_start:signature_end_byte].decode(
            "utf-8", errors="replace"
        ).strip()

        start_line = self._byte_to_line_number(ownership_start, line_starts)
        end_line = node.end_point[0] + 1
        loc = max(1, end_line - start_line + 1)

        calls = self._collect_function_calls(node, source_bytes)
        modifiers = self._extract_modifiers(signature_text)
        parameters = self._extract_structured_parameters(node, source_bytes)
        signature_hash = self._compute_signature_hash(parameters, sig_text=signature_text, function_name=function_name)
        unique_fqn = f"{fqn}#{signature_hash}" if fqn else f"{function_name}#{signature_hash}"
        lower_signature = signature_text.lower()
        lower_body = body_text.lower()
        loops = sum(
            1 for sub in self._iter_nodes(node)
            if sub.type in {"for_statement", "while_statement", "do_statement", "range_based_for_statement"}
        )
        branches = sum(
            1 for sub in self._iter_nodes(node)
            if sub.type in {"if_statement", "switch_statement", "conditional_expression"}
        )
        call_count = len(calls)
        complexity = loops + branches + call_count
        function_hash = hashlib.sha256(body_text.encode("utf-8")).hexdigest()
        legacy_patterns = {
            "has_raw_pointer": "*" in signature_text and "const" not in lower_signature,
            "has_printf": "printf" in lower_body,
            "has_malloc": "malloc" in lower_body,
            "has_free": "free" in lower_body,
            "has_null_macro": bool(re.search(r"\bNULL\b", body_text)),
        }

        return {
            "fqn": fqn,
            "unique_fqn": unique_fqn,
            "name": function_name,
            "signature": signature_text,
            "signature_hash": signature_hash,
            "body": body_text,
            "parameters": parameters,
            "call_details": calls,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
            "line_numbers": {"start": start_line, "end": end_line},
            "loc": loc,
            "is_template": owner_node.type == "template_declaration" or "template<" in lower_signature,
            "modifiers": modifiers,
            "legacy_patterns": legacy_patterns,
            "complexity": complexity,
            "function_hash": function_hash,
            "file_path": source_file,
        }

    def _build_type_record(
        self,
        node: Any,
        scope_stack: list[str],
        source_bytes: bytes,
        line_starts: list[int],
    ) -> dict[str, Any] | None:
        node_type_map = {
            "class_specifier": "class",
            "struct_specifier": "struct",
            "enum_specifier": "enum",
            "type_definition": "typedef",
            "alias_declaration": "type_alias",
            "using_declaration": "type_alias",
        }

        semantic_type = node_type_map.get(node.type)
        if semantic_type is None:
            return None
        type_name = self._extract_type_name(node, source_bytes)
        if not type_name:
            return None

        fqn = "::".join([*scope_stack, type_name]) if scope_stack else type_name
        source_code = self._node_text(node, source_bytes)
        start_line = self._byte_to_line_number(node.start_byte, line_starts)
        end_line = node.end_point[0] + 1
        bases: list[str] = []
        if node.type in {"class_specifier", "struct_specifier"}:
            bases = [
                base_name
                for child in node.children
                if child.type == "base_class_clause"
                for base_child in child.children
                if base_child.type in {
                    "type_identifier",
                    "qualified_identifier",
                    "scoped_type_identifier",
                    "scoped_identifier",
                }
                if (base_name := self._node_text(base_child, source_bytes).strip())
            ]

        return {
            "fqn": fqn,
            "name": type_name,
            "type": semantic_type,
            "source_code": source_code,
            "line_numbers": {"start": start_line, "end": end_line},
            "bases": bases,
        }

    @staticmethod
    def _ownership_node(func_node: Any) -> Any:
        p = func_node.parent
        if p is not None and p.type == "template_declaration":
            return p
        return func_node

    @staticmethod
    def _compute_line_start_bytes(src_text: str) -> list[int]:
        starts, offset = [0], 0
        for line in src_text.splitlines(keepends=True):
            offset += len(line.encode("utf-8"))
            starts.append(offset)
        return starts

    @staticmethod
    def _byte_to_line_number(byte_offset: int, line_starts: list[int]) -> int:
        lo, hi = 0, len(line_starts) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if line_starts[mid] <= byte_offset:
                lo = mid + 1
            else:
                hi = mid - 1
        return max(1, hi + 1)

    def _ownership_start_byte(self, owner_node: Any, source_text: str, source_bytes: bytes, line_starts: list[int]) -> int:
        owner_row = owner_node.start_point[0]
        lines = source_text.splitlines()
        row, first_row = owner_row - 1, owner_row
        seen_comment = False
        while row >= 0:
            line = lines[row].strip() if row < len(lines) else ""
            is_empty, is_comment = not line, self._is_comment_line(line) if line else False
            if is_empty and seen_comment:
                first_row = row
            elif not is_empty and not is_comment:
                break
            elif is_comment:
                seen_comment, first_row = True, row
            row -= 1
        if seen_comment and 0 <= first_row < len(line_starts):
            return line_starts[first_row]
        return owner_node.start_byte

    @staticmethod
    def _is_comment_line(line: str) -> bool:
        return line.startswith(("//", "/*", "*")) or line.endswith("*/")

    def _extract_function_qualified_parts(self, function_node: Any, source_bytes: bytes) -> list[str]:
        declarator = function_node.child_by_field_name("declarator")
        search_root = declarator if declarator is not None else function_node

        for found in self._iter_nodes(search_root):
            if found.type in {"qualified_identifier", "scoped_identifier"}:
                text = self._node_text(found, source_bytes).strip()
                if text:
                    parts = [p.strip() for p in text.split("::") if p.strip()]
                    if parts:
                        return parts

        skipped_subtrees = {
            "parameter_list",
            "template_parameter_list",
            "argument_list",
        }
        stack: list[Any] = [search_root]
        while stack:
            current = stack.pop()
            if current.type in {"identifier", "field_identifier", "operator_name"}:
                text = self._node_text(current, source_bytes).strip()
                if text:
                    return [text]
            for child in reversed(current.children):
                if child.type in skipped_subtrees:
                    continue
                stack.append(child)

        return ["<anonymous_function>"]

    def _extract_function_name(self, function_node: Any, source_bytes: bytes) -> str:
        return self._extract_function_qualified_parts(function_node, source_bytes)[-1]

    def _extract_structured_parameters(
        self, function_node: Any, source_bytes: bytes
    ) -> list[dict[str, Any]]:
        declarator = function_node.child_by_field_name("declarator")
        if declarator is None:
            return []

        param_list_node: Any | None = None
        for sub in self._iter_nodes(declarator):
            if sub.type == "parameter_list":
                param_list_node = sub
                break

        if param_list_node is None:
            return []
        
        params = []
        for child in param_list_node.children:
            if child.type == "parameter_declaration":
                params.append(self._parse_parameter_node(child, source_bytes))
            elif child.type == "void_type":
                params.append({
                    "name": "",
                    "type": "void",
                    "is_pointer": False,
                    "is_reference": False,
                    "is_const": False,
                })
        return params

    def _parse_parameter_node(
        self, param_node: Any, source_bytes: bytes
    ) -> dict[str, Any]:
        full_text = self._node_text(param_node, source_bytes).strip()
        
        type_node = param_node.child_by_field_name("type")
        type_str = self._node_text(type_node, source_bytes).strip() if type_node else ""
        
        decl_node = param_node.child_by_field_name("declarator")
        name = self._extract_declarator_name(decl_node, source_bytes) if decl_node else ""
        
        is_pointer = "*" in full_text
        is_reference = "&" in full_text
        is_const = "const" in full_text
        
        if not type_str:
            type_parts: list[str] = []
            for child in param_node.children:
                ctype = child.type
                ctext = self._node_text(child, source_bytes).strip()
                if ctype in {
                    "primitive_type", "type_identifier", "sized_type_specifier",
                    "qualified_identifier", "scoped_type_identifier", "template_type",
                    "placeholder_type_specifier", "auto"
                }:
                    type_parts.append(ctext)
            type_str = " ".join(type_parts)

        return {
            "name": name,
            "type": type_str,
            "is_pointer": is_pointer,
            "is_reference": is_reference,
            "is_const": is_const,
        }

    def _extract_declarator_name(self, node: Any, source_bytes: bytes) -> str:
        for child in node.children:
            if child.type == "identifier":
                return self._node_text(child, source_bytes).strip()
            if child.type in {"pointer_declarator", "reference_declarator", "rvalue_reference_declarator"}:
                res = self._extract_declarator_name(child, source_bytes)
                if res:
                    return res
        return ""

    def _collect_function_calls(self, node: Any, source_bytes: bytes) -> list[dict[str, str]]:
        bn = node.child_by_field_name("body")
        if bn is None:
            return []
        calls, seen = [], set()
        for n in self._iter_nodes(bn):
            if n.type != "call_expression":
                continue
            cn = n.child_by_field_name("function")
            if cn is None:
                continue
            if cn.type == "lambda_expression":
                ci = {"name": "<lambda>", "display": "<lambda>", "kind": "lambda"}
                dk = (ci["kind"], ci["display"])
                if dk not in seen:
                    seen.add(dk)
                    calls.append(ci)
                continue
            ci = self._extract_callee_info(cn, source_bytes)
            if ci is None or ci["name"].lower() in _CPP_KEYWORDS_TO_IGNORE:
                continue
            dk = (ci["kind"], ci["display"])
            if dk not in seen:
                seen.add(dk)
                calls.append(ci)
        return calls

    def _extract_callee_info(self, callee_node: Any, source_bytes: bytes) -> dict[str, str] | None:
        while callee_node.type in {"pointer_expression", "parenthesized_expression"}:
            inner = callee_node.child_by_field_name("argument")
            if not inner and callee_node.children:
                inner = callee_node.children[1] if callee_node.type == "parenthesized_expression" and len(callee_node.children) >= 2 else callee_node.children[-1]
            if inner:
                callee_node = inner
            else:
                break
        
        if callee_node.type == "pointer_expression":
            pointer_text = self._node_text(callee_node, source_bytes).strip()
            pointer_name = re.sub(r"^\(\*|\)$", "", pointer_text).strip("*() ")
            if pointer_name:
                return {"name": pointer_name, "display": pointer_name, "kind": "function_pointer"}

        if callee_node.type == "lambda_expression":
            return {"name": "<lambda>", "display": "<lambda>", "kind": "lambda"}

        if callee_node.type in {"parenthesized_expression", "subscript_expression"}:
            expr_text = self._node_text(callee_node, source_bytes).strip()
            if expr_text:
                name_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)", expr_text)
                if name_match:
                    inferred_name = name_match.group(1)
                    kind = "functor" if "[" in expr_text else "function_pointer"
                    return {"name": inferred_name, "display": expr_text, "kind": kind}

        if callee_node.type == "field_expression":
            obj_node = callee_node.child_by_field_name("argument")
            field_node = callee_node.child_by_field_name("field")
            if field_node is not None:
                name = self._node_text(field_node, source_bytes).strip()
                owner = self._node_text(obj_node, source_bytes).strip() if obj_node is not None else ""
                display = f"{owner}.{name}" if owner else name
                if name == "operator()":
                    return {"name": owner or "operator()", "display": display, "kind": "functor"}
                return {"name": name, "display": display, "kind": "method"}

        if callee_node.type in {"identifier", "field_identifier", "operator_name"}:
            name = self._node_text(callee_node, source_bytes).strip()
            return {"name": name, "display": name, "kind": "local"}

        if callee_node.type in {"qualified_identifier", "scoped_identifier"}:
            scoped_text = self._node_text(callee_node, source_bytes).strip()
            simple_name = scoped_text.split("::")[-1].strip() if "::" in scoped_text else scoped_text
            return {"name": simple_name, "display": scoped_text, "kind": "scoped"}

        for subnode in self._iter_nodes(callee_node):
            if subnode.type in {"field_identifier", "identifier", "operator_name"}:
                text = self._node_text(subnode, source_bytes).strip()
                if text:
                    if text == "operator()":
                        parent_text = self._node_text(callee_node, source_bytes).strip()
                        owner_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\.\s*operator\s*\(\)", parent_text)
                        owner_name = owner_match.group(1) if owner_match else "operator()"
                        return {"name": owner_name, "display": parent_text or owner_name, "kind": "functor"}
                    return {"name": text, "display": text, "kind": "local"}
        return None

    def _extract_type_name(self, node: Any, source_bytes: bytes) -> str:
        nn = node.child_by_field_name("name")
        if nn is not None:
            return self._node_text(nn, source_bytes).strip()
        if node.type == "type_definition":
            cs = [c for c in node.children if c.type in {"type_identifier", "identifier"}]
            if cs:
                return self._node_text(cs[-1], source_bytes).strip()
        if node.type in {"alias_declaration", "using_declaration"}:
            for c in node.children:
                if c.type in {"type_identifier", "identifier"}:
                    return self._node_text(c, source_bytes).strip()
        if node.type in {"class_specifier", "struct_specifier", "enum_specifier"}:
            for c in node.children:
                if c.type in {"type_identifier", "identifier"}:
                    return self._node_text(c, source_bytes).strip()
        return ""

    @staticmethod
    def _extract_modifiers(sig: str) -> list[str]:
        toks = set(re.findall(r"\b\w+\b", sig))
        return [m for m in _MODIFIER_TOKENS if m in toks]

    @staticmethod
    def _node_text(node: Any, source_bytes: bytes) -> str:
        if node is None:
            return ""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")

    def _iter_nodes(self, root: Any) -> Iterable[Any]:
        stack, cnt = [root], 0
        while stack:
            curr = stack.pop()
            yield curr
            cnt += 1
            if cnt > MAX_AST_NODES:
                break
            for child in reversed(curr.children):
                stack.append(child)

    def _collect_global_variables(self, root_node: Any, source_bytes: bytes, line_starts: list[int]) -> list[dict[str, Any]]:
        variables = []
        for child in root_node.children:
            if child.type != "declaration":
                continue
            dt = self._node_text(child, source_bytes).strip()
            if not dt or "(" in dt or ")" in dt:
                continue
            names = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b(?=\s*(?:=|;|,))", dt)
            if not names:
                continue
            line = self._byte_to_line_number(child.start_byte, line_starts)
            for n in names:
                variables.append({"name": n, "line": line, "declaration": dt})
        return variables

    def export_ast_graph(self, source_text: str, output_path: str, max_nodes: int = 1000) -> str:
        try:
            import importlib
            gv = importlib.import_module("graphviz")
            Digraph = getattr(gv, "Digraph")
        except ImportError as e:
            raise RuntimeError("graphviz not installed") from e
        sb = source_text.encode("utf-8")
        tree = self._parser.parse(sb)
        dot = Digraph("cpp_ast")
        queue, seen = [tree.root_node], 0
        while queue and seen < max_nodes:
            node = queue.pop(0)
            nid = f"n{node.start_byte}_{node.end_byte}_{seen}"
            dot.node(nid, label=node.type)
            for child in node.children:
                cid = f"n{child.start_byte}_{child.end_byte}_{seen}_{child.type}"
                dot.node(cid, label=child.type)
                dot.edge(nid, cid)
                queue.append(child)
            seen += 1
        dot.save(output_path)
        return output_path


def extract_functions_from_cpp_file(file_path: str) -> list[dict[str, Any]]:
    project_map = CppParser().parse_file(file_path)
    functions = project_map.get("functions", {})
    if isinstance(functions, dict):
        return list(functions.values())
    return functions if isinstance(functions, list) else []


_CPP20_IMPORT_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:export\s+)?import\s+"
    r"(?:"
    r"(<[^>]+>)"
    r"|"
    r'("(?:[^"\\]|\\.)*")'
    r"|"
    r"([\w.]+)"
    r")\s*;",
    re.MULTILINE,
)
_CPP20_MODULE_DECL_RE: re.Pattern[str] = re.compile(
    r"^\s*(?:export\s+)?module\s+([\w.]+)\s*;",
    re.MULTILINE,
)


def detect_module_imports(source_text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for match in _CPP20_IMPORT_RE.finditer(source_text):
        angle, quoted, named = match.group(1), match.group(2), match.group(3)
        target = (angle or quoted or named or "").strip()
        line = source_text.count("\n", 0, match.start()) + 1
        results.append({"kind": "import", "target": target, "line": line, "raw": match.group(0).strip()})
    for match in _CPP20_MODULE_DECL_RE.finditer(source_text):
        line = source_text.count("\n", 0, match.start()) + 1
        results.append({"kind": "module_decl", "target": match.group(1).strip(), "line": line, "raw": match.group(0).strip()})
    results.sort(key=lambda item: item["line"])
    return results


_LEGACY_PATTERN_SPECS = [
    ("char_pointer_array", "critical", re.compile(r"\bchar\s*\*\s*[A-Za-z_][A-Za-z0-9_]*\s*(\[[^\]]*\])"), "char* array usage detected; prefer std::string/std::array/std::span."),
    ("null_macro", "major", re.compile(r"\bNULL\b"), "NULL macro detected; replace with nullptr."),
    ("manual_delete", "critical", re.compile(r"\bdelete\s*(\[\])?\s*[A-Za-z_][A-Za-z0-9_]*\s*;"), "Manual delete detected; prefer std::unique_ptr or stack allocation."),
    ("printf", "major", re.compile(r"\bprintf\s*\("), "printf detected; prefer modern c++ I/O or std::print."),
    ("malloc", "critical", re.compile(r"\bmalloc\s*\("), "malloc detected; prefer std::vector or smart pointers."),
    ("free", "critical", re.compile(r"\bfree\s*\("), "free detected; prefer RAII structures over manual memory execution."),
    ("new", "major", re.compile(r"\bnew\s+"), "Raw new keyword detected; prefer std::make_unique or std::make_shared."),
    ("char_pointer", "major", re.compile(r"\bchar\s*\*\s*[A-Za-z_]\w*\b"), "Raw char* string definition detected; prefer std::string."),
]


def detect_legacy_patterns(source_text: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for pattern_id, severity, pattern_re, message in _LEGACY_PATTERN_SPECS:
        for match in pattern_re.finditer(source_text):
            start = match.start()
            line = source_text.count("\n", 0, start) + 1
            findings.append(
                {
                    "pattern": pattern_id,
                    "severity": severity,
                    "line": line,
                    "match": match.group(0),
                    "message": message,
                    "tag": "C++23 Overhaul",
                }
            )

    try:
        parser = CppParser()
        source_bytes = source_text.encode("utf-8")
        tree = parser._parser.parse(source_bytes)
        line_starts = parser._compute_line_start_bytes(source_text)
        cast_node_types = {"cast_expression", "c_style_cast_expression"}

        for node in parser._iter_nodes(tree.root_node):
            if node.type not in cast_node_types:
                continue
            snippet = parser._node_text(node, source_bytes).strip()
            if not snippet:
                continue
            findings.append(
                {
                    "pattern": "c_style_cast",
                    "severity": "major",
                    "line": parser._byte_to_line_number(node.start_byte, line_starts),
                    "match": snippet,
                    "message": "Potential C-style cast detected; prefer static_cast/reinterpret_cast.",
                    "tag": "C++23 Overhaul",
                }
            )
    except Exception as exc:
        logger.debug("AST cast detection failed: %s", exc, exc_info=True)

    findings.sort(key=lambda item: (int(item.get("line", 0)), str(item.get("pattern", ""))))
    return findings


def detect_legacy_patterns_from_cpp_file(file_path: str) -> list[dict[str, Any]]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"C++ file not found: {path}")
    return detect_legacy_patterns(path.read_text("utf-8"))