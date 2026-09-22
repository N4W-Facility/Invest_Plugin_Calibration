# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
# InVEST - Version 3.15.1 (update July 2025)
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel
# Email         : jonathan.nogales@tnc.org
# Date          : October, 2024
#
# -------------------------------------------------------------------------
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or option) any
# later version. This program is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
# ee the GNU General Public License for more details. You should have
# received a copy of the GNU General Public License along with this program.
# If not, see http://www.gnu.org/licenses/.
# -------------------------------------------------------------------------
#                            DESCRIPTION
# -------------------------------------------------------------------------
# This code allow

# -------------------------------------------------------------------------
#                             REFERENCES
# -------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------------------------------------
# Package
# ----------------------------------------------------------------------------------------------------------------------
import os, sys
import spotpy
import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import gdal, ogr
from osgeo.gdalconst import *
import rasterio
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.lines import Line2D
# Tipografía tipo LaTeX (Computer Modern) para texto y matemáticas, sin
# depender de una instalación de TeX ni de fuentes externas al sistema.
rcParams['font.family'] = 'serif'
rcParams['font.serif']  = ['cmr10', 'DejaVu Serif']
rcParams['mathtext.fontset'] = 'cm'
rcParams['axes.unicode_minus'] = False
from rasterstats import zonal_stats

gdal.PushErrorHandler('CPLQuietErrorHandler')

def CreateFolder(dir):
    try:
        os.makedirs(dir)
    except FileExistsError:
        # directory already exists
        pass

def Factor_BioTable(PathBioTable, Params, UserData):
    # --------------------------------------------------------------------------------------------------------------
    # Read Biophycial Table
    # --------------------------------------------------------------------------------------------------------------
    Table = pd.read_csv(PathBioTable, encoding='latin-1')

    # Anual Water Yield
    if UserData['Status_AWY']:
        # --------------------------------------------------------------------------------------------------------------
        # Afectación de parámetros Kc en la tabla biofísica
        # --------------------------------------------------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
        Values = round(Table['Kc'] * Params['Factor-Kc'], 2)
        # Si el factor hace que el Kc sea mayor que 1.2, limita el valor a 1.2
        Values[Values >= 1.2] = 1.2
        # Asigna los valores de Kc modificados a la tabla
        Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc'] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Seasonal Water Yield
    if UserData['Status_SWY']:
        # --------------------------------------------------------------------------------------------------------------
        # Afectacion de parametros Kc en la tabla biofisica
        # --------------------------------------------------------------------------------------------------------------
        for ij in range(1, 13):
            # Aplica el factor multiplicador a los valores de carga y redondea a 3 decimales
            Values = round(Table['Kc_' + str(ij)] * round(Params['Factor-Kc_m'], 2), 2)
            # Si el factor hace que el Kc sea mayor que 1.2, limita el valor a 1.2
            Values[Values >= 1.2] = 1.2
            # Asigna los valores de Kc modificados a la tabla
            Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc_' + str(ij)] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Sediment Delivery Ratio
    if UserData['Status_SDR'] == 1:
        # ---------------------------------------------------------------------
        # Afectacion de parametro de factor de cobertura en la tabla biofisica
        # ---------------------------------------------------------------------
        # Aplica el factor multiplicador a los valores del factor C y redondea a 5 decimales
        Values = round(Table['usle_c'] * round(Params['Factor-C'], 2), 5)
        # Si el factor hace que el C sea mayor que 1, limita el valor a 1
        Values[Values > 1] = 1
        # Asigna los valores de C modificados a la tabla
        Table.loc[Table['Status_Cal_C'] == 1, 'usle_c'] = Values.loc[Table['Status_Cal_C'] == 1]

        # Aplica el factor multiplicador a los valores del factor P y redondea a 2 decimales
        Values = round(Table['usle_p'] * round(Params['Factor-P'], 2), 2)
        # Si el factor hace que el P sea mayor que 1, limita el valor a 1
        Values[Values > 1] = 1
        # Asigna los valores de C modificados a la tabla
        Table.loc[Table['Status_Cal_P'] == 1, 'usle_p'] = Values.loc[Table['Status_Cal_P'] == 1]

    # Nutrient Delivery Ratio
    if (UserData['Status_NDR_N'] == 1):
        Values = round(Table['load_n'] * Params['Factor_Load_N'], 3)
        Table.loc[Table['Status_Cal_Load_N'] == 1, 'load_n'] = Values.loc[Table['Status_Cal_Load_N'] == 1]

        Values = round(Table['eff_n'] * Params['Factor_Eff_N'], 2)
        Table.loc[Table['Status_Cal_Eff_N'] == 1, 'eff_n'] = Values.loc[Table['Status_Cal_Eff_N'] == 1]

    if (UserData['Status_NDR_P'] == 1):
        Values = round(Table['load_p'] * Params['Factor_Load_P'], 3)
        Table.loc[Table['Status_Cal_Load_P'] == 1, 'load_p'] = Values.loc[Table['Status_Cal_Load_P'] == 1]

        Values = round(Table['eff_p'] * Params['Factor_Eff_P'], 2)
        Table.loc[Table['Status_Cal_Eff_P'] == 1, 'eff_p'] = Values.loc[Table['Status_Cal_Eff_P'] == 1]

    # Carbons
    # if UserData['Status_CO2'] == 1:
    #    print('')

    return Table

