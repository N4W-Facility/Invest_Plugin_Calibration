# -*- coding: utf-8 -*-
# -------------------------------------------------------------------------
# Nature For Water Facility - The Nature Conservancy
# -------------------------------------------------------------------------
#                           BASIC INFORMATION
# -------------------------------------------------------------------------
# Author        : Jonathan Nogales Pimentel / Carlos Andrés Rogéliz Prada / Miguel Angel Cañón
# Email         : jonathan.nogales@tnc.org
#
# HTML calibration report builder. Split out from Spotpy_InVEST.py so the
# report has no heavy geospatial/plotting dependencies of its own — it only
# reads the JPG figure that ``_plot_calibration`` already wrote and reuses
# its parameter layout (``_MODEL_PLOT_CONFIG``) via a deferred import.
# -------------------------------------------------------------------------

import base64
import os

# InVEST's own brand green (natcap/invest-workbench, src/styles/style.css,
# --invest-green), used here so the report reads as part of the same
# product as the Workbench — and matches _BEST_COLOR in Spotpy_InVEST.py,
# so the best-fit dot in the embedded figure matches the report's accent.
_INVEST_GREEN      = '#148F68'
_INVEST_GREEN_DARK = '#0C5A41'

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

# Which Status_Cal_* column gates which biophysical-table column, for the
# "which land covers were calibrated" section. Mirrors Factor_BioTable() in
# Spotpy_InVEST.py and the _STATUS_CAL_COLUMNS map in calibration_assistant.py.
_STATUS_CAL_TARGET_COLUMN = {
    'Status_Cal_Kc':      'Kc',
    'Status_Cal_C':       'usle_c',
    'Status_Cal_P':       'usle_p',
    'Status_Cal_Load_N':  'load_n',
    'Status_Cal_Eff_N':   'eff_n',
    'Status_Cal_Load_P':  'load_p',
    'Status_Cal_Eff_P':   'eff_p',
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
                       BestMetricValue, UsedFallback, StatusCalDetail):
    """Render a self-contained HTML calibration report and save it to disk.

    Builds one ``REPORT/Report_<ModelName>_<Suffix>.html`` file per run,
    embedding the dotty-plot/Obs-vs-Sim figure produced by
    ``Spotpy_InVEST._plot_calibration`` as a base64 image so the report is
    a single portable file with no external dependencies (works fully
    offline, no CDN, no JS libraries).

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
    StatusCalDetail : list of (str, int, int, list of (str, str))
        ``(column_name, n_flagged, n_total, classes)`` per ``Status_Cal_*``
        column relevant to ``ModelName``, where ``classes`` is the list of
        ``(lucode, description)`` for the LULC rows flagged ``1`` (i.e. the
        land-cover classes actually calibrated by that factor).

    Returns
    -------
    str
        Path to the written HTML report.
    """
    # Deferred: only pulls in Spotpy_InVEST.py's heavy geospatial/plotting
    # dependencies when a report is actually built (by then, execute() has
    # already imported them to run the calibration itself).
    from .Spotpy_InVEST import _MODEL_PLOT_CONFIG  # noqa: PLC0415

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

    # ---- Status_Cal_* detail: which LULC classes were calibrated --------
    if StatusCalDetail:
        status_rows = ''
        for col, n_flagged, n_total, classes in StatusCalDetail:
            pct = (100 * n_flagged / n_total) if n_total else 0
            target_col = _STATUS_CAL_TARGET_COLUMN.get(col, col)
            if classes:
                classes_html = ', '.join(
                    f'<span class="lulc-chip">{lucode} – {desc}</span>' if desc
                    else f'<span class="lulc-chip">{lucode}</span>'
                    for lucode, desc in classes
                )
            else:
                classes_html = '<span class="muted">none</span>'
            status_rows += (
                '<tr>'
                f'<td class="mono">{col}</td>'
                f'<td class="mono">{target_col}</td>'
                f'<td>{n_flagged} / {n_total}'
                f'<div class="status-bar-wrap"><div class="status-bar" style="width:{pct:.0f}%"></div></div>'
                '</td>'
                f'<td>{classes_html}</td>'
                '</tr>'
            )
        status_section = f'''
    <section>
      <h2>Which land-cover classes were calibrated</h2>
      <p>Rows flagged <code>1</code> in each <code>Status_Cal_*</code> column were rescaled by the
      corresponding factor; rows flagged <code>0</code> kept their original biophysical-table value.</p>
      <table>
        <thead><tr><th>Flag column</th><th>Table column scaled</th><th>Calibrated</th><th>Land-cover classes calibrated</th></tr></thead>
        <tbody>{status_rows}</tbody>
      </table>
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
    --accent: {_INVEST_GREEN};
    --accent-dark: {_INVEST_GREEN_DARK};
    --gray-dark: #404040;
    --gray-mid: #8C8C8C;
    --gray-light: #D9D9D9;
    --bg: #F4F6F5;
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
    background: linear-gradient(135deg, var(--accent), var(--accent-dark));
    color: #fff;
    padding: 40px 48px 56px 48px;
  }}
  header h1 {{ margin: 0 0 8px 0; font-size: 26px; }}
  header .subtitle {{ opacity: .9; font-size: 14px; }}
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
    border-top: 3px solid var(--accent);
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
    margin-top: 0; font-size: 18px; color: var(--accent-dark);
    border-bottom: 2px solid var(--gray-light); padding-bottom: 9px;
  }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid #EEE; vertical-align: top; }}
  th {{ color: var(--gray-mid); text-transform: uppercase; font-size: 10.5px; letter-spacing: .04em; }}
  tr:hover {{ background: #FAFAFA; }}
  .best-fit {{ color: var(--accent-dark); font-weight: 700; }}
  .mono {{ font-family: "Courier New", monospace; font-size: 12px; word-break: break-all; }}
  .muted {{ color: var(--gray-mid); }}
  .fig {{ text-align: center; }}
  .fig img {{ max-width: 100%; border-radius: 8px; box-shadow: 0 2px 14px rgba(0,0,0,.12); }}
  .explain p {{ line-height: 1.65; font-size: 14px; }}
  .status-bar-wrap {{ background: #EEE; border-radius: 6px; overflow: hidden; height: 9px; min-width: 120px; }}
  .status-bar {{ background: var(--accent); height: 100%; }}
  .lulc-chip {{
    display: inline-block; background: #EAF5F0; color: var(--accent-dark);
    border-radius: 999px; padding: 2px 10px; font-size: 12px; margin: 2px 3px 2px 0;
  }}
  .warning-banner {{
    background: #FBEAEA; border-left: 4px solid #B3261E; color: #5C1015;
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
    sampled parameter value (x-axis) against the resulting {MetricShort} (y-axis); the green dot
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
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f'Report_{ModelName}_{Suffix}.html')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html)

    return report_path
