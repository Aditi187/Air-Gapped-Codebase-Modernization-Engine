from __future__ import annotations

from collections import deque
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx


logger = logging.getLogger(__name__)

def _compute_signature_hash(parameters: List[Dict[str, Any]], return_type: str = "", function_name: str = "") -> str:
    type_str = f"{return_type}|{function_name}|" + ",".join(str(p.get("type") or "") for p in parameters)
    return hashlib.sha256(type_str.encode("utf-8")).hexdigest()[:16]


def _make_node_id(unique_fqn: str, function_name: str, signature_hash: str) -> str:
    return unique_fqn or f"{function_name}#{signature_hash}"


def _node_display_name(graph: nx.DiGraph, node_id: str) -> str:
    attrs = graph.nodes[node_id]
    simple = str(attrs.get("name") or node_id)
    sig_hash = str(attrs.get("signature_hash") or "")
    return f"{simple}#{sig_hash}" if sig_hash else simple


def _build_class_hierarchy(
    types_info: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    hierarchy: Dict[str, List[str]] = {}
    for t in types_info:
        name = str(t.get("name") or "")
        if name:
            if t.get("type") in {"class", "struct"}:
                hierarchy[name] = [str(b) for b in (t.get("bases") or [])]
            elif t.get("type") in {"typedef", "using"}:
                alias_target = str(t.get("target") or "")
                if alias_target:
                    hierarchy[name] = [alias_target]
    return hierarchy


_get_ancestors_cache: Dict[str, List[str]] = {}

def _get_ancestors(
    class_name: str,
    hierarchy: Dict[str, List[str]],
) -> List[str]:
    if class_name in _get_ancestors_cache:
        return _get_ancestors_cache[class_name]
    result: List[str] = []
    visited: Set[str] = set()
    queue: deque[str] = deque(hierarchy.get(class_name, []))
    while queue:
        base = queue.popleft()
        if base in visited:
            continue
        visited.add(base)
        result.append(base)
        queue.extend(str(item) for item in hierarchy.get(base, []))
    _get_ancestors_cache[class_name] = result
    return result


def _call_argument_count(call_detail: Dict[str, Any]) -> Optional[int]:
    args = call_detail.get("arguments")
    if isinstance(args, list):
        return len(args)
    for key in ("argument_count", "arg_count"):
        count = call_detail.get(key)
        if isinstance(count, int) and count >= 0:
            return count
    return None


def _matches_argument_count(
    graph: nx.DiGraph,
    node_id: str,
    argument_count: Optional[int],
) -> bool:
    if argument_count is None:
        return True
    count = graph.nodes[node_id].get("parameter_count")
    return isinstance(count, int) and count == argument_count


def _filter_nodes_by_arity(
    graph: nx.DiGraph,
    node_ids: List[str],
    argument_count: Optional[int],
) -> List[str]:
    return list(node_ids) if argument_count is None else [node_id for node_id in node_ids if _matches_argument_count(graph, node_id, argument_count)]


def _resolve_virtual_call_targets(
    method_name: str,
    caller_class: str,
    class_hierarchy: Dict[str, List[str]],
    graph: nx.DiGraph,
    method_to_node_ids: Dict[str, List[str]],
    free_function_node_ids: Dict[str, List[str]],
    argument_count: Optional[int],
) -> List[str]:
    if not caller_class:
        return _filter_nodes_by_arity(
            graph,
            free_function_node_ids.get(method_name, []),
            argument_count,
        )

    candidates = method_to_node_ids.get(method_name, [])
    if not candidates:
        return []

    exact_prefix = f"{caller_class}::{method_name}"
    exact_matches = [
        node_id
        for node_id in candidates
        if str(graph.nodes[node_id].get("fqn") or "").startswith(exact_prefix)
        and _matches_argument_count(graph, node_id, argument_count)
    ]
    if exact_matches:
        return _ordered_unique(exact_matches)

    inherited_matches = [
        node_id
        for ancestor in _get_ancestors(caller_class, class_hierarchy)
        for node_id in candidates
        if str(graph.nodes[node_id].get("fqn") or "").startswith(f"{ancestor}::{method_name}")
        and _matches_argument_count(graph, node_id, argument_count)
    ]
    return _ordered_unique(inherited_matches)


def _ordered_unique(values: List[str]) -> List[str]:
    return list(dict.fromkeys(values))


def _scc_modernization_order(graph: nx.DiGraph, internal_nodes: Set[str]) -> List[str]:
    if not internal_nodes:
        return []
    subgraph: nx.DiGraph = graph.subgraph(internal_nodes).copy()  # type: ignore[assignment]
    if subgraph.number_of_nodes() == 0:
        return []
    condensed = nx.condensation(subgraph)
    topo_components = list(nx.topological_sort(condensed.reverse()))
    return [
        str(node_id)
        for component in topo_components
        for node_id in sorted(condensed.nodes.get(component, {}).get("members", set()) or set())
    ]


def _is_malformed_function_record(entry: Any) -> bool:
    return not isinstance(entry, dict) or not str(entry.get("name") or "")


def build_dependency_graph(
    functions_info: List[Dict[str, Any]],
    types_info: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[nx.DiGraph, Dict[str, List[str]], Dict[str, bool], List[str]]:
    if not isinstance(functions_info, list):
        raise TypeError("functions_info must be a list of dictionaries")
    graph: nx.DiGraph = nx.DiGraph()
    is_defined_in_file: Dict[str, bool] = {}
    defined_function_names: List[str] = []

    class_hierarchy = _build_class_hierarchy(types_info or [])

    method_to_node_ids: Dict[str, List[str]] = {}
    free_function_node_ids_by_name: Dict[str, List[str]] = {}
    name_to_defined_node_ids: Dict[str, List[str]] = {}
    fqn_to_defined_node_ids: Dict[str, List[str]] = {}

    valid_functions: List[Dict[str, Any]] = []
    for idx, fn in enumerate(functions_info):
        if _is_malformed_function_record(fn):
            logger.debug("Skipping malformed function record at index %d", idx)
            continue
        valid_functions.append(fn)

    for fn in valid_functions:
        name = str(fn.get("name") or "")

        raw_parameters = fn.get("parameters")
        parameters = raw_parameters if isinstance(raw_parameters, list) else []
        parameter_count = len(parameters)
        sig_hash = str(fn.get("signature_hash") or "")
        if not sig_hash:
            sig_hash = _compute_signature_hash(parameters, str(fn.get("return_type") or ""), name)
        fqn = str(fn.get("fqn") or name)
        unique_fqn = str(fn.get("unique_fqn") or f"{fqn}#{sig_hash}")
        node_id = _make_node_id(unique_fqn, name, sig_hash)
        is_virtual = "virtual" in (fn.get("modifiers") or [])

        graph.add_node(
            node_id,
            node_id=node_id,
            display_name=name,
            name=name,
            fqn=fqn,
            unique_fqn=unique_fqn,
            signature_hash=sig_hash,
            parameter_count=parameter_count,
            is_virtual=is_virtual,
            is_defined_in_file=True,
            is_function_like=True,
        )

        name_to_defined_node_ids.setdefault(name, []).append(node_id)
        fqn_to_defined_node_ids.setdefault(fqn, []).append(node_id)
        is_defined_in_file[name] = True
        defined_function_names.append(name)

        if "::" in fqn:
            method_to_node_ids.setdefault(name, []).append(node_id)
        else:
            free_function_node_ids_by_name.setdefault(name, []).append(node_id)

    defined_function_names = _ordered_unique(defined_function_names)

    def _ensure_external_node(raw_name: str, *, is_function_like: bool) -> str:
        external_name = str(raw_name or "")
        if not (external_name and is_function_like):
            return ""
        if not graph.has_node(external_name):
            graph.add_node(
                external_name,
                node_id=external_name,
                display_name=external_name,
                name=external_name,
                fqn=external_name,
                unique_fqn=external_name,
                signature_hash="",
                is_virtual=False,
                is_defined_in_file=False,
                is_function_like=True,
            )
        else:
            attrs = graph.nodes[external_name]
            if is_function_like:
                attrs["is_function_like"] = True
        if external_name not in is_defined_in_file:
            is_defined_in_file[external_name] = False
        return external_name

    def _add_edges(source: str, targets: List[str]) -> None:
        for target in targets:
            graph.add_edge(source, target)

    for fn in valid_functions:
        caller_name = str(fn.get("name") or "")
        if not caller_name:
            continue

        caller_parameters = fn.get("parameters") or []
        caller_sig_hash = _compute_signature_hash(caller_parameters, str(fn.get("return_type") or ""), caller_name)
        caller_fqn = str(fn.get("fqn") or caller_name)
        caller_unique_fqn = str(fn.get("unique_fqn") or f"{caller_fqn}#{caller_sig_hash}")
        caller_node_id = _make_node_id(caller_unique_fqn, caller_name, caller_sig_hash)
        if not graph.has_node(caller_node_id):
            continue

        fqn_parts = caller_fqn.split("::")
        caller_class = fqn_parts[-2] if len(fqn_parts) >= 2 else ""

        call_details = fn.get("call_details") or []
        if call_details:
            for detail in call_details:
                if not isinstance(detail, dict):
                    continue
                kind = str(detail.get("kind") or "")
                call_name = str(detail.get("name") or "")
                call_display = str(detail.get("display") or call_name)
                argument_count = _call_argument_count(detail)
                if not call_name:
                    continue
                is_function_like_call = kind in {
                    "method",
                    "local",
                    "scoped",
                    "function_pointer",
                    "functor",
                    "lambda",
                } or not kind

                if kind == "method" and "::" not in call_name and "::" not in call_display:
                    resolved_node_ids = _resolve_virtual_call_targets(
                        call_name,
                        caller_class,
                        class_hierarchy,
                        graph,
                        method_to_node_ids,
                        free_function_node_ids_by_name,
                        argument_count,
                    )
                    if resolved_node_ids:
                        _add_edges(caller_node_id, resolved_node_ids)
                    else:
                        target_external = _ensure_external_node(
                            call_display,
                            is_function_like=is_function_like_call,
                        )
                        if target_external:
                            graph.add_edge(caller_node_id, target_external)
                else:
                    if "::" in call_display:
                        target_node_ids = _filter_nodes_by_arity(
                            graph,
                            fqn_to_defined_node_ids.get(call_display, []),
                            argument_count,
                        )
                        if target_node_ids:
                            _add_edges(caller_node_id, target_node_ids)
                        else:
                            target_external = _ensure_external_node(
                                call_display,
                                is_function_like=is_function_like_call,
                            )
                            if target_external:
                                graph.add_edge(caller_node_id, target_external)
                        continue

                    overload_targets = _filter_nodes_by_arity(
                        graph,
                        name_to_defined_node_ids.get(call_name, []),
                        argument_count,
                    )
                    if overload_targets:
                        _add_edges(caller_node_id, overload_targets)
                        continue

                    target_external = _ensure_external_node(
                        call_name,
                        is_function_like=is_function_like_call,
                    )
                    if target_external:
                        graph.add_edge(caller_node_id, target_external)
        else:
            raw_calls = fn.get("calls") or []
            for callee in raw_calls:
                callee_name = str(callee or "")
                if not callee_name:
                    continue

                overload_targets = name_to_defined_node_ids.get(callee_name, [])
                if overload_targets:
                    _add_edges(caller_node_id, overload_targets)
                else:
                    target_external = _ensure_external_node(callee_name, is_function_like=True)
                    if target_external:
                        graph.add_edge(caller_node_id, target_external)

    dependency_map: Dict[str, List[str]] = {}
    for fn_name in defined_function_names:
        neighbors: Set[str] = {
            str(graph.nodes[successor].get("name") or successor)
            for caller_node_id in name_to_defined_node_ids.get(fn_name, [])
            for successor in graph.successors(caller_node_id)
            if str(graph.nodes[successor].get("name") or successor)
        }
        dependency_map[fn_name] = sorted(neighbors)

    return graph, dependency_map, is_defined_in_file, defined_function_names


def analyze_dependency_graph(
    graph: nx.DiGraph,
    defined_function_names: List[str],
    is_defined_in_file: Dict[str, bool],
) -> Dict[str, Any]:
    orphans: List[str] = []
    entry_points: List[str] = []

    name_to_nodes: Dict[str, List[str]] = {}
    for node_id in graph.nodes:
        attrs = graph.nodes[node_id]
        if bool(attrs.get("is_defined_in_file", False)):
            name = str(attrs.get("name") or "")
            if name:
                name_to_nodes.setdefault(name, []).append(str(node_id))

    for fn_name in defined_function_names:
        node_ids = name_to_nodes.get(fn_name, [])
        if not any(graph.in_degree(node_id) > 0 for node_id in node_ids):
            (entry_points if fn_name == "main" else orphans).append(fn_name)

    cycles: List[List[str]] = []
    for cycle in nx.simple_cycles(graph):
        if not cycle:
            continue
        if not any(bool(graph.nodes[node_id].get("is_defined_in_file", False)) for node_id in cycle):
            continue
        cycles.append([_node_display_name(graph, str(node_id)) for node_id in cycle])

    return {
        "orphans": sorted(orphans),
        "cycles": cycles,
        "entry_points": sorted(entry_points),
    }


def build_analysis_report(
    functions_info: List[Dict[str, Any]],
    dependency_map: Dict[str, List[str]],
    orphans: List[str],
    cycles: List[List[str]],
) -> str:
    total_functions = len(functions_info)
    lines: List[str] = [
        f"Total functions: {total_functions}",
        f"Orphan functions (no callers): {', '.join(sorted(orphans)) or 'none'}",
    ]

    if cycles:
        lines.append("Circular recursion / cycles:")
        lines.extend(f"  - {' -> '.join(cycle)}" for cycle in cycles)
    else:
        lines.append("Circular recursion / cycles: none")

    lines.append("Per-function call summary:")
    for fn_name in sorted(dependency_map.keys()):
        callees = dependency_map.get(fn_name, [])
        lines.append(f"  - {fn_name} calls [{', '.join(callees) or 'none'}]")

    return "\n".join(lines)


class DependencyGraph:
    def __init__(
        self,
        functions_info: List[Dict[str, Any]],
        types_info: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        (
            graph,
            dependency_map,
            is_defined_in_file,
            defined_function_names,
        ) = build_dependency_graph(functions_info, types_info=types_info)
        self.graph: nx.DiGraph = graph
        self._dependency_map: Dict[str, List[str]] = dependency_map
        self.is_defined_in_file: Dict[str, bool] = is_defined_in_file
        self.defined_function_names: List[str] = defined_function_names
        self._criticality_scores: Dict[str, float] = self._compute_criticality_scores()

    @property
    def dependency_map(self) -> Dict[str, List[str]]:
        return self._dependency_map

    def _compute_criticality_scores(self) -> Dict[str, float]:
        internal_node_ids = {
            str(node_id)
            for node_id in self.graph.nodes
            if bool(self.graph.nodes[node_id].get("is_defined_in_file", False))
        }
        total_internal = len(internal_node_ids)
        scores: Dict[str, float] = {str(node): 0.0 for node in self.graph.nodes}
        if total_internal == 0:
            return scores

        for node_id in internal_node_ids:
            scores[node_id] = len({str(n) for n in nx.descendants(self.graph, node_id)} & internal_node_ids) / float(total_internal)

        return scores

    def analyze(self) -> Dict[str, Any]:
        return analyze_dependency_graph(
            self.graph, self.defined_function_names, self.is_defined_in_file
        )

    # get_impact_radius and get_bottlenecks removed due to unneeded complexity and dead code traits

    def get_modernization_order(self) -> List[str]:
        internal_node_ids = {
            str(node_id)
            for node_id in self.graph.nodes
            if bool(self.graph.nodes[node_id].get("is_defined_in_file", False))
        }
        if not internal_node_ids:
            return []

        ordered_node_ids = _scc_modernization_order(self.graph, internal_node_ids)
        if not ordered_node_ids:
            return sorted(_ordered_unique([str(node_id) for node_id in internal_node_ids]))

        return _ordered_unique([str(node_id) for node_id in ordered_node_ids])

    def get_dependency_levels(self) -> List[List[str]]:
        internal_node_ids = {
            str(node_id)
            for node_id in self.graph.nodes
            if bool(self.graph.nodes[node_id].get("is_defined_in_file", False))
        }
        if not internal_node_ids:
            return []

        internal_subgraph: nx.DiGraph = self.graph.subgraph(internal_node_ids).copy()  # type: ignore[assignment]
        if internal_subgraph.number_of_nodes() == 0:
            return []

        condensed = nx.condensation(internal_subgraph)
        schedule_graph = condensed.reverse()

        component_level: Dict[int, int] = {}
        for component in nx.topological_sort(schedule_graph):
            predecessors = list(schedule_graph.predecessors(component))
            component_level[int(component)] = 0 if not predecessors else max(component_level[int(pred)] for pred in predecessors) + 1

        levels_by_index: Dict[int, List[str]] = {}
        for component, level_idx in component_level.items():
            members = condensed.nodes[component].get("members") or set()
            member_names = sorted(
                {
                    str(internal_subgraph.nodes[str(node_id)].get("name") or node_id)
                    for node_id in members
                }
            )
            levels_by_index.setdefault(level_idx, []).extend(member_names)

        levels: List[List[str]] = []
        for level_idx in sorted(levels_by_index):
            level_names = sorted(_ordered_unique(levels_by_index[level_idx]))
            if level_names:
                levels.append(level_names)
        return levels

    def to_dict(self) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        for node in self.graph.nodes:
            node_id = str(node)
            attrs = self.graph.nodes[node_id]
            nodes.append(
                {
                    "node_id": str(attrs.get("node_id") or node_id),
                    "name": str(attrs.get("name") or node_id),
                    "display_name": str(attrs.get("display_name") or attrs.get("name") or node_id),
                    "fqn": str(attrs.get("fqn") or attrs.get("name") or node_id),
                    "signature_hash": str(attrs.get("signature_hash") or ""),
                    "is_virtual": bool(attrs.get("is_virtual", False)),
                    "is_defined_in_file": bool(attrs.get("is_defined_in_file", False)),
                    "criticality_score": float(
                        self._criticality_scores.get(node_id, 0.0)
                    ),
                }
            )

        edges = [{"from": str(u), "to": str(v)} for u, v in self.graph.edges]
        return {"nodes": nodes, "edges": edges}


# get_modernization_order standalone removed to consolidate with DependencyGraph native method


if __name__ == "__main__":
    demo_functions = [
        {
            "name": "foo",
            "fqn": "A::foo",
            "unique_fqn": "A::foo#1111111111111111",
            "signature_hash": "1111111111111111",
            "parameters": [{"type": "int"}],
            "call_details": [{"kind": "method", "name": "bar", "arguments": [{"expr": "x"}]}],
        },
        {
            "name": "bar",
            "fqn": "A::bar",
            "unique_fqn": "A::bar#2222222222222222",
            "signature_hash": "2222222222222222",
            "parameters": [{"type": "int"}],
            "call_details": [],
        },
    ]
    dep = DependencyGraph(demo_functions, types_info=[])
    print(json.dumps(dep.to_dict(), indent=2))
    print("Modernization order:", dep.get_modernization_order())