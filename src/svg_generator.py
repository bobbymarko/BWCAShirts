"""
Generate SVG (and PNG) shirt designs from lake geometries.

Each SVG contains:
  - white lake-outline path(s)
  - lake name in a script font (light blue)
  - "BWCA" subtitle in the same colour
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path

import cairosvg
import svgwrite
from PIL import Image, ImageDraw, ImageFont
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
        for x, y, *_ in coords  # *_ ignores Z if geometry is 3D
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
    """
    Embed font in SVG via @font-face.

    Uses a file:// URL as the primary source so CairoSVG/Pango can resolve it
    reliably during PNG conversion, with a base64 data URI as a browser fallback
    for portability when the SVG is viewed without the local font file.
    """
    ext = font_path.suffix.lower()
    fmt = "truetype" if ext == ".ttf" else "opentype"
    mime = "font/ttf" if ext == ".ttf" else "font/otf"

    file_url = font_path.resolve().as_uri()   # file:///abs/path/to/font.ttf

    with open(font_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    css = (
        f"@font-face {{"
        f"  font-family: '{FONT_FAMILY}';"
        f"  src: url('{file_url}') format('{fmt}'),"
        f"       url('data:{mime};base64,{b64}') format('{fmt}');"
        f"}}"
    )
    # Add at SVG root (not nested in <defs>) for broadest renderer compatibility
    dwg.add(dwg.style(css))


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

    # Strip Z coordinates — NHD data is sometimes 3D, which breaks path iteration.
    import shapely
    geometry = shapely.force_2d(geometry)

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

    # ── Text first (lake shape will render on top) ───────────────────────────

    # Lake name
    dwg.add(dwg.text(
        lake_name,
        insert=(layout.name_cx, layout.name_cy),
        text_anchor="middle",
        font_family=f"'{FONT_FAMILY}', cursive",
        font_size=layout.name_font_size,
        fill=TEXT_COLOR,
    ))

    # "BWCA" subtitle — right-aligned to the approximate right edge of the name.
    # Approximate name width: 0.55× font-size per character (script font estimate).
    approx_name_right = layout.name_cx + layout.name_font_size * 0.55 * len(lake_name) / 2
    dwg.add(dwg.text(
        "BWCA",
        insert=(approx_name_right, layout.bwca_cy),
        text_anchor="end",
        font_family=f"'{FONT_FAMILY}', cursive",
        font_size=layout.bwca_font_size,
        fill=TEXT_COLOR,
        letter_spacing="0.15em",
    ))

    # ── Lake outline on top ──────────────────────────────────────────────────
    path_d = geometry_to_svg_path(geometry, layout)
    dwg.add(dwg.path(
        d=path_d,
        fill="none",
        stroke=LAKE_STROKE_COLOR,
        stroke_width=LAKE_STROKE_WIDTH,
        stroke_linejoin="round",
        stroke_linecap="round",
    ))

    dwg.save(pretty=True)
    logger.info("SVG saved: %s", output_svg.name)
    return output_svg


# ── PNG generation (hybrid: CairoSVG shape + Pillow text) ───────────────────
#
# CairoSVG hands off text rendering to Pango/fontconfig, which ignores the
# SVG's embedded @font-face and falls back to a system font.  We sidestep
# this entirely: CairoSVG renders only the lake-shape path (no text), then
# Pillow adds both text elements using ImageFont.truetype(), which loads the
# TTF/OTF file directly — no fontconfig involved.

def _hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def _draw_spaced_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    x_px: float,
    baseline_px: int,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    letter_spacing_em: float = 0.0,
    h_align: str = "center",  # "center", "left", or "right"
) -> None:
    """
    Draw text with optional CSS-style letter-spacing.

    x_px is interpreted according to h_align:
      "center" → x_px is the horizontal midpoint
      "right"  → x_px is the right edge
      "left"   → x_px is the left edge
    """
    if letter_spacing_em == 0.0:
        anchor = {"center": "ms", "left": "ls", "right": "rs"}[h_align]
        draw.text((x_px, baseline_px), text, font=font, fill=fill, anchor=anchor)
        return

    spacing_px = font.size * letter_spacing_em
    widths = [draw.textlength(ch, font=font) for ch in text]
    total_w = sum(widths) + spacing_px * (len(text) - 1)

    if h_align == "center":
        start_x = x_px - total_w / 2
    elif h_align == "right":
        start_x = x_px - total_w
    else:
        start_x = x_px

    cur_x = start_x
    for ch, w in zip(text, widths):
        draw.text((cur_x, baseline_px), ch, font=font, fill=fill, anchor="ls")
        cur_x += w + spacing_px


def generate_lake_png(
    lake_name: str,
    geometry,
    layout: LakeLayout,
    output_png: Path,
    font_path: Path | None = None,
    dpi: int = PRINT_DPI,
) -> Path:
    """
    Render a 300-DPI transparent PNG for a single lake design.

    Shape path  → CairoSVG   (reliable vector rendering, no font needed)
    Text        → Pillow      (direct TTF/OTF load, bypasses fontconfig)
    """
    import shapely

    if font_path is None:
        font_path = get_font_path()

    output_png.parent.mkdir(parents=True, exist_ok=True)

    w_px = int(ARTBOARD_W / 100 * dpi)
    h_px = int(ARTBOARD_H / 100 * dpi)
    # 100 SVG units = 1 inch → at dpi, 1 SVG unit = dpi/100 pixels
    svg_to_px = dpi / 100.0

    # ── 1. Build a shape-only SVG string (no text / no font) ─────────────
    geom_2d = shapely.force_2d(geometry)
    tol = 2.0 / layout.scale if layout.scale else 1.0
    geom_2d = geom_2d.simplify(tol, preserve_topology=True)

    path_d = geometry_to_svg_path(geom_2d, layout)
    shape_svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{ARTBOARD_W / 100}in" height="{ARTBOARD_H / 100}in" '
        f'viewBox="0 0 {ARTBOARD_W} {ARTBOARD_H}">'
        f'<path d="{path_d}" fill="none"'
        f' stroke="{LAKE_STROKE_COLOR}"'
        f' stroke-width="{LAKE_STROKE_WIDTH}"'
        f' stroke-linejoin="round" stroke-linecap="round"/>'
        f'</svg>'
    )

    # ── 2. Render shape to RGBA image via CairoSVG ───────────────────────
    png_bytes = cairosvg.svg2png(
        bytestring=shape_svg.encode(),
        output_width=w_px,
        output_height=h_px,
        background_color="transparent",
    )
    img = Image.open(io.BytesIO(png_bytes)).convert("RGBA")

    # ── 3. Add text with Pillow (direct font-file loading) ───────────────
    draw = ImageDraw.Draw(img)
    fill = _hex_to_rgba(TEXT_COLOR)

    name_size_px = max(1, int(layout.name_font_size * svg_to_px))
    bwca_size_px = max(1, int(layout.bwca_font_size * svg_to_px))
    name_font = ImageFont.truetype(str(font_path), name_size_px)
    bwca_font = ImageFont.truetype(str(font_path), bwca_size_px)

    name_cx_px = int(layout.name_cx * svg_to_px)
    name_cy_px = int(layout.name_cy * svg_to_px)
    bwca_cy_px = int(layout.bwca_cy * svg_to_px)

    # Text is drawn UNDER the shape (matches SVG layer order: text then path on top)
    text_layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)

    _draw_spaced_text(text_draw, lake_name, name_cx_px, name_cy_px, name_font, fill)

    # Right-align BWCA to the right edge of the rendered lake name
    name_width_px = text_draw.textlength(lake_name, font=name_font)
    name_right_px = name_cx_px + name_width_px / 2
    _draw_spaced_text(text_draw, "BWCA", name_right_px, bwca_cy_px, bwca_font, fill,
                      letter_spacing_em=0.15, h_align="right")

    # Composite: text layer first, then the shape layer on top
    composed = Image.alpha_composite(text_layer, img)
    composed.save(str(output_png), "PNG")
    logger.info("PNG saved: %s (%dx%d)", output_png.name, w_px, h_px)
    return output_png


def svg_to_png(svg_path: Path, png_path: Path, dpi: int = PRINT_DPI) -> Path:
    """Rasterise a full SVG (including any embedded text) to a PNG.

    Note: custom @font-face fonts may not render correctly via CairoSVG/Pango.
    Prefer generate_lake_png() for designs that use a custom font.
    """
    png_path.parent.mkdir(parents=True, exist_ok=True)
    w_px = int(ARTBOARD_W / 100 * dpi)
    h_px = int(ARTBOARD_H / 100 * dpi)
    cairosvg.svg2png(
        url=str(svg_path),
        write_to=str(png_path),
        output_width=w_px,
        output_height=h_px,
        background_color="transparent",
    )
    logger.info("PNG saved: %s (%dx%d)", png_path.name, w_px, h_px)
    return png_path