def Cal_FunObj(Obs, Sim, NameFunObj):

    if NameFunObj == "Mean Square Error (MSE)":
        return spotpy.objectivefunctions.mse(Obs, Sim)
    elif NameFunObj == "Mean Absolute Error (MAE)":
        return spotpy.objectivefunctions.mae(Obs, Sim)
    elif NameFunObj == "Root Mean Square Error (RMSE)":
        return spotpy.objectivefunctions.rmse(Obs, Sim)
    elif NameFunObj == "Relative Root Mean Squared Error (RRMSE)":
        return spotpy.objectivefunctions.rrmse(Obs, Sim)

# --------------------------------------------------------------------------
# Calibration plots
# --------------------------------------------------------------------------
# Shared visual style for all calibration figures:
#   - Dotty plots: light gray points with a darker gray edge (clean/modern look).
#   - Best-fit parameter: highlighted in wine red.
_DOT_FACE   = '#D9D9D9'   # light gray fill
_DOT_EDGE   = '#8C8C8C'   # darker gray edge
_BEST_COLOR = '#7B1E24'   # wine red (vinotinto)
_REF_COLOR  = [0.8, 0.8, 0.8]

def _style_axis(ax, fontsize=16):
    """Clean, modern panel style shared by every calibration plot."""
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#595959')
    ax.spines['bottom'].set_color('#595959')
    ax.grid(True, linestyle=':', linewidth=0.7, color='#BFBFBF', alpha=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=fontsize - 3, colors='#404040')

# Per-model plot configuration: unit label, time conversion factor (only AWY
# reports Obs/Sim/Metric in per-second and needs converting to per-year),
# and the (result key, axis label) pairs in the same column order used by
# each model's EVALUATIONS/*_Metric_{Suffix}.csv file.
_MODEL_PLOT_CONFIG = {
    'AWY': {
        'unit': r'$(\mathrm{m}^3/\mathrm{s})$',
        'time_scale': 1 / (3600 * 24 * 365),
        'params': [
            ('Z', r'$Z$'),
            ('Factor-Kc', r'Factor$_{K_c}$'),
        ],
    },
    'SWY': {
        'unit': r'$(mm)$',
        'time_scale': 1,
        'params': [
            ('Alpha', r'$\alpha$'),
            ('Beta', r'$\beta$'),
            ('Gamma', r'$\gamma$'),
            ('Factor-Kc_m', r'Factor$_{K_c}$'),
        ],
    },
    'SDR': {
        'unit': r'$(ton/year)$',
        'time_scale': 1,
        'params': [
            ('sdr_max', r'SDR$_{max}$'),
            ('Borselli-K_SDR', r'$K$'),
            ('IC0', r'IC$_{0}$'),
            ('L_max', r'L$_{max}$'),
            ('Factor-C', r'Factor$_{C}$'),
            ('Factor-P', r'Factor$_{P}$'),
        ],
    },
    'NDR_N': {
        'unit': r'$(kg/year)$',
        'time_scale': 1,
        'params': [
            ('SubCri_Len_N', r'SubCri$_{Len_N}$'),
            ('Sub_Eff_N', r'Sub$_{Eff_N}$'),
            ('Borselli-K_NDR', r'Borselli$_{K}$'),
            ('Factor_Load_N', r'Factor$_{Load_N}$'),
            ('Factor_Eff_N', r'Factor$_{Eff_N}$'),
        ],
    },
    'NDR_P': {
        'unit': r'$(kg/year)$',
        'time_scale': 1,
        'params': [
            ('SubCri_Len_P', r'SubCri$_{Len_P}$'),
            ('Sub_Eff_P', r'Sub$_{Eff_P}$'),
            ('Borselli-K_NDR', r'Borselli$_{K}$'),
            ('Factor_Load_P', r'Factor$_{Load_P}$'),
            ('Factor_Eff_P', r'Factor$_{Eff_P}$'),
        ],
    },
}

