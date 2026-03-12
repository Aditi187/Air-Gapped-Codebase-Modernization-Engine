from __future__ import annotations

import os
import re
from typing import List, Dict, Any

from tree_sitter import Parser, Language


def _create_cpp_parser() -> Parser:
    try:
        import tree_sitter_cpp
    except ImportError as exc:
        raise RuntimeError(
            "C++ grammar package 'tree-sitter-cpp' is not installed. Please install it with 'pip install tree-sitter-cpp'."
        ) from exc

    cpp_language = Language(tree_sitter_cpp.language())
    parser = Parser()
    parser.language = cpp_language
    return parser


def _read_file_text(file_path: str) -> str:
    with open(file_path, "r", encoding="utf-8") as file_handle:
        return file_handle.read()


def _collect_function_definitions(root_node: Any) -> List[Any]:
    function_nodes: List[Any] = []
    stack: List[Any] = [root_node]

    while stack:
        node = stack.pop()

        if node.type == "function_definition":
            function_nodes.append(node)
        elif node.type == "template_declaration":
            for child in node.children:
                if child.type == "function_definition":
                    function_nodes.append(child)

        for child in node.children:
            stack.append(child)

    return function_nodes


def _find_enclosing_template(node: Any) -> Any | None:
    current = node.parent
    while current is not None:
        if current.type == "template_declaration":
            return current
        current = current.parent
    return None


def _span_owner_for_function(node: Any) -> Any:
    template_node = _find_enclosing_template(node)
    return template_node if template_node is not None else node


def _extract_function_signature(node: Any, source_bytes: bytes) -> str:
    body_node = node.child_by_field_name("body")

    span_owner = _span_owner_for_function(node)
    start_byte = span_owner.start_byte

    if body_node is not None:
        end_byte = body_node.start_byte
    else:
        end_byte = node.end_byte

    header_bytes = source_bytes[start_byte:end_byte]
    text = header_bytes.decode("utf-8", errors="replace").strip()
    if body_node is None and text.endswith(";"):
        text = text[:-1].rstrip()
    return text


