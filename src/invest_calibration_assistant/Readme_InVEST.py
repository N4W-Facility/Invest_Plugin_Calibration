# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel / Carlos Andrés Rogéliz Prada / Miguel Angel Cañón
# Email         : jonathan.nogales@tnc.org
#
# Files that document a finished calibration run for its user, without
# reading the code:
#   - PARAMETERS/<MODEL>_BestParams_<suffix>.csv: final parameter table,
#     reusable as the parameter search-range input of a refined run.
#   - PARAMETERS/<MODEL>_BioTable_Calibrated_<suffix>.csv (written by
#     models/*.py run_final, documented here): biophysical table with the
#     calibrated factors applied.
#   - PARAMETERS/README_<MODEL>_<suffix>.md: columns and use of the three
#     PARAMETERS files (final parameters, calibrated table, Spotpy log).
#   - EVALUATIONS/README_<MODEL>_<suffix>.md: what every row/column of the
#     Metric/Obs/Sim CSVs means, how they join, units and data sources.
#   - README_<MODEL>_<suffix>.md (workspace root): folder map, what to open
#     first, and the key results of the run.
# -------------------------------------------------------------------------

import os

import pandas as pd

from .iteration_io import _calibrated_biotable_name, _eval_csv_names, _last_iter_biotable_name
from .Report_InVEST import _MODEL_FULL_NAME, _MODEL_UNIT_PLAIN, _param_description_unit

# Where each model's simulated value comes from, and which column of the
# observed-data table it is compared against. Mirrors models/*.py
# (run_iteration): keep both in sync if a model's scoring source changes.
_SIM_SOURCE = {
    'AWY': ('`wyield_vol` column of `OUTPUTS/01-AWY/output/watershed_results_wyield_<suffix>.csv` '
            '(total water yield volume per watershed)'),
    'SWY': ('mean of `OUTPUTS/02-SWY/intermediate_outputs/aet_<suffix>.tif` over each '
            'calibration watershed (mean actual evapotranspiration)'),
    'SDR': ('`sed_export` field of `OUTPUTS/03-SDR/watershed_results_sdr_<suffix>.dbf` '
            '(total sediment export per watershed)'),
    'NDR_N': ('sum of `OUTPUTS/04-NDR_N/n_total_export_<suffix>.tif` over each calibration '
              'watershed (total nitrogen export)'),
    'NDR_P': ('sum of `OUTPUTS/04-NDR_P/p_surface_export_<suffix>.tif` over each calibration '
              'watershed (surface phosphorus export)'),
}

# Per-iteration output folder of each model under OUTPUTS/ (models/*.py).
_ITER_OUTPUT_DIR = {
    'AWY': '01-AWY', 'SWY': '02-SWY', 'SDR': '03-SDR',
    'NDR_N': '04-NDR_N', 'NDR_P': '04-NDR_P',
}

# Spotpy database name suffix per method (calibration_assistant.execute).
_SPOTPY_DB_SUFFIX = {'DDS': 'DDS', 'SCE-UA': 'SCE', 'LHS': 'LHS'}

# Internal parameter key -> row name in the parameter search-range CSV
# (inverse of inputs._read_param_ranges' map; only IC0 is renamed).
_PARAMS_CSV_NAME = {'IC0': 'Borselli-IC0'}

# Biophysical-table columns scaled by each model's factors:
# (column, factor, Status_Cal flag, decimals, upper cap). Mirrors
# Spotpy_InVEST.Factor_BioTable: keep both in sync.
_BIOTABLE_FACTORS = {
    'AWY':   [('`Kc`', 'Factor-Kc', 'Status_Cal_Kc', 2, '1.2')],
    'SWY':   [('`Kc_1` … `Kc_12`', 'Factor-Kc_m', 'Status_Cal_Kc', 2, '1.2')],
    'SDR':   [('`usle_c`', 'Factor-C', 'Status_Cal_C', 5, '1'),
              ('`usle_p`', 'Factor-P', 'Status_Cal_P', 2, '1')],
    'NDR_N': [('`load_n`', 'Factor_Load_N', 'Status_Cal_Load_N', 3, 'none'),
              ('`eff_n`', 'Factor_Eff_N', 'Status_Cal_Eff_N', 2, 'none')],
    'NDR_P': [('`load_p`', 'Factor_Load_P', 'Status_Cal_Load_P', 3, 'none'),
              ('`eff_p`', 'Factor_Eff_P', 'Status_Cal_Eff_P', 2, 'none')],
}

