
"""
Entry point for the Air-Gapped C++ Modernization Engine.

Usage:
    python main.py <input_file.cpp>

Loads .env automatically, then runs the full multi-model modernization workflow.
"""
# Load .env before anything else so all API keys / config are in the environment
import os
import sys

# Add project root to path for relative imports
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=os.path.join(project_root, ".env"), override=True)
except ImportError:
    pass

import logging

# Configure logging to show process steps clearly in the terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ModernizationEngine")

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

    print(f"[DEBUG] Starting modernization of {input_file}…")
    print("[DEBUG] Input code:\n" + code)
    result = run_modernization_workflow(code=code, source_file=input_file)
    output_file = result.get("output_file_path")
    modernized_code = result.get("modernized_code")
    print(f"[DEBUG] Output file path: {output_file}")
    if modernized_code is not None:
        print("[DEBUG] Modernized code:\n" + modernized_code)
    else:
        print("[DEBUG] No modernized code produced.")
    if output_file:
        print(f"Modernized code written to: {output_file}")
    else:
        print("Modernization complete, but no output file was written.")


if __name__ == "__main__":
    main()
