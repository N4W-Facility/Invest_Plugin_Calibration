# -*- coding: utf-8 -*-
"""
TNC InVEST Calibration Assistant - InVEST Plugin (Option 1: CSV Inputs)

Nature For Water Facility - The Nature Conservancy
Author  : Jonathan Nogales Pimentel
Email   : jonathan.nogales@tnc.org
Date    : 2025

This plugin wraps the InVEST Automatic Calibration Assistant (Spotpy_InVEST)
as a native InVEST Workbench plugin.

Option 1: CSV-based inputs
  - Table Of Input File Names   → replaces Excel sheet "UserData"
  - Table Of Parameter Ranges   → replaces Excel sheet "Params"
  - Table Of Observed Data      → replaces Excel sheet "Obs_Data"
"""

import logging
import os

import pandas as pd

from natcap.invest import gettext
from natcap.invest import spec
from natcap.invest import utils
from natcap.invest import validation

LOGGER = logging.getLogger(__name__)


def _get_si():
    """Lazy import of Spotpy_InVEST – only loaded when execute() is called.

    This keeps the top-level import of this module lightweight so the
    Workbench can read MODEL_SPEC without requiring all scientific
    dependencies (GDAL, spotpy, win32com, pyogrio, …) to be present.
    """
    from . import Spotpy_InVEST as _si  # noqa: PLC0415
    return _si