def _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, ModelName):

    cfg         = _MODEL_PLOT_CONFIG[ModelName]
    unit        = cfg['unit']
    time_scale  = cfg['time_scale']
    param_keys, param_labels = zip(*cfg['params'])
    n_params    = len(param_keys)

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :n_params]
    Metric      = Tmp[:, n_params] * time_scale

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric), NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0] * time_scale
    Obs         = Obs.reshape(NGauges, 1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric), len(Sim) // len(Metric))
    Sim         = Sim.transpose() * time_scale

    # Best Parameters
    # Metric ya viene con FactorMetric aplicado (FactorMetric*RMSE), por lo que
    # volver a multiplicar por FactorMetric antes de comparar recupera el RMSE
    # real, sin importar si el algoritmo internamente maximiza (DDS) o minimiza
    # (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(param_keys, BestParams))
    BestAREM        = FactorMetric * Metric[id_min]
    Metric          = FactorMetric * Metric

    # Grid sized to the exact number of panels needed (1 Obs-vs-Sim + 1 per
    # parameter), so no plot ever has empty/unused axes.
    n_axes = 1 + n_params
    n_cols = 3 if n_axes <= 6 else 4
    n_rows = -(-n_axes // n_cols)  # ceil division
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4.5 * n_rows))
    axes = np.array(axes).reshape(-1)
    for extra_ax in axes[n_axes:]:
        fig.delaxes(extra_ax)

    # Obs vs Sim
    ax = axes[0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=_REF_COLOR, zorder=1)
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=_DOT_EDGE, facecolor=_DOT_FACE, alpha=0.9, linewidth=1.2, zorder=2)
    ax.set_xlabel(f'Observed {unit}', fontsize=16)
    ax.set_ylabel(f'Simulated {unit}', fontsize=16)
    ax.set_title(f'{NameMetric} = {round(BestAREM, 2)} {unit}', fontsize=16, pad=10)
    _style_axis(ax)

    # Dotty plots, one per calibrated parameter
    for i, label in enumerate(param_labels):
        ax = axes[1 + i]
        ax.scatter(Params[:, i], Metric, s=30, edgecolor=_DOT_EDGE, facecolor=_DOT_FACE, alpha=0.6, linewidth=0.8, zorder=2)
        ax.scatter(BestParams[i], BestAREM, s=60, color=_BEST_COLOR, edgecolor='black', linewidth=0.6, zorder=3)
        ax.set_xlabel(label, fontsize=16)
        ax.set_ylabel(f'{NameMetric} {unit}', fontsize=16)
        ax.set_title(f'{label} = {BestParams[i]:.4g}', fontsize=16, pad=10)
        _style_axis(ax)

    fig.patch.set_facecolor('white')

    # Legend clarifying what the wine-red marker means (avoids any ambiguity
    # about which point is the best-fit parameter set).
    legend_handles = [
        Line2D([0], [0], marker='o', linestyle='', markersize=9,
               markerfacecolor=_DOT_FACE, markeredgecolor=_DOT_EDGE, label='Simulations'),
        Line2D([0], [0], marker='o', linestyle='', markersize=9,
               markerfacecolor=_BEST_COLOR, markeredgecolor='black', label='Best fit'),
    ]
    fig.legend(handles=legend_handles, loc='lower center', ncol=2, frameon=False,
               fontsize=14, bbox_to_anchor=(0.5, -0.05))

    # Save Figure
    # rect reserves the bottom margin for the legend so it doesn't crowd the
    # x-axis titles of the last row of panels.
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_{ModelName}_{Suffix}.jpg')
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    plt.savefig(FileName, dpi=200, facecolor='white', bbox_inches='tight')
    plt.close()

    return BestParamsDict

def Plot_AWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'AWY')

def Plot_SWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'SWY')

def Plot_SDR(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'SDR')

def Plot_NDR_N(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'NDR_N')

def Plot_NDR_P(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'NDR_P')

