# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - Input collection and parameter parsing

Helpers that turn the raw ``args`` dict / on-disk CSVs received by
``execute()`` into the internal ``model_paths``/``UserData``/parameter
dicts consumed by the calibration engine, plus small report-summary
helpers.
"""

import logging
import os
from importlib.metadata import PackageNotFoundError, version as _pkg_version

import pandas as pd

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Build model_paths dict from individual UI fields
# ---------------------------------------------------------------------------

def _build_model_paths(args):
    """Collect the spatial/tabular inputs relevant to the selected model.

    Parameters
    ----------
    args : dict
        Raw arguments dict as received by :func:`calibration_assistant.execute`,
        keyed by the input ids declared in ``MODEL_SPEC``.

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
        order consumed by the corresponding model's ``run_iteration``.
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
