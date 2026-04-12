# -*- coding: utf-8 -*-
"""
TNC InVEST Calibration Assistant - InVEST Plugin

Nature For Water Facility - The Nature Conservancy
Author  : Jonathan Nogales Pimentel / Miguel Angel Cañon
Email   : jonathan.nogales@tnc.org
Date    : 2025

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

import logging
import os

import numpy as np
import pandas as pd

from natcap.invest import gettext
from natcap.invest import spec
from natcap.invest import validation
from natcap.invest.unit_registry import u

LOGGER = logging.getLogger(__name__)


def _get_si():
    """Lazy import of Spotpy_InVEST – only loaded when execute() is called."""
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
_AWY_SWY        = 'model_name in ["AWY", "SWY"]'
_SWY_SDR_NDR    = 'model_name in ["SWY", "SDR", "NDR_N", "NDR_P"]'
_SWY_NDR        = 'model_name in ["SWY", "NDR_N", "NDR_P"]'
_AWY_NDR        = 'model_name in ["AWY", "NDR_N", "NDR_P"]'
_NDR            = 'model_name in ["NDR_N", "NDR_P"]'


# ---------------------------------------------------------------------------
# MODEL SPEC
# ---------------------------------------------------------------------------
MODEL_SPEC = spec.ModelSpec(
    model_id="invest_calibration_assistant",
    model_title=gettext("TNC InVEST Calibration Assistant"),
    module_name=__name__,
    userguide='',
    input_field_order=[
        ['workspace_dir', 'results_suffix'],
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

        # ── AWY + SWY ─────────────────────────────────────────────────────
        ['depth_to_root_rest_layer_path'],
        ['pawc_path'],

        # ── SWY, SDR, NDR (DEM) ──────────────────────────────────────────
        ['dem_path'],

        # ── SWY + NDR (soil group) ────────────────────────────────────────
        ['soil_group_path'],

        # ── SWY only: monthly folders + rain table ────────────────────────
        ['eto_monthly_dir'],
        ['precip_monthly_dir'],
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
        spec.DirectoryInput(
            id='workspace_dir',
            name=gettext('Workspace'),
            about=gettext(
                'Output folder for all calibration results. '
                'Sub-folders EVALUATIONS, PARAMETERS, OUTPUTS, FIGURES '
                'and TMP are created automatically.'),
            contents=[],
            must_exist=False,
            permissions='rwx',
        ),
        spec.StringInput(
            id='results_suffix',
            name=gettext('File Suffix'),
            about=gettext(
                'Optional text appended to every output file name.'),
            required=False,
            regexp='[a-zA-Z0-9_-]*',
        ),
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
                'Required columns vary by model (see InVEST documentation).'),
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
                'Used for stream delineation.'),
            units=None,
            expression='value > 0',
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
        # AWY + SWY – Root depth and PAWC
        # ==================================================================
        spec.SingleBandRasterInput(
            id='depth_to_root_rest_layer_path',
            name=gettext('Root Restricting Layer Depth'),
            about=gettext(
                'Depth to the root restricting layer raster (mm). '
                'Required for AWY and SWY.'),
            projected=True,
            units=u.millimeter,
            required=_AWY_SWY,
            allowed=_AWY_SWY,
        ),
        spec.SingleBandRasterInput(
            id='pawc_path',
            name=gettext('Plant Available Water Content'),
            about=gettext(
                'Plant available water content raster (fraction 0–1). '
                'Required for AWY and SWY.'),
            projected=True,
            units=None,
            required=_AWY_SWY,
            allowed=_AWY_SWY,
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
        # SWY + NDR – Hydrologic Soil Group
        # ==================================================================
        spec.SingleBandRasterInput(
            id='soil_group_path',
            name=gettext('Hydrologic Soil Group'),
            about=gettext(
                'Hydrologic soil group raster. Values must be integers '
                '1–4 representing groups A, B, C, D. '
                'Required for SWY and NDR.'),
            projected=True,
            units=None,
            required=_SWY_NDR,
            allowed=_SWY_NDR,
        ),

        # ==================================================================
        # SWY ONLY – Monthly ETP folder, Monthly P folder, Rain events table
        # ==================================================================
        spec.DirectoryInput(
            id='eto_monthly_dir',
            name=gettext('Monthly ETP Folder'),
            about=gettext(
                'Folder containing 12 monthly reference evapotranspiration '
                'rasters named with month numbers (e.g. eto_1.tif … eto_12.tif). '
                'Required for SWY only.'),
            contents=[],
            must_exist=True,
            permissions='r',
            required=_SWY,
            allowed=_SWY,
        ),
        spec.DirectoryInput(
            id='precip_monthly_dir',
            name=gettext('Monthly Precipitation Folder'),
            about=gettext(
                'Folder containing 12 monthly precipitation rasters '
                'named with month numbers (e.g. precip_1.tif … precip_12.tif). '
                'Required for SWY only.'),
            contents=[],
            must_exist=True,
            permissions='r',
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
                'The "Model" column is informational (AWY / SWY / SDR / NDR).'),
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
                'Unused model columns are ignored.'),
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
                'Total model evaluations during calibration. Must be > 1. '
                'Larger values improve parameter estimation at the cost of time.'),
            expression='value > 1',
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
    ],
)


# ---------------------------------------------------------------------------
# Build model_paths dict from individual UI fields
# ---------------------------------------------------------------------------

def _build_model_paths(args):
    """Extract spatial input paths from args into a unified model_paths dict.

    Returns a dict with all relevant file paths for the selected model,
    using None for fields that are not applicable to the current model.
    """
    m = args['model_name']

    def _get(key):
        return args.get(key) or ''

    mp = {
        # -- shared
        'lulc_path':                    args['lulc_path'],
        'biophysical_table_path':       args['biophysical_table_path'],
        'calibration_watersheds_path':  args['calibration_watersheds_path'],
        # Fall back to calibration watershed when no separate final-run watershed is given
        'watersheds_path':              _get('watersheds_path') or args['calibration_watersheds_path'],
        'sub_watersheds_path':          _get('awy_sub_watersheds_path'),
        'threshold_flow_accumulation':  float(args['threshold_flow_accumulation']),
        'project_suffix':               _get('project_suffix') or _get('results_suffix') or m,

        # -- AWY + NDR
        'precipitation_path':           _get('precipitation_path'),

        # -- AWY only
        'eto_path':                     _get('eto_path'),

        # -- AWY + SWY
        'depth_to_root_rest_layer_path': _get('depth_to_root_rest_layer_path'),
        'pawc_path':                    _get('pawc_path'),

        # -- SWY + SDR + NDR
        'dem_path':                     _get('dem_path'),

        # -- SWY + NDR
        'soil_group_path':              _get('soil_group_path'),

        # -- SWY only
        'eto_monthly_dir':              _get('eto_monthly_dir'),
        'precip_monthly_dir':           _get('precip_monthly_dir'),
        'rain_events_table_path':       _get('rain_events_table_path'),

        # -- SDR only
        'erosivity_path':               _get('erosivity_path'),
        'erodibility_path':             _get('erodibility_path'),
    }
    return mp


def _build_user_data(model_name, mp):
    """Build the UserData dict expected by Factor_BioTable.

    Factor_BioTable only needs Status_* flags and, for some models,
    a 'BioTable' key (unused when we pass the full path directly).
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
# Read parameter CSV
# ---------------------------------------------------------------------------

