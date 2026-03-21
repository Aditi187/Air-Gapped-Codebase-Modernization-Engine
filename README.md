# Air-Gapped Codebase Modernization Engine

Modernizes legacy C++ code using a modular, node-based LangGraph workflow with LLM-backed intelligence and robust rule-based fallbacks.

## Project Structure

```text
agents/
  workflow/         # New Modular Workflow System
    nodes/          # Workflow steps (Analyzer, Modernizer, Verifier, Fixer, etc.)
    infra/          # Infrastructure (Tracing, Model Provider, Exceptions)
    validation/     # AST and Structural validation logic
    orchestrator.py # State Graph Orchestration
    cli.py          # Command Line Interface
core/               # Core engines (Parser, RuleModernizer, Similarity, RAG)
tools/              # Integration tools and MCP server
tests/              # Test suites
cache/              # Runtime cache (Tokens, OpenAI, RAG)
```

## Overview

The engine utilizes a state-graph architecture to transform legacy C++ into modern C++17. The pipeline follows a structured flow: **Analyze → Plan → Modernize (Parallel) → Verify → Fix (Surgical) → Test**.

## Features

- **Modular Node Architecture**: Scalable, maintainable workflow powered by LangGraph.
- **Parallel Function Modernization**: Uses `ThreadPoolExecutor` for high-throughput batch processing.
- **Hybrid Modernization**: Combines LLM intelligence with deterministic `RuleModernizer` fallbacks.
- **Hierarchical Tracing**: Full project lifecycle observability via Langfuse (spans, events, and cost tracking).
- **Advanced Validation**: AST-based structural checks and differential parity testing.
- **RAII Enforcement**: Strict prompts ensuring modern memory management (`std::unique_ptr`, `std::vector`, `std::string`).

## Installation

1. Create a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Copy [.env.example](.env.example) to `.env` and configure your API keys and model settings.

```bash
cp .env.example .env
```

Key Variables:
- `API_KEY`: Modernization LLM provider key (e.g., NVIDIA, OpenAI).
- `LANGFUSE_SECRET_KEY`: Tracing dashboard key.
- `WORKFLOW_BATCH_SIZE`: Number of functions to process in parallel.

## Usage

### Run Modernization CLI

```bash
python -m agents.workflow.cli <path_to_file.cpp> --mode aggressive
```

- `--mode safe`: (Default) No signature changes.
- `--mode aggressive`: Allows RAII-driven signature refactoring.
- `--output`: Specify custom output path.

### Run MCP Server (Integration)

```bash
python tools/mcp_server.py
```

## Git Hygiene

- `.env` and `.venv` are ignored.
- Build artifacts (`*.o`, `*.exe`) and logs are ignored.
- Always run tests before pushing: `pytest -q`.

## License

MIT
