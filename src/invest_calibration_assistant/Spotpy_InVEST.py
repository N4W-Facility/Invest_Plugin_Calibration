# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel / Carlos Andrés Rogéliz Prada / Miguel Angel Cañón
# Email         : jonathan.nogales@tnc.org
#
# -------------------------------------------------------------------------
#                        DEVELOPMENT HISTORY
# -------------------------------------------------------------------------
# Core calibration methodology originated in 2021 (WaterProof project,
# InVEST 3.9), conceived by Jonathan Nogales Pimentel and Carlos
# Andres Rogeliz Prada, and coded by Jonathan Nogales Pimentel. Published
# in Rogeliz et al. (2022), Water 14(21):3447
# (https://doi.org/10.3390/w14213447). Rebuilt as a standalone
# calibration tool in 2024-2025 by Jonathan Nogales Pimentel. Adapted
# to the InVEST plugin standard in 2026 by Miguel Angel Canon Ramos.
#
# Full history, contributor roles, and a note on git-blame attribution
# for the pre-2026 codebase: see CONTRIBUTING.md.
# -------------------------------------------------------------------------


# ----------------------------------------------------------------------------------------------------------------------
# Package
# ----------------------------------------------------------------------------------------------------------------------
import base64
import os
import spotpy
import numpy as np
import pandas as pd
import geopandas as gpd
from osgeo import gdal, ogr
from osgeo.gdalconst import GA_ReadOnly
import rasterio
import matplotlib.pyplot as plt
from matplotlib import rcParams
from matplotlib.lines import Line2D
# LaTeX-style typography (Computer Modern) for text and math, without
# depending on a TeX installation or external system fonts.
rcParams['font.family'] = 'serif'
rcParams['font.serif']  = ['cmr10', 'DejaVu Serif']
rcParams['mathtext.fontset'] = 'cm'
rcParams['axes.unicode_minus'] = False
from rasterstats import zonal_stats

gdal.PushErrorHandler('CPLQuietErrorHandler')

# --------------------------------------------------------------------------
# Folder utilities
# --------------------------------------------------------------------------

def CreateFolder(dir):
    """Create a directory (and any missing parents), ignoring if it exists.

    Parameters
    ----------
    dir : str
        Path of the directory to create.

    Returns
    -------
    None
    """
    try:
        os.makedirs(dir)
    except FileExistsError:
        # Directory already exists — nothing to do.
        pass


# --------------------------------------------------------------------------
# Biophysical table factor application
# --------------------------------------------------------------------------

def Factor_BioTable(PathBioTable, Params, UserData):
    """Apply calibration factors to the biophysical table for one model.

    Reads the biophysical CSV and multiplies the columns relevant to the
    active model (flagged via ``UserData['Status_*']``) by the candidate
    calibration factors in ``Params``, but only for the LULC rows flagged
    as calibratable (``Status_Cal_*`` == 1). Values are clipped to their
    physical upper bound (e.g. Kc <= 1.2, usle_c/usle_p <= 1) after scaling.

    Parameters
    ----------
    PathBioTable : str
        Path to the biophysical table CSV (Latin-1 encoded).
    Params : dict
        Candidate calibration factors for the active model, e.g.
        ``{'Factor-Kc': 1.05}`` for AWY or
        ``{'Factor-C': 0.9, 'Factor-P': 1.0}`` for SDR.
    UserData : dict
        ``Status_*`` flags (0/1) selecting which model's columns to
        modify, as built by ``_build_user_data`` in
        ``calibration_assistant.py``.

    Returns
    -------
    pandas.DataFrame
        Biophysical table with the calibrated columns updated in place.
    """
    # Read the biophysical table.
    Table = pd.read_csv(PathBioTable, encoding='latin-1')

    # Annual Water Yield
    if UserData['Status_AWY']:
        # Scale the Kc column by the calibration factor and round to 2 decimals.
        Values = round(Table['Kc'] * Params['Factor-Kc'], 2)
        # Cap Kc at 1.2 (physical upper bound).
        Values[Values >= 1.2] = 1.2
        # Write the scaled Kc back only for rows flagged as calibratable.
        Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc'] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Seasonal Water Yield
    if UserData['Status_SWY']:
        # Scale each monthly Kc_<month> column by the calibration factor.
        for ij in range(1, 13):
            Values = round(Table['Kc_' + str(ij)] * round(Params['Factor-Kc_m'], 2), 2)
            # Cap Kc at 1.2 (physical upper bound).
            Values[Values >= 1.2] = 1.2
            # Write the scaled Kc back only for rows flagged as calibratable.
            Table.loc[Table['Status_Cal_Kc'] == 1, 'Kc_' + str(ij)] = Values.loc[Table['Status_Cal_Kc'] == 1]

    # Sediment Delivery Ratio
    if UserData['Status_SDR'] == 1:
        # Scale the USLE cover factor (C) and round to 5 decimals.
        Values = round(Table['usle_c'] * round(Params['Factor-C'], 2), 5)
        # Cap C at 1 (physical upper bound).
        Values[Values > 1] = 1
        # Write the scaled C back only for rows flagged as calibratable.
        Table.loc[Table['Status_Cal_C'] == 1, 'usle_c'] = Values.loc[Table['Status_Cal_C'] == 1]

        # Scale the USLE support-practice factor (P) and round to 2 decimals.
        Values = round(Table['usle_p'] * round(Params['Factor-P'], 2), 2)
        # Cap P at 1 (physical upper bound).
        Values[Values > 1] = 1
        # Write the scaled P back only for rows flagged as calibratable.
        Table.loc[Table['Status_Cal_P'] == 1, 'usle_p'] = Values.loc[Table['Status_Cal_P'] == 1]

    # Nutrient Delivery Ratio (nitrogen)
    if (UserData['Status_NDR_N'] == 1):
        Values = round(Table['load_n'] * Params['Factor_Load_N'], 3)
        Table.loc[Table['Status_Cal_Load_N'] == 1, 'load_n'] = Values.loc[Table['Status_Cal_Load_N'] == 1]

        Values = round(Table['eff_n'] * Params['Factor_Eff_N'], 2)
        Table.loc[Table['Status_Cal_Eff_N'] == 1, 'eff_n'] = Values.loc[Table['Status_Cal_Eff_N'] == 1]

    # Nutrient Delivery Ratio (phosphorus)
    if (UserData['Status_NDR_P'] == 1):
        Values = round(Table['load_p'] * Params['Factor_Load_P'], 3)
        Table.loc[Table['Status_Cal_Load_P'] == 1, 'load_p'] = Values.loc[Table['Status_Cal_Load_P'] == 1]

        Values = round(Table['eff_p'] * Params['Factor_Eff_P'], 2)
        Table.loc[Table['Status_Cal_Eff_P'] == 1, 'eff_p'] = Values.loc[Table['Status_Cal_Eff_P'] == 1]

    # Carbon (not yet implemented)
    # if UserData['Status_CO2'] == 1:
    #    print('')

    return Table