def _read_param_ranges(parameter_search_ranges_path):
    """Read Parameters.csv → (params_val, params_min, params_max).

    Expected format (Parameters.csv):
        Params, Model, Min, Max, Value

    Each row name in the ``Params`` column maps directly to an internal
    parameter key (with the single exception of ``Borselli-IC0`` → ``IC0``).
    The ``Model`` column is informational only; all rows are loaded and the
    calibration engine selects the relevant subset per model.

    Trailing empty rows are silently ignored.
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
    """Return spotpy.parameter.Uniform objects for the given model."""
    import spotpy  # noqa: PLC0415

    _required = {
        'AWY':   ['Z', 'Factor-Kc'],
        'SWY':   ['Alpha', 'Beta', 'Gamma', 'Factor-Kc_m'],
        'SDR':   ['sdr_max', 'Borselli-K_SDR', 'IC0', 'L_max', 'Factor-C', 'Factor-P'],
        'NDR_N': ['SubCri_Len_N', 'Sub_Eff_N', 'Borselli-K_NDR', 'Factor_Load_N', 'Factor_Eff_N'],
        'NDR_P': ['Borselli-K_NDR', 'Factor_Load_P', 'Factor_Eff_P'],
    }

    return [
        spotpy.parameter.Uniform(k, params_min.get(k, 0.0), params_max.get(k, 1.0))
        for k in _required.get(model_name, [])
    ]


# ---------------------------------------------------------------------------
# Per-model direct-path simulation functions
# ---------------------------------------------------------------------------

def _save_eval_csv(workspace, name, header, rows):
    """Append one iteration's data to an evaluation CSV."""
    path = os.path.join(workspace, 'EVALUATIONS', name)
    file_exists = os.path.isfile(path)
    with open(path, 'a') as f:
        if not file_exists:
            f.write(header + '\n')
        for row in rows:
            f.write(row + '\n')


