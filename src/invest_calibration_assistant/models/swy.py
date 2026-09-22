# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - SWY (Seasonal Water Yield)

Calibration-iteration and final best-parameters run, both for the SWY
model. Kept together so everything SWY-specific lives in one file.
"""

import logging
import os

from ..iteration_io import _save_iteration, _score_against_obs, _write_temp_biotable

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SWY calibration iteration
# ---------------------------------------------------------------------------

def run_iteration(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
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
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.

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
# SWY final best-parameters run
# ---------------------------------------------------------------------------

def run_final(workspace, mp, user_data, params_val, si):
    """Run SWY once with the best-fit parameters (final, full-watershed run).

    Builds the final biophysical table from ``params_val``, then calls
    ``natcap.invest.seasonal_water_yield`` with the full (non-calibration)
    watershed set, writing results to ``OUTPUTS/SWY_best``.

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    mp : dict
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
    params_val : dict
        Final parameter values to use, keyed by internal parameter name.
    si : module
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.

    Returns
    -------
    None
        Results are written to disk under ``OUTPUTS/SWY_best``; nothing
        is returned.
    """
    from natcap.invest.seasonal_water_yield import seasonal_water_yield as _swy  # noqa: PLC0415

    out_dir = os.path.join(workspace, 'OUTPUTS', 'SWY_best')
    os.makedirs(out_dir, exist_ok=True)
    suffix  = user_data['Suffix']

    table = si.Factor_BioTable(mp['biophysical_table_path'], params_val, user_data)
    tmp_bio = os.path.join(out_dir, 'SWY_BioTable_best.csv')
    table.to_csv(tmp_bio, index=False)
    tfa     = '%0.0f' % mp['threshold_flow_accumulation'] if mp['threshold_flow_accumulation'] is not None else ''
    sub_ws  = mp.get('sub_watersheds_path', '')

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

    LOGGER.info(f'SWY best-parameters run complete → {out_dir}')
