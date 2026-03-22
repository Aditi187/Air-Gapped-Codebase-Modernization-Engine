"""
Entry point for the Air-Gapped C++ Modernization Engine.

Usage:
    python main.py <input_file.cpp>

Loads .env automatically, then runs the full multi-model modernization workflow.
"""
import sys
import os

# Load .env before anything else so all API keys / config are in the environment
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)
except ImportError:
    # dotenv is optional — env vars may already be set in the shell
    pass

from agents.workflow.orchestrator import run_modernization_workflow


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python main.py <input_file.cpp>")
        sys.exit(1)

    input_file = sys.argv[1]
    if not os.path.exists(input_file):
        print(f"Error: File '{input_file}' not found.")
        sys.exit(1)

    with open(input_file, "r", encoding="utf-8") as fh:
        code = fh.read()

    print(f"Starting modernization of {input_file}…")
    result = run_modernization_workflow(code=code, source_file=input_file)

    output_path = result.get("output_file_path", "output_modernized.cpp")
    print(f"Modernization complete. Output → {output_path}")


if __name__ == "__main__":
    main()