# ---------------------------------------------------------------------------
# MODEL SPEC  –  defines the entire plugin UI inside InVEST Workbench
# ---------------------------------------------------------------------------
MODEL_SPEC = spec.ModelSpec(
    model_id="invest_calibration_assistant",
    model_title=gettext("TNC InVEST Calibration Assistant"),
    module_name=__name__,
    userguide='',
    input_field_order=[
        ['workspace_dir', 'results_suffix'],
        ['model_name'],
        ['input_file_names_path'],
        ['parameter_search_ranges_path'],
        ['observed_data_path'],
        ['evaluation_metric', 'optimization_method'],
        ['n_simulations'],
    ],
    inputs=[
        # ------------------------------------------------------------------
        # Standard InVEST inputs
        # ------------------------------------------------------------------
        spec.DirectoryInput(
            id='workspace_dir',
            name=gettext('Workspace'),
            about=gettext(
                'Output folder for all calibration results. '
                'Sub-folders EVALUATIONS, PARAMETERS, OUTPUTS, FIGURES '
                'and TMP will be created automatically.'),
            contents=[],
            must_exist=False,
            permissions='rwx',
        ),
        spec.StringInput(
            id='results_suffix',
            name=gettext('File Suffix'),
            about=gettext(
                'Optional text appended to every output file name. '
                'Use only letters, numbers, underscores or hyphens.'),
            required=False,
            regexp='[a-zA-Z0-9_-]*',
        ),
        spec.NumberInput(
            id='n_workers',
            name=gettext('taskgraph n_workers parameter'),
            about=gettext(
                'Number of parallel worker processes. '
                '-1 = synchronous (recommended for calibration).'),
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
                'AWY = Annual Water Yield, '
                'SWY = Seasonal Water Yield, '
                'SDR = Sediment Delivery Ratio, '
                'NDR_N = Nutrient Delivery Ratio (Nitrogen), '
                'NDR_P = Nutrient Delivery Ratio (Phosphorus).'),
            options=[
                spec.Option(key='AWY', display_name=gettext('AWY – Annual Water Yield')),
                spec.Option(key='SWY', display_name=gettext('SWY – Seasonal Water Yield')),
                spec.Option(key='SDR', display_name=gettext('SDR – Sediment Delivery Ratio')),
                spec.Option(key='NDR_N', display_name=gettext('NDR_N – Nutrient Delivery Ratio (N)')),
                spec.Option(key='NDR_P', display_name=gettext('NDR_P – Nutrient Delivery Ratio (P)')),
            ],
        ),

        # ------------------------------------------------------------------
        # CSV table inputs  (Option 1)
        # columns is a list of Input objects – id must match the column header
        # ------------------------------------------------------------------
        spec.CSVInput(
            id='input_file_names_path',
            name=gettext('Table Of Input File Names'),
            about=gettext(
                'CSV file with two columns: "Parameter" and "Value". '
                'Each row names a spatial input layer (file name without '
                'extension) used by the selected InVEST model. '
                'See DEVELOPMENT.md for the full list of expected rows.'),
            index_col='Parameter',
            columns=[
                spec.StringInput(
                    id='Parameter',
                    name=gettext('Parameter'),
                    about=gettext('Row identifier (e.g. LULC, DEM, BioTable …)'),
                ),
                spec.StringInput(
                    id='Value',
                    name=gettext('Value'),
                    about=gettext('File name or value for this parameter'),
                ),
            ],
        ),
        spec.CSVInput(
            id='parameter_search_ranges_path',
            name=gettext('Table Of Parameter Search Ranges'),
            about=gettext(
                'CSV file with four columns: "Parameter", "Value", "Min", "Max". '
                '"Value" is the initial (best-guess) parameter value; '
                '"Min" and "Max" define the calibration search bounds. '
                'See DEVELOPMENT.md for the full list of calibration parameters.'),
            index_col='Parameter',
            columns=[
                spec.StringInput(
                    id='Parameter',
                    name=gettext('Parameter'),
                    about=gettext('Calibration parameter name (e.g. Z, Factor-Kc, sdr_max …)'),
                ),
                spec.NumberInput(
                    id='Value',
                    name=gettext('Value'),
                    about=gettext('Best-guess / initial value'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Min',
                    name=gettext('Min'),
                    about=gettext('Lower search bound'),
                    units=None,
                ),
                spec.NumberInput(
                    id='Max',
                    name=gettext('Max'),
                    about=gettext('Upper search bound'),
                    units=None,
                ),
            ],
        ),
        spec.CSVInput(
            id='observed_data_path',
            name=gettext('Table Of Observed Data For Each Watershed'),
            about=gettext(
                'CSV file containing observed measurements (streamflow, '
                'sediment export, or nutrient export) for each calibration '
                'watershed. Each column represents one watershed; rows '
                'represent time steps (years or months). '
                'Column names must match the watershed IDs in the shapefile.'),
            columns=[],
        ),

        # ------------------------------------------------------------------
        # Calibration settings
        # ------------------------------------------------------------------
        spec.OptionStringInput(
            id='evaluation_metric',
            name=gettext('Evaluation Metric'),
            about=gettext(
                'Objective function used to compare simulated vs observed values.'),
            options=[
                spec.Option(key='Mean Square Error (MSE)',
                            display_name=gettext('Mean Square Error (MSE)')),
                spec.Option(key='Mean Absolute Error (MAE)',
                            display_name=gettext('Mean Absolute Error (MAE)')),
                spec.Option(key='Root Mean Square Error (RMSE)',
                            display_name=gettext('Root Mean Square Error (RMSE)')),
                spec.Option(key='Relative Root Mean Squared Error (RRMSE)',
                            display_name=gettext(
                                'Relative Root Mean Squared Error (RRMSE)')),
            ],
        ),
        spec.OptionStringInput(
            id='optimization_method',
            name=gettext('Optimization Method'),
            about=gettext(
                'Optimization algorithm used to search the parameter space.'),
            options=[
                spec.Option(key='Dynamical dimensional search (DDS)',
                            display_name=gettext(
                                'Dynamical Dimensional Search (DDS)')),
                spec.Option(key='Shuffled Complex Evolution (SCE-UA)',
                            display_name=gettext(
                                'Shuffled Complex Evolution (SCE-UA)')),
                spec.Option(key='Latin Hypercube Sampling (LHS)',
                            display_name=gettext(
                                'Latin Hypercube Sampling (LHS)')),
            ],
        ),
        spec.IntegerInput(
            id='n_simulations',
            name=gettext('Number Of Simulations'),
            about=gettext(
                'Total number of model evaluations during calibration. '
                'Must be greater than 1. Larger values improve parameter '
                'estimation at the cost of computation time.'),
            expression='value > 1',
        ),
    ],

    outputs=[
        spec.FileOutput(
            id='calibration_results',
            path='PARAMETERS',
            about=gettext(
                'Folder containing Spotpy parameter CSV files with '
                'best-fit values found during calibration.'),
        ),
        spec.FileOutput(
            id='calibration_figures',
            path='FIGURES',
            about=gettext(
                'Folder containing scatter plots comparing '
                'simulated vs observed values.'),
        ),
    ],
)


# ---------------------------------------------------------------------------
# Helpers – read CSVs into the dicts expected by Spotpy_InVEST
# ---------------------------------------------------------------------------

