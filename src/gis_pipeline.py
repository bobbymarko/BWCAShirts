"""Load, filter, and export GIS data for BWCA lakes."""

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.ops import unary_union

from .config import MIN_LAKE_AREA_KM2, UTM_CRS

logger = logging.getLogger(__name__)

# Buffer added around the BWCA legal boundary before spatial filtering.
# This ensures border lakes (Gunflint, North Lake, Saganaga, etc.) are
# included even when the BWCA boundary only covers the US portion of the lake.
# Lake geometries are NEVER clipped — only used as an inclusion filter.
BWCA_BUFFER_METRES = 3000  # 3 km


# ── NHD waterbody loading ────────────────────────────────────────────────────

def _find_nhd_waterbody_shapefiles(raw_dir: Path) -> list[Path]:
    """Locate NHDWaterbody shapefiles inside extracted zip directories."""
    results = sorted(raw_dir.glob("**/NHDWaterbody*.shp"))
    if not results:
        results = sorted(raw_dir.glob("**/*aterbody*.shp"))
    return results


def _resolve_col(gdf: gpd.GeoDataFrame, candidates: list[str], label: str) -> str:
    for c in candidates:
        if c in gdf.columns:
            return c
    raise KeyError(
        f"Could not find {label} column. Tried {candidates}. "
        f"Available: {list(gdf.columns)}"
    )


def load_nhd_waterbodies(raw_dir: Path) -> gpd.GeoDataFrame:
    shp_files = _find_nhd_waterbody_shapefiles(raw_dir)
    if not shp_files:
        raise FileNotFoundError(
            f"No NHD waterbody shapefiles found under {raw_dir}. "
            "Run 01_download_gis_data.py first."
        )

    frames = []
    for shp in shp_files:
        gdf = gpd.read_file(shp)
        frames.append(gdf)
        logger.info("Loaded %d waterbodies from %s", len(gdf), shp.name)

    combined = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True))
    logger.info("Columns in NHD data: %s", list(combined.columns))

    # Resolve column names (vary between NHD editions)
    name_col  = _resolve_col(combined, ["GNIS_Name", "GNIS_NA", "gnis_name", "NAME"], "lake name")
    id_col    = _resolve_col(combined, ["GNIS_ID", "GNIS_Id", "gnis_id", "Permanent_Identifier"], "ID")
    ftype_col = _resolve_col(combined, ["FType", "FTYPE", "ftype"], "feature type")
    area_col  = _resolve_col(combined, ["AreaSqKm", "AREASQKM", "areasqkm", "Shape_Area"], "area")

    # Deduplicate by permanent identifier if available; otherwise fall back to
    # gnis_id but only for named features — unnamed features all share a blank
    # gnis_id and would incorrectly collapse to a single row.
    perm_col_candidates = ["permanent_", "Permanent_Identifier", "PERMANENT_"]
    perm_col = next((c for c in perm_col_candidates if c in combined.columns), None)
    if perm_col:
        combined = combined.drop_duplicates(subset=[perm_col], keep="first")
    else:
        # Only dedup named features by gnis_id; keep all unnamed rows
        named_mask = combined[id_col].notna() & (combined[id_col] != "")
        combined = pd.concat([
            combined[named_mask].drop_duplicates(subset=[id_col], keep="first"),
            combined[~named_mask],
        ], ignore_index=True)

    # Lakes and ponds (390) and reservoirs (436) only
    lakes = combined[combined[ftype_col].isin([390, 436])].copy()

    # Normalize column names for downstream code
    lakes = lakes.rename(columns={
        name_col: "GNIS_Name",
        id_col:   "GNIS_ID",
        ftype_col: "FType",
        area_col:  "AreaSqKm",
    })

    # Blank out whitespace-only names so they count as unnamed
    lakes["GNIS_Name"] = lakes["GNIS_Name"].fillna("").str.strip()

    logger.info("Loaded %d lake/pond/reservoir features (named + unnamed)",
                len(lakes))
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
    bwca = gpd.GeoDataFrame()
    for col in ("WILDERNE_1", "NAME", "WILD_NAME"):
        if col in gdf.columns:
            match = gdf[gdf[col].str.contains("Boundary Waters", case=False, na=False)]
            if not match.empty:
                bwca = match.copy()
                break

    if bwca.empty:
        raise ValueError(
            "Could not locate Boundary Waters Canoe Area in the wilderness shapefile. "
            f"Available columns: {list(gdf.columns)}"
        )

    logger.info("Loaded BWCA boundary (%d polygon(s))", len(bwca))
    return bwca


