"""
Text-placement algorithm for BWCA lake shirt designs.

Given a lake's geographic bounding box (in UTM metres) and its name, compute:
  - scale / offset to fit the lake outline in the SVG artboard
  - font sizes for the lake name and "BWCA" subtitle
  - (x, y) positions for both text elements
"""

from __future__ import annotations
from dataclasses import dataclass

from .config import (
    ARTBOARD_H,
    ARTBOARD_W,
    MARGIN_X,
    MARGIN_Y,
    PRINT_AREA_H,
    PRINT_AREA_W,
)


@dataclass
class LakeLayout:
    # Lake outline transform
    scale: float          # geo-metres → SVG-units
    offset_x: float       # SVG-unit left offset
    offset_y: float       # SVG-unit top offset
    geo_bounds: tuple[float, float, float, float]  # (minx, miny, maxx, maxy)

    # Lake name text
    name_cx: float
    name_cy: float
    name_font_size: float

    # "BWCA" subtitle
    bwca_cx: float
    bwca_cy: float
    bwca_font_size: float

    # Diagnostics
    aspect_ratio: float
    shape_class: str      # "tall", "wide", or "medium"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def compute_layout(
    geo_bounds: tuple[float, float, float, float],
    lake_name: str,
    artboard_w: int = ARTBOARD_W,
    artboard_h: int = ARTBOARD_H,
) -> LakeLayout:
    """
    Compute positions and font sizes for a single lake design.

    Parameters
    ----------
    geo_bounds : (minx, miny, maxx, maxy) in projected metres (UTM).
    lake_name  : display name used to estimate text width.
    """
    minx, miny, maxx, maxy = geo_bounds
    geo_w = maxx - minx
    geo_h = maxy - miny

    if geo_w == 0 or geo_h == 0:
        raise ValueError("Degenerate lake geometry (zero width or height)")

    aspect = geo_w / geo_h

    # Classify shape
    if aspect < 0.65:
        shape_class = "tall"
    elif aspect > 1.35:
        shape_class = "wide"
    else:
        shape_class = "medium"

    # ── Scale lake to fit print area ─────────────────────────────────────
    avail_w = PRINT_AREA_W
    avail_h = PRINT_AREA_H

    scale = min(avail_w / geo_w, avail_h / geo_h)

    display_w = geo_w * scale
    display_h = geo_h * scale

    # Centre the lake bounding-box in the artboard
    offset_x = (artboard_w - display_w) / 2
    offset_y = (artboard_h - display_h) / 2

    # ── Font sizes ───────────────────────────────────────────────────────
    name_fs = _clamp(display_w * 0.22, 55, 220)

    # Shrink if the name is very long
    char_count = len(lake_name)
    if char_count > 12:
        max_fs = (artboard_w * 0.88) / (char_count * 0.52)
        name_fs = min(name_fs, max_fs)

    bwca_fs = name_fs * 0.32

    # ── Text vertical position ───────────────────────────────────────────
    lake_top  = offset_y
    lake_bot  = offset_y + display_h

    if shape_class == "tall":
        text_anchor_y = lake_top + display_h * 0.27
    elif shape_class == "wide":
        text_anchor_y = lake_top + display_h * 0.50
    else:
        text_anchor_y = lake_top + display_h * 0.38

    # The anchor represents the vertical mid-point of the text block.
    # Text block height = name_fs + descender gap + bwca_fs
    descender = name_fs * 0.25
    gap = name_fs * 0.12
    block_h = name_fs + descender + gap + bwca_fs
    block_top = text_anchor_y - block_h / 2

    name_cy = block_top + name_fs          # baseline of lake name
    bwca_cy = name_cy + descender + gap + bwca_fs  # baseline of BWCA

    # Clamp text inside the artboard (with 30-unit margin)
    name_cy = _clamp(name_cy, 60, artboard_h - 60)
    bwca_cy = _clamp(bwca_cy, 60, artboard_h - 30)

    # Horizontal: always centred
    cx = artboard_w / 2

    return LakeLayout(
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
        geo_bounds=geo_bounds,
        name_cx=cx,
        name_cy=name_cy,
        name_font_size=name_fs,
        bwca_cx=cx,
        bwca_cy=bwca_cy,
        bwca_font_size=bwca_fs,
        aspect_ratio=aspect,
        shape_class=shape_class,
    )