def _read_user_data(input_file_names_path, model_name):
    """Read CSV 1 (input file names) → UserData dict.

    The CSV must have columns  ``Parameter``  and  ``Value``
    with rows matching the Excel UserData sheet format.
    """
    df = pd.read_csv(input_file_names_path, index_col=0)
    # Support both "Parameter" as index column header and unnamed index
    # If index is already set correctly use it, otherwise reset
    if 'Value' not in df.columns:
        df = pd.read_csv(input_file_names_path)
        df = df.set_index(df.columns[0])

    def _get(row, default=None):
        try:
            return df.loc[row, 'Value']
        except KeyError:
            return default

    ud = {}
    ud['Pixel']         = _get('Pixel', 30)
    ud['Suffix']        = _get('Name', '')
    ud['BioTable']      = _get('BioTable')
    ud['RainTable']     = _get('RainTable', '')
    ud['LULC']          = _get('LULC')
    ud['DEM']           = _get('DEM')
    ud['R']             = _get('R', '')
    ud['K']             = _get('K', '')
    ud['SoilDepth']     = _get('SoilDepth', '')
    ud['ETP']           = _get('ETP')
    ud['ETP_Path']      = _get('ETP_M', '')
    ud['P']             = _get('P')
    ud['P_Path']        = _get('P_M', '')
    ud['PAWC']          = _get('PAWC', '')
    ud['SoilGroup']     = _get('HSG', '')
    ud['Stream']        = _get('Stream', '')
    ud['Basin']         = _get('Basin')
    ud['SubBasin']      = _get('SubBasin', '')
    ud['Threshold']     = float(_get('Threshold_Flow', 1000))

    # Model run flags – only the selected model is activated
    for m in ['AWY', 'SWY', 'SDR', 'NDR_N', 'NDR_P']:
        ud[f'Status_{m}'] = 1 if m == model_name else 0

    return ud