# --------------------------------------------------------------------------
# Objective function calculation
# --------------------------------------------------------------------------

def Cal_FunObj(Obs, Sim, NameFunObj):
    """Compute the calibration objective function value.

    Thin dispatcher over ``spotpy.objectivefunctions``, selecting the
    metric by its display name (as used in ``MODEL_SPEC``'s
    ``evaluation_metric`` option list).

    Parameters
    ----------
    Obs : array-like
        Observed values.
    Sim : array-like
        Simulated values, same length/order as ``Obs``.
    NameFunObj : str
        One of ``'Mean Square Error (MSE)'``, ``'Mean Absolute Error (MAE)'``,
        ``'Root Mean Square Error (RMSE)'``,
        ``'Relative Root Mean Squared Error (RRMSE)'``.

    Returns
    -------
    float or None
        The computed metric, or ``None`` if ``NameFunObj`` does not match
        any of the supported metric names.
    """
    if NameFunObj == "Mean Square Error (MSE)":
        return spotpy.objectivefunctions.mse(Obs, Sim)
    elif NameFunObj == "Mean Absolute Error (MAE)":
        return spotpy.objectivefunctions.mae(Obs, Sim)
    elif NameFunObj == "Root Mean Square Error (RMSE)":
        return spotpy.objectivefunctions.rmse(Obs, Sim)
    elif NameFunObj == "Relative Root Mean Squared Error (RRMSE)":
        return spotpy.objectivefunctions.rrmse(Obs, Sim)

# --------------------------------------------------------------------------
# Calibration plots
# --------------------------------------------------------------------------
# Shared visual style for all calibration figures:
#   - Dotty plots: light gray points with a darker gray edge (clean/modern look).
#   - Best-fit parameter: highlighted in wine red.
_DOT_FACE   = '#D9D9D9'   # light gray fill
_DOT_EDGE   = '#8C8C8C'   # darker gray edge
_BEST_COLOR = '#7B1E24'   # wine red (vinotinto)
_REF_COLOR  = [0.8, 0.8, 0.8]

def _style_axis(ax, fontsize=16):
    """Apply the shared clean/modern panel style used by every calibration plot.

    Removes the top/right spines, colors the remaining spines and tick
    labels in dark gray, and adds a light dotted grid behind the data.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        Axes to style, in place.
    fontsize : int, optional
        Reference font size (tick labels are drawn 3pt smaller). Default 16.

    Returns
    -------
    None
    """
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_color('#595959')
    ax.spines['bottom'].set_color('#595959')
    ax.grid(True, linestyle=':', linewidth=0.7, color='#BFBFBF', alpha=0.6)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=fontsize - 3, colors='#404040')

# Per-model plot configuration: unit label, time conversion factor (only AWY
# reports Obs/Sim/Metric in per-second and needs converting to per-year),
# and the (result key, axis label) pairs in the same column order used by
# each model's EVALUATIONS/*_Metric_{Suffix}.csv file.
_MODEL_PLOT_CONFIG = {
    'AWY': {
        'unit': r'$(\mathrm{m}^3/\mathrm{s})$',
        'time_scale': 1 / (3600 * 24 * 365),
        'params': [
            ('Z', r'$Z$'),
            ('Factor-Kc', r'Factor$_{K_c}$'),
        ],
    },
    'SWY': {
        'unit': r'$(mm)$',
        'time_scale': 1,
        'params': [
            ('Alpha', r'$\alpha$'),
            ('Beta', r'$\beta$'),
            ('Gamma', r'$\gamma$'),
            ('Factor-Kc_m', r'Factor$_{K_c}$'),
        ],
    },
    'SDR': {
        'unit': r'$(ton/year)$',
        'time_scale': 1,
        'params': [
            ('sdr_max', r'SDR$_{max}$'),
            ('Borselli-K_SDR', r'$K$'),
            ('IC0', r'IC$_{0}$'),
            ('L_max', r'L$_{max}$'),
            ('Factor-C', r'Factor$_{C}$'),
            ('Factor-P', r'Factor$_{P}$'),
        ],
    },
    'NDR_N': {
        'unit': r'$(kg/year)$',
        'time_scale': 1,
        'params': [
            ('SubCri_Len_N', r'SubCri$_{Len_N}$'),
            ('Sub_Eff_N', r'Sub$_{Eff_N}$'),
            ('Borselli-K_NDR', r'Borselli$_{K}$'),
            ('Factor_Load_N', r'Factor$_{Load_N}$'),
            ('Factor_Eff_N', r'Factor$_{Eff_N}$'),
        ],
    },
    'NDR_P': {
        'unit': r'$(kg/year)$',
        'time_scale': 1,
        'params': [
            ('SubCri_Len_P', r'SubCri$_{Len_P}$'),
            ('Sub_Eff_P', r'Sub$_{Eff_P}$'),
            ('Borselli-K_NDR', r'Borselli$_{K}$'),
            ('Factor_Load_P', r'Factor$_{Load_P}$'),
            ('Factor_Eff_P', r'Factor$_{Eff_P}$'),
        ],
    },
}

