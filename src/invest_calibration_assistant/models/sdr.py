# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - SDR (Sediment Delivery Ratio)

Calibration-iteration and final best-parameters run, both for the SDR
model. Kept together so everything SDR-specific lives in one file.
"""

import logging
import os

from ..iteration_io import _save_iteration, _score_against_obs, _write_temp_biotable

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SDR calibration iteration
# ---------------------------------------------------------------------------

def run_iteration(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si):
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
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.

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
# SDR final best-parameters run
# ---------------------------------------------------------------------------

def run_final(workspace, mp, user_data, params_val, si):
    """Run SDR once with the best-fit parameters (final, full-watershed run).

    Builds the final biophysical table from ``params_val``, then calls
    ``natcap.invest.sdr`` with the full (non-calibration) watershed set,
    writing results to ``OUTPUTS/SDR_best``.

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
        Results are written to disk under ``OUTPUTS/SDR_best``; nothing
        is returned.
    """
    from natcap.invest.sdr import sdr as _sdr  # noqa: PLC0415

    out_dir = os.path.join(workspace, 'OUTPUTS', 'SDR_best')
    os.makedirs(out_dir, exist_ok=True)
    suffix  = user_data['Suffix']

    table = si.Factor_BioTable(mp['biophysical_table_path'], params_val, user_data)
    tmp_bio = os.path.join(out_dir, 'SDR_BioTable_best.csv')
    table.to_csv(tmp_bio, index=False)
    tfa     = '%0.0f' % mp['threshold_flow_accumulation'] if mp['threshold_flow_accumulation'] is not None else ''
    sub_ws  = mp.get('sub_watersheds_path', '')

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

    LOGGER.info(f'SDR best-parameters run complete → {out_dir}')
