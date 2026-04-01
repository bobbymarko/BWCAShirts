#!/usr/bin/env python3
"""
Step 2: Filter NHD waterbodies to named lakes within the BWCA region.

Uses a 3 km buffer around the BWCA boundary so border lakes (Gunflint,
North Lake, Saganaga, etc.) are included even when they extend into Canada.
Lake geometries are never clipped — the full NHD shape is preserved.

Reads  : data/raw/mn_nhd/  +  data/raw/S_USA.Wilderness/
Writes : data/processed/bwca_lakes.geojson
         output/review/edge_cases.csv
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import PROCESSED_DIR, RAW_DIR, REVIEW_DIR
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

    logger.info("Filtering lakes …")
    bwca_lakes, edge_cases = filter_lakes_in_bwca(lakes, bwca)

    output_path = PROCESSED_DIR / "bwca_lakes.geojson"
    export_bwca_lakes(bwca_lakes, output_path)

    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    edge_path = REVIEW_DIR / "edge_cases.csv"
    if not edge_cases.empty:
        edge_cases.to_csv(edge_path, index=False)
        logger.info("Edge cases → %s (%d rows)", edge_path, len(edge_cases))

    logger.info("Step 2 complete: %d BWCA lakes exported.", len(bwca_lakes))


if __name__ == "__main__":
    main()
