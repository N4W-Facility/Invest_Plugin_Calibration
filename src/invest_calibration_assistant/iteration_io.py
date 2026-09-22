# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - Shared per-iteration I/O helpers

Generic helpers shared by every model's calibration-iteration runner
(``models/*.py``): writing the candidate biophysical table, scoring a run
against observations, and appending the result to the EVALUATIONS CSVs.
"""

import os


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

    Shared by every model's iteration runner: each calibration iteration
    proposes a new parameter set, which is applied to the project's
    biophysical table and written to
    ``<workspace>/TMP/<tag>_biophysical.csv`` for the InVEST model run.

    Parameters
    ----------
    si : module
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.
    mp : dict
        ``model_paths`` dict from :func:`inputs._build_model_paths`.
    user_data : dict
        ``UserData`` dict from :func:`inputs._build_user_data`.
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

    Shared by every model's iteration runner to turn a model run's
    per-watershed output into the signed objective function value spotpy
    optimizes.

    Parameters
    ----------
    si : module
        The ``Spotpy_InVEST`` module, as returned by
        :func:`calibration_assistant._get_si`.
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

    Shared tail of every model's iteration runner: writes the
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