def _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, ModelName):
    """Build the calibration figure for one model and return its best-fit parameters.

    Reads the ``EVALUATIONS/<ModelName>_{Metric,Obs,Sim}_<Suffix>.csv``
    files written during the calibration run, identifies the iteration
    with the best objective-function value, and renders one figure with:
    an Observed-vs-Simulated scatter panel (using the best-fit run) plus
    one dotty plot per calibrated parameter (parameter value vs. metric,
    best-fit point highlighted). The figure is saved to
    ``FIGURES/Calibration_<ModelName>_<Suffix>.jpg``.

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory (contains ``EVALUATIONS`` and
        ``FIGURES`` sub-folders).
    Suffix : str
        Project suffix used to build the EVALUATIONS/FIGURES file names.
    NameMetric : str
        Short metric label used in axis/title text (e.g. ``'RMSE'``).
    FactorMetric : float
        ``+1`` or ``-1``; the sign applied to the metric during
        calibration (see ``_execute_*_direct`` in
        ``calibration_assistant.py``). Used here to recover the true
        (unsigned) metric value and to find its minimum regardless of
        whether the optimizer maximized or minimized.
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``;
        selects the plot configuration from ``_MODEL_PLOT_CONFIG``.

    Returns
    -------
    tuple of (dict, float)
        ``(BestParamsDict, BestMetricValue)`` — best-fit parameter values
        keyed by internal parameter name, and the unsigned metric value
        (e.g. RMSE) achieved by that best-fit run.
    """
    cfg         = _MODEL_PLOT_CONFIG[ModelName]
    unit        = cfg['unit']
    time_scale  = cfg['time_scale']
    param_keys, param_labels = zip(*cfg['params'])
    n_params    = len(param_keys)

    # Metric and parameters
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Metric_{Suffix}.csv')
    Tmp         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Params      = Tmp[:, :n_params]
    Metric      = Tmp[:, n_params] * time_scale

    # Observed
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Obs_{Suffix}.csv')
    Obs         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    NGauges     = len(Obs) // len(Metric)
    Obs         = Obs.reshape(len(Metric), NGauges)
    Obs         = Obs.transpose()
    Obs         = Obs[:, 0] * time_scale
    Obs         = Obs.reshape(NGauges, 1)

    # Simulation
    FileName    = os.path.join(ProjectPath, 'EVALUATIONS', f'{ModelName}_Sim_{Suffix}.csv')
    Sim         = np.loadtxt(FileName, delimiter=',', skiprows=1)
    Sim         = Sim.reshape(len(Metric), len(Sim) // len(Metric))
    Sim         = Sim.transpose() * time_scale

    # Best parameters.
    # Metric already has FactorMetric applied (FactorMetric*RMSE), so
    # multiplying by FactorMetric again before comparing recovers the true
    # RMSE, regardless of whether the algorithm internally maximizes (DDS)
    # or minimizes (SCE-UA/LHS).
    id_min          = np.argmin(FactorMetric * Metric)
    BestParams      = Params[id_min, :]
    BestParamsDict  = dict(zip(param_keys, BestParams))
    BestAREM        = FactorMetric * Metric[id_min]
    Metric          = FactorMetric * Metric

    # Grid sized to the exact number of panels needed (1 Obs-vs-Sim + 1 per
    # parameter), so no plot ever has empty/unused axes.
    n_axes = 1 + n_params
    n_cols = 3 if n_axes <= 6 else 4
    n_rows = -(-n_axes // n_cols)  # ceil division
    fig, axes = plt.subplots(n_rows, n_cols, figsize=(5 * n_cols, 4.5 * n_rows))
    axes = np.array(axes).reshape(-1)
    for extra_ax in axes[n_axes:]:
        fig.delaxes(extra_ax)

    # Obs vs Sim
    ax = axes[0]
    max_val = max(np.max(Obs), np.max(Sim[:, id_min])) * 1.1
    ax.plot([0, max_val], [0, max_val], linewidth=1.2, color=_REF_COLOR, zorder=1)
    ax.scatter(Obs, Sim[:, id_min], s=100, edgecolor=_DOT_EDGE, facecolor=_DOT_FACE, alpha=0.9, linewidth=1.2, zorder=2)
    ax.set_xlabel(f'Observed {unit}', fontsize=16)
    ax.set_ylabel(f'Simulated {unit}', fontsize=16)
    ax.set_title(f'{NameMetric} = {round(BestAREM, 2)} {unit}', fontsize=16, pad=10)
    _style_axis(ax)

    # Dotty plots, one per calibrated parameter
    for i, label in enumerate(param_labels):
        ax = axes[1 + i]
        ax.scatter(Params[:, i], Metric, s=30, edgecolor=_DOT_EDGE, facecolor=_DOT_FACE, alpha=0.6, linewidth=0.8, zorder=2)
        ax.scatter(BestParams[i], BestAREM, s=60, color=_BEST_COLOR, edgecolor='black', linewidth=0.6, zorder=3)
        ax.set_xlabel(label, fontsize=16)
        ax.set_ylabel(f'{NameMetric} {unit}', fontsize=16)
        ax.set_title(f'{label} = {BestParams[i]:.4g}', fontsize=16, pad=10)
        _style_axis(ax)

    fig.patch.set_facecolor('white')

    # Legend clarifying what the wine-red marker means (avoids any ambiguity
    # about which point is the best-fit parameter set).
    legend_handles = [
        Line2D([0], [0], marker='o', linestyle='', markersize=9,
               markerfacecolor=_DOT_FACE, markeredgecolor=_DOT_EDGE, label='Simulations'),
        Line2D([0], [0], marker='o', linestyle='', markersize=9,
               markerfacecolor=_BEST_COLOR, markeredgecolor='black', label='Best fit'),
    ]
    fig.legend(handles=legend_handles, loc='lower center', ncol=2, frameon=False,
               fontsize=14, bbox_to_anchor=(0.5, -0.05))

    # Save Figure
    # rect reserves the bottom margin for the legend so it doesn't crowd the
    # x-axis titles of the last row of panels.
    FileName = os.path.join(ProjectPath, 'FIGURES', f'Calibration_{ModelName}_{Suffix}.jpg')
    plt.tight_layout(rect=[0, 0.045, 1, 1])
    plt.savefig(FileName, dpi=200, facecolor='white', bbox_inches='tight')
    plt.close()

    return BestParamsDict, BestAREM

def Plot_AWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    """Build the AWY calibration figure. See :func:`_plot_calibration`."""
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'AWY')

def Plot_SWY(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    """Build the SWY calibration figure. See :func:`_plot_calibration`."""
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'SWY')

def Plot_SDR(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    """Build the SDR calibration figure. See :func:`_plot_calibration`."""
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'SDR')

def Plot_NDR_N(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    """Build the NDR_N calibration figure. See :func:`_plot_calibration`."""
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'NDR_N')

def Plot_NDR_P(ProjectPath, Suffix, NameMetric, InVEST_Main_Path, FactorMetric):
    """Build the NDR_P calibration figure. See :func:`_plot_calibration`."""
    return _plot_calibration(ProjectPath, Suffix, NameMetric, FactorMetric, 'NDR_P')


# --------------------------------------------------------------------------
# HTML calibration report
# --------------------------------------------------------------------------
# Plain-text (non-LaTeX) labels/units for the HTML report — the matplotlib
# labels in _MODEL_PLOT_CONFIG use LaTeX markup ($...$) meant for figure
# rendering, not for display in a browser.
_MODEL_FULL_NAME = {
    'AWY':   'AWY – Annual Water Yield',
    'SWY':   'SWY – Seasonal Water Yield',
    'SDR':   'SDR – Sediment Delivery Ratio',
    'NDR_N': 'NDR_N – Nutrient Delivery Ratio (Nitrogen)',
    'NDR_P': 'NDR_P – Nutrient Delivery Ratio (Phosphorus)',
}

_MODEL_UNIT_PLAIN = {
    'AWY':   'm³/s',
    'SWY':   'mm',
    'SDR':   'ton/year',
    'NDR_N': 'kg/year',
    'NDR_P': 'kg/year',
}

_PARAM_PLAIN_LABELS = {
    'Z':              'Z — Zhang seasonality constant',
    'Factor-Kc':      'Factor-Kc — scales the Kc column',
    'Alpha':          'Alpha — monthly baseflow recession coefficient',
    'Beta':           'Beta — soil water retention factor',
    'Gamma':          'Gamma — fraction of recharge routed to stream',
    'Factor-Kc_m':    'Factor-Kc_m — scales the monthly Kc columns',
    'sdr_max':        'sdr_max — maximum sediment delivery ratio',
    'Borselli-K_SDR': 'Borselli-K — connectivity constant',
    'IC0':            'IC0 — connectivity-index threshold',
    'L_max':          'L_max — maximum hillslope length (m)',
    'Factor-C':       'Factor-C — scales the usle_c column',
    'Factor-P':       'Factor-P — scales the usle_p column',
    'SubCri_Len_N':   'SubCri_Len_N — subsurface critical flow-path length (m)',
    'Sub_Eff_N':      'Sub_Eff_N — subsurface retention efficiency',
    'Borselli-K_NDR': 'Borselli-K — connectivity constant',
    'Factor_Load_N':  'Factor_Load_N — scales the load_n column',
    'Factor_Eff_N':   'Factor_Eff_N — scales the eff_n column',
    'SubCri_Len_P':   'SubCri_Len_P — subsurface critical flow-path length (m)',
    'Sub_Eff_P':      'Sub_Eff_P — subsurface retention efficiency',
    'Factor_Load_P':  'Factor_Load_P — scales the load_p column',
    'Factor_Eff_P':   'Factor_Eff_P — scales the eff_p column',
}

# Short blurb per optimization algorithm, keyed by the short code used
# throughout the plugin (DDS / LHS / SCE-UA).
_ALGO_INFO = {
    'DDS': (
        'Dynamically Dimensioned Search (DDS)',
        'A global-search heuristic purpose-built for calibration problems with '
        'several parameters and a constrained evaluation budget. DDS perturbs '
        'every parameter early in the search (exploration) and progressively '
        'fewer as the search advances, narrowing in around the best solution '
        'found so far (exploitation). Recommended for 50–200 simulations; '
        'requires at least 10 for its initialization phase.'
    ),
    'LHS': (
        'Latin Hypercube Sampling (LHS)',
        'A stratified random sampling scheme: each parameter axis is divided '
        'into N equal intervals and one value is drawn from each, guaranteeing '
        'even coverage of the full search space. Suited to sensitivity '
        'analysis and initial exploration rather than optimization — '
        'results do not improve by adding more simulations, since each draw '
        'is independent of the others.'
    ),
    'SCE-UA': (
        'Shuffled Complex Evolution (SCE-UA)',
        'A population-based evolutionary algorithm that evolves several '
        'candidate solutions ("complexes") concurrently, mixing them through '
        'shuffling and recombination. Well suited to complex, multi-modal '
        'response surfaces where DDS or LHS might settle on a local optimum. '
        'Recommended for 200+ simulations.'
    ),
}


def _fmt_duration(seconds):
    """Format a duration in seconds as a compact ``1h 02m 03s`` string."""
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}h {m:02d}m {s:02d}s'
    if m:
        return f'{m}m {s:02d}s'
    return f'{s}s'