def _execute_awy_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """One AWY calibration iteration using direct file paths."""
    import natcap.invest.annual_water_yield as _awy  # noqa: PLC0415

    z, kc = float(vector[0]), float(vector[1])
    params = {'Z': z, 'Factor-Kc': kc}

    print(f'AWY  Z={z:.2f}  Factor-Kc={kc:.2f}')

    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', 'AWY_biophysical.csv')
    table.to_csv(tmp_bio, index=False)

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
        'threshold_flow_accumulation':  '%0.0f' % mp['threshold_flow_accumulation'],
        'results_suffix':               suffix,
        'workspace_dir':                out_dir,
    }
    if mp['sub_watersheds_path']:
        awy_args['sub_watersheds_path'] = mp['sub_watersheds_path']

    _awy.execute(awy_args)

    suffix_part = f'_{suffix}' if suffix else ''
    sim_df  = pd.read_csv(os.path.join(out_dir, 'output',
                          f'watershed_results_wyield{suffix_part}.csv'))
    sim_val = sim_df['wyield_vol'].values
    [_, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    obs_val  = obs_df['AWY'].values[idx]
    obj      = factor_metric * si.Cal_FunObj(obs_val, sim_val, metric_name)

    sl = user_data['Suffix']
    _save_eval_csv(workspace, f'AWY_Metric_{sl}.csv',
                   f'Z,Factor-Kc,{metric_name}',
                   [f'{z:.2f},{kc:.2f},{obj:.2f}'])
    _save_eval_csv(workspace, f'AWY_Obs_{sl}.csv', 'Obs',
                   [f'{v:.2f}' for v in obs_val])
    _save_eval_csv(workspace, f'AWY_Sim_{sl}.csv', 'Sim',
                   [f'{v:.2f}' for v in sim_val])
    return obj


def _execute_swy_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """One SWY calibration iteration using direct file paths."""
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415

    alpha, beta, gamma, kc_m = (float(vector[i]) for i in range(4))
    params = {'Alpha': alpha, 'Beta': beta, 'Gamma': gamma, 'Factor-Kc_m': kc_m}

    print(f'SWY  Alpha={alpha:.3f}  Beta={beta:.3f}  Gamma={gamma:.3f}  Kc_m={kc_m:.2f}')

    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', 'SWY_biophysical.csv')
    table.to_csv(tmp_bio, index=False)

    out_dir  = os.path.join(workspace, 'OUTPUTS', '02-SWY')
    suffix   = user_data['Suffix']
    swy_args = {
        'lulc_raster_path':              mp['lulc_path'],
        'biophysical_table_path':        tmp_bio,
        'depth_to_root_rest_layer_path': mp['depth_to_root_rest_layer_path'],
        'et0_dir':                       mp['eto_monthly_dir'],
        'precip_dir':                    mp['precip_monthly_dir'],
        'rain_events_table_path':        mp['rain_events_table_path'],
        'soil_group_path':               mp['soil_group_path'],
        'pawc_raster_path':              mp['pawc_path'],
        'dem_raster_path':               mp['dem_path'],
        'watersheds_path':               mp['calibration_watersheds_path'],
        'threshold_flow_accumulation':   '%0.0f' % mp['threshold_flow_accumulation'],
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
    sim_val = sim_df['mean'].values
    [I, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    obs_val  = obs_df['SWY'].values[idx]
    sim_val  = sim_val[I]
    obj      = factor_metric * si.Cal_FunObj(obs_val, sim_val, metric_name)

    sl = user_data['Suffix']
    _save_eval_csv(workspace, f'SWY_Metric_{sl}.csv',
                   f'Alpha,Beta,Gamma,Factor-Kc,{metric_name}',
                   [f'{alpha:.3f},{beta:.3f},{gamma:.3f},{kc_m:.2f},{obj:.2f}'])
    _save_eval_csv(workspace, f'SWY_Obs_{sl}.csv', 'Obs',
                   [f'{v:.2f}' for v in obs_val])
    _save_eval_csv(workspace, f'SWY_Sim_{sl}.csv', 'Sim',
                   [f'{v:.2f}' for v in sim_val])
    return obj


def _execute_sdr_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
    """One SDR calibration iteration using direct file paths."""
    from natcap.invest.sdr import sdr as _sdr  # noqa: PLC0415
    from simpledbf import Dbf5                  # noqa: PLC0415

    sdr_max, k_sdr, ic0, l_max, fc, fp = (float(vector[i]) for i in range(6))
    params = {
        'sdr_max': sdr_max, 'Borselli-K_SDR': k_sdr, 'IC0': ic0,
        'L_max': l_max, 'Factor-C': fc, 'Factor-P': fp,
    }

    print(f'SDR  sdr_max={sdr_max:.2f}  K={k_sdr:.2f}  IC0={ic0:.2f}  '
          f'L_max={l_max:.2f}  C={fc:.5f}  P={fp:.5f}')

    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', 'SDR_biophysical.csv')
    table.to_csv(tmp_bio, index=False)

    out_dir  = os.path.join(workspace, 'OUTPUTS', '03-SDR')
    suffix   = user_data['Suffix']
    sdr_args = {
        'lulc_raster_path':           mp['lulc_path'],
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
        sdr_args['watersheds_path'] = mp['sub_watersheds_path']

    _sdr.execute(sdr_args)

    dbf_path = os.path.join(out_dir, f'watershed_results_sdr_{suffix}.dbf')
    sim_df   = Dbf5(dbf_path).to_dataframe()
    sim_val  = sim_df['sed_export'].values
    [I, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    obs_val  = obs_df['SDR'].values[idx]
    sim_val  = sim_val[I]
    obj      = factor_metric * si.Cal_FunObj(obs_val, sim_val, metric_name)

    sl = user_data['Suffix']
    _save_eval_csv(workspace, f'SDR_Metric_{sl}.csv',
                   f'sdr_max,k_param,ic_0_param,l_max,Factor-C,Factor-P,{metric_name}',
                   [f'{sdr_max:.2f},{k_sdr:.2f},{ic0:.2f},{l_max:.2f},{fc:.5f},{fp:.5f},{obj:.2f}'])
    _save_eval_csv(workspace, f'SDR_Obs_{sl}.csv', 'Obs',
                   [f'{v:.2f}' for v in obs_val])
    _save_eval_csv(workspace, f'SDR_Sim_{sl}.csv', 'Sim',
                   [f'{v:.2f}' for v in sim_val])
    return obj


def _execute_ndr_direct(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si,
                        model_name):
    """One NDR_N or NDR_P calibration iteration using direct file paths."""
    from natcap.invest.ndr import ndr as _ndr  # noqa: PLC0415

    if model_name == 'NDR_N':
        k_ndr, load_n, eff_n, subcri_n, sub_eff_n = (float(vector[i]) for i in range(5))
        # NDR_N vector order matches _build_spotpy_params:
        # SubCri_Len_N, Sub_Eff_N, Borselli-K_NDR, Factor_Load_N, Factor_Eff_N
        subcri_n, sub_eff_n, k_ndr, load_n, eff_n = (float(vector[i]) for i in range(5))
        params = {
            'SubCri_Len_N': subcri_n, 'Sub_Eff_N': sub_eff_n,
            'Borselli-K_NDR': k_ndr, 'Factor_Load_N': load_n, 'Factor_Eff_N': eff_n,
        }
        print(f'NDR_N  SubCri={subcri_n:.2f}  SubEff={sub_eff_n:.2f}  '
              f'K={k_ndr:.2f}  Load={load_n:.2f}  Eff={eff_n:.2f}')
        ndr_extra = {'calc_n': True, 'calc_p': False,
                     'subsurface_critical_length_n': '%.2f' % subcri_n,
                     'subsurface_eff_n':             '%.2f' % sub_eff_n}
    else:  # NDR_P
        # Borselli-K_NDR, Factor_Load_P, Factor_Eff_P
        k_ndr, load_p, eff_p = (float(vector[i]) for i in range(3))
        params = {'Borselli-K_NDR': k_ndr, 'Factor_Load_P': load_p, 'Factor_Eff_P': eff_p}
        print(f'NDR_P  K={k_ndr:.2f}  Load={load_p:.2f}  Eff={eff_p:.2f}')
        ndr_extra = {'calc_n': False, 'calc_p': True,
                     'subsurface_critical_length_p': '%.2f' % load_p,
                     'subsurface_eff_p':             '%.2f' % eff_p}

    table = si.Factor_BioTable(mp['biophysical_table_path'], params, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', f'{model_name}_biophysical.csv')
    table.to_csv(tmp_bio, index=False)

    out_dir = os.path.join(workspace, 'OUTPUTS',
                           '04-NDR_N' if model_name == 'NDR_N' else '04-NDR_P')
    suffix  = user_data['Suffix']
    ndr_args = {
        'lulc_raster_path':           mp['lulc_path'],
        'biophysical_table_path':     tmp_bio,
        'dem_path':                   mp['dem_path'],
        'runoff_proxy_path':          mp['precipitation_path'],
        'watersheds_path':            mp['calibration_watersheds_path'],
        'soil_group_path':            mp['soil_group_path'],
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
    sim_val = sim_df[sim_col].values
    [I, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    obs_val  = obs_df[obs_col].values[idx]
    sim_val  = sim_val[I]
    obj      = factor_metric * si.Cal_FunObj(obs_val, sim_val, metric_name)

    sl = user_data['Suffix']
    if model_name == 'NDR_N':
        hdr   = f'SubCri_Len_N,Sub_Eff_N,Borselli-K,Factor_Load_N,Factor_Eff_N,{metric_name}'
        p_row = f'{subcri_n:.2f},{sub_eff_n:.2f},{k_ndr:.2f},{load_n:.2f},{eff_n:.2f},{obj:.2f}'
    else:
        hdr   = f'Borselli-K,Factor_Load_P,Factor_Eff_P,{metric_name}'
        p_row = f'{k_ndr:.2f},{load_p:.2f},{eff_p:.2f},{obj:.2f}'

    _save_eval_csv(workspace, f'{model_name}_Metric_{sl}.csv', hdr, [p_row])
    _save_eval_csv(workspace, f'{model_name}_Obs_{sl}.csv', 'Obs',
                   [f'{v:.2f}' for v in obs_val])
    _save_eval_csv(workspace, f'{model_name}_Sim_{sl}.csv', 'Sim',
                   [f'{v:.2f}' for v in sim_val])
    return obj


# ---------------------------------------------------------------------------
# Final best-parameters run for each model
# ---------------------------------------------------------------------------

def _run_best_params(workspace, model_name, mp, user_data, params_val, si):
    """Run the selected InVEST model once with the best-fit calibrated parameters."""
    import natcap.invest.annual_water_yield as _awy       # noqa: PLC0415
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415
    from natcap.invest.sdr import sdr as _sdr             # noqa: PLC0415
    from natcap.invest.ndr import ndr as _ndr             # noqa: PLC0415

    table = si.Factor_BioTable(mp['biophysical_table_path'], params_val, user_data)
    tmp_bio = os.path.join(workspace, 'TMP', f'{model_name}_BioTable_best.csv')
    table.to_csv(tmp_bio, index=False)

    out_dir = os.path.join(workspace, 'OUTPUTS', f'{model_name}_best')
    suffix  = user_data['Suffix']
    tfa     = '%0.0f' % mp['threshold_flow_accumulation']
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
            'threshold_flow_accumulation':  tfa,
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
            'depth_to_root_rest_layer_path': mp['depth_to_root_rest_layer_path'],
            'et0_dir':                       mp['eto_monthly_dir'],
            'precip_dir':                    mp['precip_monthly_dir'],
            'rain_events_table_path':        mp['rain_events_table_path'],
            'soil_group_path':               mp['soil_group_path'],
            'pawc_raster_path':              mp['pawc_path'],
            'dem_raster_path':               mp['dem_path'],
            'watersheds_path':               mp['watersheds_path'],
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
            'lulc_raster_path':           mp['lulc_path'],
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
        _sdr.execute(invest_args)

    elif model_name in ('NDR_N', 'NDR_P'):
        is_n = (model_name == 'NDR_N')
        invest_args = {
            'lulc_raster_path':           mp['lulc_path'],
            'biophysical_table_path':     tmp_bio,
            'dem_path':                   mp['dem_path'],
            'runoff_proxy_path':          mp['precipitation_path'],
            'watersheds_path':            mp['watersheds_path'],
            'soil_group_path':            mp['soil_group_path'],
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
            invest_args['subsurface_critical_length_p'] = '%.2f' % params_val.get('Factor_Load_P', 1.0)
            invest_args['subsurface_eff_p']             = '%.2f' % params_val.get('Factor_Eff_P', 1.0)
        if sub_ws:
            invest_args['sub_watersheds_path'] = sub_ws
        _ndr.execute(invest_args)

    LOGGER.info(f'{model_name} best-parameters run complete → {out_dir}')


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------

def execute(args):
    """Run InVEST calibration using individual per-model spatial inputs.

    Parameters
    ----------
    args : dict
        Keys defined in MODEL_SPEC.  Required keys vary by model_name;
        the Workbench enforces this through the required/allowed expressions.
    """
    LOGGER.info('=' * 60)
    LOGGER.info('TNC InVEST Calibration Assistant')
    LOGGER.info('=' * 60)

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

    if _plot_fn is not None:
        _plot_fn(workspace, project_name, fo_label, workspace, factor_metric)

    # ------------------------------------------------------------------
    # 9. Final run with best-fit parameters
    # ------------------------------------------------------------------
    LOGGER.info('Running InVEST with best-fit parameters …')
    _run_best_params(workspace, model_name, mp, user_data, params_val, si)

    LOGGER.info('=' * 60)
    LOGGER.info(f'Calibration complete: {model_name}')
    LOGGER.info('=' * 60)

    return {}  # InVEST framework expects a file-registry dict from execute()


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

@validation.invest_validator
def validate(args, limit_to=None):
    """Validate plugin arguments against MODEL_SPEC."""
    warnings = validation.validate(args, MODEL_SPEC)

    if limit_to is None or limit_to == 'n_simulations':
        try:
            n = int(args.get('n_simulations', 0))
            if n <= 1:
                warnings.append(
                    (['n_simulations'],
                     'Number of simulations must be an integer greater than 1.'))
        except (ValueError, TypeError):
            warnings.append(
                (['n_simulations'],
                 'Number of simulations must be a valid integer.'))

    return warnings
