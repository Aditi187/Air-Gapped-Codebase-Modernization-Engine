# Air-Gapped Codebase Modernization Engine

Modernizes legacy C/C++ code into idiomatic C++17 using a modular, intelligent LangGraph workflow powered by a Multi-Model LLM Bridge and deterministic rule fallbacks.

## Project Structure

```text
agents/
  workflow/         # Modular Workflow System
    nodes/          # Workflow steps (Analyzer, Modernizer, Verifier, Fixer)
    infra/          # Infrastructure (Model Provider multi-routing)
    orchestrator.py # State Graph Orchestration
core/               # Core engines (RuleModernizer for deterministic fallbacks)
main.py             # Main Entry Point
tests/              # Test suites
```

## Overview

The engine utilizes a state-graph architecture to transform legacy C/C++ into modern C++17. The pipeline follows a structured flow: **Analyze → Plan → Transform (Full-File) → Verify → Fix**.

### Multi-Model LLM Bridge
The engine is highly optimized for production via Nvidia's API gateway, routing specific agents to specialized models:
- **Analyzer:** `deepseek-v3` (for deep context extraction and planning)
- **Modernizer:** `llama-3.3-70b-instruct` (for raw codebase transformation)
- **Fixer:** `qwen3` (for fast iterative compiler error fixing)

If the LLMs are unavailable or return malformed code, the engine instantly falls back to the deterministic `RuleModernizer` for entirely safe, prompt-independent transformations.

## Features

- **Multi-Model Intelligence**: DeepSeek, Llama, and Qwen working in concert for optimal speed and accuracy via Nvidia API.
- **Whole-File Processing**: Replaces fragile AST-based snippet injection with full-file context awareness.
- **Rule-Based Fallbacks**: 100% deterministic regex transformations (`NULL` -> `nullptr`, `typedef` -> `using`) that function entirely offline in air-gapped modes.
- **RAII Enforcement**: Automatically transforms C-style manual memory (`malloc`/`free`, manual structs) into RAII (`std::vector`, `std::unique_ptr`, idiomatic classes).

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

Set up your API keys in the `.env` file for the multi-model bridge:

```env
# Multi-agent model routing
ANALYZER_MODEL=deepseek-ai/deepseek-v3.2
ANALYZER_API_KEY=nvapi-...

MODERNIZER_MODEL=meta/llama-3.3-70b-instruct
MODERNIZER_API_KEY=nvapi-...

FIXER_MODEL=meta/llama-70b-instruct
FIXER_API_KEY=nvapi-...
```

## Usage

Run the modernization engine directly on any C++ file:

```bash
python main.py <path_to_file.cpp>
```

The output will automatically be generated in the same directory as `<filename>_modernized.cpp`.

## License

MIT
