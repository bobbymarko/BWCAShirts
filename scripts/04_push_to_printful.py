#!/usr/bin/env python3
"""
Step 4: Upload PNG designs to Printful and create store products.

Reads  : output/png/*.png
Writes : output/printful_progress.csv  (tracks upload state per lake)

The script is idempotent: re-running skips lakes whose status is "done".

Options:
  --limit N       Process only the first N un-pushed designs.
  --dry-run       Print what would happen without making API calls.
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tqdm import tqdm

from src.config import OUTPUT_DIR, PNG_DIR
from src.printful_client import PrintfulClient, PrintfulError

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

PROGRESS_CSV = OUTPUT_DIR / "printful_progress.csv"


def _load_progress() -> pd.DataFrame:
    if PROGRESS_CSV.exists():
        return pd.read_csv(PROGRESS_CSV)
    return pd.DataFrame(columns=[
        "lake_name", "png_file", "file_id", "sync_product_id",
        "mockup_url", "status", "error",
    ])


def _save_progress(df: pd.DataFrame) -> None:
    PROGRESS_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(PROGRESS_CSV, index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push designs to Printful")
    parser.add_argument("--limit", type=int, default=0,
                        help="Process only the first N un-pushed designs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without making API calls")
    args = parser.parse_args()

    # Collect PNG files
    png_files = sorted(PNG_DIR.glob("*.png"))
    if not png_files:
        logger.error("No PNG files found in %s. Run step 3 first.", PNG_DIR)
        sys.exit(1)

    progress = _load_progress()
    done_names = set(progress.loc[progress["status"] == "done", "lake_name"])
    todo = [p for p in png_files if p.stem not in done_names]

    if args.limit > 0:
        todo = todo[: args.limit]

    logger.info("%d designs to push (%d already done)", len(todo), len(done_names))

    if args.dry_run:
        for p in todo:
            logger.info("[DRY RUN] Would upload: %s", p.name)
        return

    client = PrintfulClient()
    product_id = client.find_bella_canvas_3001()
    variants = client.get_asphalt_variants(product_id)
    variant_ids = [v["variant_id"] for v in variants]

    for png_path in tqdm(todo, desc="Printful"):
        lake_name = png_path.stem
        row = {
            "lake_name": lake_name,
            "png_file": png_path.name,
            "file_id": None,
            "sync_product_id": None,
            "mockup_url": None,
            "status": "pending",
            "error": "",
        }

        try:
            # 1. Upload file
            file_id = client.upload_file(png_path)
            row["file_id"] = file_id

            # 2. Generate mockup
            try:
                mockup_urls = client.generate_mockup(product_id, variant_ids, file_id)
                row["mockup_url"] = mockup_urls[0] if mockup_urls else None
            except PrintfulError as e:
                logger.warning("Mockup failed for %s: %s (continuing)", lake_name, e)

            # 3. Create sync product
            product_name = f"{lake_name} BWCA T-Shirt"
            sync_id = client.create_sync_product(
                product_name, file_id, variants,
                thumbnail_url=row["mockup_url"],
            )
            row["sync_product_id"] = sync_id
            row["status"] = "done"

        except Exception as e:
            row["status"] = "error"
            row["error"] = str(e)[:200]
            logger.error("Failed: %s – %s", lake_name, e)

        # Append to progress (in-place)
        progress = pd.concat(
            [progress, pd.DataFrame([row])], ignore_index=True
        )
        _save_progress(progress)

    done_count = len(progress[progress["status"] == "done"])
    logger.info("Step 4 complete: %d / %d products created.", done_count, len(progress))


if __name__ == "__main__":
    main()
