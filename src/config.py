"""Central configuration for the BWCA Lake Shirt pipeline."""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Paths ────────────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
OUTPUT_DIR = ROOT_DIR / "output"
SVG_DIR = OUTPUT_DIR / "svg"
PNG_DIR = OUTPUT_DIR / "png"
REVIEW_DIR = OUTPUT_DIR / "review"
FONTS_DIR = ROOT_DIR / "fonts"

# ── SVG Artboard (100 SVG-units per inch) ────────────────────────────────────
ARTBOARD_W = 1500   # 15 inches
ARTBOARD_H = 1800   # 18 inches
MARGIN_X = 100      # 1 inch each side
MARGIN_Y = 200      # 2 inches top/bottom
PRINT_AREA_W = ARTBOARD_W - 2 * MARGIN_X   # 1000
PRINT_AREA_H = ARTBOARD_H - 2 * MARGIN_Y   # 1400

# ── Design colours / strokes ─────────────────────────────────────────────────
LAKE_STROKE_COLOR = "#FFFFFF"
LAKE_STROKE_WIDTH = 3.5
TEXT_COLOR = "#8BBCCC"

# ── Font ─────────────────────────────────────────────────────────────────────
FONT_FAMILY = "LakeScript"
FONT_PATH = Path(os.getenv("FONT_PATH", ""))
PLACEHOLDER_FONT_NAME = "DancingScript-Regular.ttf"

def get_font_path() -> Path:
    """Return the active font file, falling back to the placeholder."""
    if FONT_PATH.is_file():
        return FONT_PATH
    placeholder = FONTS_DIR / PLACEHOLDER_FONT_NAME
    if placeholder.is_file():
        return placeholder
    raise FileNotFoundError(
        "No font file found. Place a .ttf/.otf in fonts/ or set FONT_PATH in .env"
    )

# ── GIS ──────────────────────────────────────────────────────────────────────
UTM_CRS = "EPSG:26915"  # UTM Zone 15N – Minnesota
MIN_LAKE_AREA_ACRES = float(os.getenv("MIN_LAKE_AREA_ACRES", "10.0"))
MIN_LAKE_AREA_KM2 = MIN_LAKE_AREA_ACRES * 0.00404686  # acres → km²

# ── Printful ─────────────────────────────────────────────────────────────────
PRINTFUL_API_BASE = "https://api.printful.com"
PRINTFUL_API_KEY = os.getenv("PRINTFUL_API_KEY", "")
PRINTFUL_STORE_ID = os.getenv("PRINTFUL_STORE_ID", "")
PRINT_DPI = 300

# ── GIS download URLs ───────────────────────────────────────────────────────
NHD_URL = "https://resources.gisdata.mn.gov/pub/gdrs/data/pub/us_mn_state_pca/water_national_hydrography_data/shp_water_national_hydrography_data.zip"
WILDERNESS_URL = "https://data.fs.usda.gov/geodata/edw/edw_resources/shp/S_USA.Wilderness.zip"
PLACEHOLDER_FONT_URL = "https://github.com/google/fonts/raw/refs/heads/main/ofl/dancingscript/static/DancingScript-Regular.ttf"