# --------------------------------------------------------------------------
# Name        : ismember.py
# Author      : E.Taskesen
# Contact     : erdogan@gmail.com
# --------------------------------------------------------------------------
# %% ismember
def ismember(a_vec, b_vec, method=None):
    """

    Description
    -----------
    MATLAB equivalent ismember function
    [LIA,LOCB] = ISMEMBER(A,B) also returns an array LOCB containing the
    lowest absolute index in B for each element in A which is a member of
    B and 0 if there is no such index.
    Parameters
    ----------
    a_vec : list or array
    b_vec : list or array
    method : None or 'rows' (default: None).
        rows can be used for row-wise matrice comparison.
    Returns an array containing logical 1 (true) where the data in A is found
    in B. Elsewhere, the array contains logical 0 (false)
    -------
    Tuple

    Example
    -------
    a_vec = np.array([1,2,3,None])
    b_vec = np.array([4,1,2])
    Iloc,idx = ismember(a_vec,b_vec)
    a_vec[Iloc] == b_vec[idx]

    """
    # Set types
    a_vec, b_vec = _settypes(a_vec, b_vec)

    # Compute
    if method is None:
        Iloc, idx = _compute(a_vec, b_vec)
    elif method == 'rows':
        if a_vec.shape[0] != b_vec.shape[0]: raise Exception(
            'Error: Input matrices should have same number of columns.')
        # Compute row-wise over the matrices
        out = list(map(lambda x, y: _compute(x, y), a_vec, b_vec))
        # Unzipping
        Iloc, idx = list(zip(*out))
    else:
        Iloc, idx = None, None

    return (Iloc, idx)


# %% Compute
def _settypes(a_vec, b_vec):
    if 'pandas' in str(type(a_vec)):
        a_vec.values[np.where(a_vec.values == None)] = 'NaN'
        a_vec = np.array(a_vec.values)
    if 'pandas' in str(type(b_vec)):
        b_vec.values[np.where(b_vec.values == None)] = 'NaN'
        b_vec = np.array(b_vec.values)
    if isinstance(a_vec, list):
        a_vec = np.array(a_vec)
        # a_vec[a_vec==None]='NaN'
    if isinstance(b_vec, list):
        b_vec = np.array(b_vec)
        # b_vec[b_vec==None]='NaN'

    return a_vec, b_vec


# %% Compute
def _compute(a_vec, b_vec):
    bool_ind = np.isin(a_vec, b_vec)
    common = a_vec[bool_ind]
    [common_unique, common_inv] = np.unique(common, return_inverse=True)
    [b_unique, b_ind] = np.unique(b_vec, return_index=True)
    common_ind = b_ind[np.isin(b_unique, common_unique, assume_unique=True)]

    return bool_ind, common_ind[common_inv]


"""
Zonal Statistics
Vector-Raster Analysis
Copyright 2013 Matthew Perry
Usage:
  zonal_stats.py VECTOR RASTER
  zonal_stats.py -h | --help
  zonal_stats.py --version
Options:
  -h --help     Show this screen.
  --version     Show version.
"""
def bbox_to_pixel_offsets(gt, bbox):
    originX = gt[0]
    originY = gt[3]
    pixel_width = gt[1]
    pixel_height = gt[5]
    x1 = int((bbox[0] - originX) / pixel_width)
    x2 = int((bbox[1] - originX) / pixel_width) + 1

    y1 = int((bbox[3] - originY) / pixel_height)
    y2 = int((bbox[2] - originY) / pixel_height) + 1

    xsize = x2 - x1
    ysize = y2 - y1
    return (x1, y1, xsize, ysize)


