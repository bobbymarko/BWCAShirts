#!/usr/bin/env python3
"""Debug: trace why the Canadian half of a border lake isn't being attached."""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geopandas as gpd
from shapely.ops import unary_union

from src.config import RAW_DIR, UTM_CRS
from src.gis_pipeline import BWCA_BUFFER_METRES, MERGE_SEAM_METRES, TOUCH_BUFFER_METRES, load_bwca_boundary

LAKE_NAME = "Saganaga Lake"

# ── 1. Load raw NHD ──────────────────────────────────────────────────────────
shp = next(RAW_DIR.glob("**/NHDWaterbody*.shp"))
raw = gpd.read_file(shp)
raw["gnis_name"] = raw["gnis_name"].fillna("").str.strip()

# Filter to lake/pond FTypes only (what load_nhd_waterbodies returns)
raw = raw[raw["ftype"].isin([390, 436])].copy()
raw_utm = raw.to_crs(UTM_CRS)
print(f"Total FType 390/436 features: {len(raw_utm)}")

# ── 2. Find the named lake ───────────────────────────────────────────────────
named_lake = raw_utm[raw_utm["gnis_name"] == LAKE_NAME]
print(f"\nNamed '{LAKE_NAME}' features: {len(named_lake)}")
for _, r in named_lake.iterrows():
    print(f"  area={r['areasqkm']:.3f} km²  bounds={r.geometry.bounds}")

named_geom = named_lake.geometry.union_all()

# ── 3. Check BWCA boundary buffer ───────────────────────────────────────────
bwca = load_bwca_boundary(RAW_DIR)
bwca_utm = bwca.to_crs(UTM_CRS)
bwca_geom = bwca_utm.geometry.union_all().buffer(BWCA_BUFFER_METRES)

print(f"\nNamed lake intersects BWCA buffer: {named_geom.intersects(bwca_geom)}")

# ── 4. Find the unnamed Canadian half ───────────────────────────────────────
unnamed = raw_utm[raw_utm["gnis_name"] == ""].copy()
print(f"\nTotal unnamed FType 390/436 features: {len(unnamed)}")

# The specific ~44 km² feature we found earlier
nearby = unnamed.copy()
nearby["dist_m"] = nearby.geometry.distance(named_geom)
touching = nearby[nearby["dist_m"] == 0].sort_values("areasqkm", ascending=False)
print(f"Unnamed features touching (dist=0): {len(touching)}")
for _, r in touching.iterrows():
    passes_bwca = r.geometry.intersects(bwca_geom)
    print(f"  area={r['areasqkm']:.4f} km²  intersects_BWCA_buffer={passes_bwca}")

# ── 5. Simulate the attach logic ─────────────────────────────────────────────
print(f"\n--- Simulating _attach_unnamed_adjacent ---")
print(f"TOUCH_BUFFER_METRES = {TOUCH_BUFFER_METRES}")

search_geom = named_geom.buffer(TOUCH_BUFFER_METRES)
candidates = unnamed[unnamed.geometry.intersects(search_geom)]
print(f"Candidates found via spatial index simulation: {len(candidates)}")
for _, r in candidates.iterrows():
    print(f"  area={r['areasqkm']:.4f} km²")

# ── 6. Check if unnamed pass the BWCA filter (the key question) ─────────────
print(f"\n--- Do unnamed touching features pass the BWCA buffer filter? ---")
unnamed_in_bwca = unnamed[unnamed.geometry.intersects(bwca_geom)]
print(f"Unnamed features that intersect BWCA buffer: {len(unnamed_in_bwca)}")

# Check the big one specifically
big_unnamed = touching[touching["areasqkm"] > 10]
if not big_unnamed.empty:
    row = big_unnamed.iloc[0]
    print(f"\nBig unnamed (Canadian half), area={row['areasqkm']:.3f} km²:")
    print(f"  bounds = {row.geometry.bounds}")
    print(f"  intersects BWCA buffer = {row.geometry.intersects(bwca_geom)}")
    print(f"  distance to BWCA boundary (unbuffered) = "
          f"{row.geometry.distance(bwca_utm.geometry.union_all()):.1f} m")