# A best value closer than this fraction of its search range to Min or
# Max is flagged as pinned at a boundary.
_NEAR_BOUND_FRACTION = 0.02

# Metric short code -> (definition, how its unit relates to the variable's).
_METRIC_INFO = {
    'MSE':   ('Mean Square Error: mean((Sim - Obs)²)', 'variable unit squared'),
    'MAE':   ('Mean Absolute Error: mean(|Sim - Obs|)', 'same unit as the variable'),
    'RMSE':  ('Root Mean Square Error: sqrt(mean((Sim - Obs)²))', 'same unit as the variable'),
    'RRMSE': ('Relative Root Mean Square Error: RMSE / mean(Obs)', 'dimensionless'),
}


def _metric_unit(model_name, metric_short):
    """Plain-text unit of the metric for a model (mirrors _metric_unit_label)."""
    unit = _MODEL_UNIT_PLAIN.get(model_name, '')
    if metric_short == 'RRMSE':
        return 'dimensionless'
    if metric_short == 'MSE':
        return f'({unit})²'
    return unit


def _md_table(header, rows):
    """Render a GitHub-flavored Markdown table."""
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---' for _ in header) + '|']
    lines += ['| ' + ' | '.join(str(c) for c in row) + ' |' for row in rows]
    return '\n'.join(lines)


def _fmt(value):
    """Compact number formatting for the README tables."""
    return f'{value:.6g}'


def _best_params_name(model_name, suffix):
    """File name of the final parameter table under PARAMETERS/."""
    return f'{model_name}_BestParams_{suffix}.csv'


def Save_Best_Params(ProjectPath, Suffix, ModelName, ParamsMin, ParamsMax, ParamsVal,
                     FinalParams, UsedFallback):
    """Write ``PARAMETERS/<ModelName>_BestParams_<Suffix>.csv``.

    One row per calibrated parameter. The first five columns follow the
    parameter search-range input format (``Params, Model, Min, Max,
    Value``, with ``Value`` = final value), so the file can be fed back
    as the input of a refined calibration after adjusting ``Min``/``Max``;
    the remaining columns are informational and ignored on input.

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory.
    Suffix : str
        Project suffix used in the file name.
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    ParamsMin, ParamsMax, ParamsVal : dict
        Search bounds and initial guess, keyed by internal parameter name.
    FinalParams : dict
        Parameter values used for the final InVEST run.
    UsedFallback : bool
        True when no best-fit set was found and the initial guess was used.

    Returns
    -------
    str
        Path to the written CSV.
    """
    from .Spotpy_InVEST import _MODEL_PLOT_CONFIG

    rows = []
    for key, _ in _MODEL_PLOT_CONFIG[ModelName]['params']:
        lo, hi = ParamsMin[key], ParamsMax[key]
        value = FinalParams.get(key, ParamsVal[key])
        margin = _NEAR_BOUND_FRACTION * (hi - lo)
        near = 'Min' if value <= lo + margin else 'Max' if value >= hi - margin else ''
        description, unit = _param_description_unit(key)
        rows.append({
            'Params':      _PARAMS_CSV_NAME.get(key, key),
            'Model':       ModelName,
            'Min':         lo,
            'Max':         hi,
            'Value':       value,
            'Initial':     ParamsVal[key],
            'Unit':        unit,
            'Description': description,
            'Near_Bound':  near,
            'Source':      'initial guess (no best fit found)' if UsedFallback else 'calibrated',
        })

    path = os.path.join(ProjectPath, 'PARAMETERS', _best_params_name(ModelName, Suffix))
    pd.DataFrame(rows).to_csv(path, index=False, float_format='%.6g')
    return path


