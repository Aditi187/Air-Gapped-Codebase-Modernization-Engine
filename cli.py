import argparse
import sys
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path for relative imports
project_root = Path(__file__).parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Load .env before workflow imports to ensure config is available
load_dotenv(dotenv_path=project_root / ".env", override=True)

from agents.workflow.orchestrator import run_modernization_workflow

def setup_logging(debug: bool = False) -> logging.Logger:
    """
    Configures structured logging for the modernization engine.
    """
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    return logging.getLogger("ModernizationEngine")

def main() -> None:
    """
    Professional CLI entry point for the Modernization Engine.
    """
    parser = argparse.ArgumentParser(
        description="Air-Gapped C++ Modernization Engine: Transform legacy C++ into modern C++17.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python cli.py test.cpp
  python cli.py legacy_code/module.cpp --output modernized/module.cpp --verbose
        """
    )

    parser.add_argument(
        "input",
        help="Path to the legacy C++ source file."
    )
    parser.add_argument(
        "-o", "--output",
        help="Custom output path for the modernized code. Defaults to <input>_modernized.cpp"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable detailed debug logging."
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Modernization Engine 0.1.0"
    )

    args = parser.parse_args()
    logger = setup_logging(args.verbose)

    input_path = Path(args.input)
    if not input_path.exists():
        logger.error(f"Input file not found: {args.input}")
        sys.exit(1)

    try:
        with open(input_path, "r", encoding="utf-8") as f:
            code = f.read()
    except Exception as e:
        logger.error(f"Failed to read input file: {e}")
        sys.exit(1)

    logger.info(f"Starting modernization: {input_path}")
    
    try:
        result = run_modernization_workflow(
            code=code,
            source_file=str(input_path),
            output_path=args.output
        )
        
        output_file = result.get("output_file_path")
        if output_file:
            logger.info(f"Modernization complete. Result saved to: {output_file}")
        else:
            logger.warning("Modernization finished, but no output file was generated.")
            
    except KeyboardInterrupt:
        logger.warning("\nProcess interrupted by user.")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"An unexpected error occurred during modernization: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
