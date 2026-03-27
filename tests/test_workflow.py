import pytest
from agents.workflow.state import create_initial_state
from agents.workflow.orchestrator import build_modernization_graph

def test_workflow_initialization():
    """
    Test that the modernization workflow can be initialized and compile the graph.
    """
    code = "int main() { return 0; }"
    source_file = "test.cpp"
    state = create_initial_state(code=code, source_file=source_file)
    
    assert state["code"] == code
    assert state["original_file_path"] == source_file
    assert state["attempt_count"] == 0

def test_graph_build():
    """
    Test that the LangGraph workflow builds/compiles without error.
    """
    app = build_modernization_graph()
    assert app is not None
    # We won't invoke the full app here to avoid LLM calls in unit tests