# ── Border-lake merging ───────────────────────────────────────────────────────

# NHD splits border lakes into separate MN and Canadian polygons.
# Two features with the same name are considered halves of the same lake
# (and merged) when they are within this distance of each other.
# Features further apart are genuinely separate lakes → keep with _2 suffix.
MERGE_SEAM_METRES = 50  # small buffer to close the border-line gap


def _merge_split_lakes(lakes: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    For each group of same-name features, union those that are adjacent
    (within MERGE_SEAM_METRES) into a single seamless polygon.

    A tiny buffer–union–unbuffer trick closes the shared boundary line
    that NHD leaves between the two halves so no seam appears in the SVG.
    """
    merged_rows: list[pd.Series] = []

    for name, group in lakes.groupby("GNIS_Name"):
        if len(group) == 1:
            merged_rows.append(group.iloc[0])
            continue

        # Cluster features that are close enough to be the same lake
        geoms = list(group.geometry)
        n = len(geoms)
        parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(n):
            for j in range(i + 1, n):
                if geoms[i].distance(geoms[j]) <= MERGE_SEAM_METRES:
                    pi, pj = find(i), find(j)
                    if pi != pj:
                        parent[pi] = pj

        clusters: dict[int, list[int]] = {}
        for i in range(n):
            root = find(i)
            clusters.setdefault(root, []).append(i)

        for cluster_indices in clusters.values():
            cluster_geoms = [geoms[i] for i in cluster_indices]
            base_row = group.iloc[
                max(cluster_indices, key=lambda i: geoms[i].area)
            ].copy()

            if len(cluster_indices) == 1:
                merged_rows.append(base_row)
            else:
                # Small buffer closes the shared border line; negative buffer
                # restores the original shoreline shape.
                merged_geom = unary_union(
                    [g.buffer(MERGE_SEAM_METRES) for g in cluster_geoms]
                ).buffer(-MERGE_SEAM_METRES)
                base_row["geometry"] = merged_geom
                base_row["AreaSqKm"] = merged_geom.area / 1e6
                logger.info(
                    "Merged %d NHD features → '%s' (border lake)",
                    len(cluster_indices), name,
                )
                merged_rows.append(base_row)

    result = gpd.GeoDataFrame(merged_rows, crs=lakes.crs).reset_index(drop=True)
    logger.info("After merging border halves: %d lake features", len(result))
    return result


# ── Attach unnamed adjacent features ─────────────────────────────────────────

# Tiny buffer used to catch features that nearly touch (floating-point seam).
TOUCH_BUFFER_METRES = 5


def _attach_unnamed_adjacent(
    named: gpd.GeoDataFrame,
    unnamed: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    """
    For each named lake, find any touching unnamed polygons and union them in.

    This handles border lakes where the Canadian portion exists in the NHD
    as an unnamed polygon adjacent to the named MN polygon.
    """
    if unnamed.empty:
        return named

    unnamed_sindex = unnamed.sindex
    new_geoms = list(named.geometry)
    attached_total = 0

    for i, (_, row) in enumerate(named.iterrows()):
        # Slightly expand the search envelope to catch zero-gap touches
        search_geom = row.geometry.buffer(TOUCH_BUFFER_METRES)

        candidate_idx = list(unnamed_sindex.intersection(search_geom.bounds))
        if not candidate_idx:
            continue

        candidates = unnamed.iloc[candidate_idx]
        touching = candidates[candidates.geometry.intersects(search_geom)]
        if touching.empty:
            continue

        all_geoms = [row.geometry] + list(touching.geometry)
        # Buffer/unbuffer trick closes the shared boundary line
        merged = unary_union(
            [g.buffer(MERGE_SEAM_METRES) for g in all_geoms]
        ).buffer(-MERGE_SEAM_METRES)
        new_geoms[i] = merged
        attached_total += len(touching)

    if attached_total:
        logger.info(
            "Attached %d unnamed adjacent polygon(s) to named lakes "
            "(border lake Canadian halves etc.)",
            attached_total,
        )

    result = named.copy()
    result["geometry"] = new_geoms
    result["AreaSqKm"] = result.geometry.area / 1e6
    return result


# ── Spatial filter + name disambiguation ─────────────────────────────────────

def filter_lakes_in_bwca(
    lakes: gpd.GeoDataFrame,
    bwca: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    """
    Include any lake whose geometry intersects the buffered BWCA boundary.
    Lake geometries are returned unmodified — no clipping occurs.

    Returns (filtered_lakes_utm, edge_cases_df).
    """
    lakes_utm = lakes.to_crs(UTM_CRS)
    bwca_utm  = bwca.to_crs(UTM_CRS)
    bwca_geom = bwca_utm.geometry.union_all().buffer(BWCA_BUFFER_METRES)

    # Split into named and unnamed before the spatial filter so we can
    # attach unnamed Canadian-side polygons before deciding what to keep.
    is_named = lakes_utm["GNIS_Name"] != ""
    named_utm   = lakes_utm[is_named & (lakes_utm["AreaSqKm"] >= MIN_LAKE_AREA_KM2)].copy()
    unnamed_utm = lakes_utm[~is_named].copy()

    # Filter named lakes to BWCA region first
    named_utm = named_utm[named_utm.geometry.intersects(bwca_geom)].copy()
    logger.info(
        "In BWCA region: %d named lakes; using all %d unnamed polygons for border attachment",
        len(named_utm), len(unnamed_utm),
    )

    # Attach touching unnamed polygons (Canadian lake halves) into their
    # named neighbours BEFORE the same-name merge and dedup steps.
    # We intentionally do NOT pre-filter unnamed by BWCA boundary — the
    # Canadian halves of border lakes lie outside that boundary and would
    # be dropped before they could be attached.
    named_utm = _attach_unnamed_adjacent(named_utm, unnamed_utm)

    # Merge same-name features that are adjacent (e.g. two NHD records
    # for the same named lake on either side of a state boundary)
    named_utm = _merge_split_lakes(named_utm)

    bwca_lakes = named_utm
    logger.info(
        "After attachment + merge: %d lakes",
        len(bwca_lakes),
    )

    # Disambiguate duplicate names: largest keeps original name,
    # smaller instances get _2, _3 … suffixes. All are kept.
    bwca_lakes = bwca_lakes.sort_values("AreaSqKm", ascending=False).copy()
    edge_cases: list[dict] = []
    name_count: dict[str, int] = {}
    new_names: list[str] = []

    for _, row in bwca_lakes.iterrows():
        name = row["GNIS_Name"].strip()
        count = name_count.get(name, 0)
        if count == 0:
            new_names.append(name)
        else:
            disambig = f"{name} _{count + 1}"
            new_names.append(disambig)
            edge_cases.append({
                "lake_name": disambig,
                "original_name": name,
                "reason": "duplicate_name",
                "area_sqkm": row["AreaSqKm"],
                "note": f"Renamed from '{name}' (smaller instance #{count + 1})",
            })
        name_count[name] = count + 1

    bwca_lakes = bwca_lakes.copy()
    bwca_lakes["GNIS_Name"] = new_names

    edge_df = pd.DataFrame(edge_cases)
    logger.info(
        "Total BWCA lakes: %d (%d disambiguated with _2/_3 suffix)",
        len(bwca_lakes), len(edge_cases),
    )
    return bwca_lakes, edge_df


# ── Export / import ───────────────────────────────────────────────────────────

def export_bwca_lakes(gdf: gpd.GeoDataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gdf_out = gdf[["GNIS_Name", "AreaSqKm", "geometry"]].to_crs("EPSG:4326")
    gdf_out.to_file(output_path, driver="GeoJSON")
    logger.info("Exported %d lakes → %s", len(gdf), output_path)


def load_processed_lakes(processed_dir: Path) -> gpd.GeoDataFrame:
    path = processed_dir / "bwca_lakes.geojson"
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Run 02_filter_bwca_lakes.py first."
        )
    return gpd.read_file(path).to_crs(UTM_CRS)
