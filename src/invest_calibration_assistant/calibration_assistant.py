# -*- coding: utf-8 -*-
"""
InVEST Calibration Assistant - InVEST Plugin

Nature For Water Facility - The Nature Conservancy
Author  : Jonathan Nogales Pimentel / Carlos Andrés Rogéliz Prada / Miguel Angel Cañón
Email   : jonathan.nogales@tnc.org

Per-model individual field inputs replace the legacy "Table Of Input File Names"
CSV. Fields appear/disappear dynamically based on the selected model:

  AWY  : LULC, BioTable, ETP, P, RootDepth, PAWC, Watersheds
  SWY  : LULC, BioTable, RootDepth, PAWC, DEM, SoilGroup,
          MonthlyETP dir, MonthlyP dir, RainTable, Watersheds
  SDR  : LULC, BioTable, DEM, Erosivity(R), Erodibility(K), Watersheds
  NDR_N: LULC, BioTable, DEM, P (runoff proxy), SoilGroup, Watersheds
  NDR_P: same as NDR_N

The "Table Of Parameter Search Ranges" CSV and "Table Of Observed Data" CSV
remain unchanged.
"""

"""
Development History
--------------------
Core calibration methodology originated in 2021 (WaterProof project,
InVEST 3.9), conceived by Jonathan Nogales Pimentel and Carlos
Andres Rogeliz Prada, and coded by Jonathan Nogales Pimentel. Published
in Rogeliz et al. (2022), Water 14(21):3447
(https://doi.org/10.3390/w14213447). Rebuilt as a standalone
calibration tool in 2024-2025 by Jonathan Nogales Pimentel. Adapted
to the InVEST plugin standard in 2026 by Miguel Angel Canon Ramos.

Full history, contributor roles, and a note on git-blame attribution
for the pre-2026 codebase: see CONTRIBUTING.md.
"""

import logging
import os
import webbrowser
from datetime import datetime
from importlib.metadata import PackageNotFoundError, version as _pkg_version

import numpy as np
import pandas as pd

from natcap.invest import gettext
from natcap.invest import spec
from natcap.invest import validation
from natcap.invest.unit_registry import u

from . import Report_InVEST

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy Spotpy_InVEST import
# ---------------------------------------------------------------------------

def _get_si():
    """Lazily import the ``Spotpy_InVEST`` helper module.

    The import is deferred so that heavy dependencies (spotpy, GDAL,
    rasterio, matplotlib, ...) are only loaded when :func:`execute` actually
    runs a calibration, not at plugin discovery time.

    Returns
    -------
    module
        The imported ``Spotpy_InVEST`` module.
    """
    from . import Spotpy_InVEST as _si  # noqa: PLC0415
    return _si


# ---------------------------------------------------------------------------
# Condition helpers  (kept as module constants for readability)
# ---------------------------------------------------------------------------
_AWY            = 'model_name == "AWY"'
_SWY            = 'model_name == "SWY"'
_SDR            = 'model_name == "SDR"'
_NDR_N          = 'model_name == "NDR_N"'
_NDR_P          = 'model_name == "NDR_P"'
_SWY_SDR_NDR    = 'model_name in ["SWY", "SDR", "NDR_N", "NDR_P"]'
_AWY_NDR        = 'model_name in ["AWY", "NDR_N", "NDR_P"]'
_NDR            = 'model_name in ["NDR_N", "NDR_P"]'


