# -*- coding: utf-8 -*-
"""InVEST Calibration Assistant - Shared per-iteration I/O helpers

Generic helpers shared by every model's calibration-iteration runner
(``models/*.py``): writing the candidate biophysical table, scoring a run
against observations, and appending the result to the EVALUATIONS CSVs.
"""

import os


def _calibrated_biotable_name(model_name, suffix):
    """File name of the biophysical table with the calibrated factors applied.

    Written under ``PARAMETERS/`` by every model's ``run_final`` and used as
    the biophysical table of the final ``OUTPUTS/<model_name>_best`` run.
    """
    return f'{model_name}_BioTable_Calibrated_{suffix}.csv'


def _last_iter_biotable_name(tag):
    """File name, under ``TMP/``, of the biophysical table of the last iteration."""
    return f'{tag}_BioTable_LastIter.csv'


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
    ``<workspace>/TMP/<tag>_BioTable_LastIter.csv`` for the InVEST model run.
    It is overwritten on every iteration: it is *not* the calibrated table
    (see :func:`_calibrated_biotable_name`).

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
    tmp_bio = os.path.join(workspace, 'TMP', _last_iter_biotable_name(tag))
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
        ``factor_metric``-adjusted objective function value, as returned
        to spotpy (negative for DDS, which maximizes).
    metric : float
        Unsigned metric value (e.g. the actual RMSE), as written to the
        ``_Metric_`` CSV.
    ws_ids : numpy.ndarray
        Watershed ids shared by ``obs_val`` and ``sim_val``, in the same
        order.
    obs_val : numpy.ndarray
        Observed values, matched to ``sim_val`` by ``ws_id``.
    sim_val : numpy.ndarray
        Simulated values, matched to ``obs_val`` by ``ws_id``.
    """
    [I, idx] = si.ismember(sim_df['ws_id'].values, obs_df['ws_id'].values)
    ws_ids  = sim_df['ws_id'].values[I]
    obs_val = obs_df[obs_col].values[idx]
    sim_val = sim_df[sim_col].values[I]
    metric  = si.Cal_FunObj(obs_val, sim_val, metric_name)
    obj     = factor_metric * metric
    return obj, metric, ws_ids, obs_val, sim_val


def _eval_csv_names(tag, suffix):
    """Return the EVALUATIONS CSV names for one model: (metric, obs, sim)."""
    return (f'{tag}_Metric_{suffix}.csv',
            f'{tag}_Obs_{suffix}.csv',
            f'{tag}_Sim_{suffix}.csv')


def _clear_eval_csvs(workspace, tag, suffix):
    """Delete a model's EVALUATIONS CSVs so a new calibration starts clean.

    ``_save_iteration`` appends to these files, so without this a second
    calibration with the same workspace and suffix would be mixed with
    the rows of the previous one.
    """
    for name in _eval_csv_names(tag, suffix):
        path = os.path.join(workspace, 'EVALUATIONS', name)
        if os.path.isfile(path):
            os.remove(path)


def _save_iteration(workspace, tag, suffix, header, row, ws_ids, obs_val, sim_val):
    """Append one calibration iteration to the model's EVALUATIONS CSVs.

    Shared tail of every model's iteration runner. The three files are
    laid out so they can be read side by side without the code:

    - ``<tag>_Metric_<suffix>.csv``: one row per iteration,
      ``iter,<params...>,<metric>``.
    - ``<tag>_Sim_<suffix>.csv``: one row per iteration,
      ``iter,ws_<id>,ws_<id>,...`` (same ``iter`` as the Metric row).
    - ``<tag>_Obs_<suffix>.csv``: a single row with the observed values,
      ``ws_<id>,ws_<id>,...``, written on the first iteration only
      (observations do not change between iterations).

    Parameters
    ----------
    workspace : str
        Calibration workspace directory.
    tag : str
        Model tag used in the output file names (e.g. ``'AWY'``, ``'NDR_N'``).
    suffix : str
        Project results suffix (``user_data['Suffix']``).
    header : str
        Comma-separated header for the ``_Metric_`` CSV (without ``iter``).
    row : str
        Comma-separated data row for the ``_Metric_`` CSV (without ``iter``).
        Its last value is the unsigned metric, not the signed objective
        handed to spotpy.
    ws_ids : numpy.ndarray
        Watershed ids of ``obs_val`` / ``sim_val``, in the same order.
    obs_val : numpy.ndarray
        Observed values for this iteration.
    sim_val : numpy.ndarray
        Simulated values for this iteration.

    Raises
    ------
    ValueError
        If the matched watersheds differ from the ones already written
        to the Sim CSV, which would misalign its columns.
    """
    metric_name, obs_name, sim_name = _eval_csv_names(tag, suffix)
    ws_header = ','.join(f'ws_{w}' for w in ws_ids)

    sim_path = os.path.join(workspace, 'EVALUATIONS', sim_name)
    if os.path.isfile(sim_path):
        with open(sim_path) as f:
            written_header = f.readline().strip()
        if written_header != f'iter,{ws_header}':
            raise ValueError(
                f'{tag}: watersheds matched in this iteration ({ws_header}) '
                f'differ from those already in {sim_name} ({written_header}).')

    metric_path = os.path.join(workspace, 'EVALUATIONS', metric_name)
    it = 1
    if os.path.isfile(metric_path):
        with open(metric_path) as f:
            it = sum(1 for _ in f)  # header + previous rows = next iter number

    _save_eval_csv(workspace, metric_name, f'iter,{header}', [f'{it},{row}'])
    if it == 1:
        _save_eval_csv(workspace, obs_name, ws_header,
                       [','.join(f'{v:.6g}' for v in obs_val)])
    _save_eval_csv(workspace, sim_name, f'iter,{ws_header}',
                   [f'{it},' + ','.join(f'{v:.6g}' for v in sim_val)])