def Build_HTML_Report(ProjectPath, Suffix, ModelName, MethodShort, MetricShort,
                       NSim, StartTime, EndTime, InvestVersion, InputsSummary,
                       ParamsMin, ParamsMax, ParamsVal, FinalParams,
                       BestMetricValue, UsedFallback, StatusCalSummary):
    """Render a self-contained HTML calibration report and save it to disk.

    Builds one ``REPORT/Report_<ModelName>_<Suffix>.html`` file per run,
    embedding the dotty-plot/Obs-vs-Sim figure produced by
    :func:`_plot_calibration` as a base64 image so the report is a single
    portable file with no external dependencies (works fully offline).

    Parameters
    ----------
    ProjectPath : str
        Calibration workspace directory.
    Suffix : str
        Project suffix (used to find the figure and name the report).
    ModelName : str
        One of ``'AWY'``, ``'SWY'``, ``'SDR'``, ``'NDR_N'``, ``'NDR_P'``.
    MethodShort : str
        Optimization algorithm short code (``'DDS'``, ``'LHS'``, ``'SCE-UA'``).
    MetricShort : str
        Objective metric short code (``'MSE'``, ``'MAE'``, ``'RMSE'``, ``'RRMSE'``).
    NSim : int
        Number of simulations requested.
    StartTime, EndTime : datetime.datetime
        Wall-clock start/end of the calibration run, used to report the
        run's duration.
    InvestVersion : str
        Installed ``natcap.invest`` version, for traceability.
    InputsSummary : list of (str, str)
        ``(label, path)`` pairs for the spatial/tabular inputs used.
    ParamsMin, ParamsMax, ParamsVal : dict
        Search bounds and initial guess, keyed by internal parameter name
        (as returned by ``_read_param_ranges`` in ``calibration_assistant.py``).
    FinalParams : dict
        Parameter values actually used for the final InVEST run (best-fit,
        or the initial guess when ``UsedFallback`` is True).
    BestMetricValue : float or None
        Best (unsigned) objective-function value found, or ``None`` if the
        calibration plot could not be generated.
    UsedFallback : bool
        True when no valid best-fit set was found and the initial guess
        was used for the final run instead.
    StatusCalSummary : list of (str, int, int)
        ``(column_name, n_flagged, n_total)`` per ``Status_Cal_*`` column
        relevant to ``ModelName``.

    Returns
    -------
    str
        Path to the written HTML report.
    """
    cfg = _MODEL_PLOT_CONFIG.get(ModelName, {'params': []})
    param_keys = [k for k, _ in cfg['params']]
    unit       = _MODEL_UNIT_PLAIN.get(ModelName, '')
    duration   = _fmt_duration((EndTime - StartTime).total_seconds())

    # ---- embed the calibration figure (base64, fully offline) ----------
    fig_path = os.path.join(ProjectPath, 'FIGURES', f'Calibration_{ModelName}_{Suffix}.jpg')
    if os.path.isfile(fig_path):
        with open(fig_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        fig_html = f'<img src="data:image/jpeg;base64,{b64}" alt="Calibration figure for {ModelName}">'
    else:
        fig_html = '<p class="muted"><em>Calibration figure not available for this run.</em></p>'

    # ---- parameter table rows -------------------------------------------
    param_rows = ''
    for key in param_keys:
        label = _PARAM_PLAIN_LABELS.get(key, key)
        lo, hi = ParamsMin.get(key), ParamsMax.get(key)
        initial = ParamsVal.get(key)
        final   = FinalParams.get(key, initial)
        param_rows += (
            '<tr>'
            f'<td>{label}</td>'
            f'<td>{lo:.4g}</td>'
            f'<td>{hi:.4g}</td>'
            f'<td>{initial:.4g}</td>'
            f'<td class="best-fit">{final:.4g}</td>'
            '</tr>'
        )

    # ---- inputs table rows -----------------------------------------------
    inputs_rows = ''.join(
        f'<tr><td>{label}</td><td class="mono">{path}</td></tr>'
        for label, path in InputsSummary
    )

    # ---- Status_Cal_* summary --------------------------------------------
    if StatusCalSummary:
        status_rows = ''
        for col, n_flagged, n_total in StatusCalSummary:
            pct = (100 * n_flagged / n_total) if n_total else 0
            status_rows += (
                '<tr><td class="mono">{col}</td>'
                '<td>{flagged} / {total} LULC classes calibrated</td>'
                '<td><div class="status-bar-wrap"><div class="status-bar" '
                'style="width:{pct:.0f}%"></div></div></td></tr>'
            ).format(col=col, flagged=n_flagged, total=n_total, pct=pct)
        status_section = f'''
    <section>
      <h2>Which land-cover classes were calibrated</h2>
      <p>Rows flagged <code>1</code> in each <code>Status_Cal_*</code> column were rescaled by the
      corresponding factor; rows flagged <code>0</code> kept their original biophysical-table value.</p>
      <table><tbody>{status_rows}</tbody></table>
    </section>'''
    else:
        status_section = ''

    # ---- algorithm blurb ---------------------------------------------------
    algo_name, algo_text = _ALGO_INFO.get(MethodShort, (MethodShort, ''))

    # ---- fallback warning banner --------------------------------------------
    fallback_banner = ''
    if UsedFallback:
        fallback_banner = (
            '<div class="warning-banner">No valid best-fit parameter set was found during '
            'calibration; the final InVEST run used the initial parameter guess instead. '
            'Check the EVALUATIONS/ logs for failed iterations before trusting this result.</div>'
        )

    best_metric_str = f'{BestMetricValue:.4g} {unit}' if BestMetricValue is not None else 'n/a'

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Calibration Report — {ModelName} ({Suffix})</title>
<style>
  :root {{
    --wine: #7B1E24;
    --gray-dark: #404040;
    --gray-mid: #8C8C8C;
    --gray-light: #D9D9D9;
    --bg: #F5F3F1;
    --card-bg: #FFFFFF;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 0;
    font-family: Georgia, "Times New Roman", serif;
    background: var(--bg);
    color: #262626;
  }}
  header {{
    background: linear-gradient(135deg, var(--wine), #4A1216);
    color: #fff;
    padding: 40px 48px 56px 48px;
  }}
  header h1 {{ margin: 0 0 8px 0; font-size: 26px; }}
  header .subtitle {{ opacity: .85; font-size: 14px; }}
  .container {{ max-width: 1080px; margin: -32px auto 48px auto; padding: 0 24px; }}
  .stats-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 14px;
    margin-bottom: 28px;
  }}
  .stat-card {{
    background: var(--card-bg);
    border-radius: 10px;
    padding: 16px 18px;
    box-shadow: 0 2px 10px rgba(0,0,0,.07);
    border-top: 3px solid var(--wine);
  }}
  .stat-card .label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .05em; color: var(--gray-mid);
  }}
  .stat-card .value {{ font-size: 20px; font-weight: 700; color: #262626; margin-top: 4px; }}
  section {{
    background: var(--card-bg);
    border-radius: 10px;
    padding: 26px 30px;
    margin-bottom: 22px;
    box-shadow: 0 2px 10px rgba(0,0,0,.07);
  }}
  section h2 {{
    margin-top: 0; font-size: 18px; color: var(--wine);
    border-bottom: 2px solid var(--gray-light); padding-bottom: 9px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #EEE; vertical-align: top; }}
  th {{ color: var(--gray-mid); text-transform: uppercase; font-size: 10.5px; letter-spacing: .04em; }}
  tr:hover {{ background: #FAFAFA; }}
  .best-fit {{ color: var(--wine); font-weight: 700; }}
  .mono {{ font-family: "Courier New", monospace; font-size: 12px; word-break: break-all; }}
  .muted {{ color: var(--gray-mid); }}
  .fig {{ text-align: center; }}
  .fig img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 14px rgba(0,0,0,.12); }}
  .explain p {{ line-height: 1.65; font-size: 14px; }}
  .status-bar-wrap {{ background: #EEE; border-radius: 6px; overflow: hidden; height: 9px; min-width: 120px; }}
  .status-bar {{ background: var(--wine); height: 100%; }}
  .warning-banner {{
    background: #FBEAEA; border-left: 4px solid var(--wine); color: #5C1015;
    padding: 12px 16px; border-radius: 6px; margin-bottom: 22px; font-size: 13.5px;
  }}
  footer {{ text-align: center; padding: 24px; color: var(--gray-mid); font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>Calibration Report — {_MODEL_FULL_NAME.get(ModelName, ModelName)}</h1>
  <div class="subtitle">Project: {Suffix} &nbsp;·&nbsp; Generated {EndTime.strftime('%Y-%m-%d %H:%M')}
    &nbsp;·&nbsp; InVEST {InvestVersion}</div>
</header>
<div class="container">
  {fallback_banner}
  <div class="stats-grid">
    <div class="stat-card"><div class="label">Algorithm</div><div class="value">{MethodShort}</div></div>
    <div class="stat-card"><div class="label">Metric</div><div class="value">{MetricShort}</div></div>
    <div class="stat-card"><div class="label">Simulations</div><div class="value">{NSim}</div></div>
    <div class="stat-card"><div class="label">Best {MetricShort}</div><div class="value">{best_metric_str}</div></div>
    <div class="stat-card"><div class="label">Duration</div><div class="value">{duration}</div></div>
    <div class="stat-card"><div class="label">InVEST version</div><div class="value">{InvestVersion}</div></div>
  </div>

  <section>
    <h2>Optimization algorithm</h2>
    <p class="explain"><strong>{algo_name}</strong></p>
    <p class="explain">{algo_text}</p>
  </section>

  <section>
    <h2>Inputs used</h2>
    <table><tbody>{inputs_rows}</tbody></table>
  </section>

  <section>
    <h2>Parameter search ranges &amp; best-fit values</h2>
    <table>
      <thead><tr><th>Parameter</th><th>Min</th><th>Max</th><th>Initial</th><th>Final (used)</th></tr></thead>
      <tbody>{param_rows}</tbody>
    </table>
  </section>
  {status_section}

  <section class="fig">
    <h2>Dotty plots &amp; Observed vs. Simulated</h2>
    {fig_html}
  </section>

  <section class="explain">
    <h2>How to read this report</h2>
    <p><strong>Observed vs. Simulated panel</strong> (top-left of the figure): each point is one
    calibration watershed for the best-fit run. Points close to the diagonal (1:1) line indicate
    a good fit; points far above or below it indicate over- or under-prediction for that gauge.</p>
    <p><strong>Dotty plots</strong> (one per parameter): each gray dot is one simulation, plotting the
    sampled parameter value (x-axis) against the resulting {MetricShort} (y-axis); the wine-red dot
    marks the best-fit simulation.</p>
    <ul>
      <li><strong>Clear U-shape, narrow minimum</strong> — a sensitive, well-identified parameter:
      the data support a single best value.</li>
      <li><strong>Flat, horizontal cloud</strong> — an insensitive parameter over the tested range:
      the model output barely responds to it.</li>
      <li><strong>Wide, flat minimum</strong> — equifinality: several different values fit almost
      equally well, so the best-fit value alone should not be over-interpreted.</li>
      <li><strong>Best-fit point pinned at a range boundary</strong> — the search range (or, for
      table-perturbation factors, a physical clamp such as usle_c &le; 1) may be limiting the fit;
      consider widening <code>Min</code>/<code>Max</code> in Parameters.csv.</li>
    </ul>
  </section>
</div>
<footer>InVEST Calibration Assistant · Nature For Water Facility – The Nature Conservancy</footer>
</body>
</html>'''

    report_dir = os.path.join(ProjectPath, 'REPORT')
    CreateFolder(report_dir)
    report_path = os.path.join(report_dir, f'Report_{ModelName}_{Suffix}.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return report_path


# --------------------------------------------------------------------------
# Name        : ismember.py
# Author      : E.Taskesen
# Contact     : erdogan@gmail.com
# --------------------------------------------------------------------------
# %% ismember
def ismember(a_vec, b_vec, method=None):
    """MATLAB-equivalent of ``ismember``: locate elements of ``a_vec`` in ``b_vec``.

    Equivalent to MATLAB's ``[LIA, LOCB] = ISMEMBER(A, B)``: returns a
    boolean mask over ``a_vec`` (True where that element is found in
    ``b_vec``) together with the corresponding index into ``b_vec`` for
    each matched element.

    Parameters
    ----------
    a_vec : list or array
        Values to look up.
    b_vec : list or array
        Values to look up against.
    method : {None, 'rows'}, optional
        ``'rows'`` performs the comparison row-wise over 2-D arrays
        instead of element-wise. Default ``None``.

    Returns
    -------
    Iloc : ndarray of bool
        Boolean mask over ``a_vec``, True where that element is found in
        ``b_vec``.
    idx : ndarray of int
        For each True entry in ``Iloc``, the index of the matching value
        in ``b_vec`` (same order as ``a_vec[Iloc]``).

    Examples
    --------
    >>> a_vec = np.array([1, 2, 3, None])
    >>> b_vec = np.array([4, 1, 2])
    >>> Iloc, idx = ismember(a_vec, b_vec)
    >>> a_vec[Iloc] == b_vec[idx]
    """
    # Set types
    a_vec, b_vec = _settypes(a_vec, b_vec)

    # Compute
    if method is None:
        Iloc, idx = _compute(a_vec, b_vec)
    elif method == 'rows':
        if a_vec.shape[0] != b_vec.shape[0]: raise Exception(
            'Error: Input matrices should have same number of columns.')
        # Compute row-wise over the matrices
        out = list(map(lambda x, y: _compute(x, y), a_vec, b_vec))
        # Unzipping
        Iloc, idx = list(zip(*out))
    else:
        Iloc, idx = None, None

    return (Iloc, idx)


# %% Compute
def _settypes(a_vec, b_vec):
    """Normalize inputs to numpy arrays for :func:`ismember`.

    Converts pandas/list inputs to numpy arrays, replacing ``None``
    entries with the string ``'NaN'`` for pandas inputs.

    Parameters
    ----------
    a_vec, b_vec : list, pandas.Series, or ndarray
        Inputs to normalize.

    Returns
    -------
    tuple of ndarray
        ``(a_vec, b_vec)`` as numpy arrays.
    """
    if 'pandas' in str(type(a_vec)):
        a_vec.values[np.where(a_vec.values == None)] = 'NaN'
        a_vec = np.array(a_vec.values)
    if 'pandas' in str(type(b_vec)):
        b_vec.values[np.where(b_vec.values == None)] = 'NaN'
        b_vec = np.array(b_vec.values)
    if isinstance(a_vec, list):
        a_vec = np.array(a_vec)
        # a_vec[a_vec==None]='NaN'
    if isinstance(b_vec, list):
        b_vec = np.array(b_vec)
        # b_vec[b_vec==None]='NaN'

    return a_vec, b_vec


# %% Compute
def _compute(a_vec, b_vec):
    """Core element-wise lookup used by :func:`ismember`.

    Parameters
    ----------
    a_vec, b_vec : ndarray
        Arrays to compare (as returned by :func:`_settypes`).

    Returns
    -------
    bool_ind : ndarray of bool
        Boolean mask over ``a_vec``, True where found in ``b_vec``.
    common_ind : ndarray of int
        Matching index into ``b_vec`` for each True entry in ``bool_ind``.
    """
    bool_ind = np.isin(a_vec, b_vec)
    common = a_vec[bool_ind]
    [common_unique, common_inv] = np.unique(common, return_inverse=True)
    [b_unique, b_ind] = np.unique(b_vec, return_index=True)
    common_ind = b_ind[np.isin(b_unique, common_unique, assume_unique=True)]

    return bool_ind, common_ind[common_inv]


# --------------------------------------------------------------------------
# Zonal statistics (GDAL-based)
# Name        : zonal_stats.py
# Author      : Matthew Perry
# Copyright   : 2013
# --------------------------------------------------------------------------

def bbox_to_pixel_offsets(gt, bbox):
    """Convert a geographic bounding box into raster pixel offsets/size.

    Parameters
    ----------
    gt : tuple
        GDAL geotransform, as returned by ``Dataset.GetGeoTransform()``.
    bbox : tuple
        ``(minx, maxx, miny, maxy)`` bounding box in the raster's CRS.

    Returns
    -------
    tuple of int
        ``(x1, y1, xsize, ysize)`` pixel offset and size, suitable for
        ``Band.ReadAsArray(*offset)``.
    """
    originX = gt[0]
    originY = gt[3]
    pixel_width = gt[1]
    pixel_height = gt[5]
    x1 = int((bbox[0] - originX) / pixel_width)
    x2 = int((bbox[1] - originX) / pixel_width) + 1

    y1 = int((bbox[3] - originY) / pixel_height)
    y2 = int((bbox[2] - originY) / pixel_height) + 1

    xsize = x2 - x1
    ysize = y2 - y1
    return (x1, y1, xsize, ysize)


def zonal_stats_1(vector_path, raster_path, nodata_value=None, global_src_extent=False):
    """Compute per-feature zonal statistics of a raster within vector polygons.

    For each feature in ``vector_path``, rasterizes the polygon in-memory
    and computes min/mean/max/std/sum/count over the overlapping raster
    cells in ``raster_path``.

    Parameters
    ----------
    vector_path : str
        Path to the polygon vector file (e.g. shapefile).
    raster_path : str
        Path to the single-band raster to summarize.
    nodata_value : float, optional
        Raster nodata value to mask out. If not given, uses whatever is
        already set on the raster band.
    global_src_extent : bool, optional
        If True, read the full raster extent covering all features into
        memory once (faster with slow disks / well-tiled rasters, but
        higher memory use for large extents). If False (default), read
        only the local extent per feature.

    Returns
    -------
    list of dict
        One dict per feature with keys ``min``, ``mean``, ``max``,
        ``std``, ``sum``, ``count``, ``fid``.
    """
    rds = gdal.Open(raster_path, GA_ReadOnly)
    assert(rds)
    rb = rds.GetRasterBand(1)
    rgt = rds.GetGeoTransform()

    if nodata_value:
        nodata_value = float(nodata_value)
        rb.SetNoDataValue(nodata_value)

    # Opened read-only: this function only reads stats, it never writes
    # them back to the vector layer.
    vds = ogr.Open(vector_path, GA_ReadOnly)
    assert(vds)
    vlyr = vds.GetLayer(0)

    # create an in-memory numpy array of the source raster data
    # covering the whole extent of the vector layer
    if global_src_extent:
        # use global source extent
        # useful only when disk IO or raster scanning inefficiencies are your limiting factor
        # advantage: reads raster data in one pass
        # disadvantage: large vector extents may have big memory requirements
        src_offset = bbox_to_pixel_offsets(rgt, vlyr.GetExtent())
        src_array = rb.ReadAsArray(*src_offset)

        # calculate new geotransform of the layer subset
        new_gt = (
            (rgt[0] + (src_offset[0] * rgt[1])),
            rgt[1],
            0.0,
            (rgt[3] + (src_offset[1] * rgt[5])),
            0.0,
            rgt[5]
        )

    mem_drv = ogr.GetDriverByName('Memory')
    driver = gdal.GetDriverByName('MEM')

    # Loop through vectors
    stats = []
    feat = vlyr.GetNextFeature()
    while feat is not None:

        if not global_src_extent:
            # use local source extent
            # fastest option when you have fast disks and well indexed raster (ie tiled Geotiff)
            # advantage: each feature uses the smallest raster chunk
            # disadvantage: lots of reads on the source raster
            src_offset = bbox_to_pixel_offsets(rgt, feat.geometry().GetEnvelope())
            src_array = rb.ReadAsArray(*src_offset)

            # calculate new geotransform of the feature subset
            new_gt = (
                (rgt[0] + (src_offset[0] * rgt[1])),
                rgt[1],
                0.0,
                (rgt[3] + (src_offset[1] * rgt[5])),
                0.0,
                rgt[5]
            )

        # Create a temporary vector layer in memory
        mem_ds = mem_drv.CreateDataSource('out')
        mem_layer = mem_ds.CreateLayer('poly', None, ogr.wkbPolygon)
        mem_layer.CreateFeature(feat.Clone())

        # Rasterize it
        rvds = driver.Create('', src_offset[2], src_offset[3], 1, gdal.GDT_Byte)
        rvds.SetGeoTransform(new_gt)
        gdal.RasterizeLayer(rvds, [1], mem_layer, burn_values=[1])
        rv_array = rvds.ReadAsArray()

        # Mask the source data array with our current feature
        # we take the logical_not to flip 0<->1 to get the correct mask effect
        # we also mask out nodata values explictly
        masked = np.ma.MaskedArray(
            src_array,
            mask=np.logical_or(
                src_array == nodata_value,
                np.logical_not(rv_array)
            )
        )

        feature_stats = {
            'min': float(masked.min()),
            'mean': float(masked.mean()),
            'max': float(masked.max()),
            'std': float(masked.std()),
            'sum': float(masked.sum()),
            'count': int(masked.count()),
            'fid': int(feat.GetFID())}

        stats.append(feature_stats)

        rvds = None
        mem_ds = None
        feat = vlyr.GetNextFeature()

    vds = None
    rds = None
    return stats


# --------------------------------------------------------------------------
# Zonal statistics (rasterstats-based)
# --------------------------------------------------------------------------

def calculate_zonal_stats(shapefile_path, raster_path, output_path_shp, ws_id="ws_id", Suffix=""):
    """Compute per-watershed zonal statistics of a raster (rasterstats-based).

    Reprojects the shapefile to the raster's CRS if needed, computes
    mean/min/max/median/sum per unique ``ws_id`` group via
    ``rasterstats.zonal_stats``, and writes the combined result to a new
    shapefile ``Zonal_<Suffix>.shp`` in ``output_path_shp``.

    Parameters
    ----------
    shapefile_path : str
        Path to the input polygon shapefile.
    raster_path : str
        Path to the raster to summarize.
    output_path_shp : str
        Directory where the output ``Zonal_<Suffix>.shp`` is written.
    ws_id : str, optional
        Name of the shapefile attribute used to group polygons. Default
        ``'ws_id'``.
    Suffix : str, optional
        Suffix used in the output shapefile name. Default ``''``.

    Returns
    -------
    pandas.DataFrame
        One row per unique ``ws_id`` with columns ``mean``, ``min``,
        ``max``, ``median``, ``sum`` plus geometry/id columns.

    Raises
    ------
    RuntimeError
        If the shapefile cannot be read, or the output shapefile cannot
        be written.
    """
    try:
        # Read the shapefile using pyogrio as a Fiona alternative.
        polygons = gpd.read_file(shapefile_path, engine='pyogrio')
    except Exception as e:
        raise RuntimeError(f"Error reading shapefile: {e}")

    # Check that the shapefile and raster share the same CRS.
    with rasterio.open(raster_path) as src:
        raster_crs = src.crs
        nodata_value = src.nodatavals[0] if src.nodatavals and src.nodatavals[0] is not None else None

    if polygons.crs != raster_crs:
        polygons = polygons.to_crs(raster_crs)

    # Compute zonal statistics for all polygons in a single vectorized
    # call. rasterstats scores each feature independently regardless of
    # its 'ws_id', so looping per unique id and concatenating produced
    # the same rows, just slower for many watersheds.
    stats = zonal_stats(
        polygons,  # Full polygon layer
        raster_path,  # Raster file
        stats=["mean", "min", "max", "median", "sum"],
        nodata=nodata_value,  # Desired statistics
        geojson_out=True  # Return results as GeoJSON
    )
    final_result = gpd.GeoDataFrame.from_features(stats)
    final_result[ws_id] = polygons[ws_id].values

    # Save results to a new shapefile.
    output_path = f"Zonal_{Suffix}.shp"
    try:
        final_result.to_file(os.path.join(output_path_shp, output_path), driver='ESRI Shapefile')
    except Exception as e:
        raise RuntimeError(f"Error writing output shapefile: {e}")

    # Convert results to a DataFrame.
    final_result = pd.DataFrame(final_result)

    return final_result
