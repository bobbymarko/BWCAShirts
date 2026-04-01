#!/usr/bin/env python3
"""
Step 3: Generate SVG and PNG shirt designs for every BWCA lake.

Reads  : data/processed/bwca_lakes.geojson
Writes : output/svg/<Lake Name>.svg
         output/png/<Lake Name>.png

Options:
  --limit N        Process only the first N lakes (for quick testing).
  --lake  "Name"   Generate design for a single named lake.
  --sample         Generate ~5 representative lakes (wide, tall, short name,
                   long name, medium) for quick design iteration.
  --svg-only       Skip PNG conversion (faster iteration).
"""

import argparse
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tqdm import tqdm

from src.config import PNG_DIR, PROCESSED_DIR, SVG_DIR, get_font_path
from src.gis_pipeline import load_processed_lakes
from src.layout_engine import compute_layout
from src.svg_generator import generate_lake_png, generate_lake_svg

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def sanitize_filename(name: str) -> str:
    """Make a lake name safe for use as a file name."""
    return name.replace("/", "-").replace("\\", "-").strip()


def select_sample_lakes(lakes) -> list[int]:
    """
    Return the integer positional indices of ~5 representative lakes:
      - widest  (highest aspect ratio)
      - tallest (lowest aspect ratio)
      - shortest name
      - longest name
      - medium  (closest to median aspect ratio + median name length)

    Picks are deduplicated so a lake that wins two categories only appears once.
    """
    import numpy as np

    bounds = lakes.geometry.bounds   # minx miny maxx maxy columns
    geo_w = bounds["maxx"] - bounds["minx"]
    geo_h = bounds["maxy"] - bounds["miny"]
    aspect = (geo_w / geo_h).values

    # Use display name length (strip _N suffix) for name-length picks
    display_names = lakes["GNIS_Name"].str.replace(r" _\d+$", "", regex=True)
    name_len = display_names.str.len().values

    picks_pos: list[int] = []
    seen: set[int] = set()

    def add(pos: int, label: str) -> None:
        if pos not in seen:
            seen.add(pos)
            picks_pos.append(pos)
            logger.info("Sample — %-14s → %s", label, lakes.iloc[pos]["GNIS_Name"])

    add(int(np.argmax(aspect)),   "widest")
    add(int(np.argmin(aspect)),   "tallest")
    add(int(np.argmin(name_len)), "shortest name")
    add(int(np.argmax(name_len)), "longest name")

    # Medium: normalised distance from median aspect AND median name length
    med_aspect   = float(np.median(aspect))
    med_name_len = float(np.median(name_len))
    norm_aspect  = (aspect   - med_aspect)   / (aspect.max()   - aspect.min()   + 1e-9)
    norm_name    = (name_len - med_name_len) / (name_len.max() - name_len.min() + 1e-9)
    dist = np.abs(norm_aspect) + np.abs(norm_name)
    # Exclude already-picked indices
    dist_copy = dist.copy()
    for idx in seen:
        dist_copy[idx] = np.inf
    add(int(np.argmin(dist_copy)), "medium")

    return picks_pos


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate BWCA lake shirt designs")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N lakes")
    parser.add_argument("--lake", type=str, default="",
                        help="Generate for a single lake name")
    parser.add_argument("--sample", action="store_true",
                        help="Generate ~5 representative lakes for design iteration")
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
    elif args.sample:
        sample_positions = select_sample_lakes(lakes)
        lakes = lakes.iloc[sample_positions].copy()
        logger.info("Sample mode: %d representative lakes selected", len(lakes))
    elif args.limit > 0:
        lakes = lakes.head(args.limit)

    logger.info("Generating designs for %d lakes …", len(lakes))

    SVG_DIR.mkdir(parents=True, exist_ok=True)
    PNG_DIR.mkdir(parents=True, exist_ok=True)

    errors: list[dict] = []

    for _, row in tqdm(lakes.iterrows(), total=len(lakes), desc="Designs"):
        name = row["GNIS_Name"].strip()
        geom = row.geometry
        safe_name = sanitize_filename(name)

        # Strip disambiguation suffix ( _2, _3 …) from the printed label.
        # The suffix is kept in safe_name so duplicate lakes get distinct files.
        display_name = re.sub(r" _\d+$", "", name)

        try:
            layout = compute_layout(geom.bounds, display_name)

            svg_path = SVG_DIR / f"{safe_name}.svg"
            generate_lake_svg(display_name, geom, layout, svg_path, font_path=font_path)

            if not args.svg_only:
                png_path = PNG_DIR / f"{safe_name}.png"
                generate_lake_png(display_name, geom, layout, png_path,
                                  font_path=font_path)

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
