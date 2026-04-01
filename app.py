#!/usr/bin/env python3
"""
BWCA Lake Shirt Designer — Streamlit management UI.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.config import (
    DATA_DIR,
    FONTS_DIR,
    OUTPUT_DIR,
    PNG_DIR,
    PRINTFUL_API_KEY,
    PROCESSED_DIR,
    RAW_DIR,
    REVIEW_DIR,
    SVG_DIR,
    get_font_path,
)

st.set_page_config(page_title="BWCA Lake Shirt Designer", layout="wide")

# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("BWCA Shirts")
    st.divider()

    # Font status
    try:
        fp = get_font_path()
        st.success(f"Font: {fp.name}")
    except FileNotFoundError:
        st.warning("No font file found")

    # Printful key status
    if PRINTFUL_API_KEY:
        st.success("Printful API key: set")
    else:
        st.warning("Printful API key: not set")

    st.divider()

    # Step status overview
    st.subheader("Pipeline Status")
    has_raw = any(RAW_DIR.glob("**/*.shp")) if RAW_DIR.exists() else False
    has_lakes = (PROCESSED_DIR / "bwca_lakes.geojson").exists()
    svg_count = len(list(SVG_DIR.glob("*.svg"))) if SVG_DIR.exists() else 0
    png_count = len(list(PNG_DIR.glob("*.png"))) if PNG_DIR.exists() else 0
    progress_csv = OUTPUT_DIR / "printful_progress.csv"
    pushed = 0
    if progress_csv.exists():
        pf = pd.read_csv(progress_csv)
        pushed = len(pf[pf["status"] == "done"])

    steps = [
        ("1. Download GIS Data", has_raw),
        ("2. Filter BWCA Lakes", has_lakes),
        (f"3. Generate Designs ({svg_count} SVG, {png_count} PNG)", svg_count > 0),
        (f"4. Printful ({pushed} pushed)", pushed > 0),
    ]
    for label, done in steps:
        icon = "[done]" if done else "[pending]"
        st.text(f"{icon}  {label}")


# ── Session state for persisting run output ──────────────────────────────────

if "last_run" not in st.session_state:
    st.session_state.last_run = None   # {"step": str, "output": str, "ok": bool}


def _run_script(script_name: str, extra_args: list[str] | None = None) -> None:
    """Run a pipeline script, stream its output live, and persist the result."""
    cmd = [sys.executable, str(ROOT / "scripts" / script_name)]
    if extra_args:
        cmd.extend(extra_args)

    container = st.empty()
    lines: list[str] = []

    with subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(ROOT)
    ) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            container.code("".join(lines[-40:]), language="text")
        proc.wait()

    ok = proc.returncode == 0
    # Persist result so it survives the next render cycle
    st.session_state.last_run = {
        "step": script_name,
        "output": "".join(lines),
        "ok": ok,
    }

    if ok:
        st.success("Done — pipeline step finished successfully.")
    else:
        st.error(f"Script exited with code {proc.returncode}")


def _show_last_run() -> None:
    """Render the stored output from the most recent run (if any)."""
    run = st.session_state.get("last_run")
    if not run:
        return
    label = f"Last run: {run['step']}"
    icon = "✔" if run["ok"] else "✖"
    with st.expander(f"{icon} {label}", expanded=not run["ok"]):
        st.code(run["output"], language="text")


# ── Tabs ─────────────────────────────────────────────────────────────────────

tab_data, tab_designs, tab_printful, tab_edge = st.tabs([
    "Data", "Designs", "Printful", "Edge Cases"
])


# ═══════════════════════════  TAB 1: DATA  ═══════════════════════════════════

with tab_data:
    st.header("GIS Data & BWCA Lakes")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Run Step 1: Download GIS Data"):
            _run_script("01_download_gis_data.py")
    with col2:
        if st.button("Run Step 2: Filter BWCA Lakes"):
            _run_script("02_filter_bwca_lakes.py")
    with col3:
        if st.button("Refresh Status"):
            st.rerun()

    _show_last_run()

    # Show lake stats + map
    geojson_path = PROCESSED_DIR / "bwca_lakes.geojson"
    if geojson_path.exists():
        import geopandas as gpd

        gdf = gpd.read_file(geojson_path)
        st.metric("Total BWCA Lakes", len(gdf))

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Avg Area (km\u00b2)", f"{gdf['AreaSqKm'].mean():.2f}")
        col_b.metric("Largest", gdf.loc[gdf["AreaSqKm"].idxmax(), "GNIS_Name"])
        col_c.metric("Smallest", gdf.loc[gdf["AreaSqKm"].idxmin(), "GNIS_Name"])

        # Folium map
        try:
            import folium
            from streamlit_folium import st_folium

            centroid = gdf.geometry.to_crs("EPSG:4326").centroid
            center_lat = centroid.y.mean()
            center_lon = centroid.x.mean()

            m = folium.Map(location=[center_lat, center_lon], zoom_start=9,
                           tiles="CartoDB positron")

            # Add lake polygons (keep only serializable columns for Folium)
            gdf_map = gdf[["GNIS_Name", "AreaSqKm", "geometry"]].to_crs("EPSG:4326")
            folium.GeoJson(
                gdf_map.to_json(),
                style_function=lambda _: {
                    "color": "#3388ff",
                    "weight": 1.5,
                    "fillOpacity": 0.3,
                },
                tooltip=folium.GeoJsonTooltip(fields=["GNIS_Name", "AreaSqKm"]),
            ).add_to(m)

            st_folium(m, width=900, height=500)
        except ImportError:
            st.info("Install folium and streamlit-folium for an interactive map.")

        # Lake list
        with st.expander("Full lake list"):
            st.dataframe(
                gdf[["GNIS_Name", "AreaSqKm"]].rename(
                    columns={"GNIS_Name": "Lake Name", "AreaSqKm": "Area (km\u00b2)"}
                ).sort_values("Lake Name").reset_index(drop=True),
                use_container_width=True,
            )
    else:
        st.info("No processed lake data yet. Run steps 1 and 2 to get started.")


# ═══════════════════════════  TAB 2: DESIGNS  ════════════════════════════════

with tab_designs:
    st.header("Shirt Designs")

    # Grey background so white lake outlines are visible against the preview tile
    st.markdown(
        "<style>[data-testid='stImage'] img { background-color: #3c3c3c; }</style>",
        unsafe_allow_html=True,
    )

    dcol1, dcol2, dcol3 = st.columns([3, 1, 1])
    with dcol1:
        search = st.text_input("Search by lake name", key="design_search")
    with dcol2:
        if st.button("Generate Sample (5 lakes)"):
            _run_script("03_generate_designs.py", ["--sample"])
    with dcol3:
        if st.button("Generate All Designs"):
            _run_script("03_generate_designs.py")

    _show_last_run()

    png_files = sorted(PNG_DIR.glob("*.png")) if PNG_DIR.exists() else []

    if search:
        png_files = [p for p in png_files if search.lower() in p.stem.lower()]

    if png_files:
        st.text(f"Showing {len(png_files)} designs")

        # 3-column grid
        cols = st.columns(3)
        for i, png_path in enumerate(png_files):
            with cols[i % 3]:
                st.image(str(png_path), use_container_width=True)
                lake_name = png_path.stem

                # Aspect badge
                svg_path = SVG_DIR / f"{lake_name}.svg"
                st.caption(lake_name)

                if st.button("Regenerate", key=f"regen_{i}"):
                    _run_script("03_generate_designs.py", ["--lake", lake_name])
    else:
        st.info("No designs generated yet. Run step 3.")


# ═══════════════════════════  TAB 3: PRINTFUL  ═══════════════════════════════

with tab_printful:
    st.header("Printful Upload")

    progress_path = OUTPUT_DIR / "printful_progress.csv"

    push_limit = st.number_input(
        "Limit (0 = all)", min_value=0, value=1, step=1,
        help="Set to 1 to test a single design, or 0 to push all remaining designs.",
    )
    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        if st.button("Push to Printful (dry run)"):
            extra = ["--dry-run"]
            if push_limit > 0:
                extra += ["--limit", str(push_limit)]
            _run_script("04_push_to_printful.py", extra)
    with pcol2:
        if st.button("Push Single Design"):
            _run_script("04_push_to_printful.py", ["--single"])
    with pcol3:
        if st.button("Push to Printful (live)"):
            extra = []
            if push_limit > 0:
                extra += ["--limit", str(push_limit)]
            _run_script("04_push_to_printful.py", extra)

    _show_last_run()

    if progress_path.exists():
        df = pd.read_csv(progress_path)

        # Summary metrics
        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Done", len(df[df["status"] == "done"]))
        mc2.metric("Pending", len(df[df["status"] == "pending"]))
        mc3.metric("Errors", len(df[df["status"] == "error"]))

        # Colour-coded table
        def _colour_status(val):
            colours = {"done": "#d4edda", "pending": "#fff3cd", "error": "#f8d7da"}
            return f"background-color: {colours.get(val, '')}"

        styled = df.style.map(_colour_status, subset=["status"])
        st.dataframe(styled, use_container_width=True)

        # Mockup previews
        with_mockups = df[df["mockup_url"].notna()]
        if not with_mockups.empty:
            st.subheader("Mockup Previews")
            mcols = st.columns(3)
            for i, (_, row) in enumerate(with_mockups.head(9).iterrows()):
                with mcols[i % 3]:
                    st.image(row["mockup_url"], caption=row["lake_name"])
    else:
        st.info("No Printful progress data yet. Run step 4.")


# ═══════════════════════════  TAB 4: EDGE CASES  ═════════════════════════════

with tab_edge:
    st.header("Edge Cases & Review")

    edge_path = REVIEW_DIR / "edge_cases.csv"
    gen_err_path = REVIEW_DIR / "generation_errors.csv"

    if edge_path.exists():
        st.subheader("Duplicate / Skipped Lakes")
        edge_df = pd.read_csv(edge_path)
        st.dataframe(edge_df, use_container_width=True)

        csv_bytes = edge_df.to_csv(index=False).encode()
        st.download_button("Download CSV", csv_bytes, "edge_cases.csv", "text/csv")

        # Override support
        st.subheader("Force-Include Lakes")
        st.caption(
            "Check lakes below and save to data/overrides.csv. "
            "Re-run step 2 to include them."
        )
        overrides_path = DATA_DIR / "overrides.csv"
        existing_overrides: set[str] = set()
        if overrides_path.exists():
            existing_overrides = set(pd.read_csv(overrides_path)["lake_name"])

        selected: list[str] = []
        for _, row in edge_df.iterrows():
            name = row["lake_name"]
            checked = st.checkbox(
                f"{name} ({row['reason']})",
                value=name in existing_overrides,
                key=f"override_{name}",
            )
            if checked:
                selected.append(name)

        if st.button("Save Overrides"):
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({"lake_name": selected}).to_csv(overrides_path, index=False)
            st.success(f"Saved {len(selected)} overrides to {overrides_path}")

    else:
        st.info("No edge case data. Run step 2 first.")

    if gen_err_path.exists():
        st.subheader("Design Generation Errors")
        err_df = pd.read_csv(gen_err_path)
        st.dataframe(err_df, use_container_width=True)