def zonal_stats_1(vector_path, raster_path, nodata_value=None, global_src_extent=False):
    rds = gdal.Open(raster_path, GA_ReadOnly)
    assert(rds)
    rb = rds.GetRasterBand(1)
    rgt = rds.GetGeoTransform()

    if nodata_value:
        nodata_value = float(nodata_value)
        rb.SetNoDataValue(nodata_value)

    vds = ogr.Open(vector_path, GA_ReadOnly)  # TODO maybe open update if we want to write stats
    assert(vds)
    vlyr = vds.GetLayer(0)

    # create an in-memory numpy array of the source raster data
    # covering the whole extent of the vector layer
    if global_src_extent:
        # use global source extent
        # useful only when disk IO or raster scanning inefficiencies are your limiting factor
        # advantage: reads raster data in one pass
        # disadvantage: large vector extents may have big memory requirements
        src_offset = bbox_to_pixel_offsets(rgt, vlyr.GetExtent())
        src_array = rb.ReadAsArray(*src_offset)

        # calculate new geotransform of the layer subset
        new_gt = (
            (rgt[0] + (src_offset[0] * rgt[1])),
            rgt[1],
            0.0,
            (rgt[3] + (src_offset[1] * rgt[5])),
            0.0,
            rgt[5]
        )

    mem_drv = ogr.GetDriverByName('Memory')
    driver = gdal.GetDriverByName('MEM')

    # Loop through vectors
    stats = []
    feat = vlyr.GetNextFeature()
    while feat is not None:

        if not global_src_extent:
            # use local source extent
            # fastest option when you have fast disks and well indexed raster (ie tiled Geotiff)
            # advantage: each feature uses the smallest raster chunk
            # disadvantage: lots of reads on the source raster
            src_offset = bbox_to_pixel_offsets(rgt, feat.geometry().GetEnvelope())
            src_array = rb.ReadAsArray(*src_offset)

            # calculate new geotransform of the feature subset
            new_gt = (
                (rgt[0] + (src_offset[0] * rgt[1])),
                rgt[1],
                0.0,
                (rgt[3] + (src_offset[1] * rgt[5])),
                0.0,
                rgt[5]
            )

        # Create a temporary vector layer in memory
        mem_ds = mem_drv.CreateDataSource('out')
        mem_layer = mem_ds.CreateLayer('poly', None, ogr.wkbPolygon)
        mem_layer.CreateFeature(feat.Clone())

        # Rasterize it
        rvds = driver.Create('', src_offset[2], src_offset[3], 1, gdal.GDT_Byte)
        rvds.SetGeoTransform(new_gt)
        gdal.RasterizeLayer(rvds, [1], mem_layer, burn_values=[1])
        rv_array = rvds.ReadAsArray()

        # Mask the source data array with our current feature
        # we take the logical_not to flip 0<->1 to get the correct mask effect
        # we also mask out nodata values explictly
        masked = np.ma.MaskedArray(
            src_array,
            mask=np.logical_or(
                src_array == nodata_value,
                np.logical_not(rv_array)
            )
        )

        feature_stats = {
            'min': float(masked.min()),
            'mean': float(masked.mean()),
            'max': float(masked.max()),
            'std': float(masked.std()),
            'sum': float(masked.sum()),
            'count': int(masked.count()),
            'fid': int(feat.GetFID())}

        stats.append(feature_stats)

        rvds = None
        mem_ds = None
        feat = vlyr.GetNextFeature()

    vds = None
    rds = None
    return stats

import pyogrio

def calculate_zonal_stats(shapefile_path, raster_path, output_path_shp, ws_id="ws_id", Suffix=""):
    """
    Calcula estadísticas zonales para un raster basado en un shapefile con múltiples polígonos.

    Parámetros:
        shapefile_path (str): Ruta al archivo shapefile.
        raster_path (str): Ruta al archivo raster.
        ws_id (str): Nombre del atributo en el shapefile para agrupar los polígonos.

    Retorna:
        gpd.GeoDataFrame: GeoDataFrame con las estadísticas zonales calculadas.
    """
    try:
        # Cargar el shapefile usando pyogrio como alternativa a Fiona
        polygons = gpd.read_file(shapefile_path, engine='pyogrio')
    except Exception as e:
        raise RuntimeError(f"Error al leer el shapefile: {e}")

    # Verificar que el shapefile y el raster tienen el mismo sistema de referencia
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        nodata_value = src.nodatavals[0] if src.nodatavals and src.nodatavals[0] is not None else None

    if polygons.crs != raster_crs:
        polygons = polygons.to_crs(raster_crs)

    # Calcular estadísticas zonales agrupadas por el atributo 'ws_id'
    unique_ids = polygons[ws_id].unique()
    results = []

    for uid in unique_ids:
        subset = polygons[polygons[ws_id] == uid]
        stats = zonal_stats(
            subset,  # Subconjunto del shapefile
            raster_path,  # Archivo raster
            stats=["mean", "min", "max", "median","sum"],
            nodata=nodata_value, # Estadísticas deseadas
            geojson_out=True  # Devuelve los resultados como GeoJSON
        )
        stats_gdf = gpd.GeoDataFrame.from_features(stats)
        stats_gdf[ws_id] = uid
        results.append(stats_gdf)

    # Combinar todos los resultados
    final_result = gpd.GeoDataFrame(pd.concat(results, ignore_index=True))

    # Guardar los resultados en un nuevo shapefile
    output_path = "Zonal_{}.shp".format(Suffix)
    try:
        final_result.to_file(os.path.join(output_path_shp, output_path), driver='ESRI Shapefile')
    except Exception as e:
        raise RuntimeError(f"Error al guardar el shapefile de salida: {e}")

    # Convertir los resultados a un DataFrame
    final_result = pd.DataFrame(final_result)

    return final_result
