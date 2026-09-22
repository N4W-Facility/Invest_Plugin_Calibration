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

This module is the plugin's orchestrator: it exposes the required
``MODEL_SPEC``/``execute``/``validate`` entry points and wires together the
input-collection helpers (``inputs.py``), the per-model calibration logic
(``models/``), and the HTML report builder (``Report_InVEST.py``). The
``MODEL_SPEC`` declaration itself lives in ``model_spec.py``.
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

import numpy as np
import pandas as pd

from natcap.invest import validation

from . import Report_InVEST
from .inputs import (
    _build_model_paths,
    _build_spotpy_params,
    _build_user_data,
    _inputs_summary,
    _invest_version,
    _read_param_ranges,
    _status_cal_summary,
)
from .model_spec import MODEL_SPEC
from .models import awy, ndr, sdr, swy

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


_METHOD_SHORT = {
    'Dynamical dimensional search (DDS)':   'DDS',
    'Shuffled Complex Evolution (SCE-UA)':  'SCE-UA',
    'Latin Hypercube Sampling (LHS)':       'LHS',
}


# ---------------------------------------------------------------------------
# Final best-parameters run for each model
# ---------------------------------------------------------------------------

def _run_best_params(workspace, model_name, mp, user_data, params_val, si):
    """Run the selected InVEST model once with the best-fit parameters.

    Dispatches to the corresponding model's ``run_final`` (AWY / SWY /
    SDR / NDR), which writes results to ``OUTPUTS/<model_name>_best``.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    model_name : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    mp : dict
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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
    _final_fn_map = {
        'AWY': awy.run_final,
        'SWY': swy.run_final,
        'SDR': sdr.run_final,
    }
    if model_name in ('NDR_N', 'NDR_P'):
        ndr.run_final(workspace, mp, user_data, params_val, si, model_name)
    else:
        _final_fn_map[model_name](workspace, mp, user_data, params_val, si)


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
        'AWY':   awy.run_iteration,
        'SWY':   swy.run_iteration,
        'SDR':   sdr.run_iteration,
    }

    def _sim_fn(vec):
        """Dispatch one calibration iteration to the model-specific runner."""
        if model_name in ('NDR_N', 'NDR_P'):
            return ndr.run_iteration(workspace, mp, user_data, vec,
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
                workspace, project_name, fo_label, factor_metric)
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
