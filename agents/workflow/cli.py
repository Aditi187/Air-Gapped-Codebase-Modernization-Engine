import argparse
import sys
import os
from typing import Optional

from agents.workflow.orchestrator import run_modernization_workflow
from core.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Air-Gapped C++ Modernization Engine CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s legacy.cpp                     # safe mode, output to legacy_modernized.cpp
  %(prog)s legacy.cpp --mode aggressive   # allow signature changes
  %(prog)s legacy.cpp -o output.cpp       # specify output file
  %(prog)s legacy.cpp --verbose           # enable debug logging
"""
    )
    parser.add_argument(
        "file",
        help="Path to the legacy C++ file to modernize"
    )
    parser.add_argument(
        "--mode", "-m",
        choices=["safe", "aggressive"],
        default="safe",
        help="Modernization aggressiveness (safe = no signature changes, aggressive = allow signature refactoring)"
    )
    parser.add_argument(
        "--output", "-o",
        default="",
        help="Output path for the modernized file (default: <input>_modernized.cpp)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (debug) logging"
    )
    parser.add_argument(
        "--config", "-c",
        default="",
        help="Path to a configuration file (JSON) to override default settings"
    )

    args = parser.parse_args()

    # Configure logging level based on verbosity
    if args.verbose:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
        logger.debug("Verbose logging enabled")

    # Resolve file path
    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        logger.error(f"❌ File not found: {file_path}")
        sys.exit(1)

    # Determine output path
    if not args.output:
        base, ext = os.path.splitext(file_path)
        output_path = f"{base}_modernized{ext}"
    else:
        output_path = os.path.abspath(args.output)
        # Ensure output directory exists
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)
            logger.info(f"Created output directory: {out_dir}")

    # Load configuration if provided
    config_overrides = {}
    if args.config:
        try:
            import json
            with open(args.config, "r", encoding="utf-8") as cf:
                config_overrides = json.load(cf)
                logger.info(f"Loaded configuration from {args.config}")
        except Exception as e:
            logger.error(f"Failed to load config file: {e}")
            sys.exit(1)

    # Read source file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            code = f.read()
        if not code.strip():
            logger.error("❌ Source file is empty")
            sys.exit(1)
        logger.info(f"Loaded {file_path} ({len(code)} bytes)")
    except UnicodeDecodeError:
        logger.error(f"❌ File encoding is not UTF-8: {file_path}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to read file: {e}")
        sys.exit(1)

    # Build workflow parameters
    workflow_kwargs = {
        "code": code,
        "language": "c++17",
        "source_file": file_path,
        "output_file_path": output_path,
        "config_overrides": config_overrides,
        "aggressive_mode": (args.mode == "aggressive"),
    }

    try:
        result = run_modernization_workflow(**workflow_kwargs)

        verification_ok = bool(result.get("verification_result", {}).get("success"))
        if verification_ok:
            logger.info(f"✅ Modernization completed successfully. Output written to: {output_path}")
            sys.exit(0)
        else:
            error_log = result.get("error_log", "Unknown verification error")
            logger.warning(f"⚠️  Modernization completed with verification warnings:\n{error_log}")
            sys.exit(2)   # 2 indicates success with warnings
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"❌ Workflow crashed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()