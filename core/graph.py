from __future__ import annotations

from typing import Any, Dict, List, Tuple

import networkx as nx


def build_dependency_graph(
    functions_info: List[Dict[str, Any]],
) -> Tuple[nx.DiGraph, Dict[str, List[str]], Dict[str, bool], List[str]]:
    graph: nx.DiGraph = nx.DiGraph()
    is_defined_in_file: Dict[str, bool] = {}
    defined_function_names: List[str] = []

    for fn in functions_info:
        name = str(fn.get("name") or "")
        if not name:
            continue
        if name not in graph:
            graph.add_node(name)
        is_defined_in_file[name] = True
        defined_function_names.append(name)

    for fn in functions_info:
        caller = str(fn.get("name") or "")
        if not caller:
            continue
        raw_calls = fn.get("calls") or []
        for callee in raw_calls:
            callee_name = str(callee or "")
            if not callee_name:
                continue
            if callee_name not in graph:
                graph.add_node(callee_name)
            if callee_name not in is_defined_in_file:
                is_defined_in_file[callee_name] = False
            graph.add_edge(caller, callee_name)

    dependency_map: Dict[str, List[str]] = {}
    for fn_name in defined_function_names:
        neighbors = sorted({str(n) for n in graph.successors(fn_name)})
        dependency_map[fn_name] = neighbors

    return graph, dependency_map, is_defined_in_file, defined_function_names


def analyze_dependency_graph(
    graph: nx.DiGraph,
    defined_function_names: List[str],
    is_defined_in_file: Dict[str, bool],
) -> Dict[str, Any]:
    orphans: List[str] = []
    entry_points: List[str] = []

    for fn_name in defined_function_names:
        if graph.in_degree(fn_name) == 0:
            if fn_name == "main":
                entry_points.append(fn_name)
            else:
                orphans.append(fn_name)

    cycles: List[List[str]] = []
    for cycle in nx.simple_cycles(graph):
        as_strings = [str(name) for name in cycle]
        if all(name in defined_function_names for name in as_strings):
            cycles.append(as_strings)

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
    lines: List[str] = []

    lines.append(f"Total functions: {total_functions}")
    lines.append(
        f"Orphan functions (no callers): {', '.join(sorted(orphans)) or 'none'}"
    )

    if cycles:
        formatted_cycles = [" -> ".join(cycle) for cycle in cycles]
        lines.append("Circular recursion / cycles:")
        for cycle_str in formatted_cycles:
            lines.append(f"  - {cycle_str}")
    else:
        lines.append("Circular recursion / cycles: none")

    lines.append("Per-function call summary:")
    for fn_name in sorted(dependency_map.keys()):
        callees = dependency_map.get(fn_name, [])
        lines.append(f"  - {fn_name} calls [{', '.join(callees) or 'none'}]")

    return "\n".join(lines)


class DependencyGraph:
    def __init__(self, functions_info: List[Dict[str, Any]]) -> None:
        (
            graph,
            dependency_map,
            is_defined_in_file,
            defined_function_names,
        ) = build_dependency_graph(functions_info)
        self.graph: nx.DiGraph = graph
        self._dependency_map: Dict[str, List[str]] = dependency_map
        self.is_defined_in_file: Dict[str, bool] = is_defined_in_file
        self.defined_function_names: List[str] = defined_function_names
        self._criticality_scores: Dict[str, float] = self._compute_criticality_scores()

    @property
    def dependency_map(self) -> Dict[str, List[str]]:
        return self._dependency_map

    def _compute_criticality_scores(self) -> Dict[str, float]:
        internal = {
            name for name, internal in self.is_defined_in_file.items() if internal
        }
        total_internal = len(internal)
        scores: Dict[str, float] = {
            str(node): 0.0 for node in self.graph.nodes
        }
        if total_internal == 0:
            return scores

        for fn_name in internal:
            downstream = nx.descendants(self.graph, fn_name)
            downstream_internal = len(downstream & internal)
            scores[fn_name] = downstream_internal / float(total_internal)

        return scores

    def analyze(self) -> Dict[str, Any]:
        return analyze_dependency_graph(
            self.graph, self.defined_function_names, self.is_defined_in_file
        )

    def get_impact_radius(self, function_name: str) -> float:
        return float(self._criticality_scores.get(function_name, 0.0))

    def get_bottlenecks(self) -> List[str]:
        internal_nodes = [
            name
            for name, internal in self.is_defined_in_file.items()
            if internal
        ]
        if not internal_nodes:
            return []

        in_degrees = {name: self.graph.in_degree(name) for name in internal_nodes}
        max_degree = max(in_degrees.values(), default=0)
        if max_degree == 0:
            return []

        return sorted(
            [name for name, degree in in_degrees.items() if degree == max_degree]
        )

    def get_modernization_order(self) -> List[str]:
        internal_nodes = [
            name
            for name, internal in self.is_defined_in_file.items()
            if internal
        ]
        if not internal_nodes:
            return []
        try:
            topo = list(nx.topological_sort(self.graph.reverse()))
            ordered = [name for name in topo if name in internal_nodes]
            remaining = [name for name in internal_nodes if name not in ordered]
            ordered.extend(sorted(remaining))
            return ordered
        except Exception:
            return sorted(internal_nodes)

    def to_dict(self) -> Dict[str, Any]:
        nodes: List[Dict[str, Any]] = []
        for node in self.graph.nodes:
            name = str(node)
            nodes.append(
                {
                    "name": name,
                    "is_defined_in_file": bool(
                        self.is_defined_in_file.get(name, False)
                    ),
                    "criticality_score": float(
                        self._criticality_scores.get(name, 0.0)
                    ),
                }
            )

        edges = [
            {"from": str(u), "to": str(v)}
            for u, v in self.graph.edges
        ]
        return {"nodes": nodes, "edges": edges}


def get_modernization_order(dependency_map: Dict[str, List[str]]) -> List[str]:
    graph: nx.DiGraph = nx.DiGraph()

    for caller, callees in dependency_map.items():
        graph.add_node(caller)
        for callee in callees:
            callee_name = str(callee or "")
            if not callee_name:
                continue
            graph.add_node(callee_name)
            graph.add_edge(caller, callee_name)

    internal_nodes = set(dependency_map.keys())
    if not internal_nodes:
        return []

    try:
        topo = list(nx.topological_sort(graph.reverse()))
        ordered = [name for name in topo if name in internal_nodes]
        remaining = [name for name in sorted(internal_nodes) if name not in ordered]
        ordered.extend(remaining)
        return ordered
    except Exception:
        return sorted(internal_nodes)