def Build_Evaluations_Readme(ProjectPath, Suffix, ModelName, MethodShort, MetricShort,
                             NSim, ObservedPath, EndTime):
    """Write ``EVALUATIONS/README_<ModelName>_<Suffix>.md`` for one calibration run.

    Reads the ``_Metric_``, ``_Obs_`` and ``_Sim_`` CSVs written by
    ``iteration_io._save_iteration`` and documents their layout, units,
    data sources and best iteration, with recipes to pair Sim with Obs
    in Excel or pandas.

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory.
    Suffix : str
        Project suffix used in the EVALUATIONS file names.
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    MethodShort : str
        Optimization algorithm short code (``'DDS'``, ``'LHS'``, ``'SCE-UA'``).
    MetricShort : str
        Objective metric short code (``'MSE'``, ``'MAE'``, ``'RMSE'``, ``'RRMSE'``).
    NSim : int
        Number of simulations requested.
    ObservedPath : str
        Path to the observed-data CSV given as input.
    EndTime : datetime.datetime
        End of the calibration run.

    Returns
    -------
    str
        Path to the written README.
    """
    # Deferred, as in Report_InVEST: keeps this module free of the heavy
    # plotting/geospatial imports of Spotpy_InVEST.
    from .Spotpy_InVEST import _MODEL_PLOT_CONFIG

    eval_dir = os.path.join(ProjectPath, 'EVALUATIONS')
    metric_name, obs_name, sim_name = _eval_csv_names(ModelName, Suffix)
    metric_tab = pd.read_csv(os.path.join(eval_dir, metric_name))
    obs_tab    = pd.read_csv(os.path.join(eval_dir, obs_name))
    sim_tab    = pd.read_csv(os.path.join(eval_dir, sim_name))

    unit        = _MODEL_UNIT_PLAIN.get(ModelName, '')
    metric_unit = _metric_unit(ModelName, MetricShort)
    metric_def, metric_unit_rule = _METRIC_INFO.get(MetricShort, (MetricShort, ''))
    param_keys  = [k for k, _ in _MODEL_PLOT_CONFIG[ModelName]['params']]
    param_cols  = list(metric_tab.columns[1:1 + len(param_keys)])
    metric_col  = metric_tab.columns[1 + len(param_keys)]
    ws_cols     = list(obs_tab.columns)
    first_ws    = ws_cols[0] if ws_cols else 'ws_1'

    best_row  = metric_tab.loc[metric_tab[metric_col].idxmin()]
    best_iter = int(best_row['iter'])
    best_sim  = sim_tab.set_index('iter').loc[best_iter]

    md = []
    md.append(f'# EVALUATIONS – {_MODEL_FULL_NAME.get(ModelName, ModelName)}\n')
    md.append('This folder holds one row per calibration iteration: the parameters tried, '
              'the score they got, and the simulated value of every calibration watershed, '
              'next to the observed values they were scored against. This README was '
              'generated automatically at the end of the run and describes these files only.\n')

    md.append('## Run summary\n')
    md.append(_md_table(['Item', 'Value'], [
        ['Model', _MODEL_FULL_NAME.get(ModelName, ModelName)],
        ['Optimization method', MethodShort],
        ['Evaluation metric', f'{MetricShort} ({metric_unit}) – lower is better'],
        ['Simulations requested', NSim],
        ['Iterations recorded', len(metric_tab)],
        ['Calibration watersheds', len(ws_cols)],
        ['Observed data file', f'`{ObservedPath}`'],
        ['Finished', EndTime.strftime('%Y-%m-%d %H:%M')],
    ]))
    md.append('')

    md.append('## Files\n')
    md.append(_md_table(['File', 'One row per', 'Content'], [
        [f'`{metric_name}`', 'iteration',
         '`iter`, the parameter values tried, and the metric they scored'],
        [f'`{sim_name}`', 'iteration',
         '`iter`, then the simulated value of each watershed (`ws_<id>` columns)'],
        [f'`{obs_name}`', '— (single row)',
         'the observed value of each watershed (same `ws_<id>` columns as Sim)'],
    ]))
    md.append('')

    md.append('## How the files fit together\n')
    md.append('```')
    md.append(f'{metric_name}   iter = k  ──►  parameters + {MetricShort}')
    md.append('        │ same iter')
    md.append('        ▼')
    md.append(f'{sim_name}      iter = k  ──►  Sim of {first_ws}, ...')
    md.append('        │ same ws_<id> column')
    md.append('        ▼')
    md.append(f'{obs_name}                 ──►  Obs of {first_ws}, ...')
    md.append('```\n')
    md.append('- **`iter`** links a row of the Metric file to the row of the Sim file '
              'produced by the same model run (iteration 1 is the first run).')
    md.append('- **`ws_<id>`** is the watershed id: the `ws_id` attribute of the calibration '
              'watersheds and the `ws_id` column of the observed data file. Only watersheds '
              'present in both are included.')
    md.append(f'- The {MetricShort} in row `iter = k` is computed from **all** `ws_<id>` columns '
              f'of Sim row `k` against the Obs row.\n')

    md.append('## Columns of the Metric file\n')
    rows = [['`iter`', 'Iteration number (1, 2, …)', '—']]
    for key, col in zip(param_keys, param_cols):
        description, param_unit = _param_description_unit(key)
        rows.append([f'`{col}`', description, param_unit])
    rows.append([f'`{metric_col}`', metric_def, metric_unit])
    md.append(_md_table(['Column', 'Meaning', 'Unit'], rows))
    md.append('\nParameters prefixed with `Factor` are multipliers applied to a column of the '
              'biophysical table, only for the land covers flagged in its `Status_Cal_*` '
              'columns.\n')

    md.append('## Units and data sources\n')
    md.append(_md_table(['Quantity', 'Source', 'Unit'], [
        ['Sim (`ws_<id>` in Sim file)',
         _SIM_SOURCE.get(ModelName, '—').replace('<suffix>', Suffix), unit],
        ['Obs (`ws_<id>` in Obs file)',
         f'`{ModelName}` column of the observed data file, matched by `ws_id`', unit],
        [MetricShort, f'Sim vs Obs over all watersheds ({metric_unit_rule})', metric_unit],
    ]))
    md.append('\nValues are kept in the model\'s native output units: Obs and Sim are never '
              'rescaled, so your observed data must already be in these units.\n')

    md.append('## Best iteration\n')
    md.append(f'The best iteration is the row of the Metric file with the **lowest** '
              f'`{metric_col}`: **iter = {best_iter}**, {MetricShort} = '
              f'**{_fmt(best_row[metric_col])}** {metric_unit}. Its parameters are the ones '
              f'used for the final run in `OUTPUTS/{ModelName}_best`.\n')
    md.append(_md_table(['Parameter', 'Best value'],
                        [[f'`{c}`', _fmt(best_row[c])] for c in param_cols]))
    md.append('')
    md.append(f'Observed vs simulated for iter = {best_iter} ({unit}):\n')
    rows = []
    for ws in ws_cols:
        obs, sim = float(obs_tab[ws].iloc[0]), float(best_sim[ws])
        bias = f'{100 * (sim - obs) / obs:+.1f} %' if obs else '—'
        rows.append([f'`{ws}`', _fmt(obs), _fmt(sim), bias])
    md.append(_md_table(['Watershed', 'Obs', 'Sim', '(Sim − Obs) / Obs'], rows))
    md.append('')

    md.append('## Reading the files yourself\n')
    md.append('**Excel / LibreOffice**\n')
    md.append(f'1. Open `{metric_name}` and sort by `{metric_col}` ascending: the first row is '
              f'the best iteration.')
    md.append(f'2. Open `{sim_name}` and find the row with the same `iter`.')
    md.append(f'3. Copy the single data row of `{obs_name}` right under it: the columns line up '
              f'watershed by watershed.\n')
    md.append('**Python (pandas)**\n')
    md.append('```python')
    md.append('import pandas as pd')
    md.append('')
    md.append(f"metric = pd.read_csv('{metric_name}')")
    md.append(f"sim    = pd.read_csv('{sim_name}', index_col='iter')")
    md.append(f"obs    = pd.read_csv('{obs_name}').iloc[0]")
    md.append('')
    md.append(f"best = metric.loc[metric['{metric_col}'].idxmin()]")
    md.append("pairs = pd.DataFrame({'Obs': obs, 'Sim': sim.loc[int(best['iter'])]})")
    md.append('print(best)')
    md.append('print(pairs)')
    md.append('```\n')

    md.append('## Notes\n')
    md.append('- These files are **deleted at the start of every calibration** of this model and '
              'suffix, so they always describe a single run. Copy the folder elsewhere to keep a '
              'previous run.')
    md.append(f'- The metric is stored as its true value (≥ 0, lower is better) whatever the '
              f'algorithm. Spotpy\'s own database in `PARAMETERS/` stores the value handed to the '
              f'optimizer instead, which DDS (a maximizer) receives as −{MetricShort}.')
    md.append('- The figure `FIGURES/Calibration_' + f'{ModelName}_{Suffix}.jpg` plots these '
              'same files: Obs vs Sim of the best iteration, and the metric of every iteration '
              'against each parameter.')

    path = os.path.join(eval_dir, f'README_{ModelName}_{Suffix}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    return path


def Build_Parameters_Readme(ProjectPath, Suffix, ModelName, MethodShort, MetricShort, EndTime):
    """Write ``PARAMETERS/README_<ModelName>_<Suffix>.md`` for one calibration run.

    Documents the three files of this model and suffix under PARAMETERS/:
    the final parameter table (:func:`Save_Best_Params`), the calibrated
    biophysical table (``models/*.py`` run_final) and Spotpy's database.

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory.
    Suffix : str
        Project suffix used in the file names.
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    MethodShort : str
        Optimization algorithm short code (``'DDS'``, ``'LHS'``, ``'SCE-UA'``).
    MetricShort : str
        Objective metric short code (``'MSE'``, ``'MAE'``, ``'RMSE'``, ``'RRMSE'``).
    EndTime : datetime.datetime
        End of the calibration run.

    Returns
    -------
    str
        Path to the written README.
    """
    from .Spotpy_InVEST import _MODEL_PLOT_CONFIG

    param_dir     = os.path.join(ProjectPath, 'PARAMETERS')
    params_name   = _best_params_name(ModelName, Suffix)
    biotable_name = _calibrated_biotable_name(ModelName, Suffix)
    spotpy_db     = f'{ModelName}_{_SPOTPY_DB_SUFFIX.get(MethodShort, MethodShort)}.csv'
    param_keys    = [k for k, _ in _MODEL_PLOT_CONFIG[ModelName]['params']]

    # Final factor values, to show the multiplier actually applied.
    final_val = {}
    params_path = os.path.join(param_dir, params_name)
    if os.path.isfile(params_path):
        params = pd.read_csv(params_path, keep_default_na=False)
        final_val = dict(zip(params['Params'], params['Value']))

    md = []
    md.append(f'# PARAMETERS – {_MODEL_FULL_NAME.get(ModelName, ModelName)}\n')
    md.append(f'Final results of calibrating **{ModelName}** (suffix `{Suffix}`) with '
              f'{MethodShort}, finished {EndTime.strftime("%Y-%m-%d %H:%M")}. This README was '
              'generated automatically and only describes the files of this model and suffix.\n')

    md.append('## Files\n')
    md.append(_md_table(['File', 'Content', 'Use it to'], [
        [f'`{params_name}`', 'Final value of every calibrated parameter',
         'Report the calibration; start a refined calibration'],
        [f'`{biotable_name}`', 'Biophysical table with the calibrated factors applied',
         'Run InVEST with the calibrated land-cover coefficients'],
        [f'`{spotpy_db}`', 'Spotpy\'s raw log of every iteration',
         'Debugging only: prefer `EVALUATIONS/`'],
    ]))
    md.append('')

    md.append(f'## `{params_name}`\n')
    md.append('One row per calibrated parameter.\n')
    md.append(_md_table(['Column', 'Meaning'], [
        ['`Params`', 'Parameter name, as in the parameter input file.'],
        ['`Model`', 'Model the parameter belongs to.'],
        ['`Min`, `Max`', 'Search range used in this calibration.'],
        ['`Value`', '**Final value**: the one used in the final run `OUTPUTS/'
                    f'{ModelName}_best/`.'],
        ['`Initial`', 'Initial guess given in the parameter input file.'],
        ['`Unit`', 'Unit of the parameter (empty when dimensionless).'],
        ['`Description`', 'What the parameter controls.'],
        ['`Near_Bound`', '`Min` or `Max` when `Value` lies within '
                         f'{_NEAR_BOUND_FRACTION:.0%} of that end of the search range: the '
                         'optimum may lie outside it. Empty otherwise.'],
        ['`Source`', '`calibrated`, or `initial guess (no best fit found)` when the calibration '
                     'produced no valid best fit and the initial guess was used instead.'],
    ]))
    md.append('')
    md.append('**Refined calibration:** its first five columns (`Params, Model, Min, Max, Value`) '
              'follow the parameter input format and the rest are ignored on input, so this file '
              'can be given directly as the parameter input of a new run. Widen `Min`/`Max` of '
              'the parameters flagged in `Near_Bound`, or narrow the range around `Value`, '
              'first.\n')
    md.append('Parameters whose name does not start with `Factor` are InVEST model arguments: '
              'they are **not** stored in the biophysical table. To reproduce the calibrated '
              'run in InVEST, enter their `Value` in the corresponding model input.\n')

    md.append(f'## `{biotable_name}`\n')
    md.append('Copy of the input biophysical table where the columns below were multiplied by '
              'their calibrated factor, **only in the rows (land covers) whose `Status_Cal_*` '
              'flag is 1**. Every other row and column is unchanged. It is the biophysical '
              'table the final run used.\n')
    md.append(_md_table(['Column', 'Factor', 'Final factor', 'Rows changed when',
                         'Rounding', 'Upper cap'], [
        [col, f'`{factor}`', _fmt(final_val[factor]) if factor in final_val else '–',
         f'`{flag}` = 1', f'{dec} decimals', cap]
        for col, factor, flag, dec, cap in _BIOTABLE_FACTORS[ModelName]
    ]))
    md.append('')
    if ModelName in ('NDR_N', 'NDR_P'):
        nutrient = ModelName[-1].lower()
        md.append(f'If the input table had no `load_type_{nutrient}` column, it was added with '
                  'the value `measured-runoff` (required by InVEST ≥ 3.18).\n')
    md.append('**Using it:** give it as the biophysical table of any InVEST run of this model; '
              'InVEST ignores the extra `Status_Cal_*` columns. Do **not** use it as the input '
              'biophysical table of a new calibration: the new factors would be applied on top '
              'of the already calibrated values. Start new calibrations from the original '
              'table.\n')

    md.append(f'## `{spotpy_db}`\n')
    md.append('Written by Spotpy itself, one row per iteration.\n')
    md.append(_md_table(['Column', 'Meaning'], [
        ['`like1`', f'Objective handed to the optimizer: −{MetricShort} for DDS (a maximizer), '
                    f'{MetricShort} for SCE-UA and LHS.'],
        [', '.join(f'`par{k}`' for k in param_keys), 'Parameter values of the iteration.'],
        ['`simulation_0`, `simulation_1`, …', 'A **copy of the parameter values**, not '
         'simulated values: the plugin runs InVEST inside the objective function, so Spotpy '
         'only sees the parameters. Simulated values are in `EVALUATIONS/`.'],
        ['`chain`', 'Spotpy internal bookkeeping.'],
    ]))
    md.append('')
    md.append('Its name has **no suffix**: any new calibration of this model with the same '
              'method overwrites it, even with a different suffix. `EVALUATIONS/` holds the '
              'same iterations with the metric as its true value (≥ 0, lower is better) and '
              'is the recommended source.')

    path = os.path.join(param_dir, f'README_{ModelName}_{Suffix}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    return path


def Build_Workspace_Readme(ProjectPath, Suffix, ModelName, MethodShort, MetricShort,
                           NSim, BestMetricValue, UsedFallback, EndTime):
    """Write ``README_<ModelName>_<Suffix>.md`` at the workspace root.

    Entry point for a user opening the workspace: key results, what to
    open first, and what every folder holds for this model and suffix.
    Reads the final parameter table written by :func:`Save_Best_Params`
    when it exists.

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory.
    Suffix : str
        Project suffix used in the output file names.
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    MethodShort : str
        Optimization algorithm short code (``'DDS'``, ``'LHS'``, ``'SCE-UA'``).
    MetricShort : str
        Objective metric short code (``'MSE'``, ``'MAE'``, ``'RMSE'``, ``'RRMSE'``).
    NSim : int
        Number of simulations requested.
    BestMetricValue : float or None
        Best (unsigned) metric value, or ``None`` if it could not be found.
    UsedFallback : bool
        True when no best-fit set was found and the initial guess was used.
    EndTime : datetime.datetime
        End of the calibration run.

    Returns
    -------
    str
        Path to the written README.
    """
    metric_unit = _metric_unit(ModelName, MetricShort)
    iter_dir    = _ITER_OUTPUT_DIR.get(ModelName, ModelName)
    metric_name, obs_name, sim_name = _eval_csv_names(ModelName, Suffix)
    params_name = _best_params_name(ModelName, Suffix)
    params_path = os.path.join(ProjectPath, 'PARAMETERS', params_name)
    biotable_name = _calibrated_biotable_name(ModelName, Suffix)
    spotpy_db   = f'{ModelName}_{_SPOTPY_DB_SUFFIX.get(MethodShort, MethodShort)}.csv'
    eval_readme = f'README_{ModelName}_{Suffix}.md'
    param_readme = eval_readme

    md = []
    md.append(f'# Calibration workspace – {_MODEL_FULL_NAME.get(ModelName, ModelName)}\n')
    md.append(f'Results of calibrating **{ModelName}** (suffix `{Suffix}`) with {MethodShort}, '
              f'{NSim} simulations, finished {EndTime.strftime("%Y-%m-%d %H:%M")}. '
              f'This README was generated automatically and only describes the files of this '
              f'model and suffix: other models calibrated in the same workspace have their own.\n')

    md.append('## Key results\n')
    if UsedFallback:
        md.append('> **Warning:** no valid best-fit parameter set was found. The final run used '
                  'the **initial guess** from the parameter input file. Check the logs and '
                  '`EVALUATIONS/` before using these results.\n')
    if BestMetricValue is not None:
        md.append(f'- Best {MetricShort}: **{_fmt(BestMetricValue)}** {metric_unit} '
                  f'(lower is better).')
    near_rows = []
    if os.path.isfile(params_path):
        params = pd.read_csv(params_path, keep_default_na=False)
        md.append(f'- Final parameters (`PARAMETERS/{params_name}`):\n')
        md.append(_md_table(['Parameter', 'Final value', 'Search range', 'Unit'], [
            [f'`{r.Params}`', _fmt(r.Value), f'{_fmt(r.Min)} – {_fmt(r.Max)}', r.Unit]
            for r in params.itertuples()]))
        near_rows = [r for r in params.itertuples() if r.Near_Bound]
    md.append('')
    if near_rows:
        md.append('> **Parameters at a range boundary:** '
                  + ', '.join(f'`{r.Params}` ({r.Near_Bound})' for r in near_rows)
                  + '. The optimum may lie outside the search range: consider widening it in '
                  f'`PARAMETERS/{params_name}` and running a new calibration with that file as '
                  'the parameter input.\n')

    md.append('## Where to start\n')
    md.append(f'1. `REPORT/Report_{ModelName}_{Suffix}.html` – full calibration report '
              '(open in a browser).')
    md.append(f'2. `FIGURES/Calibration_{ModelName}_{Suffix}.jpg` – Obs vs Sim of the best run '
              'and the metric against each parameter.')
    md.append(f'3. `PARAMETERS/{params_name}` – final parameter values.')
    md.append(f'4. `PARAMETERS/{biotable_name}` – biophysical table with the calibrated '
              'factors applied: use it as the biophysical table of future InVEST runs.')
    md.append(f'5. `OUTPUTS/{ModelName}_best/` – InVEST results with the final parameters over '
              'all watersheds: **these are the calibrated results to use**.')
    md.append(f'6. `PARAMETERS/{param_readme}` – columns of the PARAMETERS files and how to reuse '
              'them.')
    md.append(f'7. `EVALUATIONS/{eval_readme}` – how to read the per-iteration data.\n')

    md.append('## Folders\n')
    md.append(_md_table(['Folder', 'Files for this run', 'Content'], [
        ['`REPORT/`', f'`Report_{ModelName}_{Suffix}.html`', 'Self-contained HTML report.'],
        ['`FIGURES/`', f'`Calibration_{ModelName}_{Suffix}.jpg`', 'Calibration figure.'],
        ['`PARAMETERS/`', f'`{param_readme}`',
         'What every column of the files below means and how to reuse them.'],
        ['`PARAMETERS/`', f'`{params_name}`',
         'Final parameter table. Its first columns (`Params, Model, Min, Max, Value`) follow '
         'the parameter input format, so it can be reused as the input of a new run.'],
        ['`PARAMETERS/`', f'`{biotable_name}`',
         'Biophysical table with the calibrated factors applied (only to the land covers '
         'flagged in its `Status_Cal_*` columns). It is the table the final run used.'],
        ['`PARAMETERS/`', f'`{spotpy_db}`',
         'Spotpy\'s raw log of every iteration. Its objective column is the value handed to '
         f'the optimizer (−{MetricShort} for DDS, which maximizes); prefer `EVALUATIONS/`. '
         'Its name has no suffix, so any new run of this model and method overwrites it.'],
        ['`EVALUATIONS/`', f'`{metric_name}`, `{sim_name}`, `{obs_name}`, `{eval_readme}`',
         'Per-iteration parameters, metric and simulated values, plus the observations '
         'they are compared against.'],
        [f'`OUTPUTS/{ModelName}_best/`', 'InVEST outputs',
         'Final run with the best parameters over all watersheds.'],
        [f'`OUTPUTS/{iter_dir}/`', 'InVEST outputs',
         'Working folder of the calibration iterations, over the calibration watersheds only. '
         '**Overwritten on every iteration**: it holds the *last* iteration, not the best one.'],
        ['`TMP/`', f'`{_last_iter_biotable_name(ModelName)}`, zonal statistics',
         'Biophysical table and zonal statistics of the **last** iteration (not the calibrated '
         'one). Safe to delete.'],
    ]))
    md.append('')

    md.append('## Running again\n')
    md.append('A new calibration of this model **overwrites** the files listed above: all of '
              'them when it uses the same suffix (the `EVALUATIONS/` CSVs are cleared when it '
              'starts), and the ones without the suffix in their name (the Spotpy log, '
              '`OUTPUTS/` folders and `TMP/`) even with a different suffix. Copy this workspace '
              'to keep this run intact.')

    path = os.path.join(ProjectPath, f'README_{ModelName}_{Suffix}.md')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(md) + '\n')
    return path