def _extract_leading_comments(node: Any, source_text: str) -> str:
    lines = source_text.splitlines()
    start_row, _ = node.start_point

    comment_lines: List[str] = []
    current_row = start_row - 1

    def _looks_like_comment_or_blank(text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return True
        return (
            stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
            or stripped.endswith("*/")
        )

    while current_row >= 0:
        candidate = lines[current_row]
        if not _looks_like_comment_or_blank(candidate):
            break
        comment_lines.append(candidate)
        current_row -= 1

    comment_lines.reverse()
    return "\n".join(comment_lines).strip()


def _collect_enclosing_scopes(node: Any, source_bytes: bytes) -> List[str]:
    scopes: List[str] = []
    current = node.parent

    while current is not None:
        name_node = None

        if current.type == "namespace_definition":
            name_node = current.child_by_field_name("name")
        elif current.type in {"class_specifier", "struct_specifier"}:
            name_node = current.child_by_field_name("name")
            if name_node is None:
                for child in current.children:
                    if child.type == "type_identifier":
                        name_node = child
                        break

        if name_node is not None:
            start_byte = name_node.start_byte
            end_byte = name_node.end_byte
            scope_name = source_bytes[start_byte:end_byte].decode(
                "utf-8", errors="replace"
            )
            scopes.append(scope_name)

        current = current.parent

    scopes.reverse()
    return scopes


def _extract_identifier_from_function(node: Any, source_bytes: bytes) -> str:
    declarator = node.child_by_field_name("declarator")

    search_root = declarator if declarator is not None else node

    stack: List[Any] = [search_root]
    base_name: str | None = None

    # We want a pre-order traversal that examines the leftmost nodes first.
    # Because we're using a LIFO stack, we must push children in *reverse*
    # order; otherwise the rightmost child (often a parameter list) is
    # explored before the function name identifier and we accidentally grab
    # a parameter name ("b" in the smoke test).
    while stack and base_name is None:
        current = stack.pop()

        if current.type == "identifier":
            start_byte = current.start_byte
            end_byte = current.end_byte
            base_name = source_bytes[start_byte:end_byte].decode(
                "utf-8", errors="replace"
            )
            break

        # push children reversed so the leftmost child is visited next
        for child in reversed(current.children):
            stack.append(child)

    if base_name is None:
        base_name = "<anonymous_function>"

    scopes = _collect_enclosing_scopes(node, source_bytes)
    if scopes:
        return "::".join(scopes + [base_name])
    return base_name


def _extract_function_body_source(node: Any, source_bytes: bytes) -> str:
    body_node = node.child_by_field_name("body")

    if body_node is None:
        return ""

    start_byte = body_node.start_byte
    end_byte = body_node.end_byte

    body_bytes = source_bytes[start_byte:end_byte]
    return body_bytes.decode("utf-8", errors="replace")


def _extract_call_target_name(call_node: Any, source_bytes: bytes) -> str:
    function_target = call_node.child_by_field_name("function")
    search_root = function_target if function_target is not None else call_node

    stack: List[Any] = [search_root]

    while stack:
        current = stack.pop()

        if current.type in {"scoped_identifier", "qualified_identifier"}:
            start_byte = current.start_byte
            end_byte = current.end_byte
            full_name = source_bytes[start_byte:end_byte].decode(
                "utf-8", errors="replace"
            )
            return full_name.strip()

        if current.type == "identifier":
            start_byte = current.start_byte
            end_byte = current.end_byte
            identifier_text = source_bytes[start_byte:end_byte].decode(
                "utf-8", errors="replace"
            )
            return identifier_text

        for child in current.children:
            stack.append(child)

    return "<anonymous_call>"


def _collect_function_calls(func_node: Any, source_bytes: bytes) -> List[str]:
    body_node = func_node.child_by_field_name("body")
    if body_node is None:
        return []

    calls: List[str] = []
    stack: List[Any] = [body_node]

    while stack:
        node = stack.pop()

        if node.type == "call_expression":
            callee_name = _extract_call_target_name(node, source_bytes)
            if callee_name and callee_name != "<anonymous_call>" and callee_name not in calls:
                calls.append(callee_name)

        for child in node.children:
            stack.append(child)

    return calls


def _extract_function_flags(signature: str) -> tuple[bool, bool]:
    tokens = re.findall(r"\b\w+\b", signature)
    is_virtual = "virtual" in tokens
    is_static = "static" in tokens
    return is_virtual, is_static


def extract_functions_from_cpp_file(file_path: str) -> List[Dict[str, Any]]:
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"C++ file not found: {file_path}")

    parser = _create_cpp_parser()

    source_text = _read_file_text(file_path)
    source_bytes = source_text.encode("utf-8")

    tree = parser.parse(source_bytes)
    root_node = tree.root_node

    function_nodes = _collect_function_definitions(root_node)

    results: List[Dict[str, Any]] = []

    for func_node in function_nodes:
        span_owner = _span_owner_for_function(func_node)

        name = _extract_identifier_from_function(func_node, source_bytes)
        body = _extract_function_body_source(func_node, source_bytes)
        calls = _collect_function_calls(func_node, source_bytes)
        start_byte = span_owner.start_byte
        end_byte = func_node.end_byte
        signature = _extract_function_signature(func_node, source_bytes)
        comments = _extract_leading_comments(span_owner, source_text)
        start_row, _ = span_owner.start_point
        end_row, _ = func_node.end_point
        line_numbers = {"start": start_row + 1, "end": end_row + 1}
        is_virtual, is_static = _extract_function_flags(signature)

        results.append(
            {
                "name": name,
                "body": body,
                "calls": calls,
                "start_byte": start_byte,
                "end_byte": end_byte,
                "signature": signature,
                "comments": comments,
                "line_numbers": line_numbers,
                "is_virtual": is_virtual,
                "is_static": is_static,
            }
        )

    return results


class CppParser:
    def parse_file(self, file_path: str) -> List[Dict[str, Any]]:
        return extract_functions_from_cpp_file(file_path)