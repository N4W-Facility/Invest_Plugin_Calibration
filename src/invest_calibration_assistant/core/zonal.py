# -*- coding: utf-8 -*-
"""Zonal aggregation of an InVEST output raster over the calibration watersheds,
plus small array helpers.

``ismember`` is the MATLAB-equivalent used throughout the original engine to line
up simulated ``ws_id`` order with the observed-data table; it is copied verbatim.

``read_watershed_table`` replaces the old ``simpledbf.Dbf5`` dependency: SDR (and
the other models) write a ``watershed_results_*.csv`` next to the shapefile, and
if that is ever missing we fall back to reading the vector attributes with
pyogrio. Either way no pip-only DBF reader is needed.
"""

from __future__ import annotations

import os

import numpy as np


# ---------------------------------------------------------------------------
# ismember  (verbatim from Spotpy_InVEST.py)
# ---------------------------------------------------------------------------
def ismember(a_vec, b_vec, method=None):
    """MATLAB-equivalent ``ismember``. Returns ``(mask_in_a, index_into_b)``."""
    a_vec, b_vec = _settypes(a_vec, b_vec)
    if method is None:
        Iloc, idx = _compute(a_vec, b_vec)
    elif method == "rows":
        if a_vec.shape[0] != b_vec.shape[0]:
            raise Exception("Error: Input matrices should have same number of columns.")
        out = list(map(lambda x, y: _compute(x, y), a_vec, b_vec))
        Iloc, idx = list(zip(*out))
    else:
        Iloc, idx = None, None
    return (Iloc, idx)


def _settypes(a_vec, b_vec):
    if "pandas" in str(type(a_vec)):
        a_vec.values[np.where(a_vec.values == None)] = "NaN"  # noqa: E711
        a_vec = np.array(a_vec.values)
    if "pandas" in str(type(b_vec)):
        b_vec.values[np.where(b_vec.values == None)] = "NaN"  # noqa: E711
        b_vec = np.array(b_vec.values)
    if isinstance(a_vec, list):
        a_vec = np.array(a_vec)
    if isinstance(b_vec, list):
        b_vec = np.array(b_vec)
    return a_vec, b_vec


def _compute(a_vec, b_vec):
    bool_ind = np.isin(a_vec, b_vec)
    common = a_vec[bool_ind]
    [common_unique, common_inv] = np.unique(common, return_inverse=True)
    [b_unique, b_ind] = np.unique(b_vec, return_index=True)
    common_ind = b_ind[np.isin(b_unique, common_unique, assume_unique=True)]
    return bool_ind, common_ind[common_inv]


# ---------------------------------------------------------------------------
# zonal statistics  (behaviour preserved from Spotpy_InVEST.calculate_zonal_stats)
# ---------------------------------------------------------------------------
def calculate_zonal_stats(shapefile_path, raster_path, output_path_shp,
                          ws_id="ws_id", Suffix=""):  # noqa: N803 - legacy kw name
    """Zonal stats of ``raster_path`` per polygon of ``shapefile_path``.

    Returns a plain ``pandas.DataFrame`` with columns
    ``mean, min, max, median, sum`` plus ``ws_id``. Also writes
    ``Zonal_<Suffix>.shp`` into ``output_path_shp`` (kept for parity with the
    Workbench plugin's output folder layout).
    """
    import geopandas as gpd  # noqa: PLC0415
    import pandas as pd  # noqa: PLC0415
    import rasterio  # noqa: PLC0415
    from rasterstats import zonal_stats  # noqa: PLC0415

    try:
        polygons = gpd.read_file(shapefile_path, engine="pyogrio")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Could not read watershed vector: {e}")

    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        nodata_value = (
            src.nodatavals[0]
            if src.nodatavals and src.nodatavals[0] is not None
            else None
        )
    if polygons.crs != raster_crs:
        polygons = polygons.to_crs(raster_crs)

    results = []
    for uid in polygons[ws_id].unique():
        subset = polygons[polygons[ws_id] == uid]
        stats = zonal_stats(
            subset, raster_path,
            stats=["mean", "min", "max", "median", "sum"],
            nodata=nodata_value, geojson_out=True,
        )
        stats_gdf = gpd.GeoDataFrame.from_features(stats)
        stats_gdf[ws_id] = uid
        results.append(stats_gdf)

    final = gpd.GeoDataFrame(pd.concat(results, ignore_index=True))
    try:
        final.to_file(os.path.join(output_path_shp, f"Zonal_{Suffix}.shp"),
                      driver="ESRI Shapefile")
    except Exception:  # noqa: BLE001 - the sidecar shapefile is a convenience, not critical
        pass
    return pd.DataFrame(final)


# ---------------------------------------------------------------------------
# watershed results table  (replaces simpledbf.Dbf5)
# ---------------------------------------------------------------------------
def read_watershed_table(out_dir: str, basename: str):
    """Read an InVEST ``watershed_results_*`` table as a DataFrame.

    Prefers the ``.csv`` InVEST writes; falls back to the ``.dbf``/``.shp``
    attribute table via pyogrio.
    """
    import pandas as pd  # noqa: PLC0415

    csv = os.path.join(out_dir, basename + ".csv")
    if os.path.isfile(csv):
        return pd.read_csv(csv)
    for ext in (".dbf", ".shp", ".gpkg"):
        cand = os.path.join(out_dir, basename + ext)
        if os.path.isfile(cand):
            import pyogrio  # noqa: PLC0415

            return pyogrio.read_dataframe(cand, read_geometry=False)
    raise FileNotFoundError(
        f"No watershed results table found for {basename!r} in {out_dir}"
    )
