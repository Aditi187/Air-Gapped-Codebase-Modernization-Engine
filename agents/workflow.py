"""
Legacy workflow.py entry point.

This file has been completely refactored into a modular, production-ready architecture.
All logic now resides under the `agents/workflow/` directory.

- For programmatic usage, import `run_modernization_workflow` from `agents.workflow`.
- For CLI usage, run `python -m agents.workflow.cli file.cpp`.

This module is kept for backward compatibility.
"""

import sys
import warnings

# Export the main workflow function for backward compatibility
from agents.workflow.orchestrator import run_modernization_workflow

__all__ = ["run_modernization_workflow"]


def main() -> None:
    """CLI entry point for the legacy workflow.py."""
    # Show deprecation warning
    warnings.warn(
        "Using `workflow.py` as CLI is deprecated. Use `python -m agents.workflow.cli` instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        from agents.workflow.cli import main as cli_main

        # If run without arguments, show help
        if len(sys.argv) == 1:
            sys.argv.append("--help")
        cli_main()
    except ImportError:
        print(
            "ERROR: Could not import the CLI module. "
            "Make sure the package is installed correctly.",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()