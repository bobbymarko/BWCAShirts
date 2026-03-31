#!/usr/bin/env python3
"""
Step 3: Generate SVG and PNG shirt designs for every BWCA lake.

Reads  : data/processed/bwca_lakes.geojson
Writes : output/svg/<Lake Name>.svg
         output/png/<Lake Name>.png

Options:
  --limit N        Process only the first N lakes (for quick testing).
  --lake  "Name"   Generate design for a single named lake.
  --svg-only       Skip PNG conversion (faster iteration).
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tqdm import tqdm

from src.config import PNG_DIR, PROCESSED_DIR, SVG_DIR, get_font_path
from src.gis_pipeline import load_processed_lakes
from src.layout_engine import compute_layout
from src.svg_generator import generate_lake_svg, svg_to_png

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Make a lake name safe for use as a file name."""
    return name.replace("/", "-").replace("\\", "-").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate BWCA lake shirt designs")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N lakes")
    parser.add_argument("--lake", type=str, default="",
                        help="Generate for a single lake name")
    parser.add_argument("--svg-only", action="store_true",
                        help="Skip PNG conversion")
    args = parser.parse_args()

    font_path = get_font_path()
    logger.info("Using font: %s", font_path.name)

    lakes = load_processed_lakes(PROCESSED_DIR)

    if args.lake:
        lakes = lakes[lakes["GNIS_Name"].str.strip() == args.lake.strip()]
        if lakes.empty:
            logger.error("Lake '%s' not found in processed data.", args.lake)
            sys.exit(1)

    if args.limit > 0:
        lakes = lakes.head(args.limit)

    logger.info("Generating designs for %d lakes …", len(lakes))

    SVG_DIR.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)

    errors: list[dict] = []

    for _, row in tqdm(lakes.iterrows(), total=len(lakes), desc="Designs"):
        name = row["GNIS_Name"].strip()
        geom = row.geometry
        safe_name = sanitize_filename(name)

        try:
            layout = compute_layout(geom.bounds, name)

            svg_path = SVG_DIR / f"{safe_name}.svg"
            generate_lake_svg(name, geom, layout, svg_path, font_path=font_path)

            if not args.svg_only:
                png_path = PNG_DIR / f"{safe_name}.png"
                svg_to_png(svg_path, png_path)

        except Exception as e:
            errors.append({"lake_name": name, "error": str(e)})
            logger.warning("Failed: %s – %s", name, e)

    if errors:
        import pandas as pd
        err_path = Path("output/review/generation_errors.csv")
        err_path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(errors).to_csv(err_path, index=False)
        logger.warning("%d errors → %s", len(errors), err_path)

    logger.info("Step 3 complete: %d designs generated.", len(lakes) - len(errors))


if __name__ == "__main__":
    main()
