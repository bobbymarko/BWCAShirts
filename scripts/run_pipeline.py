#!/usr/bin/env python3
"""
Run the full BWCA Lake Shirt pipeline (or selected steps).

Usage:
  python scripts/run_pipeline.py                  # all steps
  python scripts/run_pipeline.py --steps 1,2      # download + filter only
  python scripts/run_pipeline.py --steps 3 --limit 5   # generate 5 designs
  python scripts/run_pipeline.py --steps 4 --dry-run    # preview Printful push
"""

import argparse
import importlib
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

STEP_MODULES = {
    1: "scripts.01_download_gis_data",
    2: "scripts.02_filter_bwca_lakes",
    3: "scripts.03_generate_designs",
    4: "scripts.04_push_to_printful",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="BWCA Lake Shirt Pipeline")
    parser.add_argument(
        "--steps", type=str, default="1,2,3,4",
        help="Comma-separated step numbers to run (default: 1,2,3,4)",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lake", type=str, default="")
    parser.add_argument("--svg-only", action="store_true")
    args = parser.parse_args()

    steps = [int(s.strip()) for s in args.steps.split(",")]

    for step_num in steps:
        if step_num not in STEP_MODULES:
            logger.error("Unknown step %d (valid: 1-4)", step_num)
            sys.exit(1)

    for step_num in steps:
        logger.info("=" * 60)
        logger.info("STEP %d", step_num)
        logger.info("=" * 60)

        # Build sys.argv for the sub-script
        saved_argv = sys.argv
        fake_argv = [STEP_MODULES[step_num]]

        if step_num == 3:
            if args.limit:
                fake_argv += ["--limit", str(args.limit)]
            if args.lake:
                fake_argv += ["--lake", args.lake]
            if args.svg_only:
                fake_argv.append("--svg-only")
        elif step_num == 4:
            if args.limit:
                fake_argv += ["--limit", str(args.limit)]
            if args.dry_run:
                fake_argv.append("--dry-run")

        sys.argv = fake_argv
        try:
            mod = importlib.import_module(STEP_MODULES[step_num])
            mod.main()
        finally:
            sys.argv = saved_argv

    logger.info("Pipeline finished.")


if __name__ == "__main__":
    main()
