# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - AWY (Annual Water Yield)

Calibration-iteration and final best-parameters run, both for the AWY
model. Kept together so everything AWY-specific lives in one file.
"""

import logging
import os

import pandas as pd

from ..iteration_io import _save_iteration, _score_against_obs, _write_temp_biotable

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AWY calibration iteration
# ---------------------------------------------------------------------------

def run_iteration(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
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
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.

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
# AWY final best-parameters run
# ---------------------------------------------------------------------------

def run_final(workspace, mp, user_data, params_val, si):
    """Run AWY once with the best-fit parameters (final, full-watershed run).

    Builds the final biophysical table from ``params_val``, then calls
    ``natcap.invest.annual_water_yield`` with the full (non-calibration)
    watershed set, writing results to ``OUTPUTS/AWY_best``.

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
        Results are written to disk under ``OUTPUTS/AWY_best``; nothing
        is returned.
    """
    import natcap.invest.annual_water_yield as _awy  # noqa: PLC0415

    out_dir = os.path.join(workspace, 'OUTPUTS', 'AWY_best')
    os.makedirs(out_dir, exist_ok=True)
    suffix  = user_data['Suffix']

    table = si.Factor_BioTable(mp['biophysical_table_path'], params_val, user_data)
    tmp_bio = os.path.join(out_dir, 'AWY_BioTable_best.csv')
    table.to_csv(tmp_bio, index=False)
    sub_ws  = mp.get('sub_watersheds_path', '')

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

    LOGGER.info(f'AWY best-parameters run complete → {out_dir}')
