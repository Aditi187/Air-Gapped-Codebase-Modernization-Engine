from typing import TypedDict, Dict, List, Any, Optional, Tuple

# Forward reference for WorkflowContext to avoid circular import
WorkflowContext = Any  # in practice, it's from agents.workflow.context


class ModernizationState(TypedDict, total=True):
    """
    State used throughout the LangGraph workflow.
    All keys must be present at all times (total=True).
    Use `create_initial_state()` to obtain a fully populated state.
    """
    code: str
    language: str
    analysis: str
    dependency_map: Dict[str, List[str]]
    call_graph_data: Dict[str, Any]
    impact_map: Dict[str, List[str]]
    orphans: List[str]
    analysis_report: str
    modernized_code: str
    verification_result: dict
    error_log: str
    attempt_count: int
    is_parity_passed: bool
    is_functionally_equivalent: bool
    diff_output: str
    feedback_loop_count: int
    modernization_order: List[str]
    modernized_functions: Dict[str, str]
    current_function_index: int
    partial_success: bool
    last_working_code: str
    current_target_function: str
    source_file: str
    output_file_path: str
    legacy_findings: List[Dict[str, Any]]
    compliance_report: Dict[str, Any]
    functions_info: List[Dict[str, Any]]
    functions_index: Dict[str, Dict[str, Any]]
    current_function_name: str
    current_function_span: Tuple[int, int]
    project_map: Dict[str, Any]
    batched_target_functions: List[str]
    current_target_stable_key: str
    global_refactor_done: bool
    analyzer_plan: str
    modernization_plan: str
    original_function_signatures: Dict[str, str]
    original_structure_snapshot: Dict[str, Any]
    static_validation_errors: List[str]
    global_last_score: int
    global_stagnation_count: int

    # The workflow context (holds config, caches, tracer). Not serializable, but fine in memory.
    context: WorkflowContext  # actual type: agents.workflow.context.WorkflowContext


def create_initial_state(
    code: str,
    language: str = "c++17",
    source_file: str = "",
    output_file_path: str = "",
    context: WorkflowContext = None,
) -> ModernizationState:
    """
    Create a fully populated initial state with sensible defaults.

    This factory avoids repeating the same default values across the codebase.
    """
    if context is None:
        from agents.workflow.context import WorkflowContext
        context = WorkflowContext()

    return ModernizationState(
        code=code,
        language=language,
        analysis="",
        dependency_map={},
        call_graph_data={},
        impact_map={},
        orphans=[],
        analysis_report="",
        modernized_code="",
        verification_result={},
        error_log="",
        attempt_count=0,
        is_parity_passed=False,
        is_functionally_equivalent=False,
        diff_output="",
        feedback_loop_count=0,
        modernization_order=[],
        modernized_functions={},
        current_function_index=0,
        partial_success=False,
        last_working_code=code,
        current_target_function="",
        source_file=source_file,
        output_file_path=output_file_path,
        legacy_findings=[],
        compliance_report={},
        functions_info=[],
        functions_index={},
        current_function_name="",
        current_function_span=(0, 0),
        project_map={},
        batched_target_functions=[],
        current_target_stable_key="",
        global_refactor_done=False,
        analyzer_plan="",
        modernization_plan="",
        original_function_signatures={},
        original_structure_snapshot={},
        static_validation_errors=[],
        global_last_score=-1,
        global_stagnation_count=0,
        context=context,
    )