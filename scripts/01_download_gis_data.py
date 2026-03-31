#!/usr/bin/env python3
"""
Step 1: Download GIS source data.

Downloads:
  - NHD high-resolution waterbody shapefiles (HU4 0401 + 0402)
  - USFS Wilderness boundary shapefile
  - Placeholder font (Dancing Script) if no custom font is provided

All files are saved to data/raw/ and extracted automatically.
"""

import logging
import sys
import zipfile
from pathlib import Path
from urllib.request import urlretrieve

# Allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import (
    FONTS_DIR,
    NHD_URLS,
    PLACEHOLDER_FONT_NAME,
    PLACEHOLDER_FONT_URL,
    RAW_DIR,
    WILDERNESS_URL,
    get_font_path,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)


def download_file(url: str, dest: Path) -> Path:
    """Download *url* to *dest*, skipping if the file already exists."""
    if dest.exists():
        logger.info("Already downloaded: %s", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %s …", url.split("/")[-1])
    urlretrieve(url, dest)
    logger.info("  → saved %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


def extract_zip(zip_path: Path, dest_dir: Path) -> None:
    """Extract a zip archive into *dest_dir*, skipping if already extracted."""
    # Simple heuristic: if the directory already has files, skip
    if any(dest_dir.rglob("*.shp")):
        logger.info("Already extracted: %s", dest_dir.name)
        return
    logger.info("Extracting %s …", zip_path.name)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(dest_dir)
    logger.info("  → extracted to %s", dest_dir)


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # ── NHD waterbody data ───────────────────────────────────────────────
    for url in NHD_URLS:
        fname = url.split("/")[-1]
        zip_path = RAW_DIR / fname
        download_file(url, zip_path)
        extract_dir = RAW_DIR / fname.replace(".zip", "")
        extract_zip(zip_path, extract_dir)

    # ── BWCA (Wilderness) boundary ───────────────────────────────────────
    wild_zip = RAW_DIR / "S_USA.Wilderness.zip"
    download_file(WILDERNESS_URL, wild_zip)
    extract_zip(wild_zip, RAW_DIR / "S_USA.Wilderness")

    # ── Placeholder font ─────────────────────────────────────────────────
    try:
        get_font_path()
        logger.info("Font already available.")
    except FileNotFoundError:
        font_dest = FONTS_DIR / PLACEHOLDER_FONT_NAME
        download_file(PLACEHOLDER_FONT_URL, font_dest)

    logger.info("Step 1 complete.")


if __name__ == "__main__":
    main()