def _read_param_ranges(parameter_search_ranges_path):
    """Read CSV 2 (parameter ranges) → (ParamsMin, ParamsMax, Params) dicts.

    The CSV must have columns  ``Parameter``, ``Value``, ``Min``, ``Max``.
    """
    df = pd.read_csv(parameter_search_ranges_path, index_col=0)
    if not {'Value', 'Min', 'Max'}.issubset(df.columns):
        # Try with first column as index
        df = pd.read_csv(parameter_search_ranges_path)
        df = df.set_index(df.columns[0])

    # Map CSV row names to internal key names
    _row_map = {
        'Z':              'Z',
        'Factor-Kc':      'Factor-Kc',
        'Factor-Kc_m':    'Factor-Kc_m',
        'Gamma':          'Gamma',
        'Beta':           'Beta',
        'Alpha':          'Alpha',
        'Factor-C':       'Factor-C',
        'Factor-P':       'Factor-P',
        'Borselli-IC0':   'IC0',
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

    params_val = {}
    params_min = {}
    params_max = {}

    for csv_key, internal_key in _row_map.items():
        if csv_key in df.index:
            params_val[internal_key] = float(df.loc[csv_key, 'Value'])
            params_min[internal_key] = float(df.loc[csv_key, 'Min'])
            params_max[internal_key] = float(df.loc[csv_key, 'Max'])

    return params_val, params_min, params_max


# ---------------------------------------------------------------------------
# execute()
# ---------------------------------------------------------------------------

def execute(args):
    """Run InVEST calibration using CSV-based inputs.

    Parameters
    ----------
    args : dict
        Dictionary of input values as defined in MODEL_SPEC.
        Required keys:
            workspace_dir               : str – output directory
            model_name                  : str – one of AWY/SWY/SDR/NDR_N/NDR_P
            input_file_names_path       : str – path to CSV 1
            parameter_search_ranges_path: str – path to CSV 2
            observed_data_path          : str – path to CSV 3
            evaluation_metric           : str – objective function name
            optimization_method         : str – algorithm name
            n_simulations               : int – number of iterations
        Optional keys:
            results_suffix              : str – appended to output file names
    """
    LOGGER.info('=' * 60)
    LOGGER.info('TNC InVEST Calibration Assistant  –  Option 1 (CSV inputs)')
    LOGGER.info('=' * 60)

    workspace  = args['workspace_dir']
    model_name = args['model_name']
    metric     = args['evaluation_metric']
    method     = args['optimization_method']
    n_sim      = int(args['n_simulations'])

    LOGGER.info(f'Workspace        : {workspace}')
    LOGGER.info(f'Model            : {model_name}')
    LOGGER.info(f'Metric           : {metric}')
    LOGGER.info(f'Method           : {method}')
    LOGGER.info(f'N simulations    : {n_sim}')

    utils.make_directories([workspace])

    # ------------------------------------------------------------------
    # 1. Read CSV inputs
    # ------------------------------------------------------------------
    LOGGER.info('Reading input CSV files …')
    user_data = _read_user_data(args['input_file_names_path'], model_name)
    params_val, params_min, params_max = _read_param_ranges(
        args['parameter_search_ranges_path'])
    obs_df = pd.read_csv(args['observed_data_path'])
    LOGGER.info('CSV files loaded successfully.')

    # ------------------------------------------------------------------
    # 2. Load calibration engine (deferred import)
    # ------------------------------------------------------------------
    si = _get_si()

    # ------------------------------------------------------------------
    # 3. Create required output sub-directories
    # ------------------------------------------------------------------
    for sub in ['EVALUATIONS', 'PARAMETERS', 'OUTPUTS', 'FIGURES', 'TMP']:
        si.CreateFolder(os.path.join(workspace, sub))

    # ------------------------------------------------------------------
    # 4. Determine optimisation direction
    #    DDS minimises → FactorMetric = -1
    #    SCE-UA / LHS maximise → FactorMetric = 1
    # ------------------------------------------------------------------
    factor_metric = -1 if method == 'Dynamical dimensional search (DDS)' else 1

    # ------------------------------------------------------------------
    # 5. Build a modified Spotpy_InVEST class that accepts DataFrames
    #    instead of an Excel file path.
    # ------------------------------------------------------------------
    import spotpy

    class _SpotpyPlugin(si.Spotpy_InVEST):
        """Subclass that injects pre-loaded data instead of reading Excel."""

        def __init__(self):
            # Skip the parent __init__ and configure attributes directly
            si.CreateFolder(os.path.join(workspace, 'EVALUATIONS'))
            si.CreateFolder(os.path.join(workspace, 'PARAMETERS'))
            si.CreateFolder(os.path.join(workspace, 'OUTPUTS'))
            si.CreateFolder(os.path.join(workspace, 'FIGURES'))
            si.CreateFolder(os.path.join(workspace, 'TMP'))

            self.ProjectPath  = workspace
            self.UserData     = user_data
            self.NameModel    = model_name
            self.NameFunObj   = metric
            self.FactorMetric = factor_metric
            self.Obs          = obs_df

            # Build parameter list from the CSV ranges
            self.params = _build_spotpy_params(model_name, params_min, params_max)

    # ------------------------------------------------------------------
    # 6. Run calibration
    # ------------------------------------------------------------------
    LOGGER.info('Starting calibration …')
    spot_setup = _SpotpyPlugin()

    parallel = 'seq'
    dbformat = 'csv'
    timeout  = 2

    if method == 'Dynamical dimensional search (DDS)':
        db_path = os.path.join(workspace, 'PARAMETERS', model_name + '_DDS')
        sampler = spotpy.algorithms.dds(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)
    elif method == 'Shuffled Complex Evolution (SCE-UA)':
        db_path = os.path.join(workspace, 'PARAMETERS', model_name + '_SCE')
        sampler = spotpy.algorithms.sceua(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)
    else:  # Latin Hypercube Sampling (LHS)
        db_path = os.path.join(workspace, 'PARAMETERS', model_name + '_LHS')
        sampler = spotpy.algorithms.lhs(
            spot_setup, parallel=parallel,
            dbname=db_path, dbformat=dbformat, sim_timeout=timeout)

    sampler.sample(n_sim)

    # ------------------------------------------------------------------
    # 7. Generate calibration plots
    # ------------------------------------------------------------------
    LOGGER.info('Generating calibration plots …')
    suffix_flag = args.get('results_suffix', '')
    project_name = user_data.get('Suffix') or suffix_flag or model_name

    fo_label = {
        'Mean Square Error (MSE)':                    'MSE',
        'Mean Absolute Error (MAE)':                  'MAE',
        'Root Mean Square Error (RMSE)':              'RMSE',
        'Relative Root Mean Squared Error (RRMSE)':   'RRMSE',
    }.get(metric, 'RMSE')

    _plot_fn = {
        'AWY':   si.Plot_AWY,
        'SWY':   si.Plot_SWY,
        'SDR':   si.Plot_SDR,
        'NDR_N': si.Plot_NDR_N,
        'NDR_P': si.Plot_NDR_P,
    }.get(model_name)

    if _plot_fn is not None:
        _plot_fn(workspace, project_name, fo_label,
                 args['input_file_names_path'],   # passed as InVEST_Main_Path placeholder
                 factor_metric)

    # ------------------------------------------------------------------
    # 8. Run InVEST with best-fit parameters
    # ------------------------------------------------------------------
    LOGGER.info('Running InVEST with best-fit parameters …')
    _run_invest_best_params(workspace, user_data, params_val)

    LOGGER.info('=' * 60)
    LOGGER.info(f'Calibration complete for model: {model_name}')
    LOGGER.info('=' * 60)


# ---------------------------------------------------------------------------
# Helper – build spotpy parameter list from min/max dicts
# ---------------------------------------------------------------------------

def _build_spotpy_params(model_name, params_min, params_max):
    """Return a list of spotpy.parameter.Uniform objects for the given model."""
    import spotpy

    _required = {
        'AWY':   ['Z', 'Factor-Kc'],
        'SWY':   ['Gamma', 'Beta', 'Alpha', 'Factor-Kc_m'],
        'SDR':   ['sdr_max', 'Borselli-K_SDR', 'IC0', 'L_max',
                  'Factor-C', 'Factor-P'],
        'NDR_N': ['SubCri_Len_N', 'Sub_Eff_N', 'Borselli-K_NDR',
                  'Factor_Load_N', 'Factor_Eff_N'],
        'NDR_P': ['Borselli-K_NDR', 'Factor_Load_P', 'Factor_Eff_P'],
    }

    params = []
    for key in _required.get(model_name, []):
        lo = params_min.get(key, 0.0)
        hi = params_max.get(key, 1.0)
        params.append(spotpy.parameter.Uniform(key, lo, hi))
    return params


# ---------------------------------------------------------------------------
# Helper – execute InVEST with the best calibrated parameters
# ---------------------------------------------------------------------------

def _run_invest_best_params(workspace, user_data, params_val):
    """Apply the best-fit parameters and run the appropriate InVEST model."""
    import natcap.invest.annual_water_yield as awy
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as swy
    from natcap.invest.sdr import sdr
    from natcap.invest.ndr import ndr

    si = _get_si()

    model_name = next(
        (m for m in ['AWY', 'SWY', 'SDR', 'NDR_N', 'NDR_P']
         if user_data.get(f'Status_{m}') == 1),
        None
    )
    if model_name is None:
        LOGGER.warning('No model marked as active in UserData; skipping execution.')
        return

    si.CreateFolder(os.path.join(workspace, 'OUTPUTS'))
    path_bio = os.path.join(
        workspace, '..', 'INPUTS', user_data.get('BioTable', '') + '.csv')

    invest_args = si.Create_argsInVEST(workspace.replace('/', os.sep),
                                       user_data, params_val, StatusK=model_name)
    table = si.Factor_BioTable(path_bio, params_val, user_data)
    tmp_table = os.path.join(workspace, 'TMP',
                             model_name + '_BioTable_best.csv')
    table.to_csv(tmp_table, index=False)
    invest_args['biophysical_table_path'] = tmp_table
    invest_args['workspace_dir'] = os.path.join(workspace, 'OUTPUTS', model_name)

    if model_name == 'AWY':
        awy.execute(invest_args)
    elif model_name == 'SWY':
        swy.execute(invest_args)
    elif model_name == 'SDR':
        sdr.execute(invest_args)
    elif model_name in ('NDR_N', 'NDR_P'):
        ndr.execute(invest_args)


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------

@validation.invest_validator
def validate(args, limit_to=None):
    """Validate plugin arguments against MODEL_SPEC.

    Extra check: n_simulations must be > 1.
    """
    warnings = validation.validate(args, MODEL_SPEC)

    if limit_to is None or limit_to == 'n_simulations':
        try:
            n = int(args.get('n_simulations', 0))
            if n <= 1:
                warnings.append(
                    (['n_simulations'],
                     'Number of simulations must be an integer greater than 1.')
                )
        except (ValueError, TypeError):
            warnings.append(
                (['n_simulations'],
                 'Number of simulations must be a valid integer.')
            )

    return warnings
