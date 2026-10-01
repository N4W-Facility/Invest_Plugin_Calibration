# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel / Carlos Andrés Rogéliz Prada / Miguel Angel Cañón
# Email         : jonathan.nogales@tnc.org
#
# Markdown README for the EVALUATIONS folder. Written at the end of each
# calibration run so a user opening the Metric/Obs/Sim CSVs knows what
# every row and column means, which observation each simulated value is
# compared against, and in which units — without reading the code.
# -------------------------------------------------------------------------

import os

import pandas as pd

from .iteration_io import _eval_csv_names
from .Report_InVEST import _MODEL_FULL_NAME, _MODEL_UNIT_PLAIN, _PARAM_PLAIN_LABELS

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
        label = _PARAM_PLAIN_LABELS.get(key, key)
        rows.append([f'`{col}`', label.replace(' (m)', ''),
                     'm' if label.endswith('(m)') else 'dimensionless'])
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
