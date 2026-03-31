"""Load, filter, and export GIS data for BWCA lakes."""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd

from .config import MIN_LAKE_AREA_KM2, UTM_CRS

logger = logging.getLogger(__name__)


# ── NHD waterbody loading ────────────────────────────────────────────────────

def _find_nhd_waterbody_shapefiles(raw_dir: Path) -> list[Path]:
    """Locate NHDWaterbody.shp files inside extracted NHD zip directories."""
    results = sorted(raw_dir.glob("NHD_H_*/Shape/NHDWaterbody.shp"))
    if not results:
        # Try alternate layout (some extracts have a flat structure)
        results = sorted(raw_dir.glob("**/NHDWaterbody.shp"))
    return results


def load_nhd_waterbodies(raw_dir: Path) -> gpd.GeoDataFrame:
    shp_files = _find_nhd_waterbody_shapefiles(raw_dir)
    if not shp_files:
        raise FileNotFoundError(
            f"No NHDWaterbody.shp found under {raw_dir}. Run 01_download_gis_data.py first."
        )

    frames = []
    for shp in shp_files:
        gdf = gpd.read_file(shp)
        frames.append(gdf)
        logger.info("Loaded %d waterbodies from %s", len(gdf), shp.name)

    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    combined = combined.drop_duplicates(subset=["GNIS_ID"], keep="first")

    # Keep only lakes / ponds (FType 390) and reservoirs (436)
    lakes = combined[combined["FType"].isin([390, 436])].copy()

    # Named lakes above minimum area
    lakes = lakes[
        lakes["GNIS_Name"].notna()
        & (lakes["GNIS_Name"].str.strip() != "")
        & (lakes["AreaSqKm"] >= MIN_LAKE_AREA_KM2)
    ].copy()

    logger.info("Filtered to %d named lakes >= %.1f acres", len(lakes),
                MIN_LAKE_AREA_KM2 / 0.00404686)
    return lakes


# ── BWCA boundary ────────────────────────────────────────────────────────────

def load_bwca_boundary(raw_dir: Path) -> gpd.GeoDataFrame:
    candidates = sorted(raw_dir.glob("**/S_USA.Wilderness.shp"))
    if not candidates:
        raise FileNotFoundError(
            f"Wilderness boundary shapefile not found under {raw_dir}. "
            "Run 01_download_gis_data.py first."
        )

    gdf = gpd.read_file(candidates[0])
    bwca = gdf[gdf["WILDERNE_1"].str.contains("Boundary Waters", case=False, na=False)].copy()
    if bwca.empty:
        # Fallback: check other name columns
        for col in ("NAME", "WILDERNE_1", "WILD_NAME"):
            if col in gdf.columns:
                match = gdf[gdf[col].str.contains("Boundary Waters", case=False, na=False)]
                if not match.empty:
                    bwca = match.copy()
                    break
    if bwca.empty:
        raise ValueError(
            "Could not locate Boundary Waters Canoe Area in the wilderness shapefile. "
            f"Available name columns: {list(gdf.columns)}"
        )

    logger.info("Loaded BWCA boundary (%d polygon(s))", len(bwca))
    return bwca


# ── Spatial filter ───────────────────────────────────────────────────────────

def filter_lakes_in_bwca(
    lakes: gpd.GeoDataFrame,
    bwca: gpd.GeoDataFrame,
    overrides_path: Path | None = None,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Return (filtered_lakes_utm, edge_cases_df).

    If *overrides_path* points to a CSV with a ``lake_name`` column, those
    lakes are force-included even if they were previously skipped.
    """
    lakes_utm = lakes.to_crs(UTM_CRS)
    bwca_utm = bwca.to_crs(UTM_CRS)

    bwca_geom = bwca_utm.geometry.union_all()
    mask = lakes_utm.geometry.intersects(bwca_geom)
    bwca_lakes = lakes_utm[mask].copy()
    logger.info("Spatial filter: %d lakes intersect BWCA boundary", len(bwca_lakes))

    # De-duplicate by name (keep largest)
    bwca_lakes = bwca_lakes.sort_values("AreaSqKm", ascending=False)
    edge_cases: list[dict] = []
    seen: dict[str, float] = {}
    keep_idx: list = []

    for idx, row in bwca_lakes.iterrows():
        name = row["GNIS_Name"].strip()
        if name in seen:
            edge_cases.append({
                "lake_name": name,
                "reason": "duplicate_name",
                "area_sqkm": row["AreaSqKm"],
                "note": f"Kept larger instance ({seen[name]:.4f} km²)",
            })
        else:
            seen[name] = row["AreaSqKm"]
            keep_idx.append(idx)

    deduped = bwca_lakes.loc[keep_idx].copy()

    # Handle overrides (force-include lakes from a user-edited CSV)
    if overrides_path and overrides_path.is_file():
        overrides = pd.read_csv(overrides_path)
        if "lake_name" in overrides.columns:
            override_names = set(overrides["lake_name"].str.strip())
            already = set(deduped["GNIS_Name"].str.strip())
            missing = override_names - already
            if missing:
                extras = lakes_utm[lakes_utm["GNIS_Name"].str.strip().isin(missing)]
                deduped = gpd.GeoDataFrame(
                    pd.concat([deduped, extras], ignore_index=True)
                )
                logger.info("Added %d override lakes", len(extras))

    edge_df = pd.DataFrame(edge_cases)
    logger.info("After dedup: %d unique named BWCA lakes", len(deduped))
    return deduped, edge_df


# ── Export / import processed data ───────────────────────────────────────────

def export_bwca_lakes(gdf: gpd.GeoDataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf_out = gdf.to_crs("EPSG:4326")
    gdf_out.to_file(output_path, driver="GeoJSON")
    logger.info("Exported %d lakes → %s", len(gdf), output_path)


def load_processed_lakes(processed_dir: Path) -> gpd.GeoDataFrame:
    path = processed_dir / "bwca_lakes.geojson"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run 02_filter_bwca_lakes.py first."
        )
    return gpd.read_file(path).to_crs(UTM_CRS)
