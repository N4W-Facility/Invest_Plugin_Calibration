# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - NDR (Nutrient Delivery Ratio, N and P)

Calibration-iteration and final best-parameters run, both for NDR_N and
NDR_P (they share almost all their logic, parametrized by ``model_name``).
Kept together so everything NDR-specific lives in one file.
"""

import logging
import os

from ..iteration_io import _save_iteration, _score_against_obs

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# NDR calibration iteration (N or P)
# ---------------------------------------------------------------------------

def run_iteration(workspace, mp, user_data, vector, metric_name, factor_metric, obs_df, si,
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
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.
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
        # NDR_N vector order matches inputs._build_spotpy_params:
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
        # Vector order matches inputs._build_spotpy_params:
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
# NDR final best-parameters run (N or P)
# ---------------------------------------------------------------------------

def run_final(workspace, mp, user_data, params_val, si, model_name):
    """Run NDR_N or NDR_P once with the best-fit parameters (final run).

    Builds the final biophysical table from ``params_val``, then calls
    ``natcap.invest.ndr`` with the full (non-calibration) watershed set,
    writing results to ``OUTPUTS/<model_name>_best``.

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
    model_name : {'NDR_N', 'NDR_P'}
        Which nutrient to run the final pass for.

    Returns
    -------
    None
        Results are written to disk under ``OUTPUTS/<model_name>_best``;
        nothing is returned.
    """
    from natcap.invest.ndr import ndr as _ndr  # noqa: PLC0415

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