# ---------------------------------------------------------------------------
# MODEL SPEC
# ---------------------------------------------------------------------------
MODEL_SPEC = spec.ModelSpec(
    model_id="invest_calibration_assistant",
    model_title=gettext("InVEST Calibration Assistant"),
    module_name=__name__,
    userguide='https://github.com/N4W-Facility/Invest_Plugin_Calibration/blob/main/CALIBRATION_PROCESS.md',
    input_field_order=[
        ['workspace_dir'],
        ['model_name'],

        # ── Inputs shared by all models ──────────────────────────────────
        ['lulc_path'],
        ['biophysical_table_path'],
        ['calibration_watersheds_path'],
        ['watersheds_path'],
        ['awy_sub_watersheds_path'],
        ['threshold_flow_accumulation', 'project_suffix'],

        # ── Annual rasters: AWY + NDR (annual P / runoff proxy) ──────────
        ['precipitation_path'],

        # ── AWY only ─────────────────────────────────────────────────────
        ['eto_path'],

        # ── AWY only ──────────────────────────────────────────────────────
        ['depth_to_root_rest_layer_path'],
        ['pawc_path'],

        # ── SWY, SDR, NDR (DEM) ──────────────────────────────────────────
        ['dem_path'],

        # ── SWY only (soil group) ─────────────────────────────────────────
        ['soil_group_path'],

        # ── SWY only: monthly folders + rain table ────────────────────────
        ['eto_raster_table'],
        ['precip_raster_table'],
        ['rain_events_table_path'],

        # ── SDR only: erosivity + erodibility ────────────────────────────
        ['erosivity_path'],
        ['erodibility_path'],

        # ── Calibration settings (all models) ────────────────────────────
        ['parameter_search_ranges_path'],
        ['observed_data_path'],
        ['evaluation_metric', 'optimization_method'],
        ['n_simulations'],
    ],
    inputs=[

        # ------------------------------------------------------------------
        # Standard InVEST workspace / suffix
        # ------------------------------------------------------------------
        spec.WORKSPACE.model_copy(update=dict(
            about=gettext(
                'Output folder for all calibration results. '
                'Sub-folders EVALUATIONS, PARAMETERS, OUTPUTS, FIGURES '
                'and TMP are created automatically.')
        )),
        spec.NumberInput(
            id='n_workers',
            name=gettext('taskgraph n_workers'),
            about=gettext('Parallel workers (-1 = synchronous).'),
            units=None,
            required=False,
            expression='value >= -1',
            hidden=True,
        ),

        # ------------------------------------------------------------------
        # Model selection
        # ------------------------------------------------------------------
        spec.OptionStringInput(
            id='model_name',
            name=gettext('Name Of The Model To Calibrate'),
            about=gettext(
                'Select the InVEST model to calibrate. '
                'The input fields below will update accordingly.'),
            options=[
                spec.Option(key='AWY',   display_name=gettext('AWY – Annual Water Yield')),
                spec.Option(key='SWY',   display_name=gettext('SWY – Seasonal Water Yield')),
                spec.Option(key='SDR',   display_name=gettext('SDR – Sediment Delivery Ratio')),
                spec.Option(key='NDR_N', display_name=gettext('NDR_N – Nutrient Delivery Ratio (N)')),
                spec.Option(key='NDR_P', display_name=gettext('NDR_P – Nutrient Delivery Ratio (P)')),
            ],
        ),

        # ==================================================================
        # SPATIAL INPUTS – shared by all models
        # ==================================================================
        spec.SingleBandRasterInput(
            id='lulc_path',
            name=gettext('Land Use / Land Cover'),
            about=gettext(
                'LULC raster. Each code must have a corresponding row '
                'in the biophysical table.'),
            projected=True,
            units=None,
        ),
        spec.CSVInput(
            id='biophysical_table_path',
            name=gettext('Biophysical Table'),
            about=gettext(
                'CSV table mapping LULC codes to biophysical coefficients. '
                'Standard columns vary by model (kc, usle_c/usle_p, '
                'load_n/eff_n, load_p/eff_p — see InVEST documentation). '
                'Must also include one boolean "Status_Cal_*" column per '
                'calibrated parameter (1 = row calibrated, 0 = held fixed): '
                'Status_Cal_Kc (AWY/SWY), Status_Cal_C/Status_Cal_P (SDR), '
                'Status_Cal_Load_N/Status_Cal_Eff_N (NDR_N), '
                'Status_Cal_Load_P/Status_Cal_Eff_P (NDR_P). Full '
                'explanation and examples: plugin User\'s Guide, section 3.'),
            columns=[],
        ),
        spec.VectorInput(
            id='calibration_watersheds_path',
            name=gettext('Calibration Watersheds'),
            about=gettext(
                'Watershed shapefile used during calibration iterations '
                '(the sub-set of watersheds with observed data). '
                'Must contain a "ws_id" integer field.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
        ),
        spec.VectorInput(
            id='watersheds_path',
            name=gettext('Full Watersheds (Final Run)'),
            about=gettext(
                'Watershed shapefile used for the final InVEST run with the '
                'best-fit calibrated parameters. Optional: if left blank, '
                'the Calibration Watersheds shapefile is used for the final run too.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
            required=False,
        ),
        spec.VectorInput(
            id='awy_sub_watersheds_path',
            name=gettext('Sub-Watersheds (optional)'),
            about=gettext(
                'Sub-watershed shapefile. Optional for all models.'),
            geometry_types={'POLYGON', 'MULTIPOLYGON'},
            fields=[],
            projected=True,
            required=False,
        ),
        spec.NumberInput(
            id='threshold_flow_accumulation',
            name=gettext('Threshold Flow Accumulation'),
            about=gettext(
                'Number of upstream cells required to define a stream. '
                'Used for stream delineation. '
                'Required for SWY, SDR, and NDR only.'),
            units=None,
            expression='value > 0',
            required=_SWY_SDR_NDR,
            allowed=_SWY_SDR_NDR,
        ),
        spec.StringInput(
            id='project_suffix',
            name=gettext('Project Name / Suffix'),
            about=gettext(
                'Short label appended to output file names '
                '(e.g. "MyProject2025"). Optional.'),
            required=False,
            regexp='[a-zA-Z0-9_-]*',
        ),

        # ==================================================================
        # ANNUAL PRECIPITATION  –  AWY (precipitation) + NDR (runoff proxy)
        # ==================================================================
        spec.SingleBandRasterInput(
            id='precipitation_path',
            name=gettext('Annual Precipitation'),
            about=gettext(
                'Annual precipitation raster (mm/year). '
                'Used as precipitation for AWY; as runoff proxy for NDR.'),
            projected=True,
            units=u.millimeter,
            required=_AWY_NDR,
            allowed=_AWY_NDR,
        ),

        # ==================================================================
        # AWY ONLY – Annual ETP
        # ==================================================================
        spec.SingleBandRasterInput(
            id='eto_path',
            name=gettext('Reference Evapotranspiration'),
            about=gettext(
                'Annual reference evapotranspiration raster (mm/year). '
                'Required for AWY only.'),
            projected=True,
            units=u.millimeter,
            required=_AWY,
            allowed=_AWY,
        ),

        # ==================================================================
        # AWY only – Root depth and PAWC
        # ==================================================================
        spec.SingleBandRasterInput(
            id='depth_to_root_rest_layer_path',
            name=gettext('Root Restricting Layer Depth'),
            about=gettext(
                'Depth to the root restricting layer raster (mm). '
                'Required for AWY only.'),
            projected=True,
            units=u.millimeter,
            required=_AWY,
            allowed=_AWY,
        ),
        spec.SingleBandRasterInput(
            id='pawc_path',
            name=gettext('Plant Available Water Content'),
            about=gettext(
                'Plant available water content raster (fraction 0–1). '
                'Required for AWY only.'),
            projected=True,
            units=None,
            required=_AWY,
            allowed=_AWY,
        ),

        # ==================================================================
        # SWY + SDR + NDR – Digital Elevation Model
        # ==================================================================
        spec.SingleBandRasterInput(
            id='dem_path',
            name=gettext('Digital Elevation Model'),
            about=gettext(
                'Digital elevation model raster (m). '
                'Required for SWY, SDR, NDR.'),
            projected=True,
            units=u.meter,
            required=_SWY_SDR_NDR,
            allowed=_SWY_SDR_NDR,
        ),

        # ==================================================================
        # SWY only – Hydrologic Soil Group
        # ==================================================================
        spec.SingleBandRasterInput(
            id='soil_group_path',
            name=gettext('Hydrologic Soil Group'),
            about=gettext(
                'Hydrologic soil group raster. Values must be integers '
                '1–4 representing groups A, B, C, D. '
                'Required for SWY only.'),
            projected=True,
            units=None,
            required=_SWY,
            allowed=_SWY,
        ),

        # ==================================================================
        # SWY ONLY – Monthly ETP folder, Monthly P folder, Rain events table
        # ==================================================================
        spec.CSVInput(
            id='eto_raster_table',
            name=gettext('Monthly ETP Raster Table'),
            about=gettext(
                'CSV with columns "month" (1–12) and "path" mapping each '
                'month to its reference evapotranspiration raster (.tif). '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),
        spec.CSVInput(
            id='precip_raster_table',
            name=gettext('Monthly Precipitation Raster Table'),
            about=gettext(
                'CSV with columns "month" (1–12) and "path" mapping each '
                'month to its precipitation raster (.tif). '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),
        spec.CSVInput(
            id='rain_events_table_path',
            name=gettext('Rain Events Table'),
            about=gettext(
                'CSV table with the number of monthly rain events per '
                'month. Required columns: month (1–12), events. '
                'Required for SWY only.'),
            columns=[],
            required=_SWY,
            allowed=_SWY,
        ),

        # ==================================================================
        # SDR ONLY – Erosivity (R) and Erodibility (K)
        # ==================================================================
        spec.SingleBandRasterInput(
            id='erosivity_path',
            name=gettext('Rainfall Erosivity (R factor)'),
            about=gettext(
                'Rainfall erosivity raster (MJ·mm / ha·h·year). '
                'Required for SDR only.'),
            projected=True,
            units=None,
            required=_SDR,
            allowed=_SDR,
        ),
        spec.SingleBandRasterInput(
            id='erodibility_path',
            name=gettext('Soil Erodibility (K factor)'),
            about=gettext(
                'Soil erodibility raster (t·ha·h / ha·MJ·mm). '
                'Required for SDR only.'),
            projected=True,
            units=None,
            required=_SDR,
            allowed=_SDR,
        ),

        # ==================================================================
        # CALIBRATION SETTINGS – shared by all models
        # ==================================================================
        spec.CSVInput(
            id='parameter_search_ranges_path',
            name=gettext('Table Of Parameter Search Ranges'),
            about=gettext(
                'CSV file (Parameters.csv) with columns: '
                '"Params", "Model", "Min", "Max", "Value". '
                'All parameters for all models can be in one file; '
                'only the rows for the selected model are used during calibration. '
                'The "Model" column is informational (AWY / SWY / SDR / NDR). '
                'Full list of parameter names and typical ranges per model: '
                'see the plugin User\'s Guide, section 2.'),
            index_col='Params',
            columns=[
                spec.StringInput(
                    id='Params',
                    name=gettext('Params'),
                    about=gettext('Parameter name (e.g. Z, Factor-Kc, sdr_max …)'),
                ),
                spec.StringInput(
                    id='Model',
                    name=gettext('Model'),
                    about=gettext('Model this parameter belongs to (AWY / SWY / SDR / NDR)'),
                    required=False,
                ),
                spec.NumberInput(
                    id='Min',
                    name=gettext('Min'),
                    about=gettext('Lower search bound for calibration'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Max',
                    name=gettext('Max'),
                    about=gettext('Upper search bound for calibration'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Value',
                    name=gettext('Value'),
                    about=gettext('Best-guess / initial parameter value'),
                    units=None,
                ),
            ],
        ),
        spec.CSVInput(
            id='observed_data_path',
            name=gettext('Table Of Observed Data'),
            about=gettext(
                'CSV file (Obs_Data.csv) with one row per calibration watershed. '
                'Required columns: "ws_id" (integer watershed ID matching the '
                'shapefile), plus one column per model to calibrate: '
                '"AWY" (m³/year), "SWY" (mm/year), "SDR" (tonnes/year), '
                '"NDR_N" (kg/year), "NDR_P" (kg/year). '
                'Unused model columns are ignored. Values must be '
                'incremental (per-gauge), not cumulative, and each is an '
                'absolute annual amount, never a concentration — see the '
                'plugin User\'s Guide, sections 1.2 and 5, before building '
                'this table.'),
            index_col='ws_id',
            columns=[
                spec.IntegerInput(
                    id='ws_id',
                    name=gettext('ws_id'),
                    about=gettext('Watershed identifier — must match ws_id in the shapefile'),
                ),
                spec.NumberInput(
                    id='AWY',
                    name=gettext('AWY'),
                    about=gettext('Observed streamflow for AWY calibration (m³/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='SWY',
                    name=gettext('SWY'),
                    about=gettext('Observed streamflow for SWY calibration (mm/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='SDR',
                    name=gettext('SDR'),
                    about=gettext('Observed sediment export for SDR calibration (tonnes/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='NDR_N',
                    name=gettext('NDR_N'),
                    about=gettext('Observed nitrogen load for NDR_N calibration (kg/year)'),
                    units=None,
                    required=False,
                ),
                spec.NumberInput(
                    id='NDR_P',
                    name=gettext('NDR_P'),
                    about=gettext('Observed phosphorus load for NDR_P calibration (kg/year)'),
                    units=None,
                    required=False,
                ),
            ],
        ),
        spec.OptionStringInput(
            id='evaluation_metric',
            name=gettext('Evaluation Metric'),
            about=gettext('Objective function used to compare simulated vs observed values.'),
            options=[
                spec.Option(key='Mean Square Error (MSE)',
                            display_name=gettext('Mean Square Error (MSE)')),
                spec.Option(key='Mean Absolute Error (MAE)',
                            display_name=gettext('Mean Absolute Error (MAE)')),
                spec.Option(key='Root Mean Square Error (RMSE)',
                            display_name=gettext('Root Mean Square Error (RMSE)')),
                spec.Option(key='Relative Root Mean Squared Error (RRMSE)',
                            display_name=gettext('Relative Root Mean Squared Error (RRMSE)')),
            ],
        ),
        spec.OptionStringInput(
            id='optimization_method',
            name=gettext('Optimization Method'),
            about=gettext('Optimization algorithm used to search the parameter space.'),
            options=[
                spec.Option(key='Dynamical dimensional search (DDS)',
                            display_name=gettext('Dynamical Dimensional Search (DDS)')),
                spec.Option(key='Shuffled Complex Evolution (SCE-UA)',
                            display_name=gettext('Shuffled Complex Evolution (SCE-UA)')),
                spec.Option(key='Latin Hypercube Sampling (LHS)',
                            display_name=gettext('Latin Hypercube Sampling (LHS)')),
            ],
        ),
        spec.IntegerInput(
            id='n_simulations',
            name=gettext('Number Of Simulations'),
            about=gettext(
                'Total model evaluations during calibration. Must be >= 10. '
                'The DDS algorithm requires at least 10 iterations for its '
                'initialization phase. '
                'Larger values improve parameter estimation at the cost of '
                'computation time.'),
            expression='value >= 10',
        ),
    ],

    outputs=[
        spec.FileOutput(
            id='calibration_results',
            path='PARAMETERS',
            about=gettext('Spotpy parameter CSV files with best-fit values.'),
        ),
        spec.FileOutput(
            id='calibration_figures',
            path='FIGURES',
            about=gettext('Scatter plots comparing simulated vs observed values.'),
        ),
        spec.FileOutput(
            id='calibration_report',
            path='REPORT',
            about=gettext(
                'Self-contained HTML report summarizing the run (inputs, '
                'algorithm, parameter table, dotty plots, and how to '
                'interpret them). Opens automatically when the run finishes.'),
        ),
    ],
)


# ---------------------------------------------------------------------------
# Build model_paths dict from individual UI fields
# ---------------------------------------------------------------------------

def _build_model_paths(args):
    """Collect the spatial/tabular inputs relevant to the selected model.

    Parameters
    ----------
    args : dict
        Raw arguments dict as received by :func:`execute`, keyed by the
        input ids declared in ``MODEL_SPEC``.

    Returns
    -------
    dict
        ``model_paths`` dict with one entry per possible input. Fields
        that do not apply to ``args['model_name']`` are set to ``''``
        (or ``None`` for ``threshold_flow_accumulation``) rather than
        omitted, so downstream code can always index the dict safely.
    """
    m = args['model_name']

    def _get(key):
        """Return ``args[key]`` or ``''`` when missing/empty."""
        return args.get(key) or ''

    mp = {
        # -- shared
        'lulc_path':                    args['lulc_path'],
        'biophysical_table_path':       args['biophysical_table_path'],
        'calibration_watersheds_path':  args['calibration_watersheds_path'],
        # Fall back to calibration watershed when no separate final-run watershed is given
        'watersheds_path':              _get('watersheds_path') or args['calibration_watersheds_path'],
        'sub_watersheds_path':          _get('awy_sub_watersheds_path'),
        'threshold_flow_accumulation':  float(args['threshold_flow_accumulation']) if args.get('threshold_flow_accumulation') else None,
        'project_suffix':               _get('project_suffix') or m,

        # -- AWY + NDR
        'precipitation_path':           _get('precipitation_path'),

        # -- AWY only
        'eto_path':                     _get('eto_path'),
        'depth_to_root_rest_layer_path': _get('depth_to_root_rest_layer_path'),
        'pawc_path':                    _get('pawc_path'),

        # -- SWY + SDR + NDR
        'dem_path':                     _get('dem_path'),

        # -- SWY only
        'soil_group_path':              _get('soil_group_path'),

        # -- SWY only
        'eto_raster_table':             _get('eto_raster_table'),
        'precip_raster_table':          _get('precip_raster_table'),
        'rain_events_table_path':       _get('rain_events_table_path'),

        # -- SDR only
        'erosivity_path':               _get('erosivity_path'),
        'erodibility_path':             _get('erodibility_path'),
    }
    return mp


# ---------------------------------------------------------------------------
# Build UserData dict for Spotpy_InVEST helpers
# ---------------------------------------------------------------------------

def _build_user_data(model_name, mp):
    """Build the ``UserData`` dict expected by ``Factor_BioTable``.

    ``Factor_BioTable`` only needs the ``Status_*`` flags (one per model,
    used to decide which columns of the biophysical table to modify) and,
    for some models, a ``BioTable`` key that is unused when the full path
    is passed directly.

    Parameters
    ----------
    model_name : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    mp : dict
        ``model_paths`` dict returned by :func:`_build_model_paths`.

    Returns
    -------
    dict
        Keys: ``Suffix``, ``BioTable``, and one ``Status_<MODEL>`` flag
        (0 or 1) per supported model.
    """
    bio_basename = os.path.splitext(
        os.path.basename(mp['biophysical_table_path']))[0]

    return {
        'Suffix':       mp['project_suffix'],
        'BioTable':     bio_basename,
        'Status_AWY':   1 if model_name == 'AWY'   else 0,
        'Status_SWY':   1 if model_name == 'SWY'   else 0,
        'Status_SDR':   1 if model_name == 'SDR'   else 0,
        'Status_NDR_N': 1 if model_name == 'NDR_N' else 0,
        'Status_NDR_P': 1 if model_name == 'NDR_P' else 0,
    }


# ---------------------------------------------------------------------------
# HTML report helpers
# ---------------------------------------------------------------------------
_INPUT_LABELS = [
    ('lulc_path',                     'Land Use / Land Cover'),
    ('biophysical_table_path',        'Biophysical Table'),
    ('calibration_watersheds_path',   'Calibration Watersheds'),
    ('watersheds_path',               'Full Watersheds (Final Run)'),
    ('sub_watersheds_path',           'Sub-Watersheds'),
    ('precipitation_path',            'Annual Precipitation'),
    ('eto_path',                      'Reference Evapotranspiration'),
    ('depth_to_root_rest_layer_path', 'Root Restricting Layer Depth'),
    ('pawc_path',                     'Plant Available Water Content'),
    ('dem_path',                      'Digital Elevation Model'),
    ('soil_group_path',               'Hydrologic Soil Group'),
    ('eto_raster_table',              'Monthly ETP Raster Table'),
    ('precip_raster_table',           'Monthly Precipitation Raster Table'),
    ('rain_events_table_path',        'Rain Events Table'),
    ('erosivity_path',                'Rainfall Erosivity (R factor)'),
    ('erodibility_path',              'Soil Erodibility (K factor)'),
]


def _inputs_summary(mp):
    """Return ``(label, path)`` pairs for the non-empty inputs of this run."""
    return [(label, mp[key]) for key, label in _INPUT_LABELS if mp.get(key)]


# Status_Cal_* column(s) required per model — see CALIBRATION_PROCESS.md §3.
_STATUS_CAL_COLUMNS = {
    'AWY':   ['Status_Cal_Kc'],
    'SWY':   ['Status_Cal_Kc'],
    'SDR':   ['Status_Cal_C', 'Status_Cal_P'],
    'NDR_N': ['Status_Cal_Load_N', 'Status_Cal_Eff_N'],
    'NDR_P': ['Status_Cal_Load_P', 'Status_Cal_Eff_P'],
}


def _status_cal_summary(biophysical_table_path, model_name):
    """Identify which LULC rows are flagged for calibration per factor.

    Returns
    -------
    list of (str, int, int, list of (str, str))
        ``(column_name, n_flagged, n_total, classes)`` for each
        ``Status_Cal_*`` column relevant to ``model_name``, where
        ``classes`` is the ``(lucode, description)`` pairs of the LULC
        rows flagged ``1`` (i.e. the land-cover classes actually
        calibrated by that factor). Empty list if the table or columns
        cannot be read (kept non-fatal — this only feeds the report, not
        the calibration itself).
    """
    cols = _STATUS_CAL_COLUMNS.get(model_name, [])
    if not cols:
        return []
    try:
        df = pd.read_csv(biophysical_table_path, encoding='latin-1')
    except Exception:
        LOGGER.exception('Could not read biophysical table for the report summary.')
        return []
    lucode_col = 'lucode' if 'lucode' in df.columns else None
    desc_col = 'description' if 'description' in df.columns else None
    summary = []
    for col in cols:
        if col not in df.columns:
            continue
        n_total = len(df)
        flagged = df[df[col] == 1]
        n_flagged = len(flagged)
        if lucode_col:
            classes = list(zip(
                flagged[lucode_col].astype(str),
                flagged[desc_col].astype(str) if desc_col else [''] * n_flagged,
            ))
        else:
            classes = []
        summary.append((col, n_flagged, n_total, classes))
    return summary


def _invest_version():
    """Return the installed ``natcap.invest`` version, or ``'unknown'``."""
    try:
        return _pkg_version('natcap.invest')
    except PackageNotFoundError:
        return 'unknown'


_METHOD_SHORT = {
    'Dynamical dimensional search (DDS)':   'DDS',
    'Shuffled Complex Evolution (SCE-UA)':  'SCE-UA',
    'Latin Hypercube Sampling (LHS)':       'LHS',
}


# ---------------------------------------------------------------------------
# Read parameter CSV
# ---------------------------------------------------------------------------

def _read_param_ranges(parameter_search_ranges_path):
    """Read the parameter search-range CSV into value/min/max dicts.

    Expected format (``Parameters.csv``)::

        Params, Model, Min, Max, Value

    Each row name in the ``Params`` column maps directly to an internal
    parameter key (with the single exception of ``Borselli-IC0`` -> ``IC0``).
    The ``Model`` column is informational only; all rows are loaded and the
    calibration engine selects the relevant subset per model. Trailing
    empty rows are silently ignored.

    Parameters
    ----------
    parameter_search_ranges_path : str
        Path to the parameter search-range CSV file.

    Returns
    -------
    tuple of dict
        ``(params_val, params_min, params_max)``, each keyed by internal
        parameter name, with the initial guess, lower bound and upper
        bound respectively.
    """
    df = pd.read_csv(parameter_search_ranges_path)

    # ── detect column layout ────────────────────────────────────────────
    if 'Params' in df.columns:
        # New format: Params | Model | Min | Max | Value
        df = df.set_index('Params')
    elif 'Parameter' in df.columns:
        # Legacy format: Parameter | Value | Min | Max
        df = df.set_index('Parameter')
    else:
        df = df.set_index(df.columns[0])

    # Drop fully-empty rows (trailing blank lines in the CSV)
    df = df[df.index.notna()]
    df = df[df.index.astype(str).str.strip() != '']

    # ── single name mapping needed (Borselli-IC0 → IC0 internally) ──────
    _row_map = {
        'Z':              'Z',
        'Factor-Kc':      'Factor-Kc',
        'Factor-Kc_m':    'Factor-Kc_m',
        'Alpha':          'Alpha',
        'Beta':           'Beta',
        'Gamma':          'Gamma',
        'Factor-C':       'Factor-C',
        'Factor-P':       'Factor-P',
        'Borselli-IC0':   'IC0',          # ← only rename needed
        'L_max':          'L_max',
        'sdr_max':        'sdr_max',
        'Factor_Load_N':  'Factor_Load_N',
        'Factor_Eff_N':   'Factor_Eff_N',
        'SubCri_Len_N':   'SubCri_Len_N',
        'Sub_Eff_N':      'Sub_Eff_N',
        'Factor_Load_P':  'Factor_Load_P',
        'Factor_Eff_P':   'Factor_Eff_P',
        'SubCri_Len_P':   'SubCri_Len_P',
        'Sub_Eff_P':      'Sub_Eff_P',
        'Borselli-K_SDR': 'Borselli-K_SDR',
        'Borselli-K_NDR': 'Borselli-K_NDR',
    }

    val, lo, hi = {}, {}, {}
    for csv_key, internal_key in _row_map.items():
        if csv_key in df.index:
            val[internal_key] = float(df.loc[csv_key, 'Value'])
            lo[internal_key]  = float(df.loc[csv_key, 'Min'])
            hi[internal_key]  = float(df.loc[csv_key, 'Max'])

    return val, lo, hi


# ---------------------------------------------------------------------------
# Build Spotpy parameter list
# ---------------------------------------------------------------------------

def _build_spotpy_params(model_name, params_min, params_max):
    """Build the list of ``spotpy.parameter.Uniform`` objects to sample.

    Parameters
    ----------
    model_name : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    params_min, params_max : dict
        Lower/upper search bounds per internal parameter name, as
        returned by :func:`_read_param_ranges`.

    Returns
    -------
    list of spotpy.parameter.Uniform
        One entry per parameter required by ``model_name``, in the fixed
        order consumed by the corresponding ``_execute_*_direct`` function.
    """
    import spotpy  # noqa: PLC0415

    _required = {
        'AWY':   ['Z', 'Factor-Kc'],
        'SWY':   ['Alpha', 'Beta', 'Gamma', 'Factor-Kc_m'],
        'SDR':   ['sdr_max', 'Borselli-K_SDR', 'IC0', 'L_max', 'Factor-C', 'Factor-P'],
        'NDR_N': ['SubCri_Len_N', 'Sub_Eff_N', 'Borselli-K_NDR', 'Factor_Load_N', 'Factor_Eff_N'],
        'NDR_P': ['SubCri_Len_P', 'Sub_Eff_P', 'Borselli-K_NDR', 'Factor_Load_P', 'Factor_Eff_P'],
    }

    return [
        spotpy.parameter.Uniform(k, params_min.get(k, 0.0), params_max.get(k, 1.0))
        for k in _required.get(model_name, [])
    ]


# ---------------------------------------------------------------------------
# Shared per-iteration helpers
# ---------------------------------------------------------------------------

def _save_eval_csv(workspace, name, header, rows):
    """Append one calibration iteration's data to an EVALUATIONS CSV.

    Creates the file with ``header`` as its first line the first time it
    is called for a given ``name``; subsequent calls only append rows.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory (contains the ``EVALUATIONS``
        sub-folder).
    name : str
        CSV file name, e.g. ``'AWY_Metric_MyProject.csv'``.
    header : str
        Comma-separated column header, written only when the file is
        created.
    rows : list of str
        Comma-separated data rows to append.
    """
    path = os.path.join(workspace, 'EVALUATIONS', name)
    file_exists = os.path.isfile(path)
    with open(path, 'a') as f:
        if not file_exists:
            f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


def _write_temp_biotable(si, mp, user_data, params, workspace, tag):
    """Apply candidate params to the biophysical table and save it under TMP.

    Shared by every ``_execute_*_direct`` function: each calibration
    iteration proposes a new parameter set, which is applied to the
    project's biophysical table and written to
    ``<workspace>/TMP/<tag>_biophysical.csv`` for the InVEST model run.

    Parameters
    ----------
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    params : dict
        Candidate parameter values for this iteration.
    workspace : str
        Calibration workspace directory.
    tag : str
        Model tag used in the output file name (e.g. ``'AWY'``, ``'NDR_N'``).

    Returns
    -------
    str
        Path to the written temporary biophysical table CSV.
    """
    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', f'{tag}_biophysical.csv')
    table.to_csv(tmp_bio, index=False)
    return tmp_bio


def _score_against_obs(si, sim_df, sim_col, obs_df, obs_col, metric_name, factor_metric):
    """Match simulated/observed values by ``ws_id`` and score the fit.

    Shared by every ``_execute_*_direct`` function to turn a model run's
    per-watershed output into the signed objective function value spotpy
    optimizes.

    Parameters
    ----------
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.
    sim_df : pandas.DataFrame
        Simulated per-watershed results (must contain ``ws_id`` and
        ``sim_col``).
    sim_col : str
        Column in ``sim_df`` holding the simulated values.
    obs_df : pandas.DataFrame
        Observed data table (must contain ``ws_id`` and ``obs_col``).
    obs_col : str
        Column in ``obs_df`` holding the observed values.
    metric_name : str
        Objective function name, as used by ``Spotpy_InVEST.Cal_FunObj``.
    factor_metric : float
        ``+1`` or ``-1``; flips the sign of the metric so every
        optimization algorithm searches in the same direction.

    Returns
    -------
    obj : float
        ``factor_metric``-adjusted objective function value.
    obs_val : numpy.ndarray
        Observed values, matched to ``sim_val`` by ``ws_id``.
    sim_val : numpy.ndarray
        Simulated values, matched to ``obs_val`` by ``ws_id``.
    """
    [I, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    obs_val = obs_df[obs_col].values[idx]
    sim_val = sim_df[sim_col].values[I]
    obj = factor_metric * si.Cal_FunObj(obs_val, sim_val, metric_name)
    return obj, obs_val, sim_val


def _save_iteration(workspace, tag, suffix, header, row, obs_val, sim_val):
    """Append one calibration iteration to the model's EVALUATIONS CSVs.

    Shared tail of every ``_execute_*_direct`` function: writes the
    iteration's parameters/metric row plus the matched obs/sim arrays to
    ``<tag>_Metric_<suffix>.csv``, ``<tag>_Obs_<suffix>.csv`` and
    ``<tag>_Sim_<suffix>.csv``.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    tag : str
        Model tag used in the output file names (e.g. ``'AWY'``, ``'NDR_N'``).
    suffix : str
        Project results suffix (``user_data['Suffix']``).
    header : str
        Comma-separated header for the ``_Metric_`` CSV.
    row : str
        Comma-separated data row for the ``_Metric_`` CSV.
    obs_val : numpy.ndarray
        Observed values for this iteration.
    sim_val : numpy.ndarray
        Simulated values for this iteration.
    """
    _save_eval_csv(workspace, f'{tag}_Metric_{suffix}.csv', header, [row])
    _save_eval_csv(workspace, f'{tag}_Obs_{suffix}.csv', 'Obs',
                   [f'{v:.2f}' for v in obs_val])
    _save_eval_csv(workspace, f'{tag}_Sim_{suffix}.csv', 'Sim',
                   [f'{v:.2f}' for v in sim_val])


# ---------------------------------------------------------------------------
# AWY calibration iteration
# ---------------------------------------------------------------------------

def _execute_awy_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """Run one AWY calibration iteration and score it against observations.

    Applies the candidate ``Z`` / ``Factor-Kc`` parameters to a temporary
    biophysical table, runs ``natcap.invest.annual_water_yield``, compares
    simulated watershed yield against ``obs_df``, and appends the
    iteration's parameters/metric/obs/sim to the EVALUATIONS CSVs.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    vector : sequence of float
        Candidate parameter vector ``[Z, Factor-Kc]`` proposed by spotpy.
    metric_name : str
        Objective function name, as used by ``Spotpy_InVEST.Cal_FunObj``.
    factor_metric : float
        ``+1`` or ``-1``; flips the sign of the metric so that every
        optimization algorithm consistently searches in the same
        direction (minimize vs. maximize).
    obs_df : pandas.DataFrame
        Observed data table (must contain ``ws_id`` and ``AWY`` columns).
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.

    Returns
    -------
    float
        ``factor_metric``-adjusted objective function value for this
        iteration.
    """
    import natcap.invest.annual_water_yield as _awy  # noqa: PLC0415

    z, kc = float(vector[0]), float(vector[1])
    params = {'Z': z, 'Factor-Kc': kc}

    LOGGER.info(f'AWY  Z={z:.2f}  Factor-Kc={kc:.2f}')

    tmp_bio = _write_temp_biotable(si, mp, user_data, params, workspace, 'AWY')

    out_dir = os.path.join(workspace, 'OUTPUTS', '01-AWY')
    suffix  = user_data['Suffix']
    awy_args = {
        'lulc_path':                    mp['lulc_path'],
        'biophysical_table_path':       tmp_bio,
        'depth_to_root_rest_layer_path': mp['depth_to_root_rest_layer_path'],
        'eto_path':                     mp['eto_path'],
        'pawc_path':                    mp['pawc_path'],
        'precipitation_path':           mp['precipitation_path'],
        'watersheds_path':              mp['calibration_watersheds_path'],
        'seasonality_constant':         '%.2f' % z,
        'results_suffix':               suffix,
        'workspace_dir':                out_dir,
    }
    if mp['sub_watersheds_path']:
        awy_args['sub_watersheds_path'] = mp['sub_watersheds_path']

    _awy.execute(awy_args)

    suffix_part = f'_{suffix}' if suffix else ''
    sim_df  = pd.read_csv(os.path.join(out_dir, 'output',
                          f'watershed_results_wyield{suffix_part}.csv'))
    obj, obs_val, sim_val = _score_against_obs(
        si, sim_df, 'wyield_vol', obs_df, 'AWY', metric_name, factor_metric)

    _save_iteration(workspace, 'AWY', user_data['Suffix'],
                     f'Z,Factor-Kc,{metric_name}',
                     f'{z:.2f},{kc:.2f},{obj:.2f}', obs_val, sim_val)
    return obj


# ---------------------------------------------------------------------------
# SWY calibration iteration
# ---------------------------------------------------------------------------

def _execute_swy_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """Run one SWY calibration iteration and score it against observations.

    Applies the candidate ``Alpha``/``Beta``/``Gamma``/``Factor-Kc_m``
    parameters to a temporary biophysical table, runs
    ``natcap.invest.seasonal_water_yield``, computes zonal-mean actual
    evapotranspiration per watershed, compares it against ``obs_df``, and
    appends the iteration's data to the EVALUATIONS CSVs.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    vector : sequence of float
        Candidate parameter vector ``[Alpha, Beta, Gamma, Factor-Kc_m]``
        proposed by spotpy.
    metric_name : str
        Objective function name, as used by ``Spotpy_InVEST.Cal_FunObj``.
    factor_metric : float
        ``+1`` or ``-1``; flips the sign of the metric so every
        optimization algorithm searches in the same direction.
    obs_df : pandas.DataFrame
        Observed data table (must contain ``ws_id`` and ``SWY`` columns).
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.

    Returns
    -------
    float
        ``factor_metric``-adjusted objective function value for this
        iteration.
    """
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415

    alpha, beta, gamma, kc_m = (float(vector[i]) for i in range(4))
    params = {'Alpha': alpha, 'Beta': beta, 'Gamma': gamma, 'Factor-Kc_m': kc_m}

    LOGGER.info(f'SWY  Alpha={alpha:.3f}  Beta={beta:.3f}  Gamma={gamma:.3f}  Kc_m={kc_m:.2f}')

    tmp_bio = _write_temp_biotable(si, mp, user_data, params, workspace, 'SWY')

    out_dir  = os.path.join(workspace, 'OUTPUTS', '02-SWY')
    suffix   = user_data['Suffix']

    swy_args = {
        'lulc_raster_path':              mp['lulc_path'],
        'biophysical_table_path':        tmp_bio,
        'et0_raster_table':              mp['eto_raster_table'],
        'precip_raster_table':           mp['precip_raster_table'],
        'rain_events_table_path':        mp['rain_events_table_path'],
        'soil_group_path':               mp['soil_group_path'],
        'dem_raster_path':               mp['dem_path'],
        'aoi_path':                      mp['calibration_watersheds_path'],
        'threshold_flow_accumulation':   '%0.0f' % mp['threshold_flow_accumulation'],
        'flow_dir_algorithm':            'D8',
        'alpha_m':                       '%.3f' % alpha,
        'beta_i':                        '%.3f' % beta,
        'gamma':                         '%.3f' % gamma,
        'monthly_alpha':                 False,
        'user_defined_climate_zones':    False,
        'user_defined_local_recharge':   False,
        'results_suffix':                suffix,
        'workspace_dir':                 out_dir,
    }
    if mp['sub_watersheds_path']:
        swy_args['sub_watersheds_path'] = mp['sub_watersheds_path']

    _swy.execute(swy_args)

    raster = os.path.join(out_dir, 'intermediate_outputs', f'aet_{suffix}.tif')
    sim_df  = si.calculate_zonal_stats(mp['calibration_watersheds_path'],
                                       raster, os.path.join(workspace, 'TMP'),
                                       Suffix='SWY')
    obj, obs_val, sim_val = _score_against_obs(
        si, sim_df, 'mean', obs_df, 'SWY', metric_name, factor_metric)

    _save_iteration(workspace, 'SWY', user_data['Suffix'],
                     f'Alpha,Beta,Gamma,Factor-Kc_m,{metric_name}',
                     f'{alpha:.3f},{beta:.3f},{gamma:.3f},{kc_m:.2f},{obj:.2f}',
                     obs_val, sim_val)
    return obj


# ---------------------------------------------------------------------------
# SDR calibration iteration
# ---------------------------------------------------------------------------

def _execute_sdr_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """Run one SDR calibration iteration and score it against observations.

    Applies the candidate ``sdr_max``/``Borselli-K_SDR``/``IC0``/``L_max``/
    ``Factor-C``/``Factor-P`` parameters to a temporary biophysical table,
    runs ``natcap.invest.sdr``, compares simulated sediment export against
    ``obs_df``, and appends the iteration's data to the EVALUATIONS CSVs.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    vector : sequence of float
        Candidate parameter vector
        ``[sdr_max, Borselli-K_SDR, IC0, L_max, Factor-C, Factor-P]``
        proposed by spotpy.
    metric_name : str
        Objective function name, as used by ``Spotpy_InVEST.Cal_FunObj``.
    factor_metric : float
        ``+1`` or ``-1``; flips the sign of the metric so every
        optimization algorithm searches in the same direction.
    obs_df : pandas.DataFrame
        Observed data table (must contain ``ws_id`` and ``SDR`` columns).
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.

    Returns
    -------
    float
        ``factor_metric``-adjusted objective function value for this
        iteration.
    """
    from natcap.invest.sdr import sdr as _sdr  # noqa: PLC0415
    from simpledbf import Dbf5                  # noqa: PLC0415

    sdr_max, k_sdr, ic0, l_max, fc, fp = (float(vector[i]) for i in range(6))
    params = {
        'sdr_max': sdr_max, 'Borselli-K_SDR': k_sdr, 'IC0': ic0,
        'L_max': l_max, 'Factor-C': fc, 'Factor-P': fp,
    }

    LOGGER.info(f'SDR  sdr_max={sdr_max:.2f}  K={k_sdr:.2f}  IC0={ic0:.2f}  '
                f'L_max={l_max:.2f}  C={fc:.5f}  P={fp:.5f}')

    tmp_bio = _write_temp_biotable(si, mp, user_data, params, workspace, 'SDR')

    out_dir  = os.path.join(workspace, 'OUTPUTS', '03-SDR')
    suffix   = user_data['Suffix']
    sdr_args = {
        'lulc_path':                  mp['lulc_path'],
        'biophysical_table_path':     tmp_bio,
        'dem_path':                   mp['dem_path'],
        'erosivity_path':             mp['erosivity_path'],
        'erodibility_path':           mp['erodibility_path'],
        'watersheds_path':            mp['calibration_watersheds_path'],
        'threshold_flow_accumulation': '%0.0f' % mp['threshold_flow_accumulation'],
        'sdr_max':                    '%.2f' % sdr_max,
        'ic_0_param':                 '%.2f' % ic0,
        'l_max':                      '%.2f' % l_max,
        'k_param':                    '%.2f' % k_sdr,
        'flow_dir_algorithm':         'MFD',
        'results_suffix':             suffix,
        'workspace_dir':              out_dir,
    }
    if mp['sub_watersheds_path']:
        sdr_args['sub_watersheds_path'] = mp['sub_watersheds_path']

    _sdr.execute(sdr_args)

    dbf_path = os.path.join(out_dir, f'watershed_results_sdr_{suffix}.dbf')
    sim_df   = Dbf5(dbf_path).to_dataframe()
    obj, obs_val, sim_val = _score_against_obs(
        si, sim_df, 'sed_export', obs_df, 'SDR', metric_name, factor_metric)

    _save_iteration(
        workspace, 'SDR', user_data['Suffix'],
        f'sdr_max,k_param,ic_0_param,l_max,Factor-C,Factor-P,{metric_name}',
        f'{sdr_max:.2f},{k_sdr:.2f},{ic0:.2f},{l_max:.2f},{fc:.5f},{fp:.5f},{obj:.2f}',
        obs_val, sim_val)
    return obj


# ---------------------------------------------------------------------------
# NDR calibration iteration (N or P)
# ---------------------------------------------------------------------------

def _execute_ndr_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si,
                        model_name):
    """Run one NDR_N or NDR_P calibration iteration and score it.

    Applies the candidate nutrient-delivery parameters to a temporary
    biophysical table, runs ``natcap.invest.ndr`` with either nitrogen or
    phosphorus calculation enabled (based on ``model_name``), computes
    zonal-sum export per watershed, compares it against ``obs_df``, and
    appends the iteration's data to the EVALUATIONS CSVs.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    vector : sequence of float
        Candidate parameter vector. For ``NDR_N``:
        ``[SubCri_Len_N, Sub_Eff_N, Borselli-K_NDR, Factor_Load_N, Factor_Eff_N]``.
        For ``NDR_P``:
        ``[SubCri_Len_P, Sub_Eff_P, Borselli-K_NDR, Factor_Load_P, Factor_Eff_P]``.
    metric_name : str
        Objective function name, as used by ``Spotpy_InVEST.Cal_FunObj``.
    factor_metric : float
        ``+1`` or ``-1``; flips the sign of the metric so every
        optimization algorithm searches in the same direction.
    obs_df : pandas.DataFrame
        Observed data table (must contain ``ws_id`` and either ``NDR_N``
        or ``NDR_P`` columns, matching ``model_name``).
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.
    model_name : {'NDR_N', 'NDR_P'}
        Which nutrient to calibrate.

    Returns
    -------
    float
        ``factor_metric``-adjusted objective function value for this
        iteration.
    """
    from natcap.invest.ndr import ndr as _ndr  # noqa: PLC0415

    if model_name == 'NDR_N':
        # NDR_N vector order matches _build_spotpy_params:
        # SubCri_Len_N, Sub_Eff_N, Borselli-K_NDR, Factor_Load_N, Factor_Eff_N
        subcri_n, sub_eff_n, k_ndr, load_n, eff_n = (float(vector[i]) for i in range(5))
        params = {
            'SubCri_Len_N': subcri_n, 'Sub_Eff_N': sub_eff_n,
            'Borselli-K_NDR': k_ndr, 'Factor_Load_N': load_n, 'Factor_Eff_N': eff_n,
        }
        LOGGER.info(f'NDR_N  SubCri={subcri_n:.2f}  SubEff={sub_eff_n:.2f}  '
                    f'K={k_ndr:.2f}  Load={load_n:.2f}  Eff={eff_n:.2f}')
        ndr_extra = {'calc_n': True, 'calc_p': False,
                     'subsurface_critical_length_n': '%.2f' % subcri_n,
                     'subsurface_eff_n':             '%.2f' % sub_eff_n}
    else:  # NDR_P
        # Vector order matches _build_spotpy_params:
        # SubCri_Len_P, Sub_Eff_P, Borselli-K_NDR, Factor_Load_P, Factor_Eff_P
        subcri_p, sub_eff_p, k_ndr, load_p, eff_p = (float(vector[i]) for i in range(5))
        params = {
            'SubCri_Len_P': subcri_p, 'Sub_Eff_P': sub_eff_p,
            'Borselli-K_NDR': k_ndr, 'Factor_Load_P': load_p, 'Factor_Eff_P': eff_p,
        }
        LOGGER.info(f'NDR_P  SubCri={subcri_p:.2f}  SubEff={sub_eff_p:.2f}  '
                    f'K={k_ndr:.2f}  Load={load_p:.2f}  Eff={eff_p:.2f}')
        ndr_extra = {'calc_n': False, 'calc_p': True,
                     'subsurface_critical_length_p': '%.2f' % subcri_p,
                     'subsurface_eff_p':             '%.2f' % sub_eff_p}

    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    if model_name == 'NDR_N' and 'load_type_n' not in table.columns:
        table['load_type_n'] = 'measured-runoff'
    if model_name == 'NDR_P' and 'load_type_p' not in table.columns:
        table['load_type_p'] = 'measured-runoff'
    tmp_bio = os.path.join(workspace, 'TMP', f'{model_name}_biophysical.csv')
    table.to_csv(tmp_bio, index=False)

    out_dir = os.path.join(workspace, 'OUTPUTS',
                           '04-NDR_N' if model_name == 'NDR_N' else '04-NDR_P')
    suffix  = user_data['Suffix']
    ndr_args = {
        'lulc_path':                  mp['lulc_path'],
        'biophysical_table_path':     tmp_bio,
        'dem_path':                   mp['dem_path'],
        'runoff_proxy_path':          mp['precipitation_path'],
        'watersheds_path':            mp['calibration_watersheds_path'],
        'threshold_flow_accumulation': '%0.0f' % mp['threshold_flow_accumulation'],
        'k_param':                    '%.2f' % k_ndr,
        'flow_dir_algorithm':         'MFD',
        'results_suffix':             suffix,
        'workspace_dir':              out_dir,
        **ndr_extra,
    }
    if mp['sub_watersheds_path']:
        ndr_args['sub_watersheds_path'] = mp['sub_watersheds_path']

    _ndr.execute(ndr_args)

    if model_name == 'NDR_N':
        raster  = os.path.join(out_dir, f'n_total_export_{suffix}.tif')
        obs_col = 'NDR_N'
        sim_col = 'sum'
    else:
        raster  = os.path.join(out_dir, f'p_surface_export_{suffix}.tif')
        obs_col = 'NDR_P'
        sim_col = 'sum'

    sim_df  = si.calculate_zonal_stats(mp['calibration_watersheds_path'],
                                       raster, os.path.join(workspace, 'TMP'),
                                       Suffix=model_name)
    obj, obs_val, sim_val = _score_against_obs(
        si, sim_df, sim_col, obs_df, obs_col, metric_name, factor_metric)

    if model_name == 'NDR_N':
        hdr   = f'SubCri_Len_N,Sub_Eff_N,Borselli-K,Factor_Load_N,Factor_Eff_N,{metric_name}'
        p_row = f'{subcri_n:.2f},{sub_eff_n:.2f},{k_ndr:.2f},{load_n:.2f},{eff_n:.2f},{obj:.2f}'
    else:
        hdr   = f'SubCri_Len_P,Sub_Eff_P,Borselli-K,Factor_Load_P,Factor_Eff_P,{metric_name}'
        p_row = f'{subcri_p:.2f},{sub_eff_p:.2f},{k_ndr:.2f},{load_p:.2f},{eff_p:.2f},{obj:.2f}'

    _save_iteration(workspace, model_name, user_data['Suffix'], hdr, p_row, obs_val, sim_val)
    return obj


# ---------------------------------------------------------------------------
# Final best-parameters run for each model
# ---------------------------------------------------------------------------

def _run_best_params(workspace, model_name, mp, user_data, params_val, si):
    """Run the selected InVEST model once with the best-fit parameters.

    Builds the final biophysical table from ``params_val``, then calls
    the corresponding InVEST model (AWY / SWY / SDR / NDR) with the full
    (non-calibration) watershed set, writing results to
    ``OUTPUTS/<model_name>_best``.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    model_name : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    mp : dict
        ``model_paths`` dict from :func:`_build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`_build_user_data`.
    params_val : dict
        Final parameter values to use, keyed by internal parameter name
        (typically the calibration's best-fit result merged with the
        initial guess for any parameter the model didn't calibrate).
    si : module
        The ``Spotpy_InVEST`` module, as returned by :func:`_get_si`.

    Returns
    -------
    None
        Results are written to disk under ``OUTPUTS/<model_name>_best``;
        nothing is returned.
    """
    import natcap.invest.annual_water_yield as _awy       # noqa: PLC0415
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415
    from natcap.invest.sdr import sdr as _sdr             # noqa: PLC0415
    from natcap.invest.ndr import ndr as _ndr             # noqa: PLC0415

    out_dir = os.path.join(workspace, 'OUTPUTS', f'{model_name}_best')
    os.makedirs(out_dir, exist_ok=True)
    suffix  = user_data['Suffix']

    table = si.Factor_BioTable(mp['biophysical_table_path'], params_val, user_data)
    if model_name == 'NDR_N' and 'load_type_n' not in table.columns:
        table['load_type_n'] = 'measured-runoff'
    if model_name == 'NDR_P' and 'load_type_p' not in table.columns:
        table['load_type_p'] = 'measured-runoff'
    tmp_bio = os.path.join(out_dir, f'{model_name}_BioTable_best.csv')
    table.to_csv(tmp_bio, index=False)
    tfa     = '%0.0f' % mp['threshold_flow_accumulation'] if mp['threshold_flow_accumulation'] is not None else ''
    sub_ws  = mp.get('sub_watersheds_path', '')

    if model_name == 'AWY':
        invest_args = {
            'lulc_path':                    mp['lulc_path'],
            'biophysical_table_path':       tmp_bio,
            'depth_to_root_rest_layer_path': mp['depth_to_root_rest_layer_path'],
            'eto_path':                     mp['eto_path'],
            'pawc_path':                    mp['pawc_path'],
            'precipitation_path':           mp['precipitation_path'],
            'watersheds_path':              mp['watersheds_path'],
            'seasonality_constant':         '%.2f' % params_val.get('Z', 3.0),
            'results_suffix':               suffix,
            'workspace_dir':                out_dir,
        }
        if sub_ws:
            invest_args['sub_watersheds_path'] = sub_ws
        _awy.execute(invest_args)

    elif model_name == 'SWY':
        invest_args = {
            'lulc_raster_path':              mp['lulc_path'],
            'biophysical_table_path':        tmp_bio,
            'et0_raster_table':              mp['eto_raster_table'],
            'precip_raster_table':           mp['precip_raster_table'],
            'rain_events_table_path':        mp['rain_events_table_path'],
            'soil_group_path':               mp['soil_group_path'],
            'dem_raster_path':               mp['dem_path'],
            'aoi_path':                      mp['watersheds_path'],  # SWY uses aoi_path
            'flow_dir_algorithm':            'D8',
            'threshold_flow_accumulation':   tfa,
            'alpha_m':                       '%.3f' % params_val.get('Alpha', 1.0),
            'beta_i':                        '%.3f' % params_val.get('Beta', 1.0),
            'gamma':                         '%.3f' % params_val.get('Gamma', 1.0),
            'monthly_alpha':                 False,
            'user_defined_climate_zones':    False,
            'user_defined_local_recharge':   False,
            'results_suffix':                suffix,
            'workspace_dir':                 out_dir,
        }
        if sub_ws:
            invest_args['sub_watersheds_path'] = sub_ws
        _swy.execute(invest_args)

    elif model_name == 'SDR':
        invest_args = {
            'lulc_path':                  mp['lulc_path'],
            'biophysical_table_path':     tmp_bio,
            'dem_path':                   mp['dem_path'],
            'erosivity_path':             mp['erosivity_path'],
            'erodibility_path':           mp['erodibility_path'],
            'watersheds_path':            mp['watersheds_path'],
            'threshold_flow_accumulation': tfa,
            'sdr_max':                    '%.2f' % params_val.get('sdr_max', 0.8),
            'ic_0_param':                 '%.2f' % params_val.get('IC0', 0.5),
            'l_max':                      '%.2f' % params_val.get('L_max', 122.0),
            'k_param':                    '%.2f' % params_val.get('Borselli-K_SDR', 2.0),
            'flow_dir_algorithm':         'MFD',
            'results_suffix':             suffix,
            'workspace_dir':              out_dir,
        }
        if sub_ws:
            invest_args['sub_watersheds_path'] = sub_ws
        _sdr.execute(invest_args)

    elif model_name in ('NDR_N', 'NDR_P'):
        is_n = (model_name == 'NDR_N')
        invest_args = {
            'lulc_path':                  mp['lulc_path'],
            'biophysical_table_path':     tmp_bio,
            'dem_path':                   mp['dem_path'],
            'runoff_proxy_path':          mp['precipitation_path'],
            'watersheds_path':            mp['watersheds_path'],
            'threshold_flow_accumulation': tfa,
            'k_param':                    '%.2f' % params_val.get('Borselli-K_NDR', 2.0),
            'flow_dir_algorithm':         'MFD',
            'calc_n':                     is_n,
            'calc_p':                     not is_n,
            'results_suffix':             suffix,
            'workspace_dir':              out_dir,
        }
        if is_n:
            invest_args['subsurface_critical_length_n'] = '%.2f' % params_val.get('SubCri_Len_N', 150)
            invest_args['subsurface_eff_n']             = '%.2f' % params_val.get('Sub_Eff_N', 0.8)
        else:
            invest_args['subsurface_critical_length_p'] = '%.2f' % params_val.get('SubCri_Len_P', 150)
            invest_args['subsurface_eff_p']             = '%.2f' % params_val.get('Sub_Eff_P', 0.8)
        if sub_ws:
            invest_args['sub_watersheds_path'] = sub_ws
        _ndr.execute(invest_args)

    LOGGER.info(f'{model_name} best-parameters run complete → {out_dir}')


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------

def execute(args):
    """Entry point for the InVEST Calibration Assistant plugin.

    Orchestrates a full calibration run for the model selected via
    ``args['model_name']``: builds inputs, runs the spotpy sampler
    (DDS / SCE-UA / LHS) for ``n_simulations`` iterations, generates
    calibration plots to identify the best-fit parameter set, and
    finally re-runs the InVEST model once with those best-fit
    parameters over the full watershed set.

    Parameters
    ----------
    args : dict
        Keys defined in ``MODEL_SPEC``. Required keys vary by
        ``model_name``; the Workbench enforces this through the
        ``required``/``allowed`` expressions on each input.

    Returns
    -------
    dict
        Empty dict, as required by the InVEST plugin framework's
        ``execute()`` contract (a file-registry placeholder).
    """
    LOGGER.info('=' * 60)
    LOGGER.info('InVEST Calibration Assistant')
    LOGGER.info('=' * 60)

    start_time = datetime.now()

    workspace  = args['workspace_dir']
    model_name = args['model_name']
    metric     = args['evaluation_metric']
    method     = args['optimization_method']
    n_sim      = int(args['n_simulations'])

    LOGGER.info(f'Workspace     : {workspace}')
    LOGGER.info(f'Model         : {model_name}')
    LOGGER.info(f'Metric        : {metric}')
    LOGGER.info(f'Method        : {method}')
    LOGGER.info(f'N simulations : {n_sim}')

    os.makedirs(workspace, exist_ok=True)

    # ------------------------------------------------------------------
    # 1. Collect inputs
    # ------------------------------------------------------------------
    mp        = _build_model_paths(args)
    user_data = _build_user_data(model_name, mp)
    params_val, params_min, params_max = _read_param_ranges(
        args['parameter_search_ranges_path'])
    obs_df = pd.read_csv(args['observed_data_path'])

    # ------------------------------------------------------------------
    # 2. Deferred import of calibration engine
    # ------------------------------------------------------------------
    si = _get_si()

    # ------------------------------------------------------------------
    # 3. Create output sub-directories
    # ------------------------------------------------------------------
    for sub in ['EVALUATIONS', 'PARAMETERS', 'OUTPUTS', 'FIGURES', 'TMP']:
        si.CreateFolder(os.path.join(workspace, sub))

    # ------------------------------------------------------------------
    # 4. Optimisation direction
    # ------------------------------------------------------------------
    factor_metric = -1 if method == 'Dynamical dimensional search (DDS)' else 1

    # ------------------------------------------------------------------
    # 5. Map model name → simulation function
    # ------------------------------------------------------------------
    _sim_fn_map = {
        'AWY':   _execute_awy_direct,
        'SWY':   _execute_swy_direct,
        'SDR':   _execute_sdr_direct,
    }

    def _sim_fn(vec):
        """Dispatch one calibration iteration to the model-specific runner."""
        if model_name in ('NDR_N', 'NDR_P'):
            return _execute_ndr_direct(workspace, mp, user_data, vec,
                                       metric, factor_metric, obs_df, si,
                                       model_name)
        return _sim_fn_map[model_name](workspace, mp, user_data, vec,
                                      metric, factor_metric, obs_df, si)

    # ------------------------------------------------------------------
    # 6. Build Spotpy setup class
    # ------------------------------------------------------------------
    import spotpy  # noqa: PLC0415

    _params = _build_spotpy_params(model_name, params_min, params_max)
    _obs    = obs_df

    class _SpotpyPlugin:
        """Spotpy setup object matching the original Spotpy_InVEST pattern.

        - simulation()        → returns the parameter vector (np.array)
        - evaluation()        → returns the observed-data DataFrame
        - objectivefunction() → runs InVEST and returns the metric float

        Spotpy stores evaluation() once at startup via
        ``self.evaluation = self.setup.evaluation()`` and passes that stored
        result as the ``evaluation`` kwarg to objectivefunction().  The heavy
        work therefore goes in objectivefunction(), exactly as in the original
        Spotpy_InVEST.Spotpy_InVEST class.
        """

        def parameters(self):
            return spotpy.parameter.generate(_params)

        def simulation(self, vector):
            # Just return the parameter vector; spotpy passes it to
            # objectivefunction as the ``simulation`` argument.
            return np.array(vector)

        def evaluation(self):
            return _obs  # observed-data DataFrame (captured from closure)

        def objectivefunction(self, simulation, evaluation, **kwargs):
            # simulation = parameter vector (np.array from simulation())
            # evaluation = obs_df (stored by spotpy at startup)
            # **kwargs absorbs the ``params`` arg added in newer spotpy
            return _sim_fn(simulation)

    # ------------------------------------------------------------------
    # 7. Run calibration sampler
    # ------------------------------------------------------------------
    LOGGER.info('Starting calibration …')
    spot_setup = _SpotpyPlugin()
    parallel   = 'seq'
    dbformat   = 'csv'
    timeout    = 2

    if method == 'Dynamical dimensional search (DDS)':
        db_path = os.path.join(workspace, 'PARAMETERS', f'{model_name}_DDS')
        sampler = spotpy.algorithms.dds(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)
    elif method == 'Shuffled Complex Evolution (SCE-UA)':
        db_path = os.path.join(workspace, 'PARAMETERS', f'{model_name}_SCE')
        sampler = spotpy.algorithms.sceua(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)
    else:
        db_path = os.path.join(workspace, 'PARAMETERS', f'{model_name}_LHS')
        sampler = spotpy.algorithms.lhs(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)

    sampler.sample(n_sim)

    # ------------------------------------------------------------------
    # 8. Generate calibration plots
    # ------------------------------------------------------------------
    LOGGER.info('Generating calibration plots …')
    fo_label = {
        'Mean Square Error (MSE)':                   'MSE',
        'Mean Absolute Error (MAE)':                 'MAE',
        'Root Mean Square Error (RMSE)':             'RMSE',
        'Relative Root Mean Squared Error (RRMSE)':  'RRMSE',
    }.get(metric, 'RMSE')

    project_name = mp['project_suffix']

    _plot_fn = {
        'AWY':   si.Plot_AWY,
        'SWY':   si.Plot_SWY,
        'SDR':   si.Plot_SDR,
        'NDR_N': si.Plot_NDR_N,
        'NDR_P': si.Plot_NDR_P,
    }.get(model_name)

    best_params = None
    best_metric_value = None
    if _plot_fn is not None:
        try:
            best_params, best_metric_value = _plot_fn(
                workspace, project_name, fo_label, workspace, factor_metric)
        except Exception:
            LOGGER.exception(
                'Could not generate calibration plots / determine the best-fit '
                'parameter set; falling back to the initial parameter guess.')

    # ------------------------------------------------------------------
    # 9. Final run with best-fit parameters
    # ------------------------------------------------------------------
    used_fallback = not best_params
    if best_params:
        LOGGER.info(f'Best-fit parameters found by calibration: {best_params}')
        final_params_val = {**params_val, **best_params}
    else:
        LOGGER.warning(
            'No valid best-fit parameter set was found by the calibration run; '
            'using the initial parameter guess for the final run instead.')
        final_params_val = params_val

    LOGGER.info('Running InVEST with best-fit parameters …')
    _run_best_params(workspace, model_name, mp, user_data, final_params_val, si)

    # ------------------------------------------------------------------
    # 10. Build and open the HTML calibration report
    # ------------------------------------------------------------------
    end_time = datetime.now()
    try:
        report_path = Report_InVEST.Build_HTML_Report(
            ProjectPath=workspace,
            Suffix=project_name,
            ModelName=model_name,
            MethodShort=_METHOD_SHORT.get(method, method),
            MetricShort=fo_label,
            NSim=n_sim,
            StartTime=start_time,
            EndTime=end_time,
            InvestVersion=_invest_version(),
            InputsSummary=_inputs_summary(mp),
            ParamsMin=params_min,
            ParamsMax=params_max,
            ParamsVal=params_val,
            FinalParams=final_params_val,
            BestMetricValue=best_metric_value,
            UsedFallback=used_fallback,
            StatusCalDetail=_status_cal_summary(mp['biophysical_table_path'], model_name),
        )
        LOGGER.info(f'Calibration report written to: {report_path}')
        try:
            webbrowser.open('file://' + os.path.abspath(report_path))
        except Exception:
            LOGGER.exception('Could not open the calibration report automatically.')
    except Exception:
        LOGGER.exception('Could not build the HTML calibration report.')

    LOGGER.info('=' * 60)
    LOGGER.info(f'Calibration complete: {model_name}')
    LOGGER.info('=' * 60)

    return {}  # InVEST framework expects a file-registry dict from execute()


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

@validation.invest_validator
def validate(args, limit_to=None):
    """Validate plugin arguments against ``MODEL_SPEC``.

    In addition to the standard ``MODEL_SPEC`` validation, checks that
    ``n_simulations`` is a valid integer >= 10 (required by the DDS
    algorithm's initialization phase).

    Parameters
    ----------
    args : dict
        Arguments to validate, keyed as in ``MODEL_SPEC``.
    limit_to : str, optional
        If given, restrict validation to this single input id.

    Returns
    -------
    list of tuple
        ``(keys, message)`` warnings, in the format expected by the
        InVEST validation framework.
    """
    warnings = validation.validate(args, MODEL_SPEC)

    if limit_to is None or limit_to == 'n_simulations':
        try:
            n = int(args.get('n_simulations', 0))
            if n < 10:
                warnings.append(
                    (['n_simulations'],
                     'Number of simulations must be at least 10. '
                     'The DDS optimization algorithm requires a minimum of '
                     '10 iterations for its initialization phase.'))
        except (ValueError, TypeError):
            warnings.append(
                (['n_simulations'],
                 'Number of simulations must be a valid integer.'))

    return warnings
