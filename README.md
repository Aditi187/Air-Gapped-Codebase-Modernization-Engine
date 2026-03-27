# Air-Gapped Codebase Modernization Engine

Modernizes legacy C/C++ code into idiomatic C++17 using a modular, high-stability LangGraph workflow powered by a Multi-Model LLM bridge with deterministic rule fallbacks.

## Project Overview

The engine utilizes a state-graph architecture to transform legacy C++ into modern C++17. The pipeline follows a structured "Phase 4" flow: **Analyze → Plan → Modernize → Semantic Guard → Verify → Fix**.

### Multi-Model LLM Strategy
The engine is optimized for the NVIDIA API gateway, routing specialized agents to advanced models:
- **Analyzer/Planner:** `meta/llama-3.3-70b-instruct` or `deepseek-ai/deepseek-v3`
- **Modernizer/Fixer:** `meta/llama-3.3-70b-instruct`

High-stability logic is built-in: the engine performs **15 retry attempts** with a mandatory **60-second delay** between calls to ensure resilience against API rate limits (429 errors).

## Core C++17 Features

The engine specializes in "Perfect" C++17 modernization:
- **RAII Enforcement**: Replaces `malloc`/`free` and manual memory with `std::vector`, `std::unique_ptr`, and smart resource management.
- **Logical Const-ness**: Identifies member variables needing `mutable` to allow logging/caching from `const` methods.
- **Efficiency**: Upgrades read-only string handles to `std::string_view`.
- **Thread Safety**: Replaces non-thread-safe C time functions with `localtime_s` (Windows) or `localtime_r` (POSIX).

## Project Structure

```text
agents/
  workflow/         # Modular Workflow System
    nodes/          # Workflow steps (Analyzer, Modernizer, Verifier, etc.)
    infra/          # Infrastructure (Model Provider & LLM bridge)
    orchestrator.py # State Graph Orchestration
core/               # Core engines (RuleModernizer for fallbacks, Differential Tester)
main.py             # Main CLI Entry Point
test.cpp            # Sample Legacy Input
test_modernized.cpp # Sample Modernized Output
```

## Installation

1. Create a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
2. Install minimal dependencies:
   ```powershell
   pip install -r requirements.txt
   ```

## Usage

Run the modernization engine on any C++ file:

```powershell
.\.venv\Scripts\python.exe main.py <path_to_file.cpp>
```

The modernized result will be saved as `<filename>_modernized.cpp`.

## Configuration

Configure your `.env` file with your NVIDIA API key and preferred models:

```env
NVIDIA_API_KEY=nvapi-...
LLM_MODEL=meta/llama-3.3-70b-instruct
MODERNIZER_MODEL=meta/llama-3.3-70b-instruct
FIXER_MODEL=meta/llama-3.3-70b-instruct
```

## License

MIT
