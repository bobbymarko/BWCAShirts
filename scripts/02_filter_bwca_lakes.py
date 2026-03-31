#!/usr/bin/env python3
"""
Step 2: Filter NHD waterbodies to named lakes within the BWCA boundary.

Reads shapefiles from data/raw/ and writes:
  - data/processed/bwca_lakes.geojson   (the main output)
  - output/review/edge_cases.csv        (duplicate-name lakes, etc.)
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DATA_DIR, PROCESSED_DIR, RAW_DIR, REVIEW_DIR
from src.gis_pipeline import (
    export_bwca_lakes,
    filter_lakes_in_bwca,
    load_bwca_boundary,
    load_nhd_waterbodies,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Loading NHD waterbodies …")
    lakes = load_nhd_waterbodies(RAW_DIR)

    logger.info("Loading BWCA boundary …")
    bwca = load_bwca_boundary(RAW_DIR)

    overrides = DATA_DIR / "overrides.csv"
    logger.info("Filtering lakes within BWCA …")
    bwca_lakes, edge_cases = filter_lakes_in_bwca(
        lakes, bwca, overrides_path=overrides
    )

    # Save main output
    output_path = PROCESSED_DIR / "bwca_lakes.geojson"
    export_bwca_lakes(bwca_lakes, output_path)

    # Save edge cases
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    edge_path = REVIEW_DIR / "edge_cases.csv"
    if not edge_cases.empty:
        edge_cases.to_csv(edge_path, index=False)
        logger.info("Edge cases written to %s (%d rows)", edge_path, len(edge_cases))
    else:
        logger.info("No edge cases to report.")

    logger.info("Step 2 complete: %d BWCA lakes exported.", len(bwca_lakes))


if __name__ == "__main__":
    main()
