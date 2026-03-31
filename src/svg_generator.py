"""
Generate SVG (and PNG) shirt designs from lake geometries.

Each SVG contains:
  - white lake-outline path(s)
  - lake name in a script font (light blue)
  - "BWCA" subtitle in the same colour
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import cairosvg
import svgwrite
from shapely.geometry import MultiPolygon, Polygon

from .config import (
    ARTBOARD_H,
    ARTBOARD_W,
    FONT_FAMILY,
    LAKE_STROKE_COLOR,
    LAKE_STROKE_WIDTH,
    PRINT_DPI,
    TEXT_COLOR,
    get_font_path,
)
from .layout_engine import LakeLayout

logger = logging.getLogger(__name__)


# ── Geometry → SVG path ─────────────────────────────────────────────────────

def _ring_to_path(coords, scale: float, offset_x: float, offset_y: float,
                  geo_maxy: float, geo_minx: float) -> str:
    """Convert a coordinate ring to an SVG sub-path string."""
    pts = [
        (
            (x - geo_minx) * scale + offset_x,
            (geo_maxy - y) * scale + offset_y,   # flip Y
        )
        for x, y in coords
    ]
    parts = [f"M {pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for px, py in pts[1:]:
        parts.append(f"L {px:.1f},{py:.1f}")
    parts.append("Z")
    return " ".join(parts)


def geometry_to_svg_path(geom, layout: LakeLayout) -> str:
    """Convert a Shapely Polygon/MultiPolygon to a full SVG path 'd' string."""
    minx, _miny, _maxx, maxy = layout.geo_bounds
    scale = layout.scale
    ox, oy = layout.offset_x, layout.offset_y

    def _poly_paths(poly: Polygon) -> str:
        d = _ring_to_path(poly.exterior.coords, scale, ox, oy, maxy, minx)
        for interior in poly.interiors:
            d += " " + _ring_to_path(interior.coords, scale, ox, oy, maxy, minx)
        return d

    if isinstance(geom, Polygon):
        return _poly_paths(geom)
    elif isinstance(geom, MultiPolygon):
        return " ".join(_poly_paths(p) for p in geom.geoms)
    else:
        raise TypeError(f"Unsupported geometry type: {type(geom)}")


# ── Font embedding ───────────────────────────────────────────────────────────

def _embed_font(dwg: svgwrite.Drawing, font_path: Path) -> None:
    """Embed a TTF/OTF font as a base64 @font-face rule inside the SVG."""
    with open(font_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    ext = font_path.suffix.lower()
    fmt = "truetype" if ext == ".ttf" else "opentype"

    css = (
        f"@font-face {{"
        f"  font-family: '{FONT_FAMILY}';"
        f"  src: url('data:font/{fmt};base64,{b64}') format('{fmt}');"
        f"}}"
    )
    dwg.defs.add(dwg.style(css))


# ── Main generator ───────────────────────────────────────────────────────────

def generate_lake_svg(
    lake_name: str,
    geometry,
    layout: LakeLayout,
    output_svg: Path,
    font_path: Path | None = None,
) -> Path:
    """
    Create a 12×18-inch SVG shirt design for a single lake.

    Returns the path to the written SVG file.
    """
    if font_path is None:
        font_path = get_font_path()

    output_svg.parent.mkdir(parents=True, exist_ok=True)

    # Simplify geometry to keep SVG file size reasonable.
    # Tolerance in geo-metres; 2 SVG-units ÷ scale → metres.
    tol = 2.0 / layout.scale if layout.scale else 1.0
    geometry = geometry.simplify(tol, preserve_topology=True)

    dwg = svgwrite.Drawing(
        str(output_svg),
        size=(f"{ARTBOARD_W / 100}in", f"{ARTBOARD_H / 100}in"),
        viewBox=f"0 0 {ARTBOARD_W} {ARTBOARD_H}",
    )

    # Embed font
    _embed_font(dwg, font_path)

    # Lake outline
    path_d = geometry_to_svg_path(geometry, layout)
    dwg.add(dwg.path(
        d=path_d,
        fill="none",
        stroke=LAKE_STROKE_COLOR,
        stroke_width=LAKE_STROKE_WIDTH,
        stroke_linejoin="round",
        stroke_linecap="round",
    ))

    # Lake name
    dwg.add(dwg.text(
        lake_name,
        insert=(layout.name_cx, layout.name_cy),
        text_anchor="middle",
        font_family=f"'{FONT_FAMILY}', cursive",
        font_size=layout.name_font_size,
        fill=TEXT_COLOR,
    ))

    # "BWCA" subtitle
    dwg.add(dwg.text(
        "BWCA",
        insert=(layout.bwca_cx, layout.bwca_cy),
        text_anchor="middle",
        font_family=f"'{FONT_FAMILY}', cursive",
        font_size=layout.bwca_font_size,
        fill=TEXT_COLOR,
        letter_spacing="0.15em",
    ))

    dwg.save(pretty=True)
    logger.info("SVG saved: %s", output_svg.name)
    return output_svg


# ── SVG → PNG conversion ────────────────────────────────────────────────────

def svg_to_png(svg_path: Path, png_path: Path, dpi: int = PRINT_DPI) -> Path:
    """Rasterise an SVG to a 300-DPI transparent PNG suitable for Printful."""
    png_path.parent.mkdir(parents=True, exist_ok=True)

    w_px = int(12 * dpi)   # 3600 px at 300 dpi
    h_px = int(18 * dpi)   # 5400 px at 300 dpi

    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=w_px,
        output_height=h_px,
        background_color="transparent",
    )
    logger.info("PNG saved: %s (%dx%d)", png_path.name, w_px, h_px)
    return png_path